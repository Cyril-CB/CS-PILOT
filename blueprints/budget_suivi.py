"""Parcours initial → gel confirmé → suivi ; aucun connecteur actif."""
import json
import sqlite3
import uuid
from datetime import date, datetime, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for, Response
from database import get_db
from utils import login_required
from sessions_securite import verifier_action
from budget_initial import InitialRefuse
from budget_calculs import BudgetRefuse
from budget_suivi import (SuiviRefuse, ajuster, changer_reference, encoder, figer,
                         pdf_suivi, suivi, verifier_initial)

budget_suivi_bp = Blueprint('budget_suivi_bp', __name__)


def _annee():
    raw = request.values.get('annee', str(date.today().year))
    if not raw.isdigit() or not 1900 <= int(raw) <= 2200:
        abort(400)
    return int(raw)


def _gestion():
    return session.get('profil') in ('directeur', 'comptable')


def _perimetre(conn):
    if not _gestion() and session.get('profil') != 'responsable':
        abort(403)
    sid = request.values.get('secteur_id') or None
    if sid is not None and (not sid.isdigit() or len(sid) > 18):
        abort(400)
    if session.get('profil') == 'responsable':
        user = conn.execute('SELECT secteur_id FROM users WHERE id=?', (session['user_id'],)).fetchone()
        if not user or not user['secteur_id'] or (sid is not None and int(sid) != user['secteur_id']):
            abort(403)
        sid = str(user['secteur_id'])
    return sid


def _versions(conn, annee):
    return [dict(r) for r in conn.execute('SELECT id,version,motif,date,auteur FROM budget_gels WHERE annee=? ORDER BY version DESC', (annee,))]


@budget_suivi_bp.route('/budget/gel', methods=['GET', 'POST'])
@login_required
def gel():
    if not _gestion():
        abort(403)
    annee = _annee()
    conn = get_db()
    try:
        conn.execute('BEGIN IMMEDIATE' if request.method == 'POST' else 'BEGIN')
        if request.method == 'POST':
            refus = verifier_action(conn)
            if refus is not None:
                return refus
            if not _gestion():
                abort(403)
            figer(conn, annee, request.form.get('empreinte'), session['user_id'],
                  request.form.get('motif', ''), request.form.get('confirme') == 'oui')
            conn.commit()
            flash('Version figée. Une correction ne remplace pas la référence du suivi : ce choix reste explicite.', 'success')
            return redirect(url_for('.direct', annee=annee))
        archive = None
        if request.args.get('version'):
            archive = conn.execute('SELECT * FROM budget_gels WHERE id=? AND annee=?',
                                   (request.args['version'], annee)).fetchone()
            if archive is None:
                abort(404)
        controle = json.loads(archive['donnees']) if archive else verifier_initial(conn, annee)
        return render_template('budget_gel.html', annee=annee, controle=controle,
                               archive=archive, versions=_versions(conn, annee))
    except (SuiviRefuse, InitialRefuse, BudgetRefuse) as exc:
        conn.rollback()
        message = str(exc) if isinstance(exc, SuiviRefuse) else 'Construction à vérifier dans l’initial détaillé.'
        flash(message, 'error')
        return render_template('budget_gel.html', annee=annee, controle=None, versions=_versions(conn, annee)), 409
    except sqlite3.Error:
        conn.rollback()
        flash('Gel indisponible. Rechargez avant de réessayer.', 'error')
        return render_template('budget_gel.html', annee=annee, controle=None, versions=[]), 503
    finally:
        conn.close()


