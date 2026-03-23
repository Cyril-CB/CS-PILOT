"""
Blueprint compte_resultat_bp - Compte de Résultat / Bilan.

Fonctionnalités :
- Compte de Résultat : charges (6x) vs produits (7x), comparaison N / N-1
- Bilan simplifié : actif (2-5x) vs passif (1x + dettes 4x)
  Nécessite un import BI avec tous les comptes (classes 1-7).
- Sélection de l'année
- Import BI direct (réutilise l'endpoint /api/bilan/import-bi)
- Export PDF via impression navigateur
- Accessible aux profils directeur et comptable
"""
from datetime import datetime
from flask import (Blueprint, render_template, request, session,
                   redirect, url_for, flash, jsonify)
from database import get_db
from utils import login_required

compte_resultat_bp = Blueprint('compte_resultat_bp', __name__)

# Noms lisibles pour les catégories du Compte de Résultat (2 premiers chiffres)
NOMS_CAT_CR = {
    '60': 'Achats et variations de stocks',
    '61': 'Services extérieurs',
    '62': 'Autres services extérieurs',
    '63': 'Impôts, taxes et vers. assim.',
    '64': 'Charges de personnel',
    '65': 'Autres charges de gestion',
    '66': 'Charges financières',
    '67': 'Charges exceptionnelles',
    '68': 'Dotations aux amortissements',
    '69': 'Participation / Impôt sociétés',
    '70': 'Ventes de produits / services',
    '71': 'Production stockée',
    '72': 'Production immobilisée',
    '73': 'Produits des activités annexes',
    '74': "Subventions d'exploitation",
    '75': 'Autres produits de gestion',
    '76': 'Produits financiers',
    '77': 'Produits exceptionnels',
    '78': 'Reprises sur amortissements',
    '79': 'Transferts de charges',
}

# Noms lisibles pour les catégories du Bilan (2 premiers chiffres)
NOMS_CAT_BILAN = {
    # Actif
    '20': 'Immob. incorporelles',
    '21': 'Immob. corporelles',
    '22': 'Immob. mises en concession',
    '23': 'Immob. en cours',
    '26': 'Participations',
    '27': 'Autres immob. financières',
    '28': 'Amortissements des immob.',
    '29': 'Dépréciations immob.',
    '30': 'Stocks - mat. premières',
    '31': 'Stocks - en cours production',
    '33': 'En-cours de production',
    '35': 'Stocks - produits finis',
    '37': 'Stocks - marchandises',
    '39': 'Dépréciations stocks',
    '40': 'Fournisseurs et cptes rattachés',
    '41': 'Clients et cptes rattachés',
    '42': 'Personnel et cptes rattachés',
    '43': 'Organismes sociaux',
    '44': 'État et collectivités',
    '45': 'Groupe et associés',
    '46': 'Débiteurs / créditeurs divers',
    '47': 'Cptes transitoires ou attente',
    '48': 'Cptes de régularisation',
    '49': 'Dépréciations cptes tiers',
    '50': 'Valeurs mobilières de placement',
    '51': 'Banques, CCP, chèques postaux',
    '52': 'Instruments de trésorerie',
    '53': 'Caisses',
    '54': 'Régies d\'avance / accréditifs',
    '58': 'Virements internes',
    '59': 'Dépréciations trés. / VMP',
    # Passif
    '10': 'Capital et réserves',
    '11': 'Report à nouveau',
    '12': 'Résultat de l\'exercice',
    '13': 'Subventions d\'investissement',
    '14': 'Provisions réglementées',
    '15': 'Provisions pour risques et charges',
    '16': 'Emprunts et dettes financières',
    '17': 'Dettes rattachées à participations',
    '18': 'Comptes de liaison',
    '19': 'Dépréciations',
}


def _peut_acceder():
    return session.get('profil') in ('directeur', 'comptable')


def _get_libelles_pcg(conn):
    rows = conn.execute(
        'SELECT compte_num, libelle FROM plan_comptable_general'
    ).fetchall()
    return {r['compte_num']: r['libelle'] for r in rows}


