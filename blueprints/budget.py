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
import sqlite3
from datetime import datetime, date, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, current_app
from database import get_db
from utils import login_required

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
    return profil in ['directeur', 'comptable', 'responsable']


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
        cfg = conn.execute(
            'SELECT code_analytique FROM budget_prev_config_codes WHERE secteur_id = ?',
            (secteur_id,)
        ).fetchall()
        allowed_codes.update((r['code_analytique'] or '').strip() for r in cfg if (r['code_analytique'] or '').strip())
        from_plan = conn.execute(
            'SELECT compte_num FROM comptabilite_comptes WHERE secteur_id = ?',
            (secteur_id,)
        ).fetchall()
        allowed_codes.update((r['compte_num'] or '').strip() for r in from_plan if (r['compte_num'] or '').strip())

    def row_allowed(r):
        if global_mode or not secteur_id:
            return True
        if not allowed_codes:
            return False
        code_ana = (r['code_analytique'] or '').strip()
        compte_num = (r['compte_num'] or '').strip()
        for code in allowed_codes:
            if code_ana == code or compte_num.startswith(code):
                return True
        return False

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

    accounts = []
    for compte, vals in totals.items():
        n2 = round(vals['N-2'], 2)
        n1 = round(vals['N-1'], 2)
        n_full = round(vals['N'], 2)
        nature = 'charges' if compte.startswith('6') else 'produits'
        is_salary = compte.startswith('63') or compte.startswith('64')
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
        accounts.append({
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
        })

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
    annees_traitement = [now.year, now.year + 1]
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

        annees_importees = conn.execute(
            'SELECT DISTINCT annee FROM bilan_fec_imports ORDER BY annee DESC'
        ).fetchall()
        last_month_n = conn.execute(
            'SELECT MAX(mois) as max_mois FROM bilan_fec_donnees WHERE annee = ?',
            (now.year,)
        ).fetchone()
        codes_config = conn.execute('''
            SELECT bpc.id, bpc.code_analytique, bpc.secteur_id, s.nom AS secteur_nom
            FROM budget_prev_config_codes bpc
            JOIN secteurs s ON s.id = bpc.secteur_id
            ORDER BY bpc.code_analytique
        ''').fetchall()

        return render_template(
            'budget_previsionnel.html',
            annees_traitement=annees_traitement,
            secteurs=secteurs,
            secteur_id_defaut=secteur_id_defaut,
            annees_importees=[r['annee'] for r in annees_importees],
            dernier_mois_courant=(last_month_n['max_mois'] if last_month_n else 0) or 0,
            dernier_mois_courant_label=NOMS_MOIS[(last_month_n['max_mois'] if last_month_n else 0) or 0],
            codes_config=[dict(r) for r in codes_config],
            profil=profil
        )
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
