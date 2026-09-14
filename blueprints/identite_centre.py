"""Fiche commune : lecture responsable, écriture direction/comptabilité."""
from contextlib import closing
import io
import logging
import sqlite3

from flask import (Blueprint, abort, flash, redirect, render_template,
                   request, send_file, session, url_for)

from database import get_db
from extensions import limiter
import identite_centre as service
from propositions import TYPES, limites_pieces
from sessions_securite import verifier_action
from utils import login_required

identite_centre_bp = Blueprint('identite_centre_bp', __name__)
logger = logging.getLogger(__name__)


def _autoriser(ecriture=False):
    profils = service.GESTIONNAIRES if ecriture else service.LECTEURS
    if session.get('profil') not in profils:
        abort(403)


def _page(conn, erreur=None, statut=200):
    fiche = conn.execute('SELECT * FROM identite_centre WHERE id=1').fetchone()
    return render_template('identite_centre.html', fiche=fiche,
        champs=conn.execute('SELECT * FROM identite_centre_champs ORDER BY id').fetchall(),
        documents=conn.execute('SELECT * FROM identite_centre_documents ORDER BY cree_le DESC, id').fetchall(),
        gestionnaire=session['profil'] in service.GESTIONNAIRES,
        revision_formulaire=request.form.get('revision', '') if statut == 409 else fiche['revision'],
        erreur=erreur, valeurs=request.form if erreur and request.form.get('action') == 'enregistrer' else fiche,
        maximum_fichier=limites_pieces()[0], formats=', '.join(TYPES),
        max_champs=service.MAX_CHAMPS, max_documents=service.MAX_DOCUMENTS), statut


def _modifier(conn, ecrits, a_supprimer):
    action = request.form.get('action')
    if action == 'enregistrer':
        valeurs = service.valider_identite(request.form)
        conn.execute('''UPDATE identite_centre SET nom=?, siren=?, siret=?, ape=?,
            convention_collective_code=? WHERE id=1''',
            tuple(valeurs[k] for k in ('nom', 'siren', 'siret', 'ape', 'convention_collective_code')))
    elif action in ('ajouter_champ', 'modifier_champ', 'supprimer_champ'):
        identifiant = request.form.get('champ_id', type=int)
        if action != 'ajouter_champ' and (identifiant is None or not 1 <= identifiant <= 2**63-1):
            abort(404)
        if action != 'ajouter_champ' and not conn.execute(
                'SELECT 1 FROM identite_centre_champs WHERE id=?', (identifiant,)).fetchone():
            abort(404)
        if action == 'supprimer_champ':
            conn.execute('DELETE FROM identite_centre_champs WHERE id=?', (identifiant,))
        else:
            libelle = service.texte(request.form.get('libelle', ''), 80, 'Libellé', True)
            libelle_cle = service.cle_libelle(libelle)
            valeur = service.texte(request.form.get('valeur', ''), 2000, 'Valeur')
            if conn.execute('SELECT 1 FROM identite_centre_champs WHERE libelle_cle=? AND id!=?',
                            (libelle_cle, identifiant if action == 'modifier_champ' else -1)).fetchone():
                raise ValueError('Un champ porte déjà ce libellé.')
            if action == 'ajouter_champ':
                if conn.execute('SELECT COUNT(*) FROM identite_centre_champs').fetchone()[0] >= service.MAX_CHAMPS:
                    raise ValueError(f'La fiche peut contenir au maximum {service.MAX_CHAMPS} champs supplémentaires.')
                conn.execute('''INSERT INTO identite_centre_champs(libelle, libelle_cle, valeur)
                                VALUES (?, ?, ?)''', (libelle, libelle_cle, valeur))
            else:
                conn.execute('''UPDATE identite_centre_champs
                                SET libelle=?, libelle_cle=?, valeur=? WHERE id=?''',
                             (libelle, libelle_cle, valeur, identifiant))
    elif action == 'ajouter_document':
        service.ajouter_document(conn, request.form, request.files.getlist('document'), session['user_id'], ecrits)
    elif action == 'supprimer_document':
        piece = conn.execute('SELECT * FROM identite_centre_documents WHERE id=?',
                             (request.form.get('document_id'),)).fetchone()
        if not piece:
            abort(404)
        a_supprimer.append(service.chemin_document(piece))
        conn.execute('DELETE FROM identite_centre_documents WHERE id=?', (piece['id'],))
    else:
        raise ValueError('Action inconnue. Rechargez la fiche.')


@identite_centre_bp.route('/centre/identite', methods=['GET', 'POST'])
@login_required
@limiter.limit('60 per hour', methods=['POST'], key_func=lambda: str(session.get('user_id')))
def fiche():
    _autoriser(request.method == 'POST')
    with closing(get_db()) as conn:
        if request.method == 'GET':
            return _page(conn)
        ecrits, a_supprimer = [], []
        try:
            conn.execute('BEGIN IMMEDIATE')
            erreur = verifier_action(conn)
            if erreur is not None:
                conn.rollback()
                return erreur
            _autoriser(True)
            revision = conn.execute('SELECT revision FROM identite_centre WHERE id=1').fetchone()[0]
            if request.form.get('revision', type=int) != revision:
                conn.rollback()
                return _page(conn, 'La fiche a changé depuis son ouverture. Rechargez-la avant de réessayer.', 409)
            _modifier(conn, ecrits, a_supprimer)
            conn.execute('UPDATE identite_centre SET revision=revision+1, modifie_le=?, modifie_par=? WHERE id=1',
                         (service.horodatage(), session['user_id']))
            conn.commit()
        except ValueError as exc:
            conn.rollback()
            service.nettoyer(ecrits)
            return _page(conn, str(exc), 400)
        except (OSError, sqlite3.Error):
            conn.rollback()
            service.nettoyer(ecrits)
            logger.error('Enregistrement de la fiche du centre impossible')
            return _page(conn, 'Enregistrement impossible. Réessayez dans un instant.', 503)
        except Exception:
            conn.rollback()
            service.nettoyer(ecrits)
            raise
    # Ne jamais retirer le fichier avant que sa suppression en base soit acquise.
    service.nettoyer(a_supprimer)
    flash('La fiche du centre a été mise à jour.', 'success')
    return redirect(url_for('identite_centre_bp.fiche'))


@identite_centre_bp.route('/centre/identite/documents/<document_id>')
@login_required
def telecharger(document_id):
    _autoriser()
    with closing(get_db()) as conn:
        piece = conn.execute('SELECT * FROM identite_centre_documents WHERE id=?', (document_id,)).fetchone()
    if not piece:
        abort(404)
    try:
        contenu = service.contenu_document(piece)
    except (OSError, ValueError):
        abort(404)
    reponse = send_file(io.BytesIO(contenu), as_attachment=True, download_name=piece['nom'], mimetype=piece['mime'])
    reponse.headers['X-Content-Type-Options'] = 'nosniff'
    reponse.headers['Cache-Control'] = 'no-store'
    return reponse
