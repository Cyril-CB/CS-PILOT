"""
Blueprint budget_bp - Gestion des budgets par secteur.

Fonctionnalites :
- Vue d'ensemble des budgets (direction/comptable)
- Detail budget par secteur avec repartition par poste de depense
- Support des periodes pour l'accueil de loisirs (mercredis + 5 vacances)
- Onglet parametrage (repartition) et onglet budget reel (depenses effectives)
- Gestion des postes de depense (CRUD + association types de secteur)
- Controle des droits : direction/comptable definissent le global,
  responsables ajustent la repartition sans depasser le global
"""
import io
import json
import sqlite3
from datetime import datetime, date, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, current_app
from database import get_db
from utils import login_required
from app_options import get_option_bool

budget_bp = Blueprint('budget_bp', __name__)

DEFAULT_TYPES_SECTEUR_LABELS = {
    'creche': 'Crèche',
    'accueil_loisirs': 'Accueil de loisirs',
    'famille': 'Secteur famille',
    'emploi_formation': 'Emploi/formation',
    'administratif': 'Administratif',
    'entretien': 'Entretien',
}

# Ordre : Mercredis, puis vacances dans l'ordre chronologique d'une annee scolaire
PERIODES_ALP = ['mercredis', 'hiver', 'printemps', 'ete', 'toussaint', 'noel']
PERIODES_ALP_LABELS = {
    'mercredis': 'Mercredis',
    'hiver': 'Hiver',
    'printemps': 'Printemps',
    'ete': 'Été',
    'toussaint': 'Toussaint',
    'noel': 'Noël',
}

# Mots-cles pour associer un nom de periode de vacances a une categorie budgetaire
_VACATION_KEYWORDS = {
    'hiver': ['hiver'],
    'printemps': ['printemps', 'pâques', 'paques'],
    'ete': ['été', 'ete', 'estival'],
    'toussaint': ['toussaint', 'automne'],
    'noel': ['noël', 'noel'],
}


def _get_types_secteur_labels(conn):
    """Retourne le mapping {code: libellé} des types de secteur configurés."""
    try:
        rows = conn.execute('''
            SELECT code, libelle FROM types_secteur
            ORDER BY ordre, libelle
        ''').fetchall()
    except sqlite3.OperationalError:
        current_app.logger.warning(
            "Table types_secteur introuvable, fallback sur les libellés par défaut dans budget."
        )
        return DEFAULT_TYPES_SECTEUR_LABELS
    return {row['code']: row['libelle'] for row in rows}


def _match_vacation_category(nom_periode):
    """Associe un nom de periode de vacances a une categorie budgetaire."""
    nom_lower = nom_periode.lower()
    for cat, keywords in _VACATION_KEYWORDS.items():
        for kw in keywords:
            if kw in nom_lower:
                return cat
    return None


def _calculer_jours_ouvres_periodes(annee, conn):
    """Calcule le nombre de jours ouvres par periode pour l'accueil de loisirs.

    Retourne un dict {periode: nb_jours} pour chaque periode ALP.
    - mercredis : nb de mercredis en periode scolaire (hors vacances, hors feries)
    - hiver/printemps/ete/toussaint/noel : nb de jours ouvres dans chaque
      periode de vacances (lun-ven hors feries)
    """
    # Recuperer les jours feries de l'annee
    feries_rows = conn.execute(
        'SELECT date FROM jours_feries WHERE annee = ?', (annee,)
    ).fetchall()
    jours_feries = {row['date'] for row in feries_rows}

    # Recuperer les periodes de vacances qui chevauchent l'annee
    periodes_vac = conn.execute('''
        SELECT nom, date_debut, date_fin FROM periodes_vacances
        WHERE date_debut <= ? AND date_fin >= ?
        ORDER BY date_debut
    ''', (f'{annee}-12-31', f'{annee}-01-01')).fetchall()

    # Construire un ensemble de tous les jours de vacances dans l'annee
    jours_vacances = set()
    # Dict {categorie: [(date_debut, date_fin), ...]} pour le calcul par periode
    vacances_par_cat = {}

    for pv in periodes_vac:
        cat = _match_vacation_category(pv['nom'])
        if not cat:
            continue

        d_debut = max(
            date.fromisoformat(pv['date_debut']),
            date(annee, 1, 1)
        )
        d_fin = min(
            date.fromisoformat(pv['date_fin']),
            date(annee, 12, 31)
        )

        if cat not in vacances_par_cat:
            vacances_par_cat[cat] = []
        vacances_par_cat[cat].append((d_debut, d_fin))

        d = d_debut
        while d <= d_fin:
            jours_vacances.add(d)
            d += timedelta(days=1)

    result = {}

    # Calculer les jours ouvres par periode de vacances
    for cat in ['hiver', 'printemps', 'ete', 'toussaint', 'noel']:
        nb = 0
        if cat in vacances_par_cat:
            for d_debut, d_fin in vacances_par_cat[cat]:
                d = d_debut
                while d <= d_fin:
                    # Jour ouvre = lundi-vendredi et pas ferie
                    if d.weekday() < 5 and d.isoformat() not in jours_feries:
                        nb += 1
                    d += timedelta(days=1)
        result[cat] = nb

    # Calculer les mercredis en periode scolaire
    nb_mercredis = 0
    d = date(annee, 1, 1)
    # Avancer au premier mercredi
    while d.weekday() != 2:
        d += timedelta(days=1)
    while d.year == annee:
        if d not in jours_vacances and d.isoformat() not in jours_feries:
            nb_mercredis += 1
        d += timedelta(days=7)
    result['mercredis'] = nb_mercredis

    return result


# ============================================================
# VUE D'ENSEMBLE DES BUDGETS
# ============================================================

@budget_bp.route('/gestion_budgets')
@login_required
def gestion_budgets():
    """Vue d'ensemble des budgets - direction/comptable."""
    if session.get('profil') not in ['directeur', 'comptable']:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    annee = request.args.get('annee', type=int, default=datetime.now().year)
    conn = get_db()
    types_labels = _get_types_secteur_labels(conn)

    # Recuperer tous les secteurs avec leur type
    secteurs = conn.execute('''
        SELECT s.*, COUNT(u.id) as nb_users
        FROM secteurs s
        LEFT JOIN users u ON s.id = u.secteur_id AND u.actif = 1
        GROUP BY s.id
        ORDER BY s.nom
    ''').fetchall()

    # Recuperer les budgets existants pour l'annee
    budgets_raw = conn.execute('''
        SELECT b.*, s.nom as secteur_nom, s.type_secteur
        FROM budgets b
        JOIN secteurs s ON b.secteur_id = s.id
        WHERE b.annee = ?
    ''', (annee,)).fetchall()
    budgets_map = {b['secteur_id']: dict(b) for b in budgets_raw}

    # Pour chaque budget existant, calculer le total reparti et le total reel
    for secteur_id, budget in budgets_map.items():
        total_reparti = conn.execute('''
            SELECT COALESCE(SUM(bl.montant), 0) as total
            FROM budget_lignes bl
            WHERE bl.budget_id = ?
        ''', (budget['id'],)).fetchone()['total']
        budget['total_reparti'] = total_reparti
        budget['pct_reparti'] = round(
            (total_reparti / budget['montant_global'] * 100) if budget['montant_global'] > 0 else 0, 1
        )

        total_reel = conn.execute('''
            SELECT COALESCE(SUM(brl.montant), 0) as total
            FROM budget_reel_lignes brl
            WHERE brl.budget_id = ?
        ''', (budget['id'],)).fetchone()['total']
        budget['total_reel'] = total_reel
        budget['pct_reel'] = round(
            (total_reel / budget['montant_global'] * 100) if budget['montant_global'] > 0 else 0, 1
        )

    # Construire la liste enrichie des secteurs
    secteurs_data = []
    for s in secteurs:
        sd = dict(s)
        sd['type_label'] = types_labels.get(s['type_secteur'], 'Non défini')
        sd['budget'] = budgets_map.get(s['id'])
        secteurs_data.append(sd)

    conn.close()

    return render_template('gestion_budgets.html',
                           secteurs=secteurs_data,
                           annee=annee,
                           types_labels=types_labels)


# ============================================================
# DETAIL BUDGET D'UN SECTEUR
# ============================================================

@budget_bp.route('/budget_secteur/<int:secteur_id>')
@login_required
def budget_secteur(secteur_id):
    """Detail du budget d'un secteur."""
    profil = session.get('profil')
    user_id = session.get('user_id')

    conn = get_db()
    secteur = conn.execute('SELECT * FROM secteurs WHERE id = ?', (secteur_id,)).fetchone()
    if not secteur:
        flash('Secteur introuvable', 'error')
        conn.close()
        return redirect(url_for('budget_bp.gestion_budgets'))

    # Verifier les droits d'acces
    if profil == 'responsable':
        user = conn.execute('SELECT secteur_id FROM users WHERE id = ?', (user_id,)).fetchone()
        if not user or user['secteur_id'] != secteur_id:
            flash('Accès non autorisé', 'error')
            conn.close()
            return redirect(url_for('dashboard_bp.dashboard'))
    elif profil not in ['directeur', 'comptable']:
        flash('Accès non autorisé', 'error')
        conn.close()
        return redirect(url_for('dashboard_bp.dashboard'))

    annee = request.args.get('annee', type=int, default=datetime.now().year)
    onglet = request.args.get('onglet', default='parametrage')
    types_labels = _get_types_secteur_labels(conn)
    is_alp = secteur['type_secteur'] == 'accueil_loisirs'
    peut_modifier_global = profil in ['directeur', 'comptable']
    peut_modifier_reel = profil in ['directeur', 'comptable']

    # Recuperer ou creer le budget
    budget = conn.execute(
        'SELECT * FROM budgets WHERE secteur_id = ? AND annee = ?',
        (secteur_id, annee)
    ).fetchone()

    budget_data = dict(budget) if budget else {
        'id': None, 'secteur_id': secteur_id, 'annee': annee,
        'montant_global': 0
    }

    # Recuperer les postes de depense pour ce type de secteur
    type_secteur = secteur['type_secteur'] or ''
    postes = conn.execute('''
        SELECT pd.* FROM postes_depense pd
        JOIN postes_depense_secteur_types pdst ON pd.id = pdst.poste_depense_id
        WHERE pdst.type_secteur = ? AND pd.actif = 1
        ORDER BY pd.nom
    ''', (type_secteur,)).fetchall()

    # Recuperer les lignes budgetaires previsionnelles
    lignes_map = {}
    if budget:
        lignes = conn.execute(
            'SELECT * FROM budget_lignes WHERE budget_id = ?',
            (budget['id'],)
        ).fetchall()
        for l in lignes:
            key = (l['poste_depense_id'], l['periode'])
            lignes_map[key] = dict(l)

    # Recuperer les lignes de depenses reelles
    reel_map = {}
    if budget:
        reel_lignes = conn.execute(
            'SELECT * FROM budget_reel_lignes WHERE budget_id = ?',
            (budget['id'],)
        ).fetchall()
        for rl in reel_lignes:
            key = (rl['poste_depense_id'], rl['periode'])
            reel_map[key] = dict(rl)

    # Jours ouvres par periode pour ALP
    jours_ouvres = {}
    if is_alp:
        jours_ouvres = _calculer_jours_ouvres_periodes(annee, conn)

    # Construire les donnees pour le template
    postes_data = []
    total_global_reparti = 0
    total_global_reel = 0
    has_depassement = False

    for p in postes:
        poste_info = dict(p)
        if is_alp:
            # Pour ALP : une ligne par periode
            periodes_data = []
            total_poste = 0
            total_poste_reel = 0
            for per in PERIODES_ALP:
                ligne = lignes_map.get((p['id'], per))
                montant = ligne['montant'] if ligne else 0
                reel_ligne = reel_map.get((p['id'], per))
                montant_reel = reel_ligne['montant'] if reel_ligne else 0
                periodes_data.append({
                    'periode': per,
                    'label': PERIODES_ALP_LABELS[per],
                    'montant': montant,
                    'reel': montant_reel,
                    'solde': montant - montant_reel,
                })
                total_poste += montant
                total_poste_reel += montant_reel
            poste_info['periodes'] = periodes_data
            poste_info['total'] = total_poste
            poste_info['total_reel'] = total_poste_reel
            poste_info['solde'] = total_poste - total_poste_reel
            if total_poste_reel > total_poste and total_poste > 0:
                has_depassement = True
            total_global_reparti += total_poste
            total_global_reel += total_poste_reel
        else:
            # Pour les autres : une seule ligne annuelle
            ligne = lignes_map.get((p['id'], 'annuel'))
            poste_info['montant'] = ligne['montant'] if ligne else 0
            reel_ligne = reel_map.get((p['id'], 'annuel'))
            poste_info['reel'] = reel_ligne['montant'] if reel_ligne else 0
            poste_info['solde'] = poste_info['montant'] - poste_info['reel']
            if poste_info['reel'] > poste_info['montant'] and poste_info['montant'] > 0:
                has_depassement = True
            total_global_reparti += poste_info['montant']
            total_global_reel += poste_info['reel']

        postes_data.append(poste_info)

    budget_data['total_reparti'] = total_global_reparti
    budget_data['reste'] = budget_data['montant_global'] - total_global_reparti
    budget_data['total_reel'] = total_global_reel
    budget_data['solde_reel'] = budget_data['montant_global'] - total_global_reel

    conn.close()

    return render_template('budget_secteur.html',
                           secteur=dict(secteur),
                           budget=budget_data,
                           postes=postes_data,
                           annee=annee,
                           onglet=onglet,
                           is_alp=is_alp,
                           periodes_labels=PERIODES_ALP_LABELS,
                           periodes=PERIODES_ALP,
                           jours_ouvres=jours_ouvres,
                           peut_modifier_global=peut_modifier_global,
                           peut_modifier_reel=peut_modifier_reel,
                           has_depassement=has_depassement,
                           types_labels=types_labels)


