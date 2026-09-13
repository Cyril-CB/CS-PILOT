"""Propositions explicites : sauvegarde locale, envoi et consultation sous droits."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import io
import json
import logging
import sqlite3
import uuid

from flask import (Blueprint, abort, current_app, flash, redirect, render_template,
                   request, send_file, session, url_for)
from itsdangerous import BadData, URLSafeSerializer

from database import get_db
from email_service import envoyer_message_structure, is_email_configured
from extensions import limiter
import propositions as service
from sessions_securite import verifier_action
from utils import login_required

propositions_bp = Blueprint('propositions_bp', __name__)
logger = logging.getLogger(__name__)


def _signataire():
    return URLSafeSerializer(current_app.secret_key, salt='cspilot-proposition-formulaire-v1')


def _autoriser():
    if session.get('profil') not in service.PROFILS:
        abort(403)


def _charger(conn, reference):
    proposition = conn.execute('SELECT * FROM propositions_amelioration WHERE id=?', (reference,)).fetchone()
    if not proposition or (proposition['user_id'] != session['user_id']
                          and session['profil'] not in service.GESTIONNAIRES):
        abort(404)
    return proposition


def _formulaire(auteur, contexte, valeurs=None, erreurs=None, statut=200):
    valeurs = valeurs if valeurs is not None else {
        'recherche': contexte['recherche'], 'email_reponse': auteur['email'] or ''}
    maximum_fichier, maximum_total = service.limites_pieces()
    return render_template('proposition_formulaire.html', auteur=auteur, contexte=contexte,
        valeurs=valeurs, erreurs=erreurs or {}, jeton=_signataire().dumps(contexte),
        frequences=service.FREQUENCES, origines=service.ORIGINES,
        formats=', '.join(service.TYPES), email_pret=is_email_configured(),
        gestionnaire=session['profil'] in service.GESTIONNAIRES,
        destinataire=service.DESTINATAIRE, maximum_fichier=maximum_fichier,
        maximum_total=maximum_total), statut


@propositions_bp.route('/propositions/nouvelle', methods=['GET', 'POST'])
@login_required
@limiter.limit('30 per hour', methods=['POST'], key_func=lambda: str(session.get('user_id')))
def nouvelle():
    _autoriser()
    with closing(get_db()) as conn:
        auteur = service.charger_auteur(conn, session['user_id'])
        if request.method == 'GET' or request.form.get('action') == 'preparer':
            contexte = service.contexte_initial(auteur,
                request.form.get('recherche', ''), request.form.get('origine', 'spontanee'),
                request.form.get('page', ''))
            return _formulaire(auteur, contexte)
        try:
            contexte = _signataire().loads(request.form.get('contexte', ''))
            if (contexte['user_id'] != auteur['id']
                    or contexte['session_version'] != auteur['session_version']):
                raise BadData('Compte différent')
        except (BadData, KeyError, TypeError):
            contexte = service.contexte_initial(auteur)
            return _formulaire(auteur, contexte, request.form,
                {'formulaire': 'Ce formulaire a expiré. Vérifiez les informations puis renvoyez-le.'}, 400)

        # Le jeton signé identifie la soumission : un double clic n'écrit ni n'envoie deux fois.
        conn.execute('BEGIN IMMEDIATE')
        erreur = verifier_action(conn)
        if erreur is not None:
            conn.rollback()
            return erreur
        _autoriser()
        if conn.execute('SELECT 1 FROM propositions_amelioration WHERE id=?',
                        (contexte['reference'],)).fetchone():
            conn.rollback()
            return redirect(url_for('propositions_bp.detail', reference=contexte['reference']))
        auteur = service.charger_auteur(conn, session['user_id'])
        ecrits = []
        try:
            valeurs = service.valider_champs(request.form)
            if 'pieces' in request.form:
                raise service.PropositionInvalide({'pieces': 'Une pièce jointe est mal formée. Sélectionnez-la à nouveau.'})
            pieces = service.lire_pieces(request.files.getlist('pieces'))
            contenu = service.construire_contenu(conn, auteur, valeurs, contexte, pieces)
            service.enregistrer(conn, contenu, pieces, ecrits)
            conn.commit()
        except service.PropositionInvalide as exc:
            conn.rollback()
            return _formulaire(auteur, contexte, request.form, exc.erreurs, 400)
        except (OSError, sqlite3.Error):
            conn.rollback()
            service.nettoyer_pieces(ecrits)
            logger.error('Conservation d’une proposition impossible')
            return _formulaire(auteur, contexte, request.form,
                {'formulaire': 'La demande n’a pas pu être enregistrée. Réessayez ; aucun mail n’a été envoyé.'}, 503)
        except Exception:
            conn.rollback()
            service.nettoyer_pieces(ecrits)
            raise
    return _expedier(contexte['reference'])


def _reprise_incertaine(proposition):
    if proposition['statut'] == 'incertain':
        return True
    if proposition['statut'] != 'en_cours':
        return False
    debut = datetime.fromisoformat(proposition['derniere_tentative'])
    return datetime.now(timezone.utc) - debut >= timedelta(minutes=10)


def _expedier(reference, confirmation=False):
    with closing(get_db()) as conn:
        conn.execute('BEGIN IMMEDIATE')
        erreur = verifier_action(conn)
        if erreur is not None:
            conn.rollback()
            return erreur
        _autoriser()
        proposition = _charger(conn, reference)
        retour = url_for('propositions_bp.detail', reference=reference)
        if proposition['statut'] == 'envoyee':
            conn.rollback()
            flash('Cette proposition a déjà été envoyée.', 'info')
            return redirect(retour)
        incertain = _reprise_incertaine(proposition)
        if proposition['statut'] == 'en_cours' and not incertain:
            conn.rollback()
            flash('L’envoi est déjà en cours. Consultez à nouveau cette page dans un instant.', 'info')
            return redirect(retour)
        if incertain and not confirmation:
            conn.rollback()
            flash('Vérifiez la transmission avant de confirmer un nouvel envoi.', 'warning')
            return redirect(retour)
        tentative = uuid.uuid4().hex
        conn.execute('''UPDATE propositions_amelioration SET statut='en_cours',
            tentative_id=?, derniere_tentative=?, tentatives=tentatives+1, erreur_code=NULL WHERE id=?''',
            (tentative, service.horodatage(), reference))
        contenu = json.loads(proposition['contenu_json'])
        pieces = conn.execute('SELECT * FROM propositions_pieces WHERE proposition_id=?', (reference,)).fetchall()
        conn.commit()
    try:
        message = service.construire_message(contenu, pieces)
    except (OSError, ValueError, KeyError):
        statut, code = 'a_envoyer', 'piece'
    else:
        statut, code = envoyer_message_structure(message, service.DESTINATAIRE)
    try:
        with closing(get_db()) as conn:
            conn.execute('''UPDATE propositions_amelioration SET statut=?, erreur_code=?,
                envoyee_le=? WHERE id=? AND tentative_id=?''',
                (statut, code, service.horodatage() if statut == 'envoyee' else None, reference, tentative))
            conn.commit()
    except sqlite3.Error:
        logger.error('État de transmission non enregistré pour la proposition %s', reference)
        flash('La demande est conservée, mais la transmission reste à vérifier.', 'warning')
        return redirect(retour)
    if statut == 'envoyee':
        flash('Votre proposition a été envoyée à cspilot@outlook.fr. Conservez sa référence pour les échanges.', 'success')
    else:
        flash(service.ERREURS_ENVOI[code], 'warning')
    return redirect(retour)


@propositions_bp.route('/propositions/<reference>/envoyer', methods=['POST'])
@login_required
@limiter.limit('10 per hour', key_func=lambda: str(session.get('user_id')))
def envoyer(reference):
    _autoriser()
    return _expedier(reference, request.form.get('confirmer_reenvoi') == 'oui')


@propositions_bp.route('/propositions')
@login_required
def liste():
    _autoriser()
    centre = request.args.get('centre') == '1'
    if centre and session['profil'] not in service.GESTIONNAIRES:
        abort(403)
    page = request.args.get('page', 1, type=int)
    if page < 1 or page > 100000:
        abort(400)
    with closing(get_db()) as conn:
        if centre:
            rows = conn.execute('''SELECT * FROM propositions_amelioration
                ORDER BY cree_le DESC, id DESC LIMIT 31 OFFSET ?''', ((page - 1) * 30,)).fetchall()
        else:
            rows = conn.execute('''SELECT * FROM propositions_amelioration WHERE user_id=?
                ORDER BY cree_le DESC, id DESC LIMIT 31 OFFSET ?''', (session['user_id'], (page - 1) * 30)).fetchall()
    return render_template('propositions_liste.html', propositions=[
        {'suivi': p, 'contenu': json.loads(p['contenu_json'])} for p in rows[:30]],
        suite=len(rows) > 30, page=page, centre=centre,
        gestionnaire=session['profil'] in service.GESTIONNAIRES)


@propositions_bp.route('/propositions/<reference>')
@login_required
def detail(reference):
    _autoriser()
    with closing(get_db()) as conn:
        proposition = _charger(conn, reference)
        pieces = conn.execute('SELECT * FROM propositions_pieces WHERE proposition_id=?', (reference,)).fetchall()
    return render_template('proposition_detail.html', suivi=proposition,
        contenu=json.loads(proposition['contenu_json']), pieces=pieces,
        incertain=_reprise_incertaine(proposition), erreurs_envoi=service.ERREURS_ENVOI,
        gestionnaire=session['profil'] in service.GESTIONNAIRES,
        email_pret=is_email_configured(), frequences=service.FREQUENCES,
        origines=service.ORIGINES, destinataire=service.DESTINATAIRE)


@propositions_bp.route('/propositions/<reference>/pieces/<piece_id>')
@login_required
def telecharger_piece(reference, piece_id):
    _autoriser()
    with closing(get_db()) as conn:
        _charger(conn, reference)
        piece = conn.execute('SELECT * FROM propositions_pieces WHERE id=? AND proposition_id=?',
                             (piece_id, reference)).fetchone()
    if not piece:
        abort(404)
    try:
        contenu = service.contenu_piece(piece)
    except (OSError, ValueError):
        abort(404)
    response = send_file(io.BytesIO(contenu), as_attachment=True,
                         download_name=piece['nom'], mimetype=piece['mime'])
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Cache-Control'] = 'no-store'
    return response


@propositions_bp.route('/propositions/<reference>/fiche.json')
@login_required
def telecharger_fiche(reference):
    _autoriser()
    with closing(get_db()) as conn:
        proposition = _charger(conn, reference)
    response = send_file(io.BytesIO(proposition['contenu_json'].encode('utf-8')),
        as_attachment=True, download_name=f'proposition-{reference}.json', mimetype='application/json')
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response
