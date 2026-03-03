"""
Blueprint bilan_secteurs_bp - Bilan secteurs/actions.

Fonctionnalites :
- Import FEC avec extraction des comptes 6x (charges) et 7x (produits)
  avec code analytique, annee, mois, libelle, montants
- Suppression des donnees d'une annee pour reimport
- Filtrage par annee, secteur (optionnel), action (optionnel)
- Affichage du compte de resultat : charges a gauche, produits a droite
  avec regroupement par categorie (60x, 61x, 62x, etc.)
- Detail des operations par compte (modal)
- Taux de logistique (site1, site2, global) par annee avec selection
- Calcul du resultat avec et sans logistique
- Accessible aux profils directeur et comptable
"""
import csv
import io
from datetime import datetime
from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, jsonify)
from database import get_db
from utils import login_required

bilan_secteurs_bp = Blueprint('bilan_secteurs_bp', __name__)

NOMS_MOIS = ['', 'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
             'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']


def _peut_acceder():
    return session.get('profil') in ('directeur', 'comptable')


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


# ── Import FEC ───────────────────────────────────────────────────────────────

@bilan_secteurs_bp.route('/api/bilan/import-fec', methods=['POST'])
@login_required
def api_import_fec():
    """Importe un fichier FEC pour le bilan secteurs/actions."""
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
            compte_num = (row.get('CompteNum') or '').strip()
            if not compte_num:
                continue

            # Ne garder que les comptes 6x (charges) et 7x (produits)
            premier = compte_num[0] if compte_num else ''
            if premier not in ('6', '7'):
                continue

            date_str = (row.get('EcritureDate') or '').strip()
            if len(date_str) != 8:
                continue

            try:
                annee = int(date_str[:4])
                mois = int(date_str[4:6])
            except (ValueError, IndexError):
                continue

            if mois < 1 or mois > 12:
                continue

            debit_str = (row.get('Debit') or '0').strip().replace(',', '.')
            credit_str = (row.get('Credit') or '0').strip().replace(',', '.')
            try:
                debit = float(debit_str) if debit_str else 0
                credit = float(credit_str) if credit_str else 0
            except ValueError:
                debit = 0
                credit = 0

            # Pour les charges (6x) : montant = debit - credit (positif = charge)
            # Pour les produits (7x) : montant = credit - debit (positif = produit)
            if premier == '6':
                montant = debit - credit
            else:
                montant = credit - debit

            libelle = (row.get('EcritureLib') or row.get('CompteLib') or '').strip()
            code_analytique = (row.get('CompAuxNum') or '').strip()

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
            return jsonify({'error': 'Aucune écriture 6x/7x trouvée dans le fichier.'}), 400

        # Enregistrer l'import
        cursor = conn.cursor()
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
        # Recuperer les codes analytiques associes au secteur/action
        query_parts = []
        params = []

        if secteur_id and action_id:
            query_parts.append('(c.secteur_id = ? AND c.action_id = ?)')
            params.extend([secteur_id, action_id])
        elif secteur_id:
            query_parts.append('c.secteur_id = ?')
            params.append(secteur_id)
        else:
            query_parts.append('c.action_id = ?')
            params.append(action_id)

        comptes_analytiques = conn.execute(
            f'SELECT compte_num FROM comptabilite_comptes c WHERE {query_parts[0]}',
            params
        ).fetchall()

        codes = [c['compte_num'] for c in comptes_analytiques]
        if not codes:
            return jsonify({'charges': {}, 'produits': {}, 'total_charges': 0,
                            'total_produits': 0, 'detail_comptes': {}})

        # Recuperer les donnees FEC pour ces codes analytiques
        placeholders = ','.join(['?' for _ in codes])
        all_donnees = conn.execute(f'''
            SELECT DISTINCT d.id, d.compte_num, d.libelle, d.mois, d.montant
            FROM bilan_fec_donnees d
            WHERE d.annee = ?
            AND (d.code_analytique IN ({placeholders}) OR d.compte_num IN ({placeholders}))
        ''', [annee] + codes + codes).fetchall()

        # Regrouper par categorie
        charges = {}  # {'60': {'nom': 'Achats', 'total': 0, 'comptes': {}}, ...}
        produits = {}
        detail_comptes = {}  # {compte_num: [{'mois': 1, 'libelle': '...', 'montant': 100}, ...]}

        for d in all_donnees:
            compte = d['compte_num']
            premier = compte[0]
            categorie = compte[:2]  # 60, 61, 62, 70, 71, etc.

            montant = d['montant']

            # Detail par compte
            if compte not in detail_comptes:
                detail_comptes[compte] = {'libelle': d['libelle'] or compte, 'operations': []}
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
                        'libelle': d['libelle'] or compte, 'total': 0}
                charges[categorie]['comptes'][compte]['total'] += montant
                charges[categorie]['total'] += montant
            elif premier == '7':
                if categorie not in produits:
                    produits[categorie] = {'comptes': {}, 'total': 0}
                if compte not in produits[categorie]['comptes']:
                    produits[categorie]['comptes'][compte] = {
                        'libelle': d['libelle'] or compte, 'total': 0}
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
        # Recuperer les codes analytiques du filtre
        query_parts = []
        params = []

        if secteur_id and action_id:
            query_parts.append('(c.secteur_id = ? AND c.action_id = ?)')
            params.extend([secteur_id, action_id])
        elif secteur_id:
            query_parts.append('c.secteur_id = ?')
            params.append(secteur_id)
        elif action_id:
            query_parts.append('c.action_id = ?')
            params.append(action_id)
        else:
            return jsonify({'operations': []})

        comptes_analytiques = conn.execute(
            f'SELECT compte_num FROM comptabilite_comptes c WHERE {query_parts[0]}',
            params
        ).fetchall()
        codes = [c['compte_num'] for c in comptes_analytiques]

        if not codes:
            return jsonify({'operations': []})

        placeholders = ','.join(['?' for _ in codes])
        operations = conn.execute(f'''
            SELECT d.annee, d.mois, d.libelle, d.montant
            FROM bilan_fec_donnees d
            WHERE d.annee = ? AND d.compte_num = ?
            AND (d.code_analytique IN ({placeholders}) OR d.compte_num IN ({placeholders}))
            ORDER BY d.mois
        ''', [annee, compte_num] + codes + codes).fetchall()

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