# ============================================================
# SAUVEGARDE DU BUDGET PREVISIONNEL (AJAX)
# ============================================================

@budget_bp.route('/api/budget/save', methods=['POST'])
@login_required
def api_budget_save():
    """Sauvegarde du budget previsionnel via AJAX."""
    profil = session.get('profil')
    user_id = session.get('user_id')

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Données manquantes'}), 400

    secteur_id = data.get('secteur_id')
    annee = data.get('annee')
    montant_global = data.get('montant_global')
    lignes = data.get('lignes', [])

    if not secteur_id or not annee:
        return jsonify({'error': 'Secteur et année requis'}), 400

    conn = get_db()

    # Verifier le secteur
    secteur = conn.execute('SELECT * FROM secteurs WHERE id = ?', (secteur_id,)).fetchone()
    if not secteur:
        conn.close()
        return jsonify({'error': 'Secteur introuvable'}), 404

    # Verifier les droits
    if profil == 'responsable':
        user = conn.execute('SELECT secteur_id FROM users WHERE id = ?', (user_id,)).fetchone()
        if not user or user['secteur_id'] != int(secteur_id):
            conn.close()
            return jsonify({'error': 'Accès non autorisé'}), 403
    elif profil not in ['directeur', 'comptable']:
        conn.close()
        return jsonify({'error': 'Accès non autorisé'}), 403

    try:
        # Recuperer ou creer le budget
        budget = conn.execute(
            'SELECT * FROM budgets WHERE secteur_id = ? AND annee = ?',
            (secteur_id, annee)
        ).fetchone()

        if budget:
            budget_id = budget['id']
            # Seul direction/comptable peut modifier le global
            if profil in ['directeur', 'comptable'] and montant_global is not None:
                conn.execute('''
                    UPDATE budgets SET montant_global = ?, modifie_par = ?,
                    updated_at = CURRENT_TIMESTAMP WHERE id = ?
                ''', (float(montant_global), user_id, budget_id))
        else:
            if profil not in ['directeur', 'comptable']:
                conn.close()
                return jsonify({'error': 'Seule la direction peut créer un budget'}), 403
            conn.execute('''
                INSERT INTO budgets (secteur_id, annee, montant_global, cree_par, modifie_par)
                VALUES (?, ?, ?, ?, ?)
            ''', (secteur_id, annee, float(montant_global or 0), user_id, user_id))
            budget_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]

        # Calculer le montant global effectif pour la validation
        budget_after = conn.execute(
            'SELECT montant_global FROM budgets WHERE id = ?', (budget_id,)
        ).fetchone()
        montant_global_effectif = budget_after['montant_global']

        # Calculer le total des lignes soumises
        total_lignes = sum(float(l.get('montant', 0)) for l in lignes)
        if total_lignes > montant_global_effectif + 0.01:  # tolerance arrondi
            conn.close()
            return jsonify({
                'error': f'Le total réparti ({total_lignes:.2f} €) dépasse le budget global ({montant_global_effectif:.2f} €)'
            }), 400

        # Sauvegarder les lignes
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for l in lignes:
            poste_id = l.get('poste_depense_id')
            periode = l.get('periode', 'annuel')
            montant = float(l.get('montant', 0))

            conn.execute('''
                INSERT INTO budget_lignes (budget_id, poste_depense_id, periode, montant, modifie_par, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(budget_id, poste_depense_id, periode)
                DO UPDATE SET montant = ?, modifie_par = ?, updated_at = ?
            ''', (budget_id, poste_id, periode, montant, user_id, now,
                  montant, user_id, now))

        conn.commit()
        conn.close()

        return jsonify({
            'success': True,
            'message': 'Budget sauvegardé avec succès',
            'budget_id': budget_id,
            'total_reparti': total_lignes,
            'reste': montant_global_effectif - total_lignes
        })

    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500


# ============================================================
# SAUVEGARDE DU BUDGET REEL (AJAX)
# ============================================================

