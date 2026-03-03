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
from datetime import datetime, date, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from database import get_db
from utils import login_required

budget_bp = Blueprint('budget_bp', __name__)

TYPES_SECTEUR_LABELS = {
    'creche': 'Crèche',
    'accueil_loisirs': 'Accueil de loisirs',
    'famille': 'Secteur famille',
    'emploi_formation': 'Emploi/formation',
    'administratif': 'Administratif',
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
        'SELECT date FROM jours_feries WHERE annee = %s', (annee,)
    ).fetchall()
    jours_feries = {row['date'] for row in feries_rows}

    # Recuperer les periodes de vacances qui chevauchent l'annee
    periodes_vac = conn.execute('''
        SELECT nom, date_debut, date_fin FROM periodes_vacances
        WHERE date_debut <= %s AND date_fin >= %s
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
        WHERE b.annee = %s
    ''', (annee,)).fetchall()
    budgets_map = {b['secteur_id']: dict(b) for b in budgets_raw}

    # Pour chaque budget existant, calculer le total reparti et le total reel
    for secteur_id, budget in budgets_map.items():
        total_reparti = conn.execute('''
            SELECT COALESCE(SUM(bl.montant), 0) as total
            FROM budget_lignes bl
            WHERE bl.budget_id = %s
        ''', (budget['id'],)).fetchone()['total']
        budget['total_reparti'] = total_reparti
        budget['pct_reparti'] = round(
            (total_reparti / budget['montant_global'] * 100) if budget['montant_global'] > 0 else 0, 1
        )

        total_reel = conn.execute('''
            SELECT COALESCE(SUM(brl.montant), 0) as total
            FROM budget_reel_lignes brl
            WHERE brl.budget_id = %s
        ''', (budget['id'],)).fetchone()['total']
        budget['total_reel'] = total_reel
        budget['pct_reel'] = round(
            (total_reel / budget['montant_global'] * 100) if budget['montant_global'] > 0 else 0, 1
        )

    # Construire la liste enrichie des secteurs
    secteurs_data = []
    for s in secteurs:
        sd = dict(s)
        sd['type_label'] = TYPES_SECTEUR_LABELS.get(s['type_secteur'], 'Non défini')
        sd['budget'] = budgets_map.get(s['id'])
        secteurs_data.append(sd)

    conn.close()

    return render_template('gestion_budgets.html',
                           secteurs=secteurs_data,
                           annee=annee,
                           types_labels=TYPES_SECTEUR_LABELS)


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
    secteur = conn.execute('SELECT * FROM secteurs WHERE id = %s', (secteur_id,)).fetchone()
    if not secteur:
        flash('Secteur introuvable', 'error')
        conn.close()
        return redirect(url_for('budget_bp.gestion_budgets'))

    # Verifier les droits d'acces
    if profil == 'responsable':
        user = conn.execute('SELECT secteur_id FROM users WHERE id = %s', (user_id,)).fetchone()
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
    is_alp = secteur['type_secteur'] == 'accueil_loisirs'
    peut_modifier_global = profil in ['directeur', 'comptable']
    peut_modifier_reel = profil in ['directeur', 'comptable']

    # Recuperer ou creer le budget
    budget = conn.execute(
        'SELECT * FROM budgets WHERE secteur_id = %s AND annee = %s',
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
        WHERE pdst.type_secteur = %s AND pd.actif = 1
        ORDER BY pd.nom
    ''', (type_secteur,)).fetchall()

    # Recuperer les lignes budgetaires previsionnelles
    lignes_map = {}
    if budget:
        lignes = conn.execute(
            'SELECT * FROM budget_lignes WHERE budget_id = %s',
            (budget['id'],)
        ).fetchall()
        for l in lignes:
            key = (l['poste_depense_id'], l['periode'])
            lignes_map[key] = dict(l)

    # Recuperer les lignes de depenses reelles
    reel_map = {}
    if budget:
        reel_lignes = conn.execute(
            'SELECT * FROM budget_reel_lignes WHERE budget_id = %s',
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
                           types_labels=TYPES_SECTEUR_LABELS)


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
    secteur = conn.execute('SELECT * FROM secteurs WHERE id = %s', (secteur_id,)).fetchone()
    if not secteur:
        conn.close()
        return jsonify({'error': 'Secteur introuvable'}), 404

    # Verifier les droits
    if profil == 'responsable':
        user = conn.execute('SELECT secteur_id FROM users WHERE id = %s', (user_id,)).fetchone()
        if not user or user['secteur_id'] != int(secteur_id):
            conn.close()
            return jsonify({'error': 'Accès non autorisé'}), 403
    elif profil not in ['directeur', 'comptable']:
        conn.close()
        return jsonify({'error': 'Accès non autorisé'}), 403

    try:
        # Recuperer ou creer le budget
        budget = conn.execute(
            'SELECT * FROM budgets WHERE secteur_id = %s AND annee = %s',
            (secteur_id, annee)
        ).fetchone()

        if budget:
            budget_id = budget['id']
            # Seul direction/comptable peut modifier le global
            if profil in ['directeur', 'comptable'] and montant_global is not None:
                conn.execute('''
                    UPDATE budgets SET montant_global = %s, modifie_par = %s,
                    updated_at = CURRENT_TIMESTAMP WHERE id = %s
                ''', (float(montant_global), user_id, budget_id))
        else:
            if profil not in ['directeur', 'comptable']:
                conn.close()
                return jsonify({'error': 'Seule la direction peut créer un budget'}), 403
            result = conn.execute('''
                INSERT INTO budgets (secteur_id, annee, montant_global, cree_par, modifie_par)
                VALUES (%s, %s, %s, %s, %s) RETURNING id
            ''', (secteur_id, annee, float(montant_global or 0), user_id, user_id))
            budget_id = result.lastrowid

        # Calculer le montant global effectif pour la validation
        budget_after = conn.execute(
            'SELECT montant_global FROM budgets WHERE id = %s', (budget_id,)
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
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT(budget_id, poste_depense_id, periode)
                DO UPDATE SET montant = %s, modifie_par = %s, updated_at = %s
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
        'SELECT id FROM budgets WHERE secteur_id = %s AND annee = %s',
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
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT(budget_id, poste_depense_id, periode)
                DO UPDATE SET montant = %s, modifie_par = %s, updated_at = %s
            ''', (budget_id, poste_id, periode, montant, user_id, now,
                  montant, user_id, now))

        conn.commit()

        # Calculer le nouveau total reel
        total_reel = conn.execute('''
            SELECT COALESCE(SUM(montant), 0) as total
            FROM budget_reel_lignes WHERE budget_id = %s
        ''', (budget_id,)).fetchone()['total']

        montant_global = conn.execute(
            'SELECT montant_global FROM budgets WHERE id = %s', (budget_id,)
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
                    result = conn.execute('INSERT INTO postes_depense (nom) VALUES (%s) RETURNING id', (nom,))
                    poste_id = result.lastrowid
                    for ts in types_selected:
                        conn.execute('''
                            INSERT INTO postes_depense_secteur_types (poste_depense_id, type_secteur)
                            VALUES (%s, %s)
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
                    conn.execute('UPDATE postes_depense SET nom = %s WHERE id = %s', (nom, poste_id))
                    # Supprimer les anciennes associations et recreer
                    conn.execute(
                        'DELETE FROM postes_depense_secteur_types WHERE poste_depense_id = %s',
                        (poste_id,)
                    )
                    for ts in types_selected:
                        conn.execute('''
                            INSERT INTO postes_depense_secteur_types (poste_depense_id, type_secteur)
                            VALUES (%s, %s)
                        ''', (poste_id, ts))
                    conn.commit()
                    flash(f'Poste "{nom}" modifié avec succès', 'success')
                except Exception as e:
                    flash(f'Erreur : {str(e)}', 'error')

        elif action == 'supprimer':
            poste_id = request.form.get('poste_id', type=int)
            # Verifier si le poste est utilise dans des lignes budgetaires
            nb_lignes = conn.execute(
                'SELECT COUNT(*) as nb FROM budget_lignes WHERE poste_depense_id = %s',
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
                    'DELETE FROM postes_depense_secteur_types WHERE poste_depense_id = %s',
                    (poste_id,)
                )
                conn.execute('DELETE FROM postes_depense WHERE id = %s', (poste_id,))
                conn.commit()
                flash('Poste de dépense supprimé', 'success')

        elif action == 'toggle_actif':
            poste_id = request.form.get('poste_id', type=int)
            poste = conn.execute('SELECT actif FROM postes_depense WHERE id = %s', (poste_id,)).fetchone()
            if poste:
                new_val = 0 if poste['actif'] else 1
                conn.execute('UPDATE postes_depense SET actif = %s WHERE id = %s', (new_val, poste_id))
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
            WHERE poste_depense_id = %s
        ''', (p['id'],)).fetchall()
        pd['types_secteur'] = [t['type_secteur'] for t in types]
        postes_data.append(pd)

    conn.close()

    return render_template('gestion_postes_depense.html',
                           postes=postes_data,
                           types_labels=TYPES_SECTEUR_LABELS)


# ============================================================
# BUDGET RESPONSABLE (ACCES DIRECT)
# ============================================================

@budget_bp.route('/mon_budget')
@login_required
def mon_budget():
    """Raccourci pour les responsables vers le budget de leur secteur."""
    user_id = session.get('user_id')
    conn = get_db()
    user = conn.execute('SELECT secteur_id FROM users WHERE id = %s', (user_id,)).fetchone()
    conn.close()

    if not user or not user['secteur_id']:
        flash('Aucun secteur associé à votre compte', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    return redirect(url_for('budget_bp.budget_secteur', secteur_id=user['secteur_id']))
