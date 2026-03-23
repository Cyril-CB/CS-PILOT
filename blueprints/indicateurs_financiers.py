"""
Blueprint indicateurs_financiers_bp - Indicateurs financiers.

Calcule, pour chaque année disponible en base (import BI) :
  - Capitaux permanents          : somme des comptes 1x (crédit-normal)
  - Immobilisations nettes       : somme des comptes 2x (débit-normal, amortiss. inclus)
  - Fonds de roulement (FR)      : capitaux permanents − immobilisations nettes
  - FR en mois de charges        : FR / (total charges annuelles / 12)
  - Trésorerie nette             : somme des comptes 5x (débit-normal)
  - Trésorerie en mois           : trésorerie / (total charges / 12)
  - % Masse salariale            : somme 641xxx / total charges 6x × 100

Onglet "Fonds de roulement" : détail du calcul pour une année sélectionnée.

Accessible aux profils directeur et comptable.
"""
from flask import (Blueprint, render_template, request, session,
                   redirect, url_for, flash, jsonify)
from database import get_db
from utils import login_required

indicateurs_financiers_bp = Blueprint('indicateurs_financiers_bp', __name__)


def _peut_acceder():
    return session.get('profil') in ('directeur', 'comptable')


def _compute_indicateurs(conn, annee):
    """Calcule les indicateurs financiers pour une année."""
    rows = conn.execute(
        'SELECT compte_num, SUM(montant) as montant FROM bilan_fec_donnees '
        'WHERE annee = ? GROUP BY compte_num',
        (annee,)
    ).fetchall()

    capitaux = 0.0
    immos = 0.0
    tresorerie = 0.0
    total_charges = 0.0
    total_produits = 0.0
    masse_salariale = 0.0

    for r in rows:
        compte = r['compte_num']
        montant = float(r['montant'] or 0)
        if not compte:
            continue
        premier = compte[0]
        if premier == '1':
            capitaux += montant          # crédit-normal : positif = capital/dette LT
        elif premier == '2':
            immos += montant             # débit-normal  : positif = immobilisation nette
        elif premier == '5':
            tresorerie += montant        # débit-normal  : positif = disponibilités
        elif premier == '6':
            total_charges += montant     # débit-normal  : positif = charge
            if compte.startswith('64'):
                masse_salariale += montant
        elif premier == '7':
            total_produits += montant    # crédit-normal : positif = produit

    # Le résultat de l'exercice (7x − 6x) appartient aux capitaux permanents (12x).
    # Il n'est pas dans les comptes 1x du BI (entrée de clôture), on l'injecte ici.
    resultat = total_produits - total_charges
    capitaux += resultat

    charges_mensuelles = total_charges / 12 if total_charges else 0
    fonds_roulement = capitaux - immos
    fr_mois = (round(fonds_roulement / charges_mensuelles, 2)
               if charges_mensuelles else None)
    tres_mois = (round(tresorerie / charges_mensuelles, 2)
                 if charges_mensuelles else None)
    pct_masse_sal = (round(masse_salariale / total_charges * 100, 1)
                     if total_charges else None)

    return {
        'annee': annee,
        'capitaux_permanents': round(capitaux, 2),
        'immobilisations_nettes': round(immos, 2),
        'fonds_roulement': round(fonds_roulement, 2),
        'fr_mois': fr_mois,
        'tresorerie': round(tresorerie, 2),
        'tresorerie_mois': tres_mois,
        'pct_masse_salariale': pct_masse_sal,
        'total_charges': round(total_charges, 2),
        'masse_salariale': round(masse_salariale, 2),
    }


# ── Page principale ──────────────────────────────────────────────────────────