@budget_bp.route('/api/budget/save_reel', methods=['POST'])
@login_required
def api_budget_save_reel():
    """Sauvegarde des depenses reelles via AJAX (direction/comptable)."""
    profil = session.get('profil')
    user_id = session.get('user_id')

    if profil not in ['directeur', 'comptable']:
        return jsonify({'error': 'Accès non autorisé'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Données manquantes'}), 400

    secteur_id = data.get('secteur_id')
    annee = data.get('annee')
    lignes = data.get('lignes', [])

    if not secteur_id or not annee:
        return jsonify({'error': 'Secteur et année requis'}), 400

    conn = get_db()

    # Verifier que le budget existe
    budget = conn.execute(
        'SELECT id FROM budgets WHERE secteur_id = ? AND annee = ?',
        (secteur_id, annee)
    ).fetchone()

    if not budget:
        conn.close()
        return jsonify({'error': 'Aucun budget défini pour ce secteur et cette année'}), 404

    budget_id = budget['id']

    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for l in lignes:
            poste_id = l.get('poste_depense_id')
            periode = l.get('periode', 'annuel')
            montant = float(l.get('montant', 0))

            conn.execute('''
                INSERT INTO budget_reel_lignes (budget_id, poste_depense_id, periode, montant, modifie_par, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(budget_id, poste_depense_id, periode)
                DO UPDATE SET montant = ?, modifie_par = ?, updated_at = ?
            ''', (budget_id, poste_id, periode, montant, user_id, now,
                  montant, user_id, now))

        conn.commit()

        # Calculer le nouveau total reel
        total_reel = conn.execute('''
            SELECT COALESCE(SUM(montant), 0) as total
            FROM budget_reel_lignes WHERE budget_id = ?
        ''', (budget_id,)).fetchone()['total']

        montant_global = conn.execute(
            'SELECT montant_global FROM budgets WHERE id = ?', (budget_id,)
        ).fetchone()['montant_global']

        conn.close()

        return jsonify({
            'success': True,
            'message': 'Dépenses réelles sauvegardées',
            'total_reel': total_reel,
            'solde_reel': montant_global - total_reel
        })

    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500


# ============================================================
# GESTION DES POSTES DE DEPENSE
# ============================================================

@budget_bp.route('/gestion_postes_depense', methods=['GET', 'POST'])
@login_required
def gestion_postes_depense():
    """Gestion des postes de depense (direction/comptable)."""
    if session.get('profil') not in ['directeur', 'comptable']:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    types_labels = _get_types_secteur_labels(conn)

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'ajouter':
            nom = request.form.get('nom', '').strip()
            types_selected = request.form.getlist('types_secteur')

            if not nom:
                flash('Le nom du poste de dépense est requis', 'error')
            elif not types_selected:
                flash('Sélectionnez au moins un type de secteur', 'error')
            else:
                try:
                    conn.execute('INSERT INTO postes_depense (nom) VALUES (?)', (nom,))
                    poste_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
                    for ts in types_selected:
                        conn.execute('''
                            INSERT INTO postes_depense_secteur_types (poste_depense_id, type_secteur)
                            VALUES (?, ?)
                        ''', (poste_id, ts))
                    conn.commit()
                    flash(f'Poste "{nom}" créé avec succès', 'success')
                except Exception as e:
                    flash(f'Erreur : {str(e)}', 'error')

        elif action == 'modifier':
            poste_id = request.form.get('poste_id', type=int)
            nom = request.form.get('nom', '').strip()
            types_selected = request.form.getlist('types_secteur')

            if not nom:
                flash('Le nom du poste de dépense est requis', 'error')
            elif not types_selected:
                flash('Sélectionnez au moins un type de secteur', 'error')
            else:
                try:
                    conn.execute('UPDATE postes_depense SET nom = ? WHERE id = ?', (nom, poste_id))
                    # Supprimer les anciennes associations et recreer
                    conn.execute(
                        'DELETE FROM postes_depense_secteur_types WHERE poste_depense_id = ?',
                        (poste_id,)
                    )
                    for ts in types_selected:
                        conn.execute('''
                            INSERT INTO postes_depense_secteur_types (poste_depense_id, type_secteur)
                            VALUES (?, ?)
                        ''', (poste_id, ts))
                    conn.commit()
                    flash(f'Poste "{nom}" modifié avec succès', 'success')
                except Exception as e:
                    flash(f'Erreur : {str(e)}', 'error')

        elif action == 'supprimer':
            poste_id = request.form.get('poste_id', type=int)
            # Verifier si le poste est utilise dans des lignes budgetaires
            nb_lignes = conn.execute(
                'SELECT COUNT(*) as nb FROM budget_lignes WHERE poste_depense_id = ?',
                (poste_id,)
            ).fetchone()['nb']
            if nb_lignes > 0:
                flash(
                    f'Impossible de supprimer : ce poste est utilisé dans {nb_lignes} ligne(s) budgétaire(s). '
                    'Vous pouvez le désactiver à la place.',
                    'error'
                )
            else:
                conn.execute(
                    'DELETE FROM postes_depense_secteur_types WHERE poste_depense_id = ?',
                    (poste_id,)
                )
                conn.execute('DELETE FROM postes_depense WHERE id = ?', (poste_id,))
                conn.commit()
                flash('Poste de dépense supprimé', 'success')

        elif action == 'toggle_actif':
            poste_id = request.form.get('poste_id', type=int)
            poste = conn.execute('SELECT actif FROM postes_depense WHERE id = ?', (poste_id,)).fetchone()
            if poste:
                new_val = 0 if poste['actif'] else 1
                conn.execute('UPDATE postes_depense SET actif = ? WHERE id = ?', (new_val, poste_id))
                conn.commit()
                statut = 'activé' if new_val else 'désactivé'
                flash(f'Poste {statut}', 'success')

        return redirect(url_for('budget_bp.gestion_postes_depense'))

    # GET : recuperer tous les postes avec leurs associations
    postes = conn.execute('''
        SELECT pd.* FROM postes_depense pd ORDER BY pd.nom
    ''').fetchall()

    postes_data = []
    for p in postes:
        pd = dict(p)
        types = conn.execute('''
            SELECT type_secteur FROM postes_depense_secteur_types
            WHERE poste_depense_id = ?
        ''', (p['id'],)).fetchall()
        pd['types_secteur'] = [t['type_secteur'] for t in types]
        postes_data.append(pd)

    conn.close()

    return render_template('gestion_postes_depense.html',
                           postes=postes_data,
                           types_labels=types_labels)


# ============================================================
# BUDGET RESPONSABLE (ACCES DIRECT)
# ============================================================

@budget_bp.route('/mon_budget')
@login_required
def mon_budget():
    """Raccourci pour les responsables vers le budget de leur secteur."""
    user_id = session.get('user_id')
    conn = get_db()
    user = conn.execute('SELECT secteur_id FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()

    if not user or not user['secteur_id']:
        flash('Aucun secteur associé à votre compte', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    return redirect(url_for('budget_bp.budget_secteur', secteur_id=user['secteur_id']))

# ============================================================
# MODULE BUDGET PREVISIONNEL
# ============================================================

NOMS_MOIS = [
    '', 'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
    'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre'
]


def _can_access_budget_previsionnel(profil):
    if profil in ['directeur', 'comptable']:
        return True
    if profil == 'responsable':
        return get_option_bool('budget_previsionnel_responsable_autorise')
    return False


def _secteur_allowed_codes(conn, secteur_id):
    """Codes (analytiques + comptes du plan) rattachés à un secteur."""
    allowed = set()
    if not secteur_id:
        return allowed
    for r in conn.execute(
        'SELECT code_analytique FROM budget_prev_config_codes WHERE secteur_id = ?', (secteur_id,)
    ).fetchall():
        c = (r['code_analytique'] or '').strip()
        if c:
            allowed.add(c)
    for r in conn.execute(
        'SELECT compte_num FROM comptabilite_comptes WHERE secteur_id = ?', (secteur_id,)
    ).fetchall():
        c = (r['compte_num'] or '').strip()
        if c:
            allowed.add(c)
    return allowed


def _code_allowed(code_analytique, compte_num, allowed_codes):
    """Une écriture FEC est rattachée au secteur si son code analytique
    correspond exactement, ou si son compte commence par un code autorisé."""
    if not allowed_codes:
        return False
    code_ana = (code_analytique or '').strip()
    compte = (compte_num or '').strip()
    for code in allowed_codes:
        if code_ana == code or compte.startswith(code):
            return True
    return False


def _compute_budget_previsionnel(conn, type_budget, annee, secteur_id=None, inflation=0, global_mode=False):
    years = [annee - 2, annee - 1, annee]
    rows = conn.execute('''
        SELECT compte_num, libelle, code_analytique, annee, mois, montant
        FROM bilan_fec_donnees
        WHERE annee IN (?, ?, ?)
          AND (compte_num LIKE '6%' OR compte_num LIKE '7%')
    ''', (years[0], years[1], years[2])).fetchall()

    allowed_codes = set()
    if secteur_id and not global_mode:
        allowed_codes = _secteur_allowed_codes(conn, secteur_id)

    def row_allowed(r):
        if global_mode or not secteur_id:
            return True
        return _code_allowed(r['code_analytique'], r['compte_num'], allowed_codes)

    pcg_rows = conn.execute('SELECT compte_num, libelle FROM plan_comptable_general').fetchall()
    pcg = {r['compte_num']: r['libelle'] for r in pcg_rows}

    totals = {}
    monthly = {}
    last_month = 0
    for r in rows:
        if not row_allowed(r):
            continue
        compte = r['compte_num']
        an = r['annee']
        mois = r['mois']
        montant = float(r['montant'] or 0)
        if compte not in totals:
            totals[compte] = {
                'compte_num': compte,
                'libelle': pcg.get(compte) or r['libelle'] or compte,
                'N-2': 0.0, 'N-1': 0.0, 'N': 0.0
            }
            monthly[compte] = {}
        if an == annee - 2:
            totals[compte]['N-2'] += montant
        elif an == annee - 1:
            totals[compte]['N-1'] += montant
        elif an == annee:
            totals[compte]['N'] += montant
            if mois and 1 <= mois <= 12:
                last_month = max(last_month, mois)
        monthly[compte].setdefault(an, {})
        monthly[compte][an][mois] = monthly[compte][an].get(mois, 0) + montant

    saisies_map = {}
    if secteur_id:
        saved = conn.execute('''
            SELECT compte_num, valeur_temp, valeur_def, commentaire
            FROM budget_prev_saisies
            WHERE type_budget = ? AND annee = ? AND secteur_id = ?
        ''', (type_budget, annee, secteur_id)).fetchall()
        for s in saved:
            saisies_map[s['compte_num']] = {
                'valeur_temp': s['valeur_temp'],
                'valeur_def': float(s['valeur_def'] or 0),
                'commentaire': s['commentaire'] or ''
            }

    # En budget actualisé, le budget initial (définitif) de la même année est
    # affiché en face pour mesurer l'écart d'atterrissage. En vue globale, on
    # consolide l'initial de tous les secteurs.
    initial_map = {}
    if type_budget == 'actualise':
        if global_mode:
            init_rows = conn.execute('''
                SELECT compte_num, SUM(valeur_def) AS total_def
                FROM budget_prev_saisies
                WHERE type_budget = 'initial' AND annee = ?
                GROUP BY compte_num
            ''', (annee,)).fetchall()
        elif secteur_id:
            init_rows = conn.execute('''
                SELECT compte_num, valeur_def AS total_def
                FROM budget_prev_saisies
                WHERE type_budget = 'initial' AND annee = ? AND secteur_id = ?
            ''', (annee, secteur_id)).fetchall()
        else:
            init_rows = []
        initial_map = {r['compte_num']: float(r['total_def'] or 0) for r in init_rows}

    accounts = []
    for compte, vals in totals.items():
        n2 = round(vals['N-2'], 2)
        n1 = round(vals['N-1'], 2)
        n_full = round(vals['N'], 2)
        nature = 'charges' if compte.startswith('6') else 'produits'
        # Comptes de personnel répartis au prorata du brut (641), hors 649.
        is_salary = (compte.startswith('63') or compte.startswith('64')) and not compte.startswith('649')
        n_partiel = round(sum(
            m for month, m in monthly.get(compte, {}).get(annee, {}).items()
            if month <= last_month
        ), 2)
        if type_budget == 'initial':
            if nature == 'produits':
                temp = n1
            elif is_salary:
                temp = n1
            else:
                base = n_full if n_full else n1
                temp = base * (1 + (inflation / 100))
            col_n = n_full
        else:
            if is_salary:
                temp = n1
            else:
                n1_restant = round(sum(
                    m for month, m in monthly.get(compte, {}).get(annee - 1, {}).items()
                    if month > last_month
                ), 2)
                temp = n_partiel + n1_restant
            col_n = n_partiel

        save_data = saisies_map.get(compte, {})
        saved_temp = save_data.get('valeur_temp')
        if saved_temp is not None:
            temp = float(saved_temp)
        account = {
            'compte_num': compte,
            'libelle': vals['libelle'],
            'categorie': compte[:2],
            'nature': nature,
            'is_salary': is_salary,
            'N-2': n2,
            'N-1': n1,
            'N': round(col_n, 2),
            'temp': round(temp, 2),
            'def': round(float(save_data.get('valeur_def', 0)), 2),
            'commentaire': save_data.get('commentaire', '')
        }
        if type_budget == 'actualise':
            account['initial'] = round(initial_map.get(compte, 0.0), 2)
        accounts.append(account)

    accounts.sort(key=lambda r: r['compte_num'])
    salary_brut = None
    for r in accounts:
        if r['compte_num'].startswith('641') and (r['N-1'] != 0 or r['temp'] != 0 or r['def'] != 0):
            salary_brut = r['compte_num']
            break

    salary_ratios = {}
    if salary_brut:
        brut_row = next((r for r in accounts if r['compte_num'] == salary_brut), None)
        brut_prev = brut_row['N-1'] if brut_row else 0
        brut_temp = brut_row['temp'] if brut_row else 0
        for r in accounts:
            if r['is_salary'] and r['compte_num'] != salary_brut:
                ratio = (r['N-1'] / brut_prev) if brut_prev else 0
                salary_ratios[r['compte_num']] = round(ratio, 6)
                r['temp'] = round(brut_temp * ratio, 2)

    total_charges_temp = round(sum(r['temp'] for r in accounts if r['nature'] == 'charges'), 2)
    total_produits_temp = round(sum(r['temp'] for r in accounts if r['nature'] == 'produits'), 2)
    total_charges_def = round(sum(r['def'] for r in accounts if r['nature'] == 'charges'), 2)
    total_produits_def = round(sum(r['def'] for r in accounts if r['nature'] == 'produits'), 2)

    return {
        'rows': accounts,
        'last_month': last_month,
        'last_month_label': NOMS_MOIS[last_month] if 1 <= last_month <= 12 else '',
        'salary_brut_account': salary_brut,
        'salary_ratios': salary_ratios,
        'totaux': {
            'charges_temp': total_charges_temp,
            'produits_temp': total_produits_temp,
            'resultat_temp': round(total_produits_temp - total_charges_temp, 2),
            'charges_def': total_charges_def,
            'produits_def': total_produits_def,
            'resultat_def': round(total_produits_def - total_charges_def, 2),
        }
    }


@budget_bp.route('/budget-previsionnel')
@login_required
def budget_previsionnel():
    profil = session.get('profil')
    user_id = session.get('user_id')
    if not _can_access_budget_previsionnel(profil):
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    now = datetime.now()
    # Budgets accessibles de N-3 (consultation de l'historique) a N+3
    # (previsionnel a moyen terme).
    annees_traitement = list(range(now.year - 3, now.year + 4))
    conn = get_db()
    try:
        if profil == 'responsable':
            user = conn.execute('SELECT secteur_id FROM users WHERE id = ?', (user_id,)).fetchone()
            if not user or not user['secteur_id']:
                flash('Aucun secteur associé à votre compte', 'error')
                return redirect(url_for('dashboard_bp.dashboard'))
            secteurs = conn.execute('SELECT id, nom FROM secteurs WHERE id = ?', (user['secteur_id'],)).fetchall()
            secteur_id_defaut = user['secteur_id']
        else:
            secteurs = conn.execute('SELECT id, nom FROM secteurs ORDER BY nom').fetchall()
            secteur_id_defaut = secteurs[0]['id'] if secteurs else None
            # Présélection depuis la barre de recherche : ?secteur_id=
            secteur_param = request.args.get('secteur_id', type=int)
            if secteur_param and any(s['id'] == secteur_param for s in secteurs):
                secteur_id_defaut = secteur_param

        # Présélection de l'année depuis la barre de recherche : ?annee=
        annee_param = request.args.get('annee', type=int)
        annee_selection = annee_param if annee_param in annees_traitement else now.year

        annees_importees = conn.execute(
            'SELECT DISTINCT annee FROM bilan_fec_imports ORDER BY annee DESC'
        ).fetchall()
        last_month_n = conn.execute(
            'SELECT MAX(mois) as max_mois FROM bilan_fec_donnees WHERE annee = ?',
            (now.year,)
        ).fetchone()
        dernier_mois = (last_month_n['max_mois'] if last_month_n else None)
        return render_template(
            'budget_previsionnel.html',
            annees_traitement=annees_traitement,
            annee_courante=annee_selection,
            secteurs=secteurs,
            secteur_id_defaut=secteur_id_defaut,
            annees_importees=[r['annee'] for r in annees_importees],
            dernier_mois_courant=dernier_mois or 0,
            dernier_mois_courant_label=NOMS_MOIS[dernier_mois] if dernier_mois else '',
            profil=profil
        )
    finally:
        conn.close()


@budget_bp.route('/api/budget-previsionnel/detail')
@login_required
def api_budget_previsionnel_detail():
    """Opérations comptables (FEC) derrière une somme d'une colonne compta.

    Reproduit exactement le filtrage de _compute_budget_previsionnel (compte +
    année + rattachement au secteur via les codes autorisés, et éventuellement le
    plafond de mois pour la colonne N en mode « actualisé ») afin que le détail
    corresponde à la somme affichée.
    """
    profil = session.get('profil')
    if not _can_access_budget_previsionnel(profil):
        return jsonify({'error': 'Accès non autorisé'}), 403

    compte = (request.args.get('compte') or '').strip()
    annee = request.args.get('annee', type=int)
    secteur_id = request.args.get('secteur_id', type=int)
    global_mode = request.args.get('global') == '1'
    mois_max = request.args.get('mois_max', type=int)
    if not compte or not annee:
        return jsonify({'operations': []})

    conn = get_db()
    try:
        # Le responsable est verrouillé sur son propre secteur (comme la page).
        if profil == 'responsable':
            global_mode = False
            user = conn.execute('SELECT secteur_id FROM users WHERE id = ?',
                                (session.get('user_id'),)).fetchone()
            secteur_id = user['secteur_id'] if user else None
            if not secteur_id:
                return jsonify({'error': 'Aucun secteur associé à votre compte'}), 403

        # Hors mode global, un secteur est OBLIGATOIRE pour délimiter le périmètre :
        # sans lui on ne renvoie rien (jamais toutes les opérations du compte).
        if not global_mode and not secteur_id:
            return jsonify({'operations': []})

        allowed_codes = _secteur_allowed_codes(conn, secteur_id) if not global_mode else set()

        query = ('SELECT annee, mois, libelle, code_analytique, montant '
                 'FROM bilan_fec_donnees WHERE compte_num = ? AND annee = ?')
        params = [compte, annee]
        if mois_max and 1 <= mois_max <= 12:
            query += ' AND mois <= ?'
            params.append(mois_max)
        query += ' ORDER BY mois, id'
        rows = conn.execute(query, params).fetchall()

        operations = []
        for r in rows:
            if not global_mode and not _code_allowed(
                    r['code_analytique'], compte, allowed_codes):
                continue
            m = r['mois']
            operations.append({
                'annee': r['annee'],
                'mois': m,
                'mois_nom': NOMS_MOIS[m] if m and 1 <= m <= 12 else '',
                'libelle': r['libelle'] or '',
                'montant': round(float(r['montant'] or 0), 2),
            })
        return jsonify({'operations': operations})
    finally:
        conn.close()


@budget_bp.route('/api/budget-previsionnel/config', methods=['POST'])
@login_required
def api_budget_previsionnel_config_save():
    profil = session.get('profil')
    if profil not in ['directeur', 'comptable']:
        return jsonify({'error': 'Accès non autorisé'}), 403
    data = request.get_json() or {}
    code = (data.get('code_analytique') or '').strip()
    secteur_id = data.get('secteur_id')
    if not code or not secteur_id:
        return jsonify({'error': 'Code analytique et secteur requis'}), 400
    conn = get_db()
    try:
        conn.execute('''
            INSERT INTO budget_prev_config_codes (code_analytique, secteur_id, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(code_analytique) DO UPDATE SET
                secteur_id = excluded.secteur_id,
                updated_at = CURRENT_TIMESTAMP
        ''', (code, int(secteur_id)))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


@budget_bp.route('/api/budget-previsionnel/config/<int:config_id>', methods=['DELETE'])
@login_required
def api_budget_previsionnel_config_delete(config_id):
    profil = session.get('profil')
    if profil not in ['directeur', 'comptable']:
        return jsonify({'error': 'Accès non autorisé'}), 403
    conn = get_db()
    try:
        conn.execute('DELETE FROM budget_prev_config_codes WHERE id = ?', (config_id,))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


@budget_bp.route('/api/budget-previsionnel/donnees')
@login_required
def api_budget_previsionnel_donnees():
    profil = session.get('profil')
    user_id = session.get('user_id')
    if not _can_access_budget_previsionnel(profil):
        return jsonify({'error': 'Accès non autorisé'}), 403

    type_budget = request.args.get('type_budget', 'initial')
    annee = request.args.get('annee', type=int)
    secteur_id = request.args.get('secteur_id', type=int)
    inflation = request.args.get('inflation', type=float, default=0)
    global_mode = request.args.get('global') == '1'

    if type_budget not in ['initial', 'actualise']:
        return jsonify({'error': 'Type de budget invalide'}), 400
    if not annee:
        return jsonify({'error': 'Année requise'}), 400

    conn = get_db()
    try:
        if global_mode:
            if profil not in ['directeur', 'comptable']:
                return jsonify({'error': 'Accès non autorisé'}), 403
            secteur_id = None
        elif profil == 'responsable':
            user = conn.execute('SELECT secteur_id FROM users WHERE id = ?', (user_id,)).fetchone()
            if not user or not user['secteur_id']:
                return jsonify({'error': 'Aucun secteur associé'}), 400
            secteur_id = user['secteur_id']
        elif not secteur_id:
            return jsonify({'error': 'Secteur requis'}), 400

        data = _compute_budget_previsionnel(
            conn=conn,
            type_budget=type_budget,
            annee=annee,
            secteur_id=secteur_id,
            inflation=inflation or 0,
            global_mode=global_mode
        )
        return jsonify(data)
    finally:
        conn.close()


@budget_bp.route('/api/budget-previsionnel/save-line', methods=['POST'])
@login_required
def api_budget_previsionnel_save_line():
    profil = session.get('profil')
    user_id = session.get('user_id')
    if profil not in ['directeur', 'comptable']:
        return jsonify({'error': 'Accès non autorisé'}), 403

    data = request.get_json() or {}
    type_budget = data.get('type_budget')
    annee = data.get('annee')
    secteur_id = data.get('secteur_id')
    compte_num = (data.get('compte_num') or '').strip()
    valeur_def = data.get('valeur_def', 0)
    valeur_temp = data.get('valeur_temp')
    commentaire = data.get('commentaire', '')
    if type_budget not in ['initial', 'actualise']:
        return jsonify({'error': 'Type de budget invalide'}), 400
    if not annee or not secteur_id or not compte_num:
        return jsonify({'error': 'Champs requis manquants'}), 400

    try:
        valeur_def = float(valeur_def or 0)
    except (TypeError, ValueError):
        return jsonify({'error': 'Valeur définitive invalide'}), 400
    try:
        valeur_temp = float(valeur_temp) if valeur_temp is not None else None
    except (TypeError, ValueError):
        return jsonify({'error': 'Valeur temporaire invalide'}), 400

    conn = get_db()
    try:
        conn.execute('''
            INSERT INTO budget_prev_saisies
            (type_budget, annee, secteur_id, compte_num, valeur_temp, valeur_def, commentaire, updated_by, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(type_budget, annee, secteur_id, compte_num)
            DO UPDATE SET
                valeur_temp = excluded.valeur_temp,
                valeur_def = excluded.valeur_def,
                commentaire = excluded.commentaire,
                updated_by = excluded.updated_by,
                updated_at = CURRENT_TIMESTAMP
        ''', (type_budget, int(annee), int(secteur_id), compte_num, valeur_temp, valeur_def, commentaire, user_id))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


@budget_bp.route('/api/budget-previsionnel/export-pdf')
@login_required
def api_budget_previsionnel_export_pdf():
    profil = session.get('profil')
    if not _can_access_budget_previsionnel(profil):
        return jsonify({'error': 'Accès non autorisé'}), 403

    type_budget = request.args.get('type_budget', 'initial')
    annee = request.args.get('annee', type=int)
    secteur_id = request.args.get('secteur_id', type=int)
    inflation = request.args.get('inflation', type=float, default=0)
    global_mode = request.args.get('global') == '1'
    if type_budget not in ('initial', 'actualise'):
        return jsonify({'error': 'Type de budget invalide'}), 400
    if not annee:
        return jsonify({'error': 'Année requise'}), 400
    if global_mode and profil not in ['directeur', 'comptable']:
        return jsonify({'error': 'Accès non autorisé'}), 403
    if not global_mode and not secteur_id and profil in ['directeur', 'comptable']:
        return jsonify({'error': 'Secteur requis'}), 400

    conn = get_db()
    try:
        if profil == 'responsable':
            user = conn.execute('SELECT secteur_id FROM users WHERE id = ?', (session.get('user_id'),)).fetchone()
            if not user or not user['secteur_id']:
                return jsonify({'error': 'Aucun secteur associé'}), 400
            secteur_id = user['secteur_id']

        data = _compute_budget_previsionnel(
            conn=conn, type_budget=type_budget, annee=annee, secteur_id=secteur_id,
            inflation=inflation or 0, global_mode=global_mode
        )

        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Table as RLTable, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet

        titre = f"Budget {'global' if global_mode else 'secteur'} - {type_budget.capitalize()} - {annee}"
        if secteur_id and not global_mode:
            secteur = conn.execute('SELECT nom FROM secteurs WHERE id = ?', (secteur_id,)).fetchone()
            if secteur:
                titre = f"Budget {secteur['nom']} - {type_budget.capitalize()} - {annee}"

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=1 * cm, rightMargin=1 * cm,
                                topMargin=1 * cm, bottomMargin=1 * cm)
        styles = getSampleStyleSheet()
        elements = [Paragraph(titre, styles['Title']), Spacer(1, 0.3 * cm)]

        headers = ['Compte', 'Libellé', 'N-2', 'N-1', 'N', 'Temp.', 'Déf.']
        table_data = [headers]
        for r in data['rows']:
            table_data.append([
                r['compte_num'], r['libelle'],
                f"{r['N-2']:.2f}", f"{r['N-1']:.2f}", f"{r['N']:.2f}",
                f"{r['temp']:.2f}", f"{r['def']:.2f}"
            ])
        t = RLTable(table_data, repeatRows=1, colWidths=[2 * cm, 6.4 * cm, 2 * cm, 2 * cm, 2 * cm, 2 * cm, 2 * cm])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('GRID', (0, 0), (-1, -1), 0.3, colors.grey),
            ('ALIGN', (2, 1), (-1, -1), 'RIGHT'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 0.4 * cm))
        tot = data['totaux']
        elements.append(Paragraph(
            f"Résultat Temp. : {tot['resultat_temp']:.2f} € | Résultat Déf. : {tot['resultat_def']:.2f} €",
            styles['Heading3']
        ))
        doc.build(elements)
        pdf = buffer.getvalue()
        buffer.close()
        resp = current_app.response_class(pdf, mimetype='application/pdf')
        resp.headers['Content-Disposition'] = f'attachment; filename=budget_previsionnel_{annee}.pdf'
        return resp
    finally:
        conn.close()


# ============================================================
# SIMULATEUR PRESTATION DE SERVICE (PS) CAF
# ============================================================

PS_TYPES = ('eaje', 'alsh_perisco', 'alsh_extrasco')

# Valeurs par défaut du simulateur PS EAJE (modifiables dans l'interface).
PS_EAJE_DEFAULTS = {
    'taux_ps': 6.63,
    'taux_regime': 100,
    'amplitude_horaire': 10,
    'financement_par_enfant': 8,
    'bonus_mixite': {
        'seuil1': 0.91, 'montant1': 2100,
        'seuil2': 1.20, 'montant2': 800,
        'seuil3': 1.52, 'montant3': 300,
    },
    'journees_peda': {'nb_journees': 3, 'nb_heures': 10},
    'bonus_attractivite_taux': 970,
}

# Valeurs par défaut des simulateurs PS ALSH.
PS_ALSH_EXTRASCO_DEFAULTS = {'taux_ps': 0.624, 'taux_compl_inclusif': 3.90, 'taux_regime': 100}
PS_ALSH_PERISCO_DEFAULTS = {'taux_ps': 0.59, 'taux_compl_inclusif': 3.90, 'mercredis_deduction': 7}


def _ps_num(value, default=0.0):
    """Convertit une valeur saisie (str/None) en float, avec valeur par défaut."""
    try:
        if value is None or value == '':
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _compute_ps_eaje(donnees):
    """Calcule le détail du simulateur PS EAJE (crèche) à partir des saisies.

    Les colonnes calculées (heures d'ouverture, amplitude totale, taux
    d'occupation, taux horaire, PSU, PSU - participation), les totaux/moyennes
    et les bonus sont dérivés ici afin que le montant stocké et reporté sur le
    compte soit toujours fiable (recalcul côté serveur).
    """
    d = donnees or {}
    taux_ps = _ps_num(d.get('taux_ps'), PS_EAJE_DEFAULTS['taux_ps'])
    taux_regime_pct = _ps_num(d.get('taux_regime'), PS_EAJE_DEFAULTS['taux_regime'])
    taux_regime = taux_regime_pct / 100.0

    mois_in = d.get('mois') or []
    if not isinstance(mois_in, list):
        mois_in = []
    mois_out = []
    tot = {
        'jours_ouverture': 0.0, 'heures_facturees': 0.0, 'heures_realisees': 0.0,
        'participation': 0.0, 'amplitude_totale': 0.0, 'psu': 0.0, 'psu_participation': 0.0,
    }
    places_list = []
    for m in mois_in:
        # Par défaut « réel » : c'est le comportement historique (heures saisies,
        # taux calculés) et le tableau actuel.
        prev_reel = m.get('prev_reel') or 'reel'
        jours = _ps_num(m.get('jours_ouverture'))
        places = _ps_num(m.get('places'))
        amplitude_h = _ps_num(m.get('amplitude_horaire'), PS_EAJE_DEFAULTS['amplitude_horaire'])
        heures_ouv = amplitude_h * jours
        amplitude_tot = heures_ouv * places
        if prev_reel == 'reel':
            # Réel : heures facturées / réalisées / participation saisies,
            #        taux d'occupation et taux horaire calculés.
            h_fact = _ps_num(m.get('heures_facturees'))
            h_real = _ps_num(m.get('heures_realisees'))
            participation = _ps_num(m.get('participation'))
            taux_occ = (h_fact / amplitude_tot) if amplitude_tot else 0.0
            taux_horaire = (participation / h_fact) if h_fact else 0.0
        else:
            # Prévisionnel : taux d'occupation (%) et taux horaire saisis,
            #                heures facturées / réalisées et participation calculées.
            taux_occ = _ps_num(m.get('taux_occupation')) / 100.0
            taux_horaire = _ps_num(m.get('taux_horaire'))
            h_fact = taux_occ * amplitude_tot
            h_real = h_fact
            participation = taux_horaire * h_fact
        psu = h_fact * taux_ps * taux_regime
        psu_part = psu - participation
        mois_out.append({
            'prev_reel': prev_reel,
            'jours_ouverture': jours, 'heures_facturees': round(h_fact, 2),
            'heures_realisees': round(h_real, 2), 'participation': round(participation, 2),
            'places': places, 'amplitude_horaire': amplitude_h,
            'heures_ouverture': round(heures_ouv, 2),
            'amplitude_totale': round(amplitude_tot, 2),
            'taux_occupation': round(taux_occ, 4),
            'taux_horaire': round(taux_horaire, 4),
            'psu': round(psu, 2),
            'psu_participation': round(psu_part, 2),
        })
        tot['jours_ouverture'] += jours
        tot['heures_facturees'] += h_fact
        tot['heures_realisees'] += h_real
        tot['participation'] += participation
        tot['amplitude_totale'] += amplitude_tot
        tot['psu'] += psu
        tot['psu_participation'] += psu_part
        if places > 0:
            places_list.append(places)

    # Le nombre de places est généralement constant : sinon on prend la moyenne
    # des mois renseignés (places > 0).
    places_moyen = (sum(places_list) / len(places_list)) if places_list else 0.0
    # Moyennes pondérées (cohérentes avec le calcul CAF du taux de participation).
    taux_occ_moyen = (tot['heures_facturees'] / tot['amplitude_totale']) if tot['amplitude_totale'] else 0.0
    taux_horaire_moyen = (tot['participation'] / tot['heures_facturees']) if tot['heures_facturees'] else 0.0

    nb_enfants = _ps_num(d.get('nb_enfants_inscrits'))
    financement_enfant = _ps_num(d.get('financement_par_enfant'), PS_EAJE_DEFAULTS['financement_par_enfant'])
    ps_prepa = nb_enfants * financement_enfant * taux_regime

    bm = d.get('bonus_mixite') or {}
    bm_def = PS_EAJE_DEFAULTS['bonus_mixite']
    seuil1 = _ps_num(bm.get('seuil1'), bm_def['seuil1'])
    montant1 = _ps_num(bm.get('montant1'), bm_def['montant1'])
    seuil2 = _ps_num(bm.get('seuil2'), bm_def['seuil2'])
    montant2 = _ps_num(bm.get('montant2'), bm_def['montant2'])
    seuil3 = _ps_num(bm.get('seuil3'), bm_def['seuil3'])
    montant3 = _ps_num(bm.get('montant3'), bm_def['montant3'])
    if taux_horaire_moyen <= seuil1:
        bonus_mixite_place = montant1
    elif taux_horaire_moyen <= seuil2:
        bonus_mixite_place = montant2
    elif taux_horaire_moyen <= seuil3:
        bonus_mixite_place = montant3
    else:
        bonus_mixite_place = 0.0
    bonus_mixite = bonus_mixite_place * places_moyen

    jp = d.get('journees_peda') or {}
    jp_def = PS_EAJE_DEFAULTS['journees_peda']
    jp_nb = _ps_num(jp.get('nb_journees'), jp_def['nb_journees'])
    jp_h = _ps_num(jp.get('nb_heures'), jp_def['nb_heures'])
    journees_peda = jp_nb * jp_h * taux_ps * taux_regime * places_moyen

    bonus_attr_taux = _ps_num(d.get('bonus_attractivite_taux'), PS_EAJE_DEFAULTS['bonus_attractivite_taux'])
    bonus_attractivite = bonus_attr_taux * places_moyen

    total = tot['psu_participation'] + ps_prepa + bonus_mixite + journees_peda + bonus_attractivite

    return {
        'mois': mois_out,
        'totaux': {k: round(v, 2) for k, v in tot.items()},
        'taux_occupation_moyen': round(taux_occ_moyen, 4),
        'taux_horaire_moyen': round(taux_horaire_moyen, 4),
        'places_moyen': round(places_moyen, 2),
        'ps_prepa': round(ps_prepa, 2),
        'bonus_mixite': round(bonus_mixite, 2),
        'bonus_mixite_place': round(bonus_mixite_place, 2),
        'journees_peda': round(journees_peda, 2),
        'bonus_attractivite': round(bonus_attractivite, 2),
        'total': round(total, 2),
    }


# ---- PS ALSH : jours ouvrés / mercredis (dérivés du calendrier en base) ----

def _alsh_jours_ouvres_periodes_reelles(conn, annee):
    """Jours ouvrés (lun-ven hors fériés) par période de vacances de l'année.

    Les périodes proviennent de la page Gestion des vacances (periodes_vacances),
    bornées à l'année civile du budget.
    """
    feries = {r['date'] for r in conn.execute(
        'SELECT date FROM jours_feries WHERE annee = ?', (annee,)
    ).fetchall()}
    rows = conn.execute('''
        SELECT id, nom, date_debut, date_fin FROM periodes_vacances
        WHERE date_debut <= ? AND date_fin >= ?
        ORDER BY date_debut
    ''', (f'{annee}-12-31', f'{annee}-01-01')).fetchall()
    result = []
    for r in rows:
        try:
            d0 = max(date.fromisoformat(r['date_debut']), date(annee, 1, 1))
            d1 = min(date.fromisoformat(r['date_fin']), date(annee, 12, 31))
        except (ValueError, TypeError):
            continue
        nb = 0
        d = d0
        while d <= d1:
            if d.weekday() < 5 and d.isoformat() not in feries:
                nb += 1
            d += timedelta(days=1)
        result.append({
            'id': r['id'], 'nom': r['nom'],
            'date_debut': r['date_debut'], 'date_fin': r['date_fin'],
            'jours_ouvres': nb,
        })
    return result


def _alsh_mercredis_scolaires(conn, annee):
    """Liste ISO des mercredis de l'année en période scolaire (hors vacances/fériés)."""
    feries = {r['date'] for r in conn.execute(
        'SELECT date FROM jours_feries WHERE annee = ?', (annee,)
    ).fetchall()}
    periodes_vac = conn.execute('''
        SELECT date_debut, date_fin FROM periodes_vacances
        WHERE date_debut <= ? AND date_fin >= ?
    ''', (f'{annee}-12-31', f'{annee}-01-01')).fetchall()
    jours_vac = set()
    for pv in periodes_vac:
        try:
            d0 = max(date.fromisoformat(pv['date_debut']), date(annee, 1, 1))
            d1 = min(date.fromisoformat(pv['date_fin']), date(annee, 12, 31))
        except (ValueError, TypeError):
            continue
        d = d0
        while d <= d1:
            jours_vac.add(d)
            d += timedelta(days=1)
    dates = []
    d = date(annee, 1, 1)
    while d.weekday() != 2:  # avancer au premier mercredi
        d += timedelta(days=1)
    while d.year == annee:
        if d not in jours_vac and d.isoformat() not in feries:
            dates.append(d.isoformat())
        d += timedelta(days=7)
    return dates


def _compute_ps_alsh_extrasco(donnees, jours_by_periode):
    """Calcule la PS ALSH EXTRASCO (par période de vacances × tranche d'âge).

    Heures (prévisionnel) = enfants/jour × jours ouvrés × heures/jour ; en mode
    réel, on saisit directement le nombre d'heures. PS = heures × taux PS × taux
    régime. Le complément inclusif (bonus handicap) porte sur un total d'heures
    d'enfants en situation de handicap saisi à part.
    """
    d = donnees or {}
    taux_ps = _ps_num(d.get('taux_ps'), PS_ALSH_EXTRASCO_DEFAULTS['taux_ps'])
    taux_compl = _ps_num(d.get('taux_compl_inclusif'), PS_ALSH_EXTRASCO_DEFAULTS['taux_compl_inclusif'])
    taux_regime = _ps_num(d.get('taux_regime'), PS_ALSH_EXTRASCO_DEFAULTS['taux_regime']) / 100.0
    cells_in = d.get('cellules') or []
    if not isinstance(cells_in, list):
        cells_in = []
    cells_out = []
    total_heures = 0.0
    total_ps = 0.0
    for c in cells_in:
        if not isinstance(c, dict):
            continue
        try:
            pid = int(c.get('periode_id'))
        except (TypeError, ValueError):
            continue
        jours = float(jours_by_periode.get(pid, 0) or 0)
        prev_reel = c.get('prev_reel') or 'prev'
        enfants = _ps_num(c.get('enfants'))
        heures_jour = _ps_num(c.get('heures_jour'))
        if prev_reel == 'reel':
            heures = _ps_num(c.get('heures_reel'))
        else:
            heures = enfants * jours * heures_jour
        ps = heures * taux_ps * taux_regime
        cells_out.append({
            'periode_id': pid, 'tranche_id': c.get('tranche_id'),
            'jours': jours, 'heures': round(heures, 2), 'ps': round(ps, 2),
        })
        total_heures += heures
        total_ps += ps
    heures_handicap = _ps_num(d.get('heures_handicap'))
    compl_inclusif = heures_handicap * taux_compl * taux_regime
    total = total_ps + compl_inclusif
    return {
        'cellules': cells_out,
        'total_heures': round(total_heures, 2),
        'total_ps': round(total_ps, 2),
        'heures_handicap': round(heures_handicap, 2),
        'compl_inclusif': round(compl_inclusif, 2),
        'total': round(total, 2),
    }


def _compute_ps_alsh_perisco(donnees, jours_initial, jours_restant, type_budget):
    """Calcule la PS ALSH PERISCO (mercredis périscolaires, par tranche d'âge).

    Budget initial : heures = enfants × jours × heures/jour sur l'ensemble de
    l'année (jours = mercredis scolaires − déduction). Budget actualisé : on
    saisit le réel (heures) et on ajoute un prévisionnel sur le reste de l'année
    (jours restants après la date d'arrêté). PS = heures × taux PS ; complément
    inclusif = heures d'enfants en situation de handicap × taux complément.
    """
    d = donnees or {}
    taux_ps = _ps_num(d.get('taux_ps'), PS_ALSH_PERISCO_DEFAULTS['taux_ps'])
    taux_compl = _ps_num(d.get('taux_compl_inclusif'), PS_ALSH_PERISCO_DEFAULTS['taux_compl_inclusif'])
    actualise = (type_budget == 'actualise')
    cells_in = d.get('cellules') or []
    if not isinstance(cells_in, list):
        cells_in = []
    cells_out = []
    total_ps = 0.0
    total_compl = 0.0
    total_heures = 0.0
    for c in cells_in:
        if not isinstance(c, dict):
            continue
        enfants = _ps_num(c.get('enfants'))
        heures_jour = _ps_num(c.get('heures_jour'))
        enfants_handicap = _ps_num(c.get('enfants_handicap'))
        if actualise:
            heures_reel = _ps_num(c.get('heures_reel'))
            heures_reste = enfants * jours_restant * heures_jour
            heures = heures_reel + heures_reste
            heures_h_reel = _ps_num(c.get('heures_handicap_reel'))
            heures_h_reste = enfants_handicap * jours_restant * heures_jour
            heures_h = heures_h_reel + heures_h_reste
            cell = {'heures_reel': round(heures_reel, 2), 'heures_reste': round(heures_reste, 2),
                    'heures_handicap_reste': round(heures_h_reste, 2)}
        else:
            heures = enfants * jours_initial * heures_jour
            heures_h = enfants_handicap * jours_initial * heures_jour
            cell = {}
        ps = heures * taux_ps
        compl = heures_h * taux_compl
        cell.update({
            'tranche_id': c.get('tranche_id'),
            'heures': round(heures, 2), 'heures_handicap': round(heures_h, 2),
            'ps': round(ps, 2), 'compl': round(compl, 2),
        })
        cells_out.append(cell)
        total_ps += ps
        total_compl += compl
        total_heures += heures
    total = total_ps + total_compl
    return {
        'cellules': cells_out,
        'total_ps': round(total_ps, 2),
        'compl_inclusif': round(total_compl, 2),
        'total_heures': round(total_heures, 2),
        'jours_initial': jours_initial,
        'jours_restant': jours_restant,
        'total': round(total, 2),
    }


def _perisco_deduction_restant(annee, date_arrete):
    """Jours à déduire du reste de l'année selon la date d'arrêté du réel :
    5 jours si l'arrêté est avant fin août, 1 jour s'il est fin août ou après."""
    return 1 if date_arrete >= f'{annee}-08-31' else 5


def _ps_alsh_perisco_jours(conn, annee, donnees):
    """Retourne (jours_initial, jours_restant) pour la PS PERISCO."""
    mercredis = _alsh_mercredis_scolaires(conn, annee)
    jours_initial = max(len(mercredis) - PS_ALSH_PERISCO_DEFAULTS['mercredis_deduction'], 0)
    date_arrete = ((donnees or {}).get('date_arrete') or '').strip()
    if not date_arrete:
        return jours_initial, 0
    restants = sum(1 for dt in mercredis if dt > date_arrete)
    jours_restant = max(restants - _perisco_deduction_restant(annee, date_arrete), 0)
    return jours_initial, jours_restant


@budget_bp.route('/api/budget-previsionnel/ps-comptes')
@login_required
def api_ps_comptes_liste():
    """Liste des comptes paramétrés comme PS (compte_num -> type_ps)."""
    profil = session.get('profil')
    if not _can_access_budget_previsionnel(profil):
        return jsonify({'error': 'Accès non autorisé'}), 403
    conn = get_db()
    try:
        rows = conn.execute(
            'SELECT compte_num, type_ps FROM budget_ps_comptes ORDER BY compte_num'
        ).fetchall()
        return jsonify({'comptes': {r['compte_num']: r['type_ps'] for r in rows}})
    finally:
        conn.close()


@budget_bp.route('/api/budget-previsionnel/ps-comptes-disponibles')
@login_required
def api_ps_comptes_disponibles():
    """Liste des comptes de produits 70x disponibles pour le paramétrage PS."""
    profil = session.get('profil')
    if profil not in ['directeur', 'comptable']:
        return jsonify({'error': 'Accès non autorisé'}), 403
    conn = get_db()
    try:
        comptes = {}
        for r in conn.execute(
            "SELECT compte_num, libelle FROM plan_comptable_general WHERE compte_num LIKE '70%'"
        ).fetchall():
            comptes[r['compte_num']] = r['libelle'] or r['compte_num']
        for r in conn.execute(
            "SELECT DISTINCT compte_num, libelle FROM bilan_fec_donnees WHERE compte_num LIKE '70%'"
        ).fetchall():
            comptes.setdefault(r['compte_num'], r['libelle'] or r['compte_num'])
        liste = [{'compte_num': k, 'libelle': v} for k, v in sorted(comptes.items())]
        return jsonify({'comptes': liste})
    finally:
        conn.close()


@budget_bp.route('/api/budget-previsionnel/ps-comptes', methods=['POST'])
@login_required
def api_ps_comptes_save():
    """Rattache un compte 70x à un type de PS (EAJE/ALSH)."""
    profil = session.get('profil')
    if profil not in ['directeur', 'comptable']:
        return jsonify({'error': 'Accès non autorisé'}), 403
    data = request.get_json() or {}
    compte_num = (data.get('compte_num') or '').strip()
    type_ps = (data.get('type_ps') or '').strip()
    if not compte_num:
        return jsonify({'error': 'Compte requis'}), 400
    if type_ps not in PS_TYPES:
        return jsonify({'error': 'Type de PS invalide'}), 400
    conn = get_db()
    try:
        conn.execute('''
            INSERT INTO budget_ps_comptes (compte_num, type_ps, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(compte_num) DO UPDATE SET
                type_ps = excluded.type_ps,
                updated_at = CURRENT_TIMESTAMP
        ''', (compte_num, type_ps))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


@budget_bp.route('/api/budget-previsionnel/ps-comptes/<compte_num>', methods=['DELETE'])
@login_required
def api_ps_comptes_delete(compte_num):
    """Retire un compte du paramétrage PS."""
    profil = session.get('profil')
    if profil not in ['directeur', 'comptable']:
        return jsonify({'error': 'Accès non autorisé'}), 403
    conn = get_db()
    try:
        conn.execute('DELETE FROM budget_ps_comptes WHERE compte_num = ?', (compte_num,))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


@budget_bp.route('/api/budget-previsionnel/ps-alsh-context')
@login_required
def api_ps_alsh_context():
    """Contexte des simulateurs ALSH : tranches d'âge, périodes de vacances avec
    jours ouvrés et mercredis scolaires (déduits du calendrier en base)."""
    profil = session.get('profil')
    if not _can_access_budget_previsionnel(profil):
        return jsonify({'error': 'Accès non autorisé'}), 403
    annee = request.args.get('annee', type=int)
    if not annee:
        return jsonify({'error': 'Année requise'}), 400
    conn = get_db()
    try:
        tranches = conn.execute(
            'SELECT id, libelle FROM alsh_tranches_age WHERE active = 1 ORDER BY ordre, id'
        ).fetchall()
        periodes = _alsh_jours_ouvres_periodes_reelles(conn, annee)
        mercredis = _alsh_mercredis_scolaires(conn, annee)
        deduction = PS_ALSH_PERISCO_DEFAULTS['mercredis_deduction']
        return jsonify({
            'tranches': [dict(t) for t in tranches],
            'periodes': periodes,
            'mercredis_dates': mercredis,
            'mercredis_count': len(mercredis),
            'mercredis_deduction': deduction,
            'jours_initial': max(len(mercredis) - deduction, 0),
            'defaults': {
                'extrasco': PS_ALSH_EXTRASCO_DEFAULTS,
                'perisco': PS_ALSH_PERISCO_DEFAULTS,
            },
        })
    finally:
        conn.close()


@budget_bp.route('/api/budget-previsionnel/ps-simulation')
@login_required
def api_ps_simulation_get():
    """Récupère une simulation PS enregistrée pour (compte, année, type budget)."""
    profil = session.get('profil')
    if not _can_access_budget_previsionnel(profil):
        return jsonify({'error': 'Accès non autorisé'}), 403
    compte_num = (request.args.get('compte_num') or '').strip()
    annee = request.args.get('annee', type=int)
    secteur_id = request.args.get('secteur_id', type=int)
    type_budget = request.args.get('type_budget', 'initial')
    if not compte_num or not annee or not secteur_id:
        return jsonify({'error': 'Compte, secteur et année requis'}), 400
    if type_budget not in ('initial', 'actualise'):
        return jsonify({'error': 'Type de budget invalide'}), 400
    conn = get_db()
    try:
        type_row = conn.execute(
            'SELECT type_ps FROM budget_ps_comptes WHERE compte_num = ?', (compte_num,)
        ).fetchone()
        type_ps = type_row['type_ps'] if type_row else 'eaje'
        row = conn.execute('''
            SELECT donnees, total, type_ps, updated_at FROM budget_ps_simulations
            WHERE compte_num = ? AND annee = ? AND secteur_id = ? AND type_budget = ?
        ''', (compte_num, annee, secteur_id, type_budget)).fetchone()
        if not row:
            return jsonify({'found': False, 'type_ps': type_ps, 'donnees': None})
        try:
            donnees = json.loads(row['donnees']) if row['donnees'] else None
        except (ValueError, TypeError):
            donnees = None
        return jsonify({
            'found': True,
            'type_ps': row['type_ps'] or type_ps,
            'donnees': donnees,
            'total': row['total'],
            'updated_at': row['updated_at'],
        })
    finally:
        conn.close()


@budget_bp.route('/api/budget-previsionnel/ps-simulation', methods=['POST'])
@login_required
def api_ps_simulation_save():
    """Enregistre une simulation PS et reporte le total sur le compte produit."""
    profil = session.get('profil')
    user_id = session.get('user_id')
    if profil not in ['directeur', 'comptable']:
        return jsonify({'error': 'Accès non autorisé'}), 403

    data = request.get_json() or {}
    compte_num = (data.get('compte_num') or '').strip()
    annee = data.get('annee')
    type_budget = data.get('type_budget')
    type_ps = (data.get('type_ps') or 'eaje').strip()
    secteur_id = data.get('secteur_id')
    donnees = data.get('donnees') or {}
    if not isinstance(donnees, dict):
        donnees = {}

    if not compte_num or not annee or not secteur_id:
        return jsonify({'error': 'Compte, secteur et année requis'}), 400
    if type_budget not in ('initial', 'actualise'):
        return jsonify({'error': 'Type de budget invalide'}), 400
    if type_ps not in PS_TYPES:
        return jsonify({'error': 'Type de PS invalide'}), 400

    conn = get_db()
    try:
        # Le total reporté est recalculé côté serveur (source de vérité).
        if type_ps == 'eaje':
            computed = _compute_ps_eaje(donnees)
        elif type_ps == 'alsh_extrasco':
            periodes = _alsh_jours_ouvres_periodes_reelles(conn, int(annee))
            jours_by = {p['id']: p['jours_ouvres'] for p in periodes}
            computed = _compute_ps_alsh_extrasco(donnees, jours_by)
        elif type_ps == 'alsh_perisco':
            jours_initial, jours_restant = _ps_alsh_perisco_jours(conn, int(annee), donnees)
            computed = _compute_ps_alsh_perisco(donnees, jours_initial, jours_restant, type_budget)
        else:
            computed = {'total': 0.0}
        total = computed.get('total', 0.0)

        conn.execute('''
            INSERT INTO budget_ps_simulations
            (compte_num, annee, secteur_id, type_budget, type_ps, donnees, total, updated_by, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(compte_num, annee, secteur_id, type_budget) DO UPDATE SET
                type_ps = excluded.type_ps,
                donnees = excluded.donnees,
                total = excluded.total,
                updated_by = excluded.updated_by,
                updated_at = CURRENT_TIMESTAMP
        ''', (compte_num, int(annee), int(secteur_id), type_budget, type_ps,
              json.dumps(donnees), total, user_id))

        # Report du total sur la valeur définitive du compte dans le budget du
        # secteur, en préservant la valeur temporaire et le commentaire éventuels.
        conn.execute('''
            INSERT INTO budget_prev_saisies
            (type_budget, annee, secteur_id, compte_num, valeur_def, updated_by, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(type_budget, annee, secteur_id, compte_num) DO UPDATE SET
                valeur_def = excluded.valeur_def,
                updated_by = excluded.updated_by,
                updated_at = CURRENT_TIMESTAMP
        ''', (type_budget, int(annee), int(secteur_id), compte_num, total, user_id))

        conn.commit()
        return jsonify({'success': True, 'total': total, 'reported': True, 'computed': computed})
    finally:
        conn.close()


# ============================================================
# FICHE DE TRAVAIL (BUDGET ACTUALISÉ, COMPTES NON PARAMÉTRÉS)
# ============================================================

# Méthodes de projection des mois restants (après le mois d'arrêté du réel).
FICHE_METHODES = {
    'n1': 'N-1 mois par mois',
    'moyenne_n1_n2': 'moyenne N-1 / N-2',
    'tendance': 'tendance du réel',
    'solde_initial': 'solde du budget initial',
    'manuel': 'saisie mensuelle',
}


def _fiche_contexte(conn, compte_num, annee, secteur_id):
    """Contexte de calcul d'une fiche : réel mensuel N / N-1 / N-2 du compte
    (périmètre analytique du secteur), mois d'arrêté du réel (même définition
    que le tableau : dernier mois importé de l'année N, tous comptes du
    secteur confondus) et budget initial définitif du compte."""
    allowed_codes = _secteur_allowed_codes(conn, secteur_id) if secteur_id else set()

    def code_ok(code, compte):
        if not secteur_id:
            return True
        return _code_allowed(code, compte, allowed_codes)

    mensuels = {annee: {}, annee - 1: {}, annee - 2: {}}
    last_month = 0
    rows = conn.execute('''
        SELECT compte_num, code_analytique, annee, mois, montant
        FROM bilan_fec_donnees
        WHERE annee IN (?, ?, ?)
          AND (compte_num LIKE '6%' OR compte_num LIKE '7%')
    ''', (annee - 2, annee - 1, annee)).fetchall()
    for r in rows:
        if not code_ok(r['code_analytique'], r['compte_num']):
            continue
        mois = r['mois']
        if not mois or not (1 <= mois <= 12):
            continue
        if r['annee'] == annee:
            last_month = max(last_month, mois)
        if r['compte_num'] != compte_num:
            continue
        par_mois = mensuels[r['annee']]
        par_mois[mois] = par_mois.get(mois, 0.0) + float(r['montant'] or 0)

    init_row = conn.execute('''
        SELECT valeur_def FROM budget_prev_saisies
        WHERE type_budget = 'initial' AND annee = ? AND secteur_id = ? AND compte_num = ?
    ''', (annee, secteur_id, compte_num)).fetchone()
    budget_initial = float(init_row['valeur_def'] or 0) if init_row else 0.0

    return {
        'reel': mensuels[annee],
        'n1': mensuels[annee - 1],
        'n2': mensuels[annee - 2],
        'last_month': last_month,
        'budget_initial': budget_initial,
    }


def _compute_fiche_travail(donnees, contexte):
    """Calcule une fiche de travail : réel à date + projection des mois
    restants selon la méthode choisie + lignes d'ajustement. Le total est
    recalculé côté serveur (source de vérité, le JS ne fait qu'un aperçu)."""
    d = donnees if isinstance(donnees, dict) else {}
    methode = d.get('methode') if d.get('methode') in FICHE_METHODES else 'n1'
    reel = contexte['reel']
    n1 = contexte['n1']
    n2 = contexte['n2']
    last_month = contexte['last_month']

    mois_reel = {m: round(reel.get(m, 0.0), 2) for m in range(1, last_month + 1)}
    total_reel = sum(mois_reel.values())
    restants = range(last_month + 1, 13)

    saisis = d.get('mois_prevus') or {}
    mois_prevus = {}
    for m in restants:
        if methode == 'n1':
            val = n1.get(m, 0.0)
        elif methode == 'moyenne_n1_n2':
            val = (n1.get(m, 0.0) + n2.get(m, 0.0)) / 2.0
        elif methode == 'tendance':
            val = (total_reel / last_month) if last_month else 0.0
        elif methode == 'solde_initial':
            nb_restants = 12 - last_month
            val = (contexte['budget_initial'] - total_reel) / nb_restants if nb_restants else 0.0
        else:  # manuel
            val = _ps_num(saisis.get(str(m), saisis.get(m)))
        mois_prevus[m] = round(val, 2)
    total_prevu = sum(mois_prevus.values())

    ajustements = []
    for a in (d.get('ajustements') or []):
        if not isinstance(a, dict):
            continue
        montant = _ps_num(a.get('montant'))
        libelle = str(a.get('libelle') or '').strip()
        if not montant and not libelle:
            continue
        ajustements.append({'libelle': libelle, 'montant': round(montant, 2)})
    total_ajustements = sum(a['montant'] for a in ajustements)

    return {
        'methode': methode,
        'mois_reel': mois_reel,
        'mois_prevus': mois_prevus,
        'ajustements': ajustements,
        'total_reel': round(total_reel, 2),
        'total_prevu': round(total_prevu, 2),
        'total_ajustements': round(total_ajustements, 2),
        'total': round(total_reel + total_prevu + total_ajustements, 2),
    }


def _fiche_commentaire_auto(computed, last_month):
    """Commentaire de traçabilité écrit sur le compte au report du total."""
    label = FICHE_METHODES.get(computed['methode'], computed['methode'])
    if last_month:
        base = f"Fiche : réel à fin {NOMS_MOIS[last_month].lower()} + {label}"
    else:
        base = f"Fiche : {label}"
    nb = len(computed['ajustements'])
    if nb:
        base += f", {nb} ajustement(s)"
    return base


@budget_bp.route('/api/budget-previsionnel/fiche-travail')
@login_required
def api_fiche_travail_get():
    """Fiche de travail d'un compte (budget actualisé) : saisie enregistrée +
    contexte de calcul (réel mensuel, références N-1/N-2, budget initial)."""
    profil = session.get('profil')
    if not _can_access_budget_previsionnel(profil):
        return jsonify({'error': 'Accès non autorisé'}), 403
    compte_num = (request.args.get('compte_num') or '').strip()
    annee = request.args.get('annee', type=int)
    secteur_id = request.args.get('secteur_id', type=int)
    type_budget = request.args.get('type_budget', 'actualise')
    if type_budget != 'actualise':
        return jsonify({'error': 'La fiche de travail est réservée au budget actualisé'}), 400

    conn = get_db()
    try:
        # Un responsable ne consulte que son secteur (même règle que la page).
        if profil == 'responsable':
            user = conn.execute('SELECT secteur_id FROM users WHERE id = ?',
                                (session.get('user_id'),)).fetchone()
            if not user or not user['secteur_id']:
                return jsonify({'error': 'Aucun secteur associé'}), 400
            secteur_id = user['secteur_id']
        if not compte_num or not annee or not secteur_id:
            return jsonify({'error': 'Compte, secteur et année requis'}), 400

        contexte = _fiche_contexte(conn, compte_num, annee, secteur_id)
        row = conn.execute('''
            SELECT donnees, total, updated_at FROM budget_fiches_travail
            WHERE compte_num = ? AND annee = ? AND secteur_id = ? AND type_budget = ?
        ''', (compte_num, annee, secteur_id, type_budget)).fetchone()
        donnees = None
        if row:
            try:
                donnees = json.loads(row['donnees']) if row['donnees'] else None
            except (ValueError, TypeError):
                donnees = None
        return jsonify({
            'found': bool(row),
            'donnees': donnees,
            'total': row['total'] if row else None,
            'updated_at': row['updated_at'] if row else None,
            'contexte': {
                'reel_mensuel': contexte['reel'],
                'n1_mensuel': contexte['n1'],
                'n2_mensuel': contexte['n2'],
                'last_month': contexte['last_month'],
                'last_month_label': (NOMS_MOIS[contexte['last_month']]
                                     if 1 <= contexte['last_month'] <= 12 else ''),
                'budget_initial': round(contexte['budget_initial'], 2),
                'methodes': FICHE_METHODES,
            },
        })
    finally:
        conn.close()


@budget_bp.route('/api/budget-previsionnel/fiche-travail', methods=['POST'])
@login_required
def api_fiche_travail_save():
    """Enregistre une fiche de travail et reporte le total sur la valeur
    définitive du compte, avec un commentaire auto traçant la méthode."""
    profil = session.get('profil')
    user_id = session.get('user_id')
    if profil not in ['directeur', 'comptable']:
        return jsonify({'error': 'Accès non autorisé'}), 403

    data = request.get_json() or {}
    compte_num = (data.get('compte_num') or '').strip()
    annee = data.get('annee')
    secteur_id = data.get('secteur_id')
    type_budget = data.get('type_budget')
    donnees = data.get('donnees') or {}
    if not isinstance(donnees, dict):
        donnees = {}
    if not compte_num or not annee or not secteur_id:
        return jsonify({'error': 'Compte, secteur et année requis'}), 400
    if type_budget != 'actualise':
        return jsonify({'error': 'La fiche de travail est réservée au budget actualisé'}), 400

    conn = get_db()
    try:
        contexte = _fiche_contexte(conn, compte_num, int(annee), int(secteur_id))
        computed = _compute_fiche_travail(donnees, contexte)
        total = computed['total']
        commentaire = _fiche_commentaire_auto(computed, contexte['last_month'])

        conn.execute('''
            INSERT INTO budget_fiches_travail
            (compte_num, annee, secteur_id, type_budget, donnees, total, updated_by, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(compte_num, annee, secteur_id, type_budget) DO UPDATE SET
                donnees = excluded.donnees,
                total = excluded.total,
                updated_by = excluded.updated_by,
                updated_at = CURRENT_TIMESTAMP
        ''', (compte_num, int(annee), int(secteur_id), type_budget,
              json.dumps(donnees), total, user_id))

        # Report sur la valeur définitive du compte + commentaire auto de
        # traçabilité, en préservant la valeur temporaire éventuelle.
        conn.execute('''
            INSERT INTO budget_prev_saisies
            (type_budget, annee, secteur_id, compte_num, valeur_def, commentaire, updated_by, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(type_budget, annee, secteur_id, compte_num) DO UPDATE SET
                valeur_def = excluded.valeur_def,
                commentaire = excluded.commentaire,
                updated_by = excluded.updated_by,
                updated_at = CURRENT_TIMESTAMP
        ''', (type_budget, int(annee), int(secteur_id), compte_num, total, commentaire, user_id))

        conn.commit()
        return jsonify({'success': True, 'total': total, 'commentaire': commentaire,
                        'reported': True, 'computed': computed})
    finally:
        conn.close()


# ============================================================
# SIMULATEUR DE PAIE (MASSE SALARIALE)
# ============================================================

PAIE_DEFAULTS = {
    'salaire_socle': 23000,
    'valeur_point': 55,
    'forfait_cee': 70,
    'temps_plein': 35,  # heures hebdomadaires de référence (temps plein)
}


def _paie_anciennete_annees(date_ref, annee):
    """Années révolues d'ancienneté au 1er janvier de l'année de budget (floor).

    La date de référence est la date de début du contrat en cours de validité
    (c'est le contrat qui compte, pas users.date_entree saisie à la création).
    """
    if not date_ref:
        return 0
    try:
        d = date.fromisoformat(str(date_ref)[:10])
    except (ValueError, TypeError):
        return 0
    ref = date(annee, 1, 1)
    if d > ref:
        return 0
    return max(ref.year - d.year - ((ref.month, ref.day) < (d.month, d.day)), 0)


def _paie_mois_actifs(date_debut, date_fin, annee):
    """(mois_debut, mois_fin) d'activité du contrat dans l'année, ou (None, None)."""
    try:
        dd = date.fromisoformat(str(date_debut)[:10]) if date_debut else date(annee, 1, 1)
    except (ValueError, TypeError):
        dd = date(annee, 1, 1)
    df = None
    if date_fin:
        try:
            df = date.fromisoformat(str(date_fin)[:10])
        except (ValueError, TypeError):
            df = None
    if dd.year > annee:
        return None, None
    if df and df.year < annee:
        return None, None
    mois_debut = dd.month if dd.year == annee else 1
    mois_fin = df.month if (df and df.year == annee) else 12
    if mois_debut > mois_fin:
        return None, None
    return mois_debut, mois_fin


def _paie_employes_secteur(conn, secteur_id, annee):
    """Salariés actifs du secteur avec un contrat CDI/CDD chevauchant l'année.

    La direction (profil 'directeur') est comptée dans SON secteur lorsqu'elle en
    a un (utile pour les budgets, ex. « Pilotage » = administratif + direction).
    Une direction SANS secteur est rattachée par défaut au secteur administratif
    principal (le plus petit id parmi les secteurs de type 'administratif') et n'y
    apparaît qu'une fois — jamais en double avec un secteur explicitement assigné.
    """
    sect = conn.execute('SELECT type_secteur FROM secteurs WHERE id = ?', (secteur_id,)).fetchone()
    is_admin = bool(sect) and (sect['type_secteur'] == 'administratif')
    inclut_direction = False
    if is_admin:
        primary = conn.execute(
            "SELECT MIN(id) AS mid FROM secteurs WHERE type_secteur = 'administratif'"
        ).fetchone()
        inclut_direction = bool(primary) and (primary['mid'] == secteur_id)

    if inclut_direction:
        rows = conn.execute('''
            SELECT id, nom, prenom, pesee, competence, maintien
            FROM users
            WHERE actif = 1 AND profil != 'prestataire'
              AND (secteur_id = ? OR (profil = 'directeur' AND secteur_id IS NULL))
            ORDER BY nom, prenom
        ''', (secteur_id,)).fetchall()
    else:
        # Hors secteur administratif principal : on inclut la direction
        # explicitement rattachée à CE secteur (les directions sans secteur, elles,
        # restent sur l'administratif principal via la branche ci-dessus).
        rows = conn.execute('''
            SELECT id, nom, prenom, pesee, competence, maintien
            FROM users
            WHERE actif = 1 AND profil != 'prestataire'
              AND secteur_id = ?
            ORDER BY nom, prenom
        ''', (secteur_id,)).fetchall()
    employes = []
    for u in rows:
        # Ne retenir que les contrats CDI/CDD qui chevauchent l'année de budget :
        # commencés au plus tard le 31/12 et finissant au plus tôt le 01/01.
        # Sinon un contrat saisi pour l'année suivante serait sélectionné en
        # premier (date_debut la plus récente) puis écarté, faisant disparaître
        # le salarié alors qu'il a un contrat valide sur l'année.
        contrat = conn.execute('''
            SELECT type_contrat, date_debut, date_fin, temps_hebdo FROM contrats
            WHERE user_id = ? AND type_contrat IN ('CDI', 'CDD')
              AND date_debut <= ?
              AND (date_fin IS NULL OR date_fin >= ?)
            ORDER BY date_debut DESC LIMIT 1
        ''', (u['id'], f'{annee}-12-31', f'{annee}-01-01')).fetchone()
        if not contrat:
            continue
        mb, mf = _paie_mois_actifs(contrat['date_debut'], contrat['date_fin'], annee)
        if mb is None:
            continue
        employes.append({
            'id': u['id'], 'nom': u['nom'], 'prenom': u['prenom'],
            'pesee': u['pesee'], 'competence': u['competence'],
            'maintien': u['maintien'] if u['maintien'] is not None else 0,
            'temps_hebdo': contrat['temps_hebdo'],
            'type_contrat': contrat['type_contrat'],
            'anciennete': _paie_anciennete_annees(contrat['date_debut'], annee),
            'mois_debut': mb, 'mois_fin': mf,
        })
    employes.sort(key=lambda e: (0 if e['type_contrat'] == 'CDI' else 1, e['nom'], e['prenom']))
    return employes


def _paie_cee_dates(conn, annee):
    """(mercredis_scolaires, vacances_ouvres) en dates ISO, hors fériés.

    - mercredis_scolaires : mercredis en période scolaire (hors vacances/fériés)
    - vacances_ouvres     : jours ouvrés (lun-ven) en vacances scolaires (hors fériés)
    """
    feries = {r['date'] for r in conn.execute(
        'SELECT date FROM jours_feries WHERE annee = ?', (annee,)).fetchall()}
    jours_vac = set()
    for pv in conn.execute('''
        SELECT date_debut, date_fin FROM periodes_vacances
        WHERE date_debut <= ? AND date_fin >= ?
    ''', (f'{annee}-12-31', f'{annee}-01-01')).fetchall():
        try:
            d0 = max(date.fromisoformat(pv['date_debut']), date(annee, 1, 1))
            d1 = min(date.fromisoformat(pv['date_fin']), date(annee, 12, 31))
        except (ValueError, TypeError):
            continue
        d = d0
        while d <= d1:
            jours_vac.add(d)
            d += timedelta(days=1)
    mercredis, vacances = [], []
    d = date(annee, 1, 1)
    end = date(annee, 12, 31)
    while d <= end:
        if d.weekday() < 5 and d.isoformat() not in feries:
            if d in jours_vac:
                vacances.append(d.isoformat())
            elif d.weekday() == 2:
                mercredis.append(d.isoformat())
        d += timedelta(days=1)
    return mercredis, vacances


def _paie_fermetures_set(fermetures, annee):
    """Ensemble des dates de fermeture de la structure (dans l'année)."""
    fermees = set()
    for f in (fermetures or []):
        if not isinstance(f, dict):
            continue
        deb = (f.get('debut') or '').strip()
        fin = (f.get('fin') or '').strip()
        if not deb or not fin:
            continue
        try:
            d0 = date.fromisoformat(deb)
            d1 = date.fromisoformat(fin)
        except (ValueError, TypeError):
            continue
        if d1 < d0:
            continue
        d = d0
        while d <= d1:
            if d.year == annee:
                fermees.add(d.isoformat())
            d += timedelta(days=1)
    return fermees


def _paie_cee_jours_par_mois(conn, annee, fermetures):
    """{mois: {'mercredis': n, 'vacances': n}} hors périodes de fermeture."""
    mercredis, vacances = _paie_cee_dates(conn, annee)
    fermees = _paie_fermetures_set(fermetures, annee)
    result = {m: {'mercredis': 0, 'vacances': 0} for m in range(1, 13)}
    for iso in mercredis:
        if iso not in fermees:
            result[int(iso[5:7])]['mercredis'] += 1
    for iso in vacances:
        if iso not in fermees:
            result[int(iso[5:7])]['vacances'] += 1
    return result


def _paie_reel_641(conn, secteur_id, compte_num, annee):
    """(last_real_month, montant_reel) du compte brut sur l'année, restreint au
    périmètre du secteur (même filtrage que le budget : codes analytiques +
    comptes rattachés). Évite de compter le réel d'un autre secteur partageant
    le même compte 641."""
    if not compte_num:
        return 0, 0.0
    allowed = _secteur_allowed_codes(conn, secteur_id)
    rows = conn.execute('''
        SELECT mois, code_analytique, montant FROM bilan_fec_donnees
        WHERE compte_num = ? AND annee = ?
    ''', (compte_num, annee)).fetchall()
    by_month = {}
    for r in rows:
        if not _code_allowed(r['code_analytique'], compte_num, allowed):
            continue
        m = r['mois']
        if m and 1 <= m <= 12:
            by_month[m] = by_month.get(m, 0.0) + float(r['montant'] or 0)
    if not by_month:
        return 0, 0.0
    last = max(by_month)
    total = round(sum(v for m, v in by_month.items() if m <= last), 2)
    return last, total


def _compute_paie(donnees, employes_base, cee_jours, last_real_month, montant_reel):
    """Calcule le brut par salarié et par mois, le coût CEE et le total annuel.

    Brut mensuel = (socle + (pesée + ancienneté + compétence) × valeur du point) / 12,
    proratisé selon le temps de travail (temps_hebdo / temps plein de référence)
    pour les salariés à temps partiel, puis + maintien (montant fixe non proratisé).
    En budget actualisé, seuls les mois > last_real_month sont simulés ; le total
    intègre le réel (FEC) déjà constaté.
    """
    d = donnees or {}
    socle = _ps_num(d.get('salaire_socle'), PAIE_DEFAULTS['salaire_socle'])
    point = _ps_num(d.get('valeur_point'), PAIE_DEFAULTS['valeur_point'])
    forfait_cee = _ps_num(d.get('forfait_cee'), PAIE_DEFAULTS['forfait_cee'])
    temps_plein = _ps_num(d.get('temps_plein'), PAIE_DEFAULTS['temps_plein'])
    cee_mercredi = _ps_num(d.get('cee_mercredi'))
    cee_vacances = _ps_num(d.get('cee_vacances'))
    overrides = d.get('employes') if isinstance(d.get('employes'), dict) else {}
    ajouts = d.get('ajouts') if isinstance(d.get('ajouts'), list) else []

    start_month = (last_real_month or 0) + 1

    def brut_mensuel(pesee, anciennete, competence):
        return (socle + (pesee + anciennete + competence) * point) / 12.0

    def ratio_temps(temps_hebdo):
        # Temps inconnu ou non renseigné => temps plein (ratio 1).
        return (temps_hebdo / temps_plein) if (temps_hebdo and temps_hebdo > 0 and temps_plein) else 1.0

    def override_num(ov, key, db_value):
        # Champ présent (même vide) => saisie (vide = 0, cohérent avec la
        # persistance sur la fiche) ; champ absent => valeur de la fiche.
        if isinstance(ov, dict) and key in ov:
            return _ps_num(ov.get(key), 0)
        return _ps_num(db_value, 0)

    monthly_totals = {m: 0.0 for m in range(1, 13)}
    lignes = []
    for e in employes_base:
        ov = overrides.get(str(e['id'])) or overrides.get(e['id']) or {}
        pesee_act = override_num(ov, 'pesee', e['pesee'])
        nouv = ov.get('nouvelle_pesee')
        pesee_eff = _ps_num(nouv) if nouv not in (None, '') else pesee_act
        anciennete = override_num(ov, 'anciennete', e['anciennete'])
        competence = override_num(ov, 'competence', e['competence'])
        maintien = override_num(ov, 'maintien', e.get('maintien'))
        ratio = ratio_temps(override_num(ov, 'temps_hebdo', e.get('temps_hebdo')))
        mois_vals, total_e = {}, 0.0
        for m in range(max(start_month, e['mois_debut']), e['mois_fin'] + 1):
            val = brut_mensuel(pesee_eff, anciennete, competence) * ratio + maintien
            mois_vals[m] = round(val, 2)
            monthly_totals[m] += val
            total_e += val
        lignes.append({
            'id': e['id'], 'nom': e['nom'], 'prenom': e['prenom'],
            'type_contrat': e['type_contrat'], 'pesee_eff': pesee_eff,
            'anciennete': anciennete, 'competence': competence, 'maintien': maintien,
            'mois': mois_vals, 'total': round(total_e, 2),
        })

    ajouts_out = []
    for a in ajouts:
        if not isinstance(a, dict):
            continue
        typ = 'cdd' if a.get('type') == 'cdd' else 'cdi'
        pesee_eff = _ps_num(a.get('pesee'))
        anciennete = _ps_num(a.get('anciennete'))
        competence = _ps_num(a.get('competence'))
        maintien = _ps_num(a.get('maintien'))
        ratio = ratio_temps(_ps_num(a.get('temps_hebdo'), temps_plein))
        if typ == 'cdd':
            mb = int(_ps_num(a.get('mois_debut'), 1)) or 1
            mf = int(_ps_num(a.get('mois_fin'), 12)) or 12
        else:
            mb = int(_ps_num(a.get('mois_embauche'), 1)) or 1
            mf = 12
        mb = min(max(mb, 1), 12)
        mf = min(max(mf, 1), 12)
        mois_vals, total_a = {}, 0.0
        for m in range(max(start_month, mb), mf + 1):
            val = brut_mensuel(pesee_eff, anciennete, competence) * ratio + maintien
            mois_vals[m] = round(val, 2)
            monthly_totals[m] += val
            total_a += val
        ajouts_out.append({
            'type': typ, 'pesee': pesee_eff, 'anciennete': anciennete,
            'competence': competence, 'maintien': maintien, 'mois_debut': mb, 'mois_fin': mf,
            'mois': mois_vals, 'total': round(total_a, 2),
        })

    cee_mois = {}
    for m in range(start_month, 13):
        cj = cee_jours.get(m) or {'mercredis': 0, 'vacances': 0}
        cout = (cj['mercredis'] * cee_mercredi + cj['vacances'] * cee_vacances) * forfait_cee
        cee_mois[m] = round(cout, 2)
        monthly_totals[m] += cout

    total_simule = sum(monthly_totals[m] for m in range(start_month, 13))
    return {
        'lignes': lignes,
        'ajouts': ajouts_out,
        'cee_mois': cee_mois,
        'monthly_totals': {m: round(v, 2) for m, v in monthly_totals.items()},
        'last_real_month': last_real_month or 0,
        'montant_reel': round(montant_reel or 0, 2),
        'total_simule': round(total_simule, 2),
        'total': round((montant_reel or 0) + total_simule, 2),
    }


def _paie_report_brut(conn, secteur_id, annee, type_budget, brut_compte, total_brut, user_id):
    """Reporte le brut sur le 641 et répartit 63x/64x (hors 649) au prorata.

    Ratio = compte N-1 / brut N-1 (budget initial) ou réel YTD / brut YTD
    (budget actualisé). Écrit la valeur définitive dans budget_prev_saisies.
    """
    data = _compute_budget_previsionnel(
        conn=conn, type_budget=type_budget, annee=annee, secteur_id=secteur_id
    )
    rows = {r['compte_num']: r for r in data['rows']}
    actualise = (type_budget == 'actualise')
    brut_row = rows.get(brut_compte)
    brut_prev = (brut_row['N'] if actualise else brut_row['N-1']) if brut_row else 0

    reports = {brut_compte: round(total_brut, 2)}
    for compte, r in rows.items():
        if compte == brut_compte or not r.get('is_salary'):
            continue
        prev = r['N'] if actualise else r['N-1']
        ratio = (prev / brut_prev) if brut_prev else 0
        reports[compte] = round(total_brut * ratio, 2)

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for compte, val in reports.items():
        conn.execute('''
            INSERT INTO budget_prev_saisies
            (type_budget, annee, secteur_id, compte_num, valeur_def, updated_by, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(type_budget, annee, secteur_id, compte_num) DO UPDATE SET
                valeur_def = excluded.valeur_def,
                updated_by = excluded.updated_by,
                updated_at = excluded.updated_at
        ''', (type_budget, int(annee), int(secteur_id), compte, val, user_id, now))
    return reports


@budget_bp.route('/api/budget-previsionnel/paie-context')
@login_required
def api_paie_context():
    """Contexte du simulateur de paie : salariés du secteur + calendrier CEE."""
    if session.get('profil') not in ['directeur', 'comptable']:
        return jsonify({'error': 'Accès non autorisé'}), 403
    annee = request.args.get('annee', type=int)
    secteur_id = request.args.get('secteur_id', type=int)
    compte_num = (request.args.get('compte_num') or '').strip()
    type_budget = request.args.get('type_budget', 'initial')
    if not annee or not secteur_id:
        return jsonify({'error': 'Année et secteur requis'}), 400
    conn = get_db()
    try:
        employes = _paie_employes_secteur(conn, secteur_id, annee)
        mercredis, vacances = _paie_cee_dates(conn, annee)
        if type_budget == 'actualise':
            last_real_month, montant_reel = _paie_reel_641(conn, secteur_id, compte_num, annee)
        else:
            last_real_month, montant_reel = 0, 0.0
        return jsonify({
            'employes': employes,
            'mercredis_dates': mercredis,
            'vacances_dates': vacances,
            'last_real_month': last_real_month,
            'montant_reel': montant_reel,
            'defaults': PAIE_DEFAULTS,
        })
    finally:
        conn.close()


@budget_bp.route('/api/budget-previsionnel/paie-simulation')
@login_required
def api_paie_simulation_get():
    """Récupère la simulation de paie enregistrée (année, secteur, type budget)."""
    if session.get('profil') not in ['directeur', 'comptable']:
        return jsonify({'error': 'Accès non autorisé'}), 403
    annee = request.args.get('annee', type=int)
    secteur_id = request.args.get('secteur_id', type=int)
    type_budget = request.args.get('type_budget', 'initial')
    if not annee or not secteur_id:
        return jsonify({'error': 'Année et secteur requis'}), 400
    conn = get_db()
    try:
        row = conn.execute('''
            SELECT donnees, total, updated_at FROM budget_paie_simulations
            WHERE annee = ? AND secteur_id = ? AND type_budget = ?
        ''', (annee, secteur_id, type_budget)).fetchone()
        if not row:
            return jsonify({'found': False, 'donnees': None})
        try:
            donnees = json.loads(row['donnees']) if row['donnees'] else None
        except (ValueError, TypeError):
            donnees = None
        return jsonify({'found': True, 'donnees': donnees, 'total': row['total'],
                        'updated_at': row['updated_at']})
    finally:
        conn.close()


@budget_bp.route('/api/budget-previsionnel/paie-simulation', methods=['POST'])
@login_required
def api_paie_simulation_save():
    """Enregistre la simulation de paie et reporte le brut sur le 641 (+ 63x/64x)."""
    profil = session.get('profil')
    user_id = session.get('user_id')
    if profil not in ['directeur', 'comptable']:
        return jsonify({'error': 'Accès non autorisé'}), 403

    data = request.get_json() or {}
    annee = data.get('annee')
    secteur_id = data.get('secteur_id')
    type_budget = data.get('type_budget')
    compte_num = (data.get('compte_num') or '').strip()
    donnees = data.get('donnees') or {}
    if not isinstance(donnees, dict):
        donnees = {}
    if not annee or not secteur_id:
        return jsonify({'error': 'Année et secteur requis'}), 400
    if type_budget not in ('initial', 'actualise'):
        return jsonify({'error': 'Type de budget invalide'}), 400

    conn = get_db()
    try:
        employes = _paie_employes_secteur(conn, secteur_id, annee)
        cee_jours = _paie_cee_jours_par_mois(conn, annee, donnees.get('fermetures'))
        if type_budget == 'actualise':
            last_real_month, montant_reel = _paie_reel_641(conn, secteur_id, compte_num, annee)
        else:
            last_real_month, montant_reel = 0, 0.0
        computed = _compute_paie(donnees, employes, cee_jours, last_real_month, montant_reel)
        total = computed['total']

        # Persister pesée et compétence sur les fiches salariés (mêmes variables
        # que infos_salaries) à partir des saisies du simulateur.
        overrides = donnees.get('employes') if isinstance(donnees.get('employes'), dict) else {}
        emp_ids = {e['id'] for e in employes}
        for key, ov in overrides.items():
            if not isinstance(ov, dict):
                continue
            try:
                uid = int(key)
            except (TypeError, ValueError):
                continue
            if uid not in emp_ids:
                continue
            pesee = ov.get('pesee')
            comp = ov.get('competence')
            maint = ov.get('maintien')
            conn.execute(
                'UPDATE users SET pesee = ?, competence = ?, maintien = ? WHERE id = ?',
                (int(float(pesee)) if str(pesee).strip() not in ('', 'None') else None,
                 # Les points de compétence peuvent comporter des décimales (ex. 4,25).
                 float(comp) if str(comp).strip() not in ('', 'None') else None,
                 float(maint) if str(maint).strip() not in ('', 'None') else 0,
                 uid)
            )

        conn.execute('''
            INSERT INTO budget_paie_simulations
            (annee, secteur_id, type_budget, compte_num, donnees, total, updated_by, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(annee, secteur_id, type_budget) DO UPDATE SET
                compte_num = excluded.compte_num,
                donnees = excluded.donnees,
                total = excluded.total,
                updated_by = excluded.updated_by,
                updated_at = CURRENT_TIMESTAMP
        ''', (int(annee), int(secteur_id), type_budget, compte_num,
              json.dumps(donnees), total, user_id))

        reports = {}
        if compte_num:
            reports = _paie_report_brut(conn, secteur_id, annee, type_budget,
                                        compte_num, total, user_id)
        conn.commit()
        return jsonify({'success': True, 'total': total, 'computed': computed,
                        'reports': reports})
    finally:
        conn.close()
