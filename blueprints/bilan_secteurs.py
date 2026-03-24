"""
Blueprint bilan_secteurs_bp - Bilan secteurs/actions.

Fonctionnalites :
- Import BI (export comptable) avec extraction des comptes 6x (charges)
  et 7x (produits) avec code analytique, annee, mois, libelle, montants
- Suppression des donnees d'une annee pour reimport
- Filtrage par annee, secteur (optionnel), action (optionnel)
- Affichage du compte de resultat : charges a gauche, produits a droite
  avec regroupement par categorie (60x, 61x, 62x, etc.)
- Detail des operations par compte (modal)
- Taux de logistique (site1, site2, global) par annee avec selection
- Calcul du resultat avec et sans logistique
- Export PDF du bilan
- Accessible aux profils directeur et comptable
"""
import csv
import io
from datetime import datetime
from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, jsonify, make_response)
from database import get_db
from utils import login_required

bilan_secteurs_bp = Blueprint('bilan_secteurs_bp', __name__)

NOMS_MOIS = ['', 'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
             'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']


def _peut_acceder():
    return session.get('profil') in ('directeur', 'comptable')


def _get_libelles_pcg(conn):
    """Retourne un dict {compte_num: libelle} depuis le plan comptable general."""
    rows = conn.execute('SELECT compte_num, libelle FROM plan_comptable_general').fetchall()
    return {row['compte_num']: row['libelle'] for row in rows}


# ── Page principale ──────────────────────────────────────────────────────────

