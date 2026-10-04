"""Construction volontaire du budget initial ; aucun effet sur les fiches RH."""
import sqlite3
from datetime import date

from flask import Blueprint, jsonify, render_template, request, session
from database import get_db
from utils import login_required
from sessions_securite import verifier_action
from budget_initial import (
    InitialRefuse, calculer, charger, enregistrer, preparer_report, reporter, serialisable,
)

budget_initial_bp = Blueprint('budget_initial_bp', __name__)


def _annee(value):
    try:
        if isinstance(value, bool) or not str(value).isdigit():
            raise ValueError
        n = int(value)
        if not 1900 <= n <= 2200:
            raise ValueError
        return n
    except (TypeError, ValueError):
        raise InitialRefuse('Choisissez une année entre 1900 et 2200.') from None


def _autorise():
    # Les détails individuels et la ventilation intersectorielle sont réservés
    # aux mêmes profils que l'écriture du budget et des simulations de paie.
    return session.get('profil') in ('directeur', 'comptable')


def _contexte(conn, annee):
    from blueprints.budget import _compute_budget_previsionnel
    secteurs = {str(r['id']): r['nom'] for r in conn.execute('SELECT id, nom FROM secteurs ORDER BY nom')}
    bases, charges = {}, {}
    for sid in secteurs:
        data = _compute_budget_previsionnel(conn, 'initial', annee, int(sid))
        bases[sid] = data.get('salary_brut_account')
        charges[sid] = next((r['compte_num'] for r in data['rows'] if r['compte_num'].startswith('645')), None)
    return secteurs, bases, charges


def _calcul(conn, annee):
    etat = charger(conn, annee)
    secteurs, bases, charges = _contexte(conn, annee)
    calcul = calculer(annee, etat['hypotheses'], etat['lignes'], secteurs, bases, charges)
    return etat, secteurs, bases, calcul


@budget_initial_bp.route('/budget-initial-detaille')
@login_required
def construction():
    if not _autorise():
        return 'Accès non autorisé.', 403
    try:
        annee = _annee(request.args.get('annee', date.today().year))
    except InitialRefuse as exc:
        return str(exc), 400
    return render_template('budget_initial.html', annee=annee)


@budget_initial_bp.route('/api/budget-initial-detaille')
@login_required
def donnees():
    if not _autorise():
        return jsonify(error='Accès non autorisé.'), 403
    conn = get_db()
    try:
        conn.execute('BEGIN')
        annee = _annee(request.args.get('annee'))
        etat, secteurs, bases, calcul = _calcul(conn, annee)
        reports, reference = preparer_report(conn, annee, calcul)
        salaries = [dict(r) for r in conn.execute('SELECT id, nom, prenom, actif FROM users ORDER BY nom, prenom, id')]
        return jsonify(serialisable({**etat, 'secteurs': secteurs, 'premiers_641': bases,
                                     'salaries': salaries, 'calcul': calcul,
                                     'reports': reports, 'reference_report': reference}))
    except InitialRefuse as exc:
        return jsonify(error=str(exc)), 400
    finally:
        conn.close()


@budget_initial_bp.route('/api/budget-initial-detaille/enregistrer', methods=['POST'])
@login_required
def sauvegarder():
    if not _autorise():
        return jsonify(error='Accès non autorisé.'), 403
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        return jsonify(error='Formulaire invalide.'), 400
    conn = get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        refus = verifier_action(conn)
        if refus is not None:
            return refus
        if not _autorise():
            return jsonify(error='Accès non autorisé.'), 403
        annee = _annee(d.get('annee'))
        secteurs, bases, charges = _contexte(conn, annee)
        action = d.get('action')
        if action not in ('hypotheses', 'ligne', 'supprimer'):
            raise InitialRefuse('Action inconnue.')
        kwargs = {action: d.get(action)}
        if kwargs[action] is None:
            raise InitialRefuse('Saisie manquante.')
        enregistrer(conn, annee, d.get('revision'), session['user_id'], secteurs, **kwargs)
        # Refus atomique d'une ventilation incohérente, même si le client est modifié.
        etat = charger(conn, annee)
        calculer(annee, etat['hypotheses'], etat['lignes'], secteurs, bases, charges)
        conn.commit()
        return jsonify(success=True)
    except InitialRefuse as exc:
        conn.rollback()
        return jsonify(error=str(exc)), 409
    except sqlite3.Error:
        conn.rollback()
        return jsonify(error='Enregistrement indisponible. Rechargez avant de réessayer.'), 503
    finally:
        conn.close()


@budget_initial_bp.route('/api/budget-initial-detaille/reporter', methods=['POST'])
@login_required
def report():
    if not _autorise():
        return jsonify(error='Accès non autorisé.'), 403
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        return jsonify(error='Formulaire invalide.'), 400
    conn = get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        refus = verifier_action(conn)
        if refus is not None:
            return refus
        if not _autorise():
            return jsonify(error='Accès non autorisé.'), 403
        annee = _annee(d.get('annee'))
        _, _, _, calcul = _calcul(conn, annee)
        n = reporter(conn, annee, d.get('revision'), session['user_id'], calcul, d.get('reference_report'))
        conn.commit()
        return jsonify(success=True, reportes=n)
    except InitialRefuse as exc:
        conn.rollback()
        return jsonify(error=str(exc)), 409
    except sqlite3.Error:
        conn.rollback()
        return jsonify(error='Report indisponible. Rechargez avant de réessayer.'), 503
    finally:
        conn.close()