def _aggregate_by_cat(rows, premiers, pcg):
    """Agrège les lignes par catégorie (2 premiers chiffres) pour les classes données."""
    cats = {}
    for r in rows:
        compte = r['compte_num']
        if not compte or compte[0] not in premiers:
            continue
        cat = compte[:2]
        montant = float(r['montant'] or 0)
        lib = pcg.get(compte) or r['libelle'] or compte
        if cat not in cats:
            cats[cat] = {'comptes': {}, 'total': 0.0}
        if compte not in cats[cat]['comptes']:
            cats[cat]['comptes'][compte] = {'libelle': lib, 'total': 0.0}
        cats[cat]['comptes'][compte]['total'] += montant
        cats[cat]['total'] += montant
    for cat in cats.values():
        cat['total'] = round(cat['total'], 2)
        for c in cat['comptes'].values():
            c['total'] = round(c['total'], 2)
    return cats


def _cr_for_year(conn, annee, pcg):
    """Calcule le Compte de Résultat pour une année."""
    rows = conn.execute(
        """SELECT compte_num, libelle, SUM(montant) as montant
           FROM bilan_fec_donnees
           WHERE annee = ? AND (compte_num LIKE '6%' OR compte_num LIKE '7%')
           GROUP BY compte_num""",
        (annee,)
    ).fetchall()
    charges = _aggregate_by_cat(rows, {'6'}, pcg)
    produits = _aggregate_by_cat(rows, {'7'}, pcg)
    total_charges = round(sum(c['total'] for c in charges.values()), 2)
    total_produits = round(sum(p['total'] for p in produits.values()), 2)
    return {
        'charges': charges,
        'produits': produits,
        'total_charges': total_charges,
        'total_produits': total_produits,
        'resultat': round(total_produits - total_charges, 2),
    }


def _bilan_for_year(conn, annee, pcg):
    """Calcule le Bilan simplifié pour une année."""
    rows = conn.execute(
        """SELECT compte_num, libelle, SUM(montant) as montant
           FROM bilan_fec_donnees
           WHERE annee = ? AND compte_num NOT LIKE '6%' AND compte_num NOT LIKE '7%'
           GROUP BY compte_num""",
        (annee,)
    ).fetchall()

    # Actif immobilisé : 2x  (montant = debit − credit, positif = actif)
    actif_immo = _aggregate_by_cat(rows, {'2'}, pcg)
    # Actif circulant : 3x (stocks) + 5x (trésorerie)
    actif_stocks = _aggregate_by_cat(rows, {'3'}, pcg)
    actif_tresorerie = _aggregate_by_cat(rows, {'5'}, pcg)
    # Tiers (4x) : montant positif → créance (actif), négatif → dette (passif)
    tiers_rows_actif = [
        {'compte_num': r['compte_num'], 'libelle': r['libelle'],
         'montant': r['montant']}
        for r in rows
        if r['compte_num'] and r['compte_num'][0] == '4' and (r['montant'] or 0) >= 0
    ]
    tiers_rows_passif = [
        {'compte_num': r['compte_num'], 'libelle': r['libelle'],
         'montant': abs(r['montant'] or 0)}
        for r in rows
        if r['compte_num'] and r['compte_num'][0] == '4' and (r['montant'] or 0) < 0
    ]
    actif_tiers = _aggregate_by_cat(tiers_rows_actif, {'4'}, pcg)
    passif_dettes_expl = _aggregate_by_cat(tiers_rows_passif, {'4'}, pcg)

    # Passif : 1x  (montant = credit − debit, positif = passif)
    passif_capitaux = _aggregate_by_cat(rows, {'1'}, pcg)

    total_actif_immo = round(sum(c['total'] for c in actif_immo.values()), 2)
    total_actif_stocks = round(sum(c['total'] for c in actif_stocks.values()), 2)
    total_actif_tiers = round(sum(c['total'] for c in actif_tiers.values()), 2)
    total_actif_tresorerie = round(sum(c['total'] for c in actif_tresorerie.values()), 2)
    total_passif_capitaux = round(sum(c['total'] for c in passif_capitaux.values()), 2)
    total_passif_dettes = round(sum(c['total'] for c in passif_dettes_expl.values()), 2)

    return {
        'actif_immo': actif_immo,
        'actif_stocks': actif_stocks,
        'actif_tiers': actif_tiers,
        'actif_tresorerie': actif_tresorerie,
        'passif_capitaux': passif_capitaux,
        'passif_dettes_expl': passif_dettes_expl,
        'total_actif_immo': total_actif_immo,
        'total_actif_stocks': total_actif_stocks,
        'total_actif_tiers': total_actif_tiers,
        'total_actif_tresorerie': total_actif_tresorerie,
        'total_passif_capitaux': total_passif_capitaux,
        'total_passif_dettes': total_passif_dettes,
        'total_actif': round(
            total_actif_immo + total_actif_stocks
            + total_actif_tiers + total_actif_tresorerie, 2),
        'total_passif': round(total_passif_capitaux + total_passif_dettes, 2),
    }


