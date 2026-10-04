"""Construction volontaire du budget initial ; aucun effet sur les fiches RH."""
import sqlite3
from datetime import date
from decimal import Decimal

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


def _comptes(conn):
    return [dict(r) for r in conn.execute(
        'SELECT compte_num, libelle FROM plan_comptable_general ORDER BY compte_num')]


def _verifier_comptes(conn, annee, ligne):
    """Filtrer les nouveaux choix sans bloquer la reprise des anciens comptes."""
    if not isinstance(ligne, dict) or not isinstance(ligne.get('donnees'), dict):
        raise InitialRefuse('Ligne invalide.')
    d = ligne['donnees']
    ancienne = next((l['donnees'] for l in charger(conn, annee)['lignes']
                     if l['id'] == ligne.get('id')), {})
    codes = {r['compte_num'] for r in _comptes(conn)}
    nature, code = d.get('nature'), d.get('compte')

    def autorise(c, n):
        return isinstance(c, str) and c in codes and (
            (n == 'salaire' and c.startswith('641')) or
            (n == 'depense' and c.startswith('6') and not c.startswith(('63', '64'))) or
            (n == 'financement' and c.startswith('7')))

    conserve = ancienne.get('nature') == nature and ancienne.get('compte') == code
    if not conserve and not autorise(code, nature):
        raise InitialRefuse('Choisissez un compte du plan général : salaire 641, dépense 6 hors 63/64, financement 7.')
    if nature == 'salaire' and isinstance(d.get('complements'), list):
        anciens = {c['compte'] for c in ancienne.get('complements', [])}
        for c in d['complements']:
            if not isinstance(c, dict) or not isinstance(c.get('compte'), str) or (not autorise(c.get('compte'), 'salaire')
                                         and c.get('compte') not in anciens):
                raise InitialRefuse('Choisissez un compte 641 du plan général pour chaque complément.')


@budget_initial_bp.route('/api/budget-initial-detaille/alisfa')
@login_required
def alisfa():
    if not _autorise():
        return jsonify(error='Accès non autorisé.'), 403
    conn = get_db()
    try:
        from blueprints.budget import PAIE_DEFAULTS, _paie_anciennete_annees
        annee = _annee(request.args.get('annee'))
        ident = request.args.get('salarie_id', '')
        if not ident.isdigit() or len(ident) > 18:
            raise InitialRefuse('Choisissez un salarié existant.')
        conn.execute('BEGIN')
        user = conn.execute('SELECT pesee, competence, maintien FROM users WHERE id=?', (ident,)).fetchone()
        if user is None:
            raise InitialRefuse('Choisissez un salarié existant.')
        contrat = conn.execute('''SELECT date_debut, temps_hebdo FROM contrats
            WHERE user_id=? AND type_contrat!='CEE' AND date_debut<=?
              AND (date_fin IS NULL OR date_fin>=?) ORDER BY date_debut DESC, id DESC LIMIT 1''',
            (ident, f'{annee}-12-31', f'{annee}-01-01')).fetchone()
        valeurs = {**dict(user), 'socle': PAIE_DEFAULTS['salaire_socle'],
                   'point': PAIE_DEFAULTS['valeur_point'], 'anciennete': None, 'quotite': None}
        if contrat:
            try:
                date.fromisoformat(contrat['date_debut'])
                valeurs['anciennete'] = _paie_anciennete_annees(contrat['date_debut'], annee)
            except (ValueError, TypeError):
                pass
            if contrat['temps_hebdo'] is not None:
                valeurs['quotite'] = Decimal(str(contrat['temps_hebdo'])) * 100 / Decimal(str(PAIE_DEFAULTS['temps_plein']))
        return jsonify(serialisable({'valeurs': valeurs,
            'message': 'Copie budgétaire modifiable, sans écriture RH. Pesée, compétences et maintien : fiche salarié ; quotité et ancienneté au 1er janvier : dernier contrat hors CEE couvrant l’année. Socle et point : valeurs par défaut du simulateur, à vérifier. Les données absentes restent à compléter.'}))
    except InitialRefuse as exc:
        return jsonify(error=str(exc)), 400
    finally:
        conn.close()


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
    premier_645 = conn.execute("SELECT compte_num FROM plan_comptable_general WHERE compte_num LIKE '645%' ORDER BY compte_num LIMIT 1").fetchone()
    for sid in secteurs:
        # Garder aussi le compte d'une ancienne construction non encore reportée.
        charges[sid] = charges[sid] or min((l['donnees']['compte'] for l in etat['lignes']
            if sid in l['donnees']['secteurs'] and l['donnees']['compte'].startswith('645')),
            default=premier_645['compte_num'] if premier_645 else None)
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
                                     'salaries': salaries, 'comptes': _comptes(conn), 'calcul': calcul,
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
        secteurs, _, _ = _contexte(conn, annee)
        action = d.get('action')
        if action not in ('hypotheses', 'ligne', 'supprimer'):
            raise InitialRefuse('Action inconnue.')
        kwargs = {action: d.get(action)}
        if kwargs[action] is None:
            raise InitialRefuse('Saisie manquante.')
        if action == 'ligne':
            _verifier_comptes(conn, annee, kwargs[action])
        enregistrer(conn, annee, d.get('revision'), session['user_id'], secteurs, **kwargs)
        # Refus atomique d'une ventilation incohérente, même si le client est modifié.
        _calcul(conn, annee)
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