@bilan_secteurs_bp.route('/bilan-secteurs')
@login_required
def bilan_secteurs():
    """Affiche le bilan secteurs/actions."""
    if not _peut_acceder():
        flash('Accès non autorisé.', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    now = datetime.now()
    annee_courante = now.year
    annees = list(range(annee_courante - 3, annee_courante + 2))

    conn = get_db()
    try:
        secteurs = conn.execute('SELECT id, nom FROM secteurs ORDER BY nom').fetchall()
        actions = conn.execute('SELECT id, nom FROM comptabilite_actions ORDER BY nom').fetchall()

        # Annees ayant des donnees importees
        annees_importees = conn.execute(
            'SELECT DISTINCT annee FROM bilan_fec_imports ORDER BY annee DESC'
        ).fetchall()

        return render_template('bilan_secteurs.html',
                               annees=annees, annee_courante=annee_courante,
                               secteurs=secteurs, actions=actions,
                               annees_importees=[r['annee'] for r in annees_importees])
    finally:
        conn.close()


# ── Import BI (export comptable) ─────────────────────────────────────────────

def _parse_date_bi(date_str):
    """Parse une date au format DD/MM/YYYY, DD/MM/YY ou YYYYMMDD.

    Retourne (annee, mois) ou None si format non reconnu.
    """
    date_str = date_str.strip()
    if '/' in date_str:
        parts = date_str.split('/')
        if len(parts) == 3:
            try:
                annee = int(parts[2])
                if annee < 100:
                    annee += 2000
                return annee, int(parts[1])
            except (ValueError, IndexError):
                return None
    elif len(date_str) == 8 and date_str.isdigit():
        try:
            return int(date_str[:4]), int(date_str[4:6])
        except (ValueError, IndexError):
            return None
    return None


@bilan_secteurs_bp.route('/api/bilan/import-bi', methods=['POST'])
@login_required
def api_import_bi():
    """Importe un fichier BI (export comptable) pour le bilan secteurs/actions.

    Colonnes attendues (separateur tabulation ou point-virgule) :
    Code journal | Date de pièce | Numéro de pièce | Numéro de facture |
    Numéro de règlement | Numéro de compte général | Numéro de compte tiers |
    Intitulé compte tiers | Libellé écriture | Libellé du compte analytique |
    Montant Débit | Montant Crédit | Mode de règlement | Date d'échéance |
    Type d'écriture | Compte analytique | Lettrage
    """
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    fichier = request.files.get('fichier')
    if not fichier or not fichier.filename:
        return jsonify({'error': 'Aucun fichier fourni.'}), 400

    try:
        content = fichier.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        try:
            fichier.seek(0)
            content = fichier.read().decode('latin-1')
        except Exception:
            return jsonify({'error': 'Encodage du fichier non reconnu.'}), 400

    # Detecter le separateur
    first_line = content.split('\n')[0] if content else ''
    if '\t' in first_line:
        delimiter = '\t'
    elif ';' in first_line:
        delimiter = ';'
    else:
        delimiter = '\t'

    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)

    conn = get_db()
    try:
        nb_ecritures = 0
        annee_val = None
        rows_to_insert = []

        for row in reader:
            # Colonnes BI
            compte_num = (row.get('Numéro de compte général')
                          or row.get('Numero de compte general')
                          or '').strip()
            if not compte_num:
                continue

            # Classes 1-7 : bilan (1-5) et compte de résultat (6-7)
            # Les classes 8, 9 et 0 sont ignorées (analytique, hors bilan)
            premier = compte_num[0] if compte_num else ''
            if premier not in ('1', '2', '3', '4', '5', '6', '7'):
                continue

            date_str = (row.get('Date de pièce')
                        or row.get('Date de piece')
                        or '').strip()
            parsed = _parse_date_bi(date_str)
            if parsed is None:
                continue
            annee, mois = parsed

            if mois < 1 or mois > 12:
                continue

            debit_str = (row.get('Montant Débit')
                         or row.get('Montant Debit')
                         or '0').strip().replace(',', '.')
            credit_str = (row.get('Montant Crédit')
                          or row.get('Montant Credit')
                          or '0').strip().replace(',', '.')
            try:
                debit = float(debit_str) if debit_str else 0
                credit = float(credit_str) if credit_str else 0
            except ValueError:
                debit = 0
                credit = 0

            # Calcul du montant selon la nature du compte :
            # - Comptes débit-normal (2, 3, 4, 5, 6) : debit - credit
            # - Comptes crédit-normal (1, 7)          : credit - debit
            if premier in ('1', '7'):
                montant = credit - debit
            else:
                montant = debit - credit

            libelle = (row.get('Libellé écriture')
                       or row.get('Libelle ecriture')
                       or '').strip()
            code_analytique = (row.get('Compte analytique')
                               or row.get('Compte Analytique')
                               or '').strip()

            # Règle métier : les comptes 6x/7x ont toujours une double entrée
            # dans le BI — une ligne 'G' (général, sans code analytique) et une
            # ligne 'A' (analytique, avec code analytique et même montant).
            # On n'importe que la ligne analytique ('A') pour éviter le doublon.
            # Les comptes 1x-5x n'ont jamais de code analytique : on les importe
            # tels quels.
            if premier in ('6', '7') and not code_analytique:
                continue

            if annee_val is None:
                annee_val = annee

            rows_to_insert.append({
                'compte_num': compte_num,
                'libelle': libelle,
                'code_analytique': code_analytique,
                'annee': annee,
                'mois': mois,
                'montant': round(montant, 2),
            })
            nb_ecritures += 1

        if nb_ecritures == 0:
            return jsonify({'error': 'Aucune écriture trouvée dans le fichier (classes 1 à 7 attendues).'}), 400

        # Supprimer les données existantes pour cette année (évite les doublons en cas de ré-import)
        cursor = conn.cursor()
        anciens_imports = conn.execute(
            'SELECT id FROM bilan_fec_imports WHERE annee = ?', (annee_val,)
        ).fetchall()
        for imp in anciens_imports:
            cursor.execute('DELETE FROM bilan_fec_donnees WHERE import_id = ?', (imp['id'],))
        cursor.execute('DELETE FROM bilan_fec_imports WHERE annee = ?', (annee_val,))

        # Enregistrer le nouvel import
        cursor.execute('''
            INSERT INTO bilan_fec_imports (fichier_nom, annee, nb_ecritures, importe_par)
            VALUES (?, ?, ?, ?)
        ''', (fichier.filename, annee_val, nb_ecritures, session.get('user_id')))
        import_id = cursor.lastrowid

        # Inserer les donnees
        for r in rows_to_insert:
            cursor.execute('''
                INSERT INTO bilan_fec_donnees
                (compte_num, libelle, code_analytique, annee, mois, montant, import_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (r['compte_num'], r['libelle'], r['code_analytique'],
                  r['annee'], r['mois'], r['montant'], import_id))

        conn.commit()

        return jsonify({
            'success': True,
            'message': f'{nb_ecritures} écritures importées pour {annee_val}.',
            'nb_ecritures': nb_ecritures,
            'annee': annee_val,
        })
    finally:
        conn.close()


# ── Suppression donnees d'une annee ──────────────────────────────────────────

@bilan_secteurs_bp.route('/api/bilan/annee/<int:annee>', methods=['DELETE'])
@login_required
def api_supprimer_annee(annee):
    """Supprime toutes les donnees FEC d'une annee."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    conn = get_db()
    try:
        # Recuperer les imports de cette annee
        imports = conn.execute(
            'SELECT id FROM bilan_fec_imports WHERE annee = ?', (annee,)
        ).fetchall()

        for imp in imports:
            conn.execute('DELETE FROM bilan_fec_donnees WHERE import_id = ?', (imp['id'],))

        conn.execute('DELETE FROM bilan_fec_imports WHERE annee = ?', (annee,))
        conn.commit()

        return jsonify({'success': True, 'message': f'Données {annee} supprimées.'})
    finally:
        conn.close()


# ── Donnees du bilan (API JSON) ──────────────────────────────────────────────

@bilan_secteurs_bp.route('/api/bilan/donnees')
@login_required
def api_bilan_donnees():
    """Retourne les donnees du bilan pour une annee/secteur/action."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    annee = request.args.get('annee', type=int)
    secteur_id = request.args.get('secteur_id', type=int)
    action_id = request.args.get('action_id', type=int)

    if not annee:
        return jsonify({'error': 'Année requise.'}), 400

    if not secteur_id and not action_id:
        return jsonify({'error': 'Sélectionnez un secteur et/ou une action.'}), 400

    conn = get_db()
    try:
        # Construire le filtre secteur/action
        compte_filter_parts = []
        params = [annee]

        if secteur_id and action_id:
            compte_filter_parts.append('c.secteur_id = ? AND c.action_id = ?')
            params.extend([secteur_id, action_id])
        elif secteur_id:
            compte_filter_parts.append('c.secteur_id = ?')
            params.append(secteur_id)
        else:
            compte_filter_parts.append('c.action_id = ?')
            params.append(action_id)

        compte_filter = ' AND '.join(compte_filter_parts)

        # Recuperer les donnees FEC liees aux comptes du plan comptable analytique.
        # Correspondance par prefixe : le compte_num du plan analytique peut etre
        # un prefixe du compte FEC (ex: "601" correspond a "601000", "601100", etc.)
        # ou une correspondance exacte sur le code analytique du FEC.
        all_donnees = conn.execute(f'''
            SELECT d.id, d.compte_num, d.libelle, d.mois, d.montant
            FROM bilan_fec_donnees d
            WHERE d.annee = ?
            AND EXISTS (
                SELECT 1 FROM comptabilite_comptes c
                WHERE {compte_filter}
                AND (d.compte_num LIKE c.compte_num || '%'
                     OR d.code_analytique = c.compte_num)
            )
        ''', params).fetchall()

        # Regrouper par categorie
        charges = {}  # {'60': {'nom': 'Achats', 'total': 0, 'comptes': {}}, ...}
        produits = {}
        detail_comptes = {}  # {compte_num: [{'mois': 1, 'libelle': '...', 'montant': 100}, ...]}

        # Utiliser le plan comptable general pour les libelles de comptes
        pcg = _get_libelles_pcg(conn)

        for d in all_donnees:
            compte = d['compte_num']
            premier = compte[0]
            categorie = compte[:2]  # 60, 61, 62, 70, 71, etc.

            montant = d['montant']
            libelle_compte = pcg.get(compte) or d['libelle'] or compte

            # Detail par compte
            if compte not in detail_comptes:
                detail_comptes[compte] = {'libelle': libelle_compte, 'operations': []}
            detail_comptes[compte]['operations'].append({
                'annee': annee,
                'mois': d['mois'],
                'mois_nom': NOMS_MOIS[d['mois']] if d['mois'] <= 12 else str(d['mois']),
                'libelle': d['libelle'] or '',
                'montant': montant,
            })

            if premier == '6':
                if categorie not in charges:
                    charges[categorie] = {'comptes': {}, 'total': 0}
                if compte not in charges[categorie]['comptes']:
                    charges[categorie]['comptes'][compte] = {
                        'libelle': libelle_compte, 'total': 0}
                charges[categorie]['comptes'][compte]['total'] += montant
                charges[categorie]['total'] += montant
            elif premier == '7':
                if categorie not in produits:
                    produits[categorie] = {'comptes': {}, 'total': 0}
                if compte not in produits[categorie]['comptes']:
                    produits[categorie]['comptes'][compte] = {
                        'libelle': libelle_compte, 'total': 0}
                produits[categorie]['comptes'][compte]['total'] += montant
                produits[categorie]['total'] += montant

        # Arrondir les totaux
        total_charges = round(sum(c['total'] for c in charges.values()), 2)
        total_produits = round(sum(p['total'] for p in produits.values()), 2)

        for cat in charges.values():
            cat['total'] = round(cat['total'], 2)
            for c in cat['comptes'].values():
                c['total'] = round(c['total'], 2)
        for cat in produits.values():
            cat['total'] = round(cat['total'], 2)
            for c in cat['comptes'].values():
                c['total'] = round(c['total'], 2)

        # Taux de logistique
        taux_row = conn.execute(
            'SELECT * FROM bilan_taux_logistique WHERE annee = ?', (annee,)
        ).fetchone()
        taux = {
            'taux_site1': taux_row['taux_site1'] if taux_row else 0,
            'taux_site2': taux_row['taux_site2'] if taux_row else 0,
            'taux_global': taux_row['taux_global'] if taux_row else 0,
            'taux_selectionne': taux_row['taux_selectionne'] if taux_row else 'global',
        }

        return jsonify({
            'charges': charges,
            'produits': produits,
            'total_charges': total_charges,
            'total_produits': total_produits,
            'detail_comptes': detail_comptes,
            'taux': taux,
        })
    finally:
        conn.close()


# ── Detail operations d'un compte ────────────────────────────────────────────

@bilan_secteurs_bp.route('/api/bilan/detail-compte')
@login_required
def api_detail_compte():
    """Retourne le detail des operations d'un compte."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    annee = request.args.get('annee', type=int)
    compte_num = request.args.get('compte_num', '')
    secteur_id = request.args.get('secteur_id', type=int)
    action_id = request.args.get('action_id', type=int)

    if not annee or not compte_num:
        return jsonify({'error': 'Paramètres manquants.'}), 400

    conn = get_db()
    try:
        # Construire le filtre secteur/action
        compte_filter_parts = []
        params = [annee, compte_num]

        if secteur_id and action_id:
            compte_filter_parts.append('c.secteur_id = ? AND c.action_id = ?')
            params.extend([secteur_id, action_id])
        elif secteur_id:
            compte_filter_parts.append('c.secteur_id = ?')
            params.append(secteur_id)
        elif action_id:
            compte_filter_parts.append('c.action_id = ?')
            params.append(action_id)
        else:
            return jsonify({'operations': []})

        compte_filter = ' AND '.join(compte_filter_parts)

        operations = conn.execute(f'''
            SELECT d.annee, d.mois, d.libelle, d.montant
            FROM bilan_fec_donnees d
            WHERE d.annee = ? AND d.compte_num = ?
            AND EXISTS (
                SELECT 1 FROM comptabilite_comptes c
                WHERE {compte_filter}
                AND (d.compte_num LIKE c.compte_num || '%'
                     OR d.code_analytique = c.compte_num)
            )
            ORDER BY d.mois
        ''', params).fetchall()

        result = []
        for op in operations:
            result.append({
                'annee': op['annee'],
                'mois': op['mois'],
                'mois_nom': NOMS_MOIS[op['mois']] if op['mois'] <= 12 else str(op['mois']),
                'libelle': op['libelle'] or '',
                'montant': op['montant'],
            })

        return jsonify({'operations': result})
    finally:
        conn.close()


# ── Taux de logistique ───────────────────────────────────────────────────────

@bilan_secteurs_bp.route('/api/bilan/taux-logistique', methods=['POST'])
@login_required
def api_save_taux_logistique():
    """Sauvegarde les taux de logistique pour une annee."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    data = request.get_json() or {}
    annee = data.get('annee')
    taux_site1 = data.get('taux_site1', 0)
    taux_site2 = data.get('taux_site2', 0)
    taux_global = data.get('taux_global', 0)
    taux_selectionne = data.get('taux_selectionne', 'global')

    if not annee:
        return jsonify({'error': 'Année requise.'}), 400

    # Valider le taux selectionne
    if taux_selectionne not in ('site1', 'site2', 'global'):
        taux_selectionne = 'global'

    try:
        taux_site1 = float(str(taux_site1).replace(',', '.')) if taux_site1 else 0
        taux_site2 = float(str(taux_site2).replace(',', '.')) if taux_site2 else 0
        taux_global = float(str(taux_global).replace(',', '.')) if taux_global else 0
    except (ValueError, TypeError):
        return jsonify({'error': 'Taux invalides.'}), 400

    conn = get_db()
    try:
        conn.execute('''
            INSERT INTO bilan_taux_logistique (annee, taux_site1, taux_site2, taux_global, taux_selectionne)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(annee) DO UPDATE SET
                taux_site1 = ?, taux_site2 = ?, taux_global = ?, taux_selectionne = ?,
                updated_at = CURRENT_TIMESTAMP
        ''', (annee, taux_site1, taux_site2, taux_global, taux_selectionne,
              taux_site1, taux_site2, taux_global, taux_selectionne))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


# ── Export PDF ───────────────────────────────────────────────────────────────

NOMS_CATEGORIES = {
    '60': 'Achats', '61': 'Services extérieurs', '62': 'Autres services ext.',
    '63': 'Impôts et taxes', '64': 'Charges de personnel',
    '65': 'Autres charges de gestion', '66': 'Charges financières',
    '67': 'Charges exceptionnelles', '68': 'Dotations amort.',
    '70': 'Ventes/prestations', '71': 'Production stockée',
    '72': 'Production immobilisée', '73': 'Produits nets partiels',
    '74': 'Subventions', '75': 'Autres produits de gestion',
    '76': 'Produits financiers', '77': 'Produits exceptionnels',
    '78': 'Reprises amort.', '79': 'Transferts de charges',
}


def _fmt(n):
    """Formate un nombre en style français : 1 234,56."""
    return f'{n:,.2f}'.replace(',', '\xa0').replace('.', ',')


@bilan_secteurs_bp.route('/api/bilan/export-pdf')
@login_required
def api_export_pdf():
    """Génère un PDF du bilan secteurs/actions."""
    if not _peut_acceder():
        flash('Accès non autorisé.', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    annee = request.args.get('annee', type=int)
    secteur_id = request.args.get('secteur_id', type=int)
    action_id = request.args.get('action_id', type=int)
    taux_selectionne = request.args.get('taux_selectionne', 'global')

    if not annee:
        flash('Année requise.', 'error')
        return redirect(url_for('bilan_secteurs_bp.bilan_secteurs'))

    if not secteur_id and not action_id:
        flash('Sélectionnez un secteur ou une action.', 'error')
        return redirect(url_for('bilan_secteurs_bp.bilan_secteurs'))

    conn = get_db()
    try:
        # --- Recuperer les donnees (meme logique que api_bilan_donnees) ---
        compte_filter_parts = []
        params = [annee]

        if secteur_id and action_id:
            compte_filter_parts.append('c.secteur_id = ? AND c.action_id = ?')
            params.extend([secteur_id, action_id])
        elif secteur_id:
            compte_filter_parts.append('c.secteur_id = ?')
            params.append(secteur_id)
        else:
            compte_filter_parts.append('c.action_id = ?')
            params.append(action_id)

        compte_filter = ' AND '.join(compte_filter_parts)

        all_donnees = conn.execute(f'''
            SELECT d.id, d.compte_num, d.libelle, d.mois, d.montant
            FROM bilan_fec_donnees d
            WHERE d.annee = ?
            AND EXISTS (
                SELECT 1 FROM comptabilite_comptes c
                WHERE {compte_filter}
                AND (d.compte_num LIKE c.compte_num || '%'
                     OR d.code_analytique = c.compte_num)
            )
        ''', params).fetchall()

        charges = {}
        produits = {}

        # Utiliser le plan comptable general pour les libelles de comptes
        pcg = _get_libelles_pcg(conn)

        for d in all_donnees:
            compte = d['compte_num']
            premier = compte[0]
            categorie = compte[:2]
            montant = d['montant']
            libelle_compte = pcg.get(compte) or d['libelle'] or compte

            if premier == '6':
                if categorie not in charges:
                    charges[categorie] = {'comptes': {}, 'total': 0}
                if compte not in charges[categorie]['comptes']:
                    charges[categorie]['comptes'][compte] = {
                        'libelle': libelle_compte, 'total': 0}
                charges[categorie]['comptes'][compte]['total'] += montant
                charges[categorie]['total'] += montant
            elif premier == '7':
                if categorie not in produits:
                    produits[categorie] = {'comptes': {}, 'total': 0}
                if compte not in produits[categorie]['comptes']:
                    produits[categorie]['comptes'][compte] = {
                        'libelle': libelle_compte, 'total': 0}
                produits[categorie]['comptes'][compte]['total'] += montant
                produits[categorie]['total'] += montant

        total_charges = round(sum(c['total'] for c in charges.values()), 2)
        total_produits = round(sum(p['total'] for p in produits.values()), 2)

        for cat in charges.values():
            cat['total'] = round(cat['total'], 2)
            for c in cat['comptes'].values():
                c['total'] = round(c['total'], 2)
        for cat in produits.values():
            cat['total'] = round(cat['total'], 2)
            for c in cat['comptes'].values():
                c['total'] = round(c['total'], 2)

        # Taux de logistique
        taux_row = conn.execute(
            'SELECT * FROM bilan_taux_logistique WHERE annee = ?', (annee,)
        ).fetchone()

        taux_val = 0
        if taux_row:
            if taux_selectionne == 'site1':
                taux_val = taux_row['taux_site1']
            elif taux_selectionne == 'site2':
                taux_val = taux_row['taux_site2']
            else:
                taux_val = taux_row['taux_global']

        logistique = total_charges * (taux_val / 100)
        resultat_sans = total_produits - total_charges
        resultat_avec = total_produits - total_charges - logistique

        # Noms secteur / action pour le titre
        titre_parts = [f'Bilan {annee}']
        if secteur_id:
            row_s = conn.execute('SELECT nom FROM secteurs WHERE id = ?',
                                 (secteur_id,)).fetchone()
            if row_s:
                titre_parts.append(f'Secteur : {row_s["nom"]}')
        if action_id:
            row_a = conn.execute('SELECT nom FROM comptabilite_actions WHERE id = ?',
                                 (action_id,)).fetchone()
            if row_a:
                titre_parts.append(f'Action : {row_a["nom"]}')

        # --- Generer le PDF ---
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import cm
        from reportlab.platypus import (SimpleDocTemplate, Table as RLTable,
                                        TableStyle, Paragraph, Spacer)
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4,
                                topMargin=1.5 * cm, bottomMargin=1.5 * cm,
                                leftMargin=1.5 * cm, rightMargin=1.5 * cm)
        elements = []
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle('BilanTitle', parent=styles['Heading1'],
                                     alignment=TA_CENTER, fontSize=14,
                                     spaceAfter=6)
        subtitle_style = ParagraphStyle('BilanSub', parent=styles['Normal'],
                                        alignment=TA_CENTER, fontSize=10,
                                        spaceAfter=14)
        section_style = ParagraphStyle('BilanSection', parent=styles['Heading2'],
                                       fontSize=12, spaceAfter=6, spaceBefore=12)
        normal_style = styles['Normal']

        elements.append(Paragraph('BILAN SECTEURS / ACTIONS', title_style))
        elements.append(Paragraph(' — '.join(titre_parts), subtitle_style))

        # --- Helper : table pour charges ou produits ---
        def _build_section(categories, label, color_header):
            elements.append(Paragraph(label, section_style))
            if not categories:
                elements.append(Paragraph('Aucune donnée.', normal_style))
                return

            data = [['Compte', 'Libellé', 'Montant']]
            for cat_code in sorted(categories.keys()):
                cat = categories[cat_code]
                cat_name = NOMS_CATEGORIES.get(cat_code, f'Catégorie {cat_code}')
                data.append([f'{cat_code} - {cat_name}', '', _fmt(cat['total']) + ' €'])
                for cpt_num in sorted(cat['comptes'].keys()):
                    cpt = cat['comptes'][cpt_num]
                    data.append([f'   {cpt_num}', cpt['libelle'], _fmt(cpt['total']) + ' €'])

            col_widths = [4 * cm, 9 * cm, 4 * cm]
            t = RLTable(data, colWidths=col_widths, repeatRows=1)

            style_cmds = [
                ('BACKGROUND', (0, 0), (-1, 0), color_header),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
                ('TOPPADDING', (0, 0), (-1, 0), 6),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('TOPPADDING', (0, 1), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 1), (-1, -1), 3),
                ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ]

            # Mettre en gras les lignes de catégorie
            row_idx = 1
            for cat_code in sorted(categories.keys()):
                style_cmds.append(('FONTNAME', (0, row_idx), (-1, row_idx), 'Helvetica-Bold'))
                style_cmds.append(('BACKGROUND', (0, row_idx), (-1, row_idx),
                                   colors.HexColor('#F0F0F0')))
                row_idx += 1 + len(categories[cat_code]['comptes'])

            t.setStyle(TableStyle(style_cmds))
            elements.append(t)

        _build_section(charges, 'Charges', colors.HexColor('#C0392B'))
        _build_section(produits, 'Produits', colors.HexColor('#27AE60'))

        # --- Résumé ---
        elements.append(Spacer(1, 0.5 * cm))
        summary_data = [
            ['Total charges', _fmt(total_charges) + ' €'],
            ['Total produits', _fmt(total_produits) + ' €'],
            [f'Logistique ({_fmt(taux_val)} %)', _fmt(round(logistique, 2)) + ' €'],
            ['Résultat sans logistique', _fmt(round(resultat_sans, 2)) + ' €'],
            ['Résultat avec logistique', _fmt(round(resultat_avec, 2)) + ' €'],
        ]
        summary_t = RLTable(summary_data, colWidths=[10 * cm, 7 * cm])
        summary_t.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('BACKGROUND', (0, 3), (-1, 3), colors.HexColor('#FFF9C4')),
            ('BACKGROUND', (0, 4), (-1, 4), colors.HexColor('#FFF9C4')),
        ]))
        elements.append(summary_t)

        # Construire le PDF
        doc.build(elements)
        buffer.seek(0)

        response = make_response(buffer.getvalue())
        response.headers['Content-Type'] = 'application/pdf'
        filename = f'bilan_{annee}'
        if secteur_id:
            filename += f'_secteur{secteur_id}'
        if action_id:
            filename += f'_action{action_id}'
        response.headers['Content-Disposition'] = (
            f'attachment; filename={filename}.pdf'
        )
        return response
    finally:
        conn.close()