@indicateurs_financiers_bp.route('/indicateurs-financiers')
@login_required
def indicateurs_financiers():
    """Affiche la page Indicateurs financiers."""
    if not _peut_acceder():
        flash('Accès non autorisé.', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    try:
        annees_importees = conn.execute(
            'SELECT DISTINCT annee FROM bilan_fec_imports ORDER BY annee DESC'
        ).fetchall()
        annees_list = [r['annee'] for r in annees_importees]
        return render_template(
            'indicateurs_financiers.html',
            annees_importees=annees_list,
        )
    finally:
        conn.close()


# ── API tableau des indicateurs ──────────────────────────────────────────────

@indicateurs_financiers_bp.route('/api/indicateurs/donnees')
@login_required
def api_indicateurs_donnees():
    """Retourne les indicateurs pour toutes les années disponibles."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    conn = get_db()
    try:
        annees = conn.execute(
            'SELECT DISTINCT annee FROM bilan_fec_imports ORDER BY annee'
        ).fetchall()
        result = [_compute_indicateurs(conn, r['annee']) for r in annees]
        return jsonify({'indicateurs': result})
    finally:
        conn.close()


# ── API détail Fonds de Roulement ────────────────────────────────────────────

@indicateurs_financiers_bp.route('/api/indicateurs/fonds-roulement')
@login_required
def api_fonds_roulement_detail():
    """Retourne le détail du calcul du Fonds de Roulement pour une année."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    annee = request.args.get('annee', type=int)
    if not annee:
        return jsonify({'error': 'Année requise.'}), 400

    conn = get_db()
    try:
        pcg = {r['compte_num']: r['libelle']
               for r in conn.execute(
                   'SELECT compte_num, libelle FROM plan_comptable_general'
               ).fetchall()}

        rows = conn.execute(
            """SELECT compte_num, libelle, SUM(montant) as montant
               FROM bilan_fec_donnees
               WHERE annee = ? AND (compte_num LIKE '1%' OR compte_num LIKE '2%')
               GROUP BY compte_num
               ORDER BY compte_num""",
            (annee,)
        ).fetchall()

        capitaux_rows = []
        immo_rows = []
        for r in rows:
            compte = r['compte_num']
            if not compte:
                continue
            lib = pcg.get(compte) or r['libelle'] or compte
            entry = {
                'compte_num': compte,
                'libelle': lib,
                'montant': round(float(r['montant'] or 0), 2),
            }
            if compte[0] == '1':
                capitaux_rows.append(entry)
            elif compte[0] == '2':
                immo_rows.append(entry)

        total_capitaux = round(sum(r['montant'] for r in capitaux_rows), 2)
        total_immos = round(sum(r['montant'] for r in immo_rows), 2)

        # Charges et produits pour le résultat de l'exercice
        row_charges = conn.execute(
            "SELECT SUM(montant) as total FROM bilan_fec_donnees "
            "WHERE annee = ? AND compte_num LIKE '6%'",
            (annee,)
        ).fetchone()
        total_charges = float(row_charges['total'] or 0)

        row_produits = conn.execute(
            "SELECT SUM(montant) as total FROM bilan_fec_donnees "
            "WHERE annee = ? AND compte_num LIKE '7%'",
            (annee,)
        ).fetchone()
        total_produits = float(row_produits['total'] or 0)

        # Le résultat (7x − 6x) s'ajoute aux capitaux permanents (compte 12x)
        resultat = round(total_produits - total_charges, 2)
        if resultat != 0:
            compte_res = '120000' if resultat > 0 else '129000'
            lib_res = ('Résultat exercice créditeur' if resultat > 0
                       else 'Résultat exercice débiteur')
            capitaux_rows.append({
                'compte_num': compte_res,
                'libelle': lib_res,
                'montant': resultat,
            })
            total_capitaux = round(total_capitaux + resultat, 2)

        fonds_roulement = round(total_capitaux - total_immos, 2)
        charges_mensuelles = round(total_charges / 12, 2) if total_charges else 0
        fr_mois = (round(fonds_roulement / charges_mensuelles, 2)
                   if charges_mensuelles else None)

        return jsonify({
            'annee': annee,
            'capitaux_rows': capitaux_rows,
            'immo_rows': immo_rows,
            'total_capitaux': total_capitaux,
            'total_immos': total_immos,
            'fonds_roulement': fonds_roulement,
            'total_charges': round(total_charges, 2),
            'charges_mensuelles': charges_mensuelles,
            'fr_mois': fr_mois,
        })
    finally:
        conn.close()