@budget_suivi_bp.route('/budget/suivi', methods=['GET', 'POST'])
@login_required
def direct():
    annee = _annee()
    conn = get_db()
    status, erreur = 200, None
    try:
        conn.execute('BEGIN IMMEDIATE' if request.method == 'POST' else 'BEGIN')
        sid = _perimetre(conn)
        if request.method == 'POST':
            if not _gestion():
                abort(403)
            refus = verifier_action(conn)
            if refus is not None:
                return refus
            if not _gestion():
                abort(403)
            try:
                revision = request.form.get('revision', '')
                revision = int(revision) if revision.isdigit() and len(revision) < 15 else None
                action = request.form.get('action')
                if action == 'ajuster':
                    ajuster(conn, annee, revision, session['user_id'], request.form.to_dict(),
                            ident=request.form.get('element_id') or None)
                elif action == 'annuler':
                    ajuster(conn, annee, revision, session['user_id'], {},
                            ident=request.form.get('element_id'), annuler=True)
                elif action == 'reference':
                    changer_reference(conn, annee, revision, request.form.get('gel_id'),
                                      session['user_id'], request.form.get('motif', ''))
                elif action == 'instantane':
                    data = suivi(conn, annee, sid)
                    if revision != data['revision']:
                        raise SuiviRefuse('Page périmée : rechargez avant de créer l’instantané.')
                    # BEGIN IMMEDIATE couvre recherche et insertion : deux requêtes
                    # concurrentes ne peuvent pas archiver le même état. IS traite
                    # aussi le périmètre consolidé (secteur_id NULL).
                    archive = conn.execute('''SELECT id FROM budget_instantanes
                        WHERE annee=? AND gel_id=? AND revision=? AND secteur_id IS ?
                        LIMIT 1''', (annee, data['gel_id'], revision, sid)).fetchone()
                    if archive is None:
                        data['instantane_date'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
                        ident = str(uuid.uuid4())
                        conn.execute('''INSERT INTO budget_instantanes
                            (id,annee,secteur_id,gel_id,revision,donnees,pdf_synthese,pdf_detail,auteur,date)
                            VALUES (?,?,?,?,?,?,?,?,?,?)''', (ident, annee, sid, data['gel_id'], revision,
                            encoder(data), pdf_suivi(data), pdf_suivi(data, True), session['user_id'], data['instantane_date']))
                else:
                    raise SuiviRefuse('Action inconnue.')
                conn.commit()
                flash('Enregistrement effectué.', 'success')
                return redirect(url_for('.direct', annee=annee, secteur_id=sid))
            except SuiviRefuse as exc:
                conn.rollback()
                conn.execute('BEGIN')
                erreur, status = str(exc), 409
        try:
            data = suivi(conn, annee, sid, confidentiel=_gestion())
        except SuiviRefuse as exc:
            data, erreur = None, str(exc)
        versions = _versions(conn, annee) if _gestion() else []
        # PDF archivés complets réservés à direction/comptabilité. Les responsables
        # consultent le suivi sectoriel expurgé, jamais une archive nominative.
        archives = [dict(r) for r in conn.execute('SELECT id,date,secteur_id,revision FROM budget_instantanes WHERE annee=? ORDER BY date DESC,id', (annee,))] if _gestion() else []
        comptes = [r['compte_num'] for r in conn.execute("SELECT compte_num FROM plan_comptable_general WHERE compte_num LIKE '6%' OR compte_num LIKE '7%' ORDER BY compte_num")] if _gestion() else []
        return render_template('budget_suivi.html', annee=annee, data=data, erreur=erreur,
                               gestion=_gestion(), versions=versions, archives=archives, comptes=comptes), status
    except sqlite3.Error:
        conn.rollback()
        return 'Enregistrement indisponible. Rechargez avant de réessayer.', 503
    finally:
        conn.close()


@budget_suivi_bp.route('/budget/instantanes/<ident>/<mode>.pdf')
@login_required
def pdf(ident, mode):
    if not _gestion():
        abort(403)
    if mode not in ('synthese', 'detail'):
        abort(404)
    conn = get_db()
    try:
        row = conn.execute('SELECT * FROM budget_instantanes WHERE id=?', (ident,)).fetchone()
        if not row:
            abort(404)
        # La colonne provient de la liste fermée ci-dessus, jamais de SQL dynamique.
        return Response(row['pdf_' + mode], mimetype='application/pdf', headers={
            'Content-Disposition': f'attachment; filename="budget-{row["annee"]}-{mode}.pdf"',
            'Cache-Control': 'private, no-store'})
    finally:
        conn.close()
