"""
Blueprint planning_enfance_bp.
Simulateur de planning annualisé pour le secteur Enfance.
Récupère vacances et jours fériés depuis les tables existantes.
Accès : directeur, responsable, comptable.
"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
import json
from datetime import datetime, date, timedelta
from database import get_db
from utils import login_required

planning_enfance_bp = Blueprint('planning_enfance_bp', __name__)

PROFILS_AUTORISES = ['directeur', 'responsable', 'comptable']


def check_access():
    """Vérifie que l'utilisateur a le droit d'accéder au module."""
    return session.get('profil') in PROFILS_AUTORISES


def get_salaries_visibles():
    """Retourne la liste des salariés visibles selon le profil connecté."""
    conn = get_db()
    profil = session.get('profil')

    if profil in ['directeur', 'comptable']:
        # Voir tous les salariés actifs
        salaries = conn.execute('''
            SELECT u.id, u.nom, u.prenom, u.profil, s.nom as secteur_nom
            FROM users u
            LEFT JOIN secteurs s ON u.secteur_id = s.id
            WHERE u.actif = 1 AND u.profil != 'prestataire'
            ORDER BY u.nom, u.prenom
        ''').fetchall()
    else:
        # Responsable : voir les salariés de son secteur + lui-même
        user = conn.execute('SELECT secteur_id FROM users WHERE id = %s',
                            (session['user_id'],)).fetchone()
        secteur_id = user['secteur_id'] if user else None

        if secteur_id:
            salaries = conn.execute('''
                SELECT u.id, u.nom, u.prenom, u.profil, s.nom as secteur_nom
                FROM users u
                LEFT JOIN secteurs s ON u.secteur_id = s.id
                WHERE u.actif = 1 AND (u.secteur_id = %s OR u.id = %s)
                ORDER BY u.nom, u.prenom
            ''', (secteur_id, session['user_id'])).fetchall()
        else:
            salaries = conn.execute('''
                SELECT u.id, u.nom, u.prenom, u.profil, s.nom as secteur_nom
                FROM users u
                LEFT JOIN secteurs s ON u.secteur_id = s.id
                WHERE u.id = %s AND u.actif = 1
            ''', (session['user_id'],)).fetchall()

    conn.close()
    return salaries


@planning_enfance_bp.route('/planning_enfance')
@login_required
def planning_enfance():
    """Page principale du simulateur de planning annualisé enfance."""
    if not check_access():
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    salaries = get_salaries_visibles()
    annee = request.args.get('annee', datetime.now().year, type=int)
    user_id = request.args.get('user_id', type=int)

    return render_template('planning_enfance.html',
                           salaries=salaries,
                           annee=annee,
                           selected_user_id=user_id)


@planning_enfance_bp.route('/api/planning_enfance/vacances/<int:annee>')
@login_required
def api_vacances(annee):
    """Retourne les périodes de vacances pour une année donnée."""
    if not check_access():
        return jsonify({'error': 'Accès non autorisé'}), 403

    conn = get_db()
    periodes = conn.execute('''
        SELECT nom, date_debut, date_fin FROM periodes_vacances
        WHERE date_debut LIKE %s OR date_fin LIKE %s
           OR (date_debut < %s AND date_fin > %s)
        ORDER BY date_debut
    ''', (f'{annee}%', f'{annee}%', f'{annee}-01-01', f'{annee}-12-31')).fetchall()
    conn.close()

    result = []
    for p in periodes:
        # Tronquer aux bornes de l'année civile
        d = max(p['date_debut'], f'{annee}-01-01')
        f = min(p['date_fin'], f'{annee}-12-31')
        result.append({
            'nom': p['nom'],
            'debut': d,
            'fin': f
        })

    return jsonify(result)


@planning_enfance_bp.route('/api/planning_enfance/feries/<int:annee>')
@login_required
def api_feries(annee):
    """Retourne les jours fériés pour une année, enrichis du jour de la semaine."""
    if not check_access():
        return jsonify({'error': 'Accès non autorisé'}), 403

    conn = get_db()
    feries = conn.execute('''
        SELECT date, libelle FROM jours_feries
        WHERE annee = %s
        ORDER BY date
    ''', (annee,)).fetchall()
    conn.close()

    jours = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']
    result = []
    for f in feries:
        d = datetime.strptime(f['date'], '%Y-%m-%d')
        wd = d.weekday()  # 0=lundi
        result.append({
            'date': f['date'],
            'label': f['libelle'],
            'jour_semaine': jours[wd],
            'wd': wd,  # 0-4 lun-ven, 5-6 sam-dim
            'ouvre': wd < 5  # True si jour ouvré
        })

    return jsonify(result)


@planning_enfance_bp.route('/api/planning_enfance/config', methods=['GET'])
@login_required
def api_get_config():
    """Charge la configuration sauvegardée pour un salarié et une année."""
    if not check_access():
        return jsonify({'error': 'Accès non autorisé'}), 403

    user_id = request.args.get('user_id', type=int)
    annee = request.args.get('annee', type=int)

    if not user_id or not annee:
        return jsonify({'error': 'Paramètres manquants'}), 400

    conn = get_db()
    config = conn.execute('''
        SELECT config_json FROM planning_enfance_config
        WHERE user_id = %s AND annee = %s
    ''', (user_id, annee)).fetchone()
    conn.close()

    if config:
        return jsonify(json.loads(config['config_json']))
    else:
        return jsonify(None)


@planning_enfance_bp.route('/api/planning_enfance/config', methods=['POST'])
@login_required
def api_save_config():
    """Sauvegarde la configuration du planning pour un salarié et une année."""
    if not check_access():
        return jsonify({'error': 'Accès non autorisé'}), 403

    data = request.get_json()
    user_id = data.get('user_id')
    annee = data.get('annee')
    config = data.get('config')

    if not user_id or not annee or config is None:
        return jsonify({'error': 'Paramètres manquants'}), 400

    config_json = json.dumps(config, ensure_ascii=False)

    conn = get_db()
    existing = conn.execute('''
        SELECT id FROM planning_enfance_config
        WHERE user_id = %s AND annee = %s
    ''', (user_id, annee)).fetchone()

    if existing:
        conn.execute('''
            UPDATE planning_enfance_config
            SET config_json = %s, updated_at = CURRENT_TIMESTAMP, updated_by = %s
            WHERE user_id = %s AND annee = %s
        ''', (config_json, session['user_id'], user_id, annee))
    else:
        conn.execute('''
            INSERT INTO planning_enfance_config (user_id, annee, config_json, created_by, updated_by)
            VALUES (%s, %s, %s, %s, %s)
        ''', (user_id, annee, config_json, session['user_id'], session['user_id']))

    conn.commit()
    conn.close()

    return jsonify({'success': True})