# ── Page principale ──────────────────────────────────────────────────────────

@compte_resultat_bp.route('/compte-resultat')
@login_required
def compte_resultat():
    """Affiche la page Compte de Résultat / Bilan."""
    if not _peut_acceder():
        flash('Accès non autorisé.', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    now = datetime.now()
    conn = get_db()
    try:
        annees_importees = conn.execute(
            'SELECT DISTINCT annee FROM bilan_fec_imports ORDER BY annee DESC'
        ).fetchall()
        annees_list = [r['annee'] for r in annees_importees]
        annee_courante = annees_list[0] if annees_list else now.year
        return render_template(
            'compte_resultat.html',
            annee_courante=annee_courante,
            annees_importees=annees_list,
        )
    finally:
        conn.close()


# ── API Compte de Résultat ────────────────────────────────────────────────────

@compte_resultat_bp.route('/api/cr/donnees')
@login_required
def api_cr_donnees():
    """Retourne le Compte de Résultat pour l'année N (et N-1 si disponible)."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    annee = request.args.get('annee', type=int)
    if not annee:
        return jsonify({'error': 'Année requise.'}), 400

    conn = get_db()
    try:
        pcg = _get_libelles_pcg(conn)
        data_n = _cr_for_year(conn, annee, pcg)
        data_n1 = _cr_for_year(conn, annee - 1, pcg)
        has_n1 = bool(data_n1['charges'] or data_n1['produits'])
        return jsonify({
            'annee': annee,
            'n': data_n,
            'n1': data_n1 if has_n1 else None,
            'noms_cat': NOMS_CAT_CR,
        })
    finally:
        conn.close()


# ── API Bilan ─────────────────────────────────────────────────────────────────

@compte_resultat_bp.route('/api/cr/bilan-donnees')
@login_required
def api_bilan_donnees():
    """Retourne le Bilan simplifié pour l'année N (et N-1 si disponible)."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    annee = request.args.get('annee', type=int)
    if not annee:
        return jsonify({'error': 'Année requise.'}), 400

    conn = get_db()
    try:
        pcg = _get_libelles_pcg(conn)
        data_n = _bilan_for_year(conn, annee, pcg)
        data_n1 = _bilan_for_year(conn, annee - 1, pcg)
        has_n = bool(
            data_n['actif_immo'] or data_n['passif_capitaux']
            or data_n['actif_tresorerie']
        )
        has_n1 = bool(
            data_n1['actif_immo'] or data_n1['passif_capitaux']
            or data_n1['actif_tresorerie']
        )
        return jsonify({
            'annee': annee,
            'n': data_n,
            'n1': data_n1 if has_n1 else None,
            'has_bilan': has_n,
            'noms_cat': NOMS_CAT_BILAN,
        })
    finally:
        conn.close()
