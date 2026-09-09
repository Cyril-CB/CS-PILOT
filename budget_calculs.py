"""Paramètres et calculs explicites des budgets (aucun commit dans les helpers)."""
import hashlib
import json
import math
from decimal import Decimal, InvalidOperation

from flask import current_app, session
from itsdangerous import BadSignature, URLSafeSerializer


MODES = {'manuel', 'proportionnel', 'mensuel'}


class BudgetRefuse(ValueError):
    pass


def creer_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS budget_parametres (
        type_budget TEXT NOT NULL CHECK(type_budget IN ('initial', 'actualise')),
        annee INTEGER NOT NULL, secteur_id INTEGER NOT NULL REFERENCES secteurs(id),
        mois_arrete INTEGER CHECK(mois_arrete BETWEEN 0 AND 12),
        annee_reference INTEGER, reference_empreinte TEXT,
        updated_by INTEGER REFERENCES users(id), updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(type_budget, annee, secteur_id))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS budget_modes_comptes (
        type_budget TEXT NOT NULL CHECK(type_budget IN ('initial', 'actualise')),
        annee INTEGER NOT NULL, secteur_id INTEGER NOT NULL REFERENCES secteurs(id),
        compte_num TEXT NOT NULL,
        mode TEXT NOT NULL CHECK(mode IN ('manuel', 'proportionnel', 'mensuel')),
        PRIMARY KEY(type_budget, annee, secteur_id, compte_num))''')
    # Les saisies existantes restent intactes, sans affirmation sur l'ancien import.


def montant(value, nullable=False):
    if value is None or value == '':
        return None if nullable else 0.0
    try:
        n = Decimal(str(value))
        if not n.is_finite() or abs(n) > Decimal('999999999999.99'):
            raise ValueError
        return float(n.quantize(Decimal('0.01')))
    except (InvalidOperation, ValueError, TypeError):
        raise BudgetRefuse('Montant invalide : indiquez un nombre fini en euros.') from None


def contexte_valide(conn, type_budget, annee, secteur_id):
    try:
        if isinstance(annee, bool) or isinstance(secteur_id, bool):
            raise ValueError
        annee, secteur_id = int(annee), int(secteur_id)
    except (ValueError, TypeError, OverflowError):
        raise BudgetRefuse('Année ou secteur invalide.') from None
    if type_budget not in ('initial', 'actualise') or not 1900 <= annee <= 2200:
        raise BudgetRefuse('Année ou type de budget invalide.')
    if not conn.execute('SELECT 1 FROM secteurs WHERE id=?', (secteur_id,)).fetchone():
        raise BudgetRefuse('Secteur introuvable.')
    return annee, secteur_id


def canonique(value):
    def normaliser(v):
        if isinstance(v, float) and not math.isfinite(v):
            return {'non_fini': str(v)}
        if isinstance(v, dict):
            return {str(k): normaliser(x) for k, x in v.items()}
        if isinstance(v, (tuple, list)):
            return [normaliser(x) for x in v]
        return v
    return json.dumps(normaliser(value), sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def empreinte(value):
    return hashlib.sha256(canonique(value).encode()).hexdigest()


def parametres(conn, type_budget, annee, secteur_id):
    row = conn.execute('SELECT * FROM budget_parametres WHERE type_budget=? AND annee=? AND secteur_id=?',
                       (type_budget, annee, secteur_id)).fetchone()
    return dict(row) if row else {
        'mois_arrete': 0 if type_budget == 'initial' else None,
        'annee_reference': None, 'reference_empreinte': None}


def mois_arrete(conn, type_budget, annee, secteur_id, obligatoire=False):
    if type_budget == 'initial':
        return 0
    mois = parametres(conn, type_budget, annee, secteur_id)['mois_arrete']
    if mois is None and obligatoire:
        raise BudgetRefuse('Choisissez le mois d’arrêté du réalisé dans les paramètres du budget.')
    return mois


def modes(conn, type_budget, annee, secteur_id):
    return {r['compte_num']: r['mode'] for r in conn.execute(
        'SELECT compte_num, mode FROM budget_modes_comptes WHERE type_budget=? AND annee=? AND secteur_id=?',
        (type_budget, annee, secteur_id))}


def donnees_reference(conn, annee, secteur_id):
    # Même périmètre canonique que le tableau et les détails comptables.
    from blueprints.budget import _secteur_allowed_codes, _code_allowed
    allowed = _secteur_allowed_codes(conn, secteur_id)
    rows = [dict(r) for r in conn.execute('''SELECT id, compte_num, code_analytique,
        annee, mois, montant, import_id FROM bilan_fec_donnees WHERE annee=?
        AND (compte_num LIKE '6%' OR compte_num LIKE '7%') ORDER BY id''', (annee,))
        if _code_allowed(r['code_analytique'], r['compte_num'], allowed)]
    totals = {}
    for r in rows:
        totals[r['compte_num']] = totals.get(r['compte_num'], 0.0) + montant(r['montant'])
    return {'empreinte': empreinte([sorted(allowed), rows]), 'totaux': totals,
            'mois': sorted({r['mois'] for r in rows if 1 <= r['mois'] <= 12}),
            'nb_lignes': len(rows)}


def reference_budget(conn, type_budget, annee, secteur_id):
    """Lie les formulaires à leur périmètre, leurs paramètres et leurs sources."""
    from blueprints.budget import _secteur_allowed_codes, _code_allowed, _paie_employes_secteur
    allowed = _secteur_allowed_codes(conn, secteur_id)
    p = parametres(conn, type_budget, annee, secteur_id)
    years = {annee - 2, annee - 1, annee}
    if p['annee_reference']:
        years.add(p['annee_reference'])
    years = sorted(years)
    placeholders = ','.join('?' for _ in years)
    fec = [tuple(r) for r in conn.execute(f'''SELECT id, compte_num, code_analytique,
        annee, mois, montant, import_id FROM bilan_fec_donnees WHERE annee IN ({placeholders}) ORDER BY id''', years)
        if _code_allowed(r['code_analytique'], r['compte_num'], allowed)]
    saisies = [tuple(r) for r in conn.execute('''SELECT * FROM budget_prev_saisies
        WHERE annee=? AND secteur_id=? ORDER BY type_budget, compte_num''', (annee, secteur_id))]
    fiches = [tuple(r) for r in conn.execute('''SELECT * FROM budget_fiches_travail
        WHERE annee=? AND secteur_id=? AND type_budget=? ORDER BY compte_num''', (annee, secteur_id, type_budget))]
    source = [session.get('user_id'), type_budget, annee, secteur_id, p,
              modes(conn, type_budget, annee, secteur_id), sorted(allowed), fec, saisies, fiches,
              _paie_employes_secteur(conn, secteur_id, annee)]
    return URLSafeSerializer(current_app.secret_key, salt='budget-v1').dumps(empreinte(source))


def verifier_reference(conn, token, type_budget, annee, secteur_id):
    if not isinstance(token, str):
        raise BudgetRefuse('Rechargez le budget avant d’enregistrer : référence de page absente ou invalide.')
    serializer = URLSafeSerializer(current_app.secret_key, salt='budget-v1')
    try:
        valeur = serializer.loads(token or '')
        attendu = serializer.loads(reference_budget(conn, type_budget, annee, secteur_id))
    except BadSignature:
        raise BudgetRefuse('Rechargez le budget avant d’enregistrer : référence de page absente ou invalide.') from None
    if valeur != attendu:
        raise BudgetRefuse('Le budget, ses paramètres ou ses sources ont changé. Rechargez avant d’enregistrer.')


def appliquer_calculs(conn, type_budget, annee, secteur_id, accounts):
    """Deux étages sans boucle : autres 641 / premier 641, puis charges / tous 641."""
    from blueprints.budget import _fiche_contexte, _compute_fiche_travail
    p = parametres(conn, type_budget, annee, secteur_id)
    selected = modes(conn, type_budget, annee, secteur_id)
    base = next((r['compte_num'] for r in accounts if r['compte_num'].startswith('641')), None)
    by_num = {r['compte_num']: r for r in accounts}
    ref = donnees_reference(conn, p['annee_reference'], secteur_id) if p['annee_reference'] else None
    ref_ok = bool(ref and ref['nb_lignes'] and p['reference_empreinte'] == ref['empreinte'])
    reference_totals = ref['totaux'] if ref else {}
    arrete = p['mois_arrete'] if type_budget == 'actualise' else 0
    alerts = []
    if arrete is None:
        alerts.append('Choisissez le mois d’arrêté du réalisé.')

    def ratio(compte, denom):
        if not ref_ok:
            raise BudgetRefuse('Confirmez une année de référence complète ; son import doit rester inchangé.')
        if compte not in reference_totals or denom <= 0:
            raise BudgetRefuse('Référence annuelle absente ou brut de référence nul. Choisissez un autre mode.')
        return reference_totals[compte] / denom

    def proportion(row, restant, denom):
        if arrete is None:
            raise BudgetRefuse('Mois d’arrêté non choisi.')
        if arrete == 12:
            return row['N']
        taux = ratio(row['compte_num'], denom)
        row['taux'] = taux
        row['reference_montant'] = round(reference_totals[row['compte_num']], 2)
        row['reference_brut'] = round(denom, 2)
        if restant is None:
            raise BudgetRefuse('Complétez le brut de base et les autres comptes 641 avant le calcul des charges.')
        if restant < -0.01:
            raise BudgetRefuse('Le brut annuel prévu est inférieur au brut déjà réalisé. Vérifiez les montants 641.')
        return round((row['N'] if type_budget == 'actualise' else 0) + restant * taux, 2)

    for r in accounts:
        c = r['compte_num']
        r['mode'] = 'base' if c == base else selected.get(c, 'manuel') if c.startswith(('63', '64')) else None
        r['calcul_erreur'] = None
        r['taux'] = r['reference_montant'] = r['reference_brut'] = None
        if r['mode'] in ('base', 'manuel'):
            # Une saisie définitive a priorité sur une ancienne aide temporaire.
            r['temp'] = r['def'] if r['def'] is not None else (r['temp'] if r['mode'] == 'base' else None)
        if r['mode'] == 'mensuel':
            fiche = conn.execute('''SELECT donnees FROM budget_fiches_travail
                WHERE type_budget=? AND annee=? AND secteur_id=? AND compte_num=?''',
                (type_budget, annee, secteur_id, c)).fetchone()
            try:
                if not fiche:
                    raise BudgetRefuse('Complétez la projection mensuelle de ce compte.')
                if arrete is None:
                    raise BudgetRefuse('Mois d’arrêté non choisi.')
                cx = _fiche_contexte(conn, c, annee, secteur_id, type_budget)
                r['temp'] = _compute_fiche_travail(json.loads(fiche['donnees']), cx)['total']
            except (ValueError, TypeError) as exc:
                r['temp'] = None
                r['calcul_erreur'] = str(exc) if isinstance(exc, BudgetRefuse) else 'Projection mensuelle invalide.'

    base_row = by_num.get(base)
    base_annuel = base_row['def'] if base_row else None
    restant_base = (base_annuel - (base_row['N'] if type_budget == 'actualise' else 0)) if base_annuel is not None else None
    for r in accounts:
        if r['mode'] == 'proportionnel' and r['compte_num'].startswith('641'):
            try:
                r['temp'] = proportion(r, restant_base, reference_totals.get(base, 0))
            except BudgetRefuse as exc:
                r['temp'], r['calcul_erreur'] = None, str(exc)

    bruts = [r for r in accounts if r['compte_num'].startswith('641')]
    valeurs = [r['temp'] if r['mode'] in ('proportionnel', 'mensuel') else r['def'] for r in bruts]
    brut_global = round(sum(valeurs), 2) if bruts and all(v is not None for v in valeurs) else None
    brut_reel = sum(r['N'] for r in bruts) if type_budget == 'actualise' else 0
    restant_global = brut_global - brut_reel if brut_global is not None else None
    denom_global = sum(v for c, v in reference_totals.items() if c.startswith('641'))
    for r in accounts:
        if r['mode'] == 'proportionnel' and not r['compte_num'].startswith('641'):
            try:
                r['temp'] = proportion(r, restant_global, denom_global)
            except BudgetRefuse as exc:
                r['temp'], r['calcul_erreur'] = None, str(exc)
        if r['calcul_erreur']:
            alerts.append(f"{r['compte_num']} : {r['calcul_erreur']}")
        r['a_recalculer'] = r['mode'] in ('mensuel', 'proportionnel') and (
            r['temp'] is None or r['def'] is None or abs(r['temp'] - r['def']) >= 0.005)
        if r['a_recalculer'] and not r['calcul_erreur']:
            alerts.append(f"{r['compte_num']} : projection modifiée, cliquez sur Recalculer et reporter.")
    return {'salary_brut_account': base, 'salary_ratios': {}, 'brut_global': brut_global,
            'brut_reel': round(brut_reel, 2), 'alertes': alerts,
            'parametres': {**p, 'reference_valide': ref_ok,
                           'reference_mois': ref['mois'] if ref else [],
                           'reference_nb_lignes': ref['nb_lignes'] if ref else 0}}


def reporter_automatiques(conn, type_budget, annee, secteur_id, user_id):
    from blueprints.budget import _compute_budget_previsionnel
    data = _compute_budget_previsionnel(conn, type_budget, annee, secteur_id)
    reports = {}
    for r in data['rows']:
        if r['mode'] not in ('proportionnel', 'mensuel') or r['temp'] is None:
            continue
        conn.execute('''INSERT INTO budget_prev_saisies
            (type_budget, annee, secteur_id, compte_num, valeur_def, updated_by)
            VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(type_budget, annee, secteur_id, compte_num)
            DO UPDATE SET valeur_def=excluded.valeur_def, updated_by=excluded.updated_by,
                updated_at=CURRENT_TIMESTAMP''', (type_budget, annee, secteur_id, r['compte_num'], r['temp'], user_id))
        reports[r['compte_num']] = r['temp']
    return reports
