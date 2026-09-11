"""Taux de charges du simulateur ; aucun commit ni modification des fiches RH."""
import json
from decimal import Decimal, InvalidOperation

from budget_calculs import BudgetRefuse, montant


def compte_charge(compte):
    return compte.startswith(('645', '646', '647', '648'))


def taux_actifs(donnees):
    actif = donnees.get('utiliser_taux_charges', False)
    if not isinstance(actif, bool):
        raise BudgetRefuse('option_taux_invalide')
    return actif


def taux_charges(value):
    if value is None or value == '':
        return None
    try:
        if isinstance(value, bool):
            raise ValueError
        taux = Decimal(str(value))
        if not taux.is_finite() or not 0 <= taux <= 100:
            raise ValueError
        return float(taux)
    except (InvalidOperation, ValueError, TypeError):
        raise BudgetRefuse('taux_charges_invalide') from None


def calculer_taux(donnees, lignes, ajouts, cee_total):
    """Pondère les taux par les bruts réellement simulés sur la période restante."""
    # Les taux inutilisés ne doivent pas empêcher de restaurer le mode habituel.
    if not taux_actifs(donnees):
        return None
    overrides = donnees.get('employes') if isinstance(donnees.get('employes'), dict) else {}
    ajouts_saisis = donnees.get('ajouts') if isinstance(donnees.get('ajouts'), list) else []
    brut = charges = 0.0

    def ajouter(total, valeur):
        nonlocal brut, charges
        taux = taux_charges(valeur)
        if total < 0:
            raise BudgetRefuse('brut_simule_negatif')
        if total and taux is None:
            raise BudgetRefuse('taux_charges_manquant')
        brut += total
        charges += total * (taux or 0) / 100

    for ligne in lignes:
        ov = overrides.get(str(ligne['id'])) or overrides.get(ligne['id']) or {}
        ajouter(ligne['total'], ov.get('taux_charges'))
    for ligne, saisie in zip(ajouts, (a for a in ajouts_saisis if isinstance(a, dict))):
        ajouter(ligne['total'], saisie.get('taux_charges'))
    ajouter(cee_total, donnees.get('taux_charges_cee'))
    montant(brut)
    montant(charges)
    return {'brut_simule': round(brut, 2), 'charges_simulees': round(charges, 2),
            'taux_moyen': charges / brut if brut > 0 else None}


def calculer_report(taux, brut_global, brut_reel, charges_reelles, arrete, compte):
    if not compte:
        raise BudgetRefuse('premier_645_requis')
    if arrete is None:
        raise BudgetRefuse('arrete_non_choisi')
    if arrete == 12:
        restant, prevues = 0, 0
    else:
        if brut_global is None:
            raise BudgetRefuse('brut_incomplet')
        restant = round(brut_global - brut_reel, 2)
        if restant < -0.01:
            raise BudgetRefuse('brut_inferieur_reel')
        restant = max(0, restant)
        if restant and taux['taux_moyen'] is None:
            raise BudgetRefuse('base_taux_absente')
        prevues = montant(restant * (taux['taux_moyen'] or 0))
    return {**taux, 'compte': compte, 'brut_restant': restant,
            'charges_reelles': montant(charges_reelles), 'charges_prevues': prevues,
            'total': montant(charges_reelles + prevues)}


def simulation_enregistree(conn, type_budget, annee, secteur_id):
    row = conn.execute('''SELECT donnees FROM budget_paie_simulations
        WHERE type_budget=? AND annee=? AND secteur_id=?''', (type_budget, annee, secteur_id)).fetchone()
    if not row:
        return {}
    try:
        data = json.loads(row['donnees'])
    except (ValueError, TypeError):
        raise BudgetRefuse('simulation_charges_invalide') from None
    if not isinstance(data, dict):
        raise BudgetRefuse('simulation_charges_invalide')
    return data


def memoriser_montants(conn, donnees, type_budget, annee, secteur_id, comptes):
    """Conserve aussi les nouveaux comptes apparus pendant l'utilisation des taux."""
    sauvegarde = donnees.setdefault('_charges_avant_taux', {})
    for compte in comptes:
        if not compte_charge(compte) or compte in sauvegarde:
            continue
        row = conn.execute('''SELECT valeur_temp, valeur_def FROM budget_prev_saisies
            WHERE type_budget=? AND annee=? AND secteur_id=? AND compte_num=?''',
            (type_budget, annee, secteur_id, compte)).fetchone()
        sauvegarde[compte] = dict(row) if row else {'valeur_temp': None, 'valeur_def': None}


def preparer_transition(conn, donnees, type_budget, annee, secteur_id, user_id, comptes):
    """La sauvegarde vient exclusivement du serveur, jamais du formulaire."""
    ancien = simulation_enregistree(conn, type_budget, annee, secteur_id)
    avant, apres = taux_actifs(ancien), taux_actifs(donnees)
    donnees = {k: v for k, v in donnees.items() if k != '_charges_avant_taux'}
    if apres:
        donnees['_charges_avant_taux'] = ancien.get('_charges_avant_taux', {}) if avant else {}
        memoriser_montants(conn, donnees, type_budget, annee, secteur_id, comptes)
    elif avant:
        sauvegarde = ancien.get('_charges_avant_taux', {})
        for compte in set(comptes) | set(sauvegarde):
            if not compte_charge(compte):
                continue
            valeurs = sauvegarde.get(compte, {})
            conn.execute('''INSERT INTO budget_prev_saisies
                (type_budget, annee, secteur_id, compte_num, valeur_temp, valeur_def, updated_by)
                VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(type_budget, annee, secteur_id, compte_num)
                DO UPDATE SET valeur_temp=excluded.valeur_temp, valeur_def=excluded.valeur_def,
                    updated_by=excluded.updated_by, updated_at=CURRENT_TIMESTAMP''',
                (type_budget, annee, secteur_id, compte,
                 montant(valeurs.get('valeur_temp'), nullable=True),
                 montant(valeurs.get('valeur_def'), nullable=True), user_id))
    return donnees
