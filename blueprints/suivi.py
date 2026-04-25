"""
Blueprint suivi_bp.
"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from datetime import datetime, timedelta
import json
from database import get_db
from utils import login_required

suivi_bp = Blueprint('suivi_bp', __name__)


SURCHARGE_CATEGORIES = [
    {'label': 'Vert', 'min': 0, 'max': 25, 'color': '#16a34a', 'text_color': '#14532d'},
    {'label': 'Jaune', 'min': 26, 'max': 50, 'color': '#eab308', 'text_color': '#713f12'},
    {'label': 'Orange', 'min': 51, 'max': 75, 'color': '#f97316', 'text_color': '#7c2d12'},
    {'label': 'Rouge', 'min': 76, 'max': 99, 'color': '#dc2626', 'text_color': '#7f1d1d'},
    {'label': 'Noir', 'min': 100, 'max': 100, 'color': '#111827', 'text_color': '#111827'},
]


def _profil_direction_compta():
    return session.get('profil') in ['directeur', 'comptable']


def _get_previous_month_range(reference_date):
    first_day_current_month = reference_date.replace(day=1)
    last_day_previous_month = first_day_current_month - timedelta(days=1)
    first_day_previous_month = last_day_previous_month.replace(day=1)
    return first_day_previous_month, last_day_previous_month


def _get_last_completed_week_monday(reference_date):
    current_week_monday = reference_date - timedelta(days=reference_date.weekday())
    return current_week_monday - timedelta(days=7)


def _get_feries_set(conn):
    return {
        row['date']
        for row in conn.execute('SELECT date FROM jours_feries').fetchall()
    }


def _get_type_periode_cached(conn, date_str, type_periode_cache):
    if date_str not in type_periode_cache:
        periode = conn.execute('''
            SELECT 1
            FROM periodes_vacances
            WHERE ? >= date_debut AND ? <= date_fin
            LIMIT 1
        ''', (date_str, date_str)).fetchone()
        type_periode_cache[date_str] = 'vacances' if periode else 'periode_scolaire'
    return type_periode_cache[date_str]


def _get_planning_cached(conn, user_id, date_str, planning_cache, type_periode_cache):
    cache_key = (user_id, date_str)
    if cache_key not in planning_cache:
        type_periode = _get_type_periode_cached(conn, date_str, type_periode_cache)
        planning = conn.execute('''
            SELECT *
            FROM planning_theorique
            WHERE user_id = ?
              AND type_periode = ?
              AND (type_alternance IS NULL OR type_alternance = 'fixe')
              AND date_debut_validite <= ?
            ORDER BY date_debut_validite DESC
            LIMIT 1
        ''', (user_id, type_periode, date_str)).fetchone()
        planning_cache[cache_key] = planning
    return planning_cache[cache_key]


def _day_segments_from_row(row):
    segments = []
    if row['heure_debut_matin'] and row['heure_fin_matin']:
        segments.append((row['heure_debut_matin'], row['heure_fin_matin']))
    if row['heure_debut_aprem'] and row['heure_fin_aprem']:
        segments.append((row['heure_debut_aprem'], row['heure_fin_aprem']))
    return segments


def _day_segments_from_planning(planning, date_obj):
    if not planning or date_obj.weekday() > 4:
        return []

    jour_nom = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi'][date_obj.weekday()]
    segments = []
    matin_debut = planning[f'{jour_nom}_matin_debut']
    matin_fin = planning[f'{jour_nom}_matin_fin']
    aprem_debut = planning[f'{jour_nom}_aprem_debut']
    aprem_fin = planning[f'{jour_nom}_aprem_fin']

    if matin_debut and matin_fin:
        segments.append((matin_debut, matin_fin))
    if aprem_debut and aprem_fin:
        segments.append((aprem_debut, aprem_fin))
    return segments


def _compute_segments_metrics(date_obj, segments):
    metrics = {
        'worked_hours': 0.0,
        'start_at': None,
        'end_at': None,
        'break_minutes': None,
        'longest_consecutive_hours': 0.0,
    }
    if not segments:
        return metrics

    dt_segments = []
    for start_str, end_str in segments:
        start_dt = datetime.combine(date_obj, datetime.strptime(start_str, '%H:%M').time())
        end_dt = datetime.combine(date_obj, datetime.strptime(end_str, '%H:%M').time())
        if end_dt < start_dt:
            end_dt += timedelta(days=1)
        dt_segments.append((start_dt, end_dt))

    metrics['worked_hours'] = round(sum((end - start).total_seconds() for start, end in dt_segments) / 3600, 2)
    metrics['start_at'] = dt_segments[0][0]
    metrics['end_at'] = dt_segments[-1][1]

    if len(dt_segments) >= 2:
        break_seconds = (dt_segments[1][0] - dt_segments[0][1]).total_seconds()
        metrics['break_minutes'] = round(max(0, break_seconds) / 60, 2)

    longest_seconds = (dt_segments[0][1] - dt_segments[0][0]).total_seconds()
    current_seconds = longest_seconds
    for index in range(1, len(dt_segments)):
        gap_seconds = (dt_segments[index][0] - dt_segments[index - 1][1]).total_seconds()
        segment_seconds = (dt_segments[index][1] - dt_segments[index][0]).total_seconds()
        if gap_seconds < 20 * 60:
            current_seconds += max(gap_seconds, 0) + segment_seconds
        else:
            longest_seconds = max(longest_seconds, current_seconds)
            current_seconds = segment_seconds
    longest_seconds = max(longest_seconds, current_seconds)
    metrics['longest_consecutive_hours'] = round(longest_seconds / 3600, 2)

    return metrics


def _compute_day_metrics(conn, user_id, row, planning_cache, type_periode_cache):
    date_obj = datetime.strptime(row['date'], '%Y-%m-%d').date()
    planning = _get_planning_cached(conn, user_id, row['date'], planning_cache, type_periode_cache)
    planned_segments = _day_segments_from_planning(planning, date_obj)
    actual_segments = planned_segments if row['declaration_conforme'] else _day_segments_from_row(row)

    planned_metrics = _compute_segments_metrics(date_obj, planned_segments)
    actual_metrics = _compute_segments_metrics(date_obj, actual_segments)

    theoretical_hours = 0.0
    if date_obj.weekday() == 5:
        theoretical_hours = 0.0
    elif date_obj.weekday() < 5:
        theoretical_hours = planned_metrics['worked_hours']

    actual_hours = theoretical_hours if row['declaration_conforme'] else actual_metrics['worked_hours']

    pause_reduced = (
        planned_metrics['break_minutes'] is not None
        and actual_metrics['break_minutes'] is not None
        and actual_metrics['break_minutes'] < planned_metrics['break_minutes']
    )

    return {
        'date': row['date'],
        'date_obj': date_obj,
        'theoretical_hours': theoretical_hours,
        'actual_hours': actual_hours,
        'delta': round(actual_hours - theoretical_hours, 2),
        'start_at': actual_metrics['start_at'],
        'end_at': actual_metrics['end_at'],
        'break_minutes': actual_metrics['break_minutes'],
        'planned_break_minutes': planned_metrics['break_minutes'],
        'pause_reduced': pause_reduced,
        'longest_consecutive_hours': actual_metrics['longest_consecutive_hours'],
    }


def _recent_business_days(end_date, limit, feries_set):
    days = []
    current = end_date
    while len(days) < limit:
        if current.weekday() < 5 and current.strftime('%Y-%m-%d') not in feries_set:
            days.append(current.strftime('%Y-%m-%d'))
        current -= timedelta(days=1)
    days.reverse()
    return days


def _format_points(label, points, detail):
    return {'label': label, 'points': points, 'detail': detail}


def _get_score_category(score):
    score = min(100, max(0, int(round(score))))
    for category in SURCHARGE_CATEGORIES:
        if category['min'] <= score <= category['max']:
            return category
    return SURCHARGE_CATEGORIES[0]


def _calculate_surcharge_alert(conn, user, today, feries_set, planning_cache, type_periode_cache):
    rows = conn.execute('''
        SELECT date, heure_debut_matin, heure_fin_matin, heure_debut_aprem, heure_fin_aprem, declaration_conforme
        FROM heures_reelles
        WHERE user_id = ? AND date <= ?
        ORDER BY date
    ''', (user['id'], today.strftime('%Y-%m-%d'))).fetchall()

    day_metrics = {}
    solde_courant = user['solde_initial'] or 0
    previous_month_start, previous_month_end = _get_previous_month_range(today)
    solde_dernier_mois = 0

    sparkline_start = today - timedelta(days=59)
    sparkline_labels = []
    sparkline_points = []
    solde_avant_fenetre = solde_courant

    for row in rows:
        metrics = _compute_day_metrics(conn, user['id'], row, planning_cache, type_periode_cache)
        day_metrics[metrics['date']] = metrics
        if metrics['date_obj'] < sparkline_start:
            solde_avant_fenetre += metrics['delta']
        solde_courant += metrics['delta']
        if previous_month_start <= metrics['date_obj'] <= previous_month_end:
            solde_dernier_mois += metrics['delta']

    running_balance = solde_avant_fenetre
    current_day = sparkline_start
    while current_day <= today:
        date_str = current_day.strftime('%Y-%m-%d')
        if date_str in day_metrics:
            running_balance += day_metrics[date_str]['delta']
        sparkline_labels.append(current_day.strftime('%d/%m'))
        sparkline_points.append(round(running_balance, 2))
        current_day += timedelta(days=1)

    reference_workday = today - timedelta(days=1)
    recent_5_days = _recent_business_days(reference_workday, 5, feries_set)
    recent_20_days = _recent_business_days(reference_workday, 20, feries_set)

    overtime_last_5 = round(sum(max(day_metrics.get(day, {}).get('delta', 0), 0) for day in recent_5_days), 2)
    overtime_points = 0
    overtime_detail = 'Aucun dépassement sur les 5 derniers jours ouvrés'
    if overtime_last_5 > 12:
        overtime_points = 14
        overtime_detail = f'{overtime_last_5:.1f}h sur les 5 derniers jours ouvrés'
    elif overtime_last_5 > 7:
        overtime_points = 8
        overtime_detail = f'{overtime_last_5:.1f}h sur les 5 derniers jours ouvrés'
    elif overtime_last_5 > 3.5:
        overtime_points = 4
        overtime_detail = f'{overtime_last_5:.1f}h sur les 5 derniers jours ouvrés'

    last_completed_week_monday = _get_last_completed_week_monday(today)
    weekly_totals = []
    for offset in range(3):
        week_start = last_completed_week_monday - timedelta(days=offset * 7)
        week_dates = [
            (week_start + timedelta(days=day_offset)).strftime('%Y-%m-%d')
            for day_offset in range(5)
            if (week_start + timedelta(days=day_offset)).strftime('%Y-%m-%d') not in feries_set
        ]
        weekly_totals.append(round(sum(day_metrics.get(day, {}).get('actual_hours', 0) for day in week_dates), 2))

    weekly_average_12 = []
    for offset in range(12):
        week_start = last_completed_week_monday - timedelta(days=offset * 7)
        week_dates = [
            (week_start + timedelta(days=day_offset)).strftime('%Y-%m-%d')
            for day_offset in range(5)
            if (week_start + timedelta(days=day_offset)).strftime('%Y-%m-%d') not in feries_set
        ]
        weekly_average_12.append(round(sum(day_metrics.get(day, {}).get('actual_hours', 0) for day in week_dates), 2))
    moyenne_12_semaines = round(sum(weekly_average_12) / len(weekly_average_12), 2) if weekly_average_12 else 0

    threshold_options = []
    if any(day_metrics.get(day, {}).get('actual_hours', 0) > 10 for day in recent_5_days):
        threshold_options.append(_format_points('Seuil', 18, 'Au moins une journée au-delà de 10h sur les 5 derniers jours ouvrés'))
    if moyenne_12_semaines > 44:
        threshold_options.append(_format_points('Seuil', 18, f'Moyenne hebdomadaire de {moyenne_12_semaines:.1f}h sur les 12 dernières semaines complètes'))
    max_three_weeks = max(weekly_totals) if weekly_totals else 0
    if max_three_weeks >= 48:
        threshold_options.append(_format_points('Seuil', 20, f'Une semaine à {max_three_weeks:.1f}h sur les 3 dernières semaines complètes'))

    threshold_points = max((item['points'] for item in threshold_options), default=0)
    threshold_detail = next((item['detail'] for item in threshold_options if item['points'] == threshold_points), 'Aucun seuil dépassé')

    rest_options = []
    previous_worked_day = None
    for date_str in recent_20_days:
        metrics = day_metrics.get(date_str)
        if not metrics or not metrics['start_at'] or not metrics['end_at']:
            continue
        if previous_worked_day:
            rest_hours = (metrics['start_at'] - previous_worked_day['end_at']).total_seconds() / 3600
            if rest_hours < 11:
                rest_options.append(_format_points('Repos', 20, f'Repos quotidien réduit à {rest_hours:.1f}h entre deux journées travaillées'))
                break
        previous_worked_day = metrics

    if any(day_metrics.get(day, {}).get('longest_consecutive_hours', 0) >= 6 for day in recent_20_days):
        rest_options.append(_format_points('Repos', 20, 'Au moins 6h de travail consécutif avec une pause inférieure à 20 minutes'))

    pause_reduced_5 = sum(1 for day in recent_5_days if day_metrics.get(day, {}).get('pause_reduced'))
    pause_reduced_20 = sum(1 for day in recent_20_days if day_metrics.get(day, {}).get('pause_reduced'))
    if pause_reduced_20 >= 8:
        rest_options.append(_format_points('Repos', 16, f'Pause prévue réduite {pause_reduced_20} fois sur les 20 derniers jours ouvrés'))
    elif pause_reduced_5 >= 3:
        rest_options.append(_format_points('Repos', 12, f'Pause prévue réduite {pause_reduced_5} fois sur les 5 derniers jours ouvrés'))
    elif pause_reduced_5 >= 1:
        rest_options.append(_format_points('Repos', 5, 'Pause prévue réduite au moins une fois sur les 5 derniers jours ouvrés'))

    rest_points = max((item['points'] for item in rest_options), default=0)
    rest_detail = next((item['detail'] for item in rest_options if item['points'] == rest_points), 'Aucun signal repos détecté')

    monthly_points = 0
    monthly_detail = 'Solde du dernier mois écoulé inférieur à 5h'
    if solde_dernier_mois > 20:
        monthly_points = 18
        monthly_detail = f'Solde du dernier mois écoulé : +{solde_dernier_mois:.1f}h'
    elif solde_dernier_mois > 10:
        monthly_points = 12
        monthly_detail = f'Solde du dernier mois écoulé : +{solde_dernier_mois:.1f}h'
    elif solde_dernier_mois >= 5:
        monthly_points = 6
        monthly_detail = f'Solde du dernier mois écoulé : +{solde_dernier_mois:.1f}h'

    current_balance_points = 0
    current_balance_detail = 'Solde actuel inférieur à 20h'
    if solde_courant > 50:
        current_balance_points = 20
        current_balance_detail = f'Solde actuel : +{solde_courant:.1f}h'
    elif solde_courant > 35:
        current_balance_points = 16
        current_balance_detail = f'Solde actuel : +{solde_courant:.1f}h'
    elif solde_courant >= 20:
        current_balance_points = 12
        current_balance_detail = f'Solde actuel : +{solde_courant:.1f}h'

    breakdown = [
        _format_points('Heures supplémentaires hebdomadaires', overtime_points, overtime_detail),
        _format_points('Seuil', threshold_points, threshold_detail),
        _format_points('Repos', rest_points, rest_detail),
        _format_points('Solde du dernier mois', monthly_points, monthly_detail),
        _format_points('Solde non récupéré', current_balance_points, current_balance_detail),
    ]

    score = min(100, sum(item['points'] for item in breakdown))
    if score <= 0 or solde_courant <= 0:
        return None

    category = _get_score_category(score)
    return {
        'user_id': user['id'],
        'nom_complet': f"{user['prenom']} {user['nom']}",
        'secteur_nom': user['secteur_nom'] or 'Sans secteur',
        'profil': user['profil'],
        'score': score,
        'category': category,
        'solde_actuel': round(solde_courant, 2),
        'solde_dernier_mois': round(solde_dernier_mois, 2),
        'sparkline_labels': sparkline_labels,
        'sparkline_points': sparkline_points,
        'breakdown': breakdown,
    }


@suivi_bp.route('/historique_modifications')
@login_required
def historique_modifications():
    """Historique des modifications (directeur uniquement)"""
    if session.get('profil') != 'directeur':
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))
    
    # Filtres optionnels
    user_id_filtre = request.args.get('user_id', type=int)
    date_debut = request.args.get('date_debut')
    date_fin = request.args.get('date_fin')
    
    conn = get_db()
    
    # Construire la requête avec filtres
    query = '''
        SELECT h.*,
               u_modifie.nom || ' ' || u_modifie.prenom as nom_modifie,
               u_par.nom || ' ' || u_par.prenom as nom_modificateur
        FROM historique_modifications h
        JOIN users u_modifie ON h.user_id_modifie = u_modifie.id
        JOIN users u_par ON h.modifie_par = u_par.id
        WHERE 1=1
    '''
    params = []
    
    if user_id_filtre:
        query += ' AND h.user_id_modifie = ?'
        params.append(user_id_filtre)
    
    if date_debut:
        query += ' AND h.date_concernee >= ?'
        params.append(date_debut)
    
    if date_fin:
        query += ' AND h.date_concernee <= ?'
        params.append(date_fin)
    
    query += ' ORDER BY h.date_modification DESC LIMIT 200'
    
    modifications = conn.execute(query, params).fetchall()
    
    # Récupérer la liste des utilisateurs pour le filtre
    users = conn.execute('''
        SELECT id, nom, prenom FROM users 
        WHERE actif = 1 AND profil NOT IN ('directeur', 'prestataire')
        ORDER BY nom, prenom
    ''').fetchall()
    
    conn.close()
    
    # Convertir les modifications en dictionnaires avec parsing JSON
    modifications_list = []
    for m in modifications:
        mod_dict = dict(m)
        if mod_dict['anciennes_valeurs']:
            mod_dict['anciennes_valeurs_obj'] = json.loads(mod_dict['anciennes_valeurs'])
        else:
            mod_dict['anciennes_valeurs_obj'] = None
        
        if mod_dict['nouvelles_valeurs']:
            mod_dict['nouvelles_valeurs_obj'] = json.loads(mod_dict['nouvelles_valeurs'])
        else:
            mod_dict['nouvelles_valeurs_obj'] = None
        
        modifications_list.append(mod_dict)
    
    return render_template('historique_modifications.html',
                         modifications=modifications_list,
                         users=users,
                         user_id_filtre=user_id_filtre,
                         date_debut=date_debut,
                         date_fin=date_fin)

@suivi_bp.route('/suivi_anomalies', methods=['GET', 'POST'])
@login_required
def suivi_anomalies():
    """Suivi des anomalies et modifications suspectes (direction uniquement)"""
    if session.get('profil') not in ['directeur', 'comptable']:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))
    
    conn = get_db()
    
    # POST : Marquer une anomalie comme traitée
    if request.method == 'POST':
        anomalie_id = request.form.get('anomalie_id', type=int)
        action = request.form.get('action')
        
        if anomalie_id and action == 'traiter':
            conn.execute('UPDATE anomalies SET traitee = 1 WHERE id = ?', (anomalie_id,))
            conn.commit()
            flash('Anomalie marquée comme traitée', 'success')
        
        conn.close()
        return redirect(url_for('suivi_bp.suivi_anomalies'))
    
    # GET : Afficher les anomalies
    gravite_filtre = request.args.get('gravite', 'toutes')
    afficher_traitees = request.args.get('traitees', '0') == '1'
    
    # Construire la requête
    query = '''
        SELECT a.*,
               u.nom || ' ' || u.prenom as nom_salarie,
               u.profil
        FROM anomalies a
        JOIN users u ON a.user_id = u.id
        WHERE 1=1
    '''
    params = []
    
    if not afficher_traitees:
        query += ' AND a.traitee = 0'
    
    if gravite_filtre != 'toutes':
        query += ' AND a.gravite = ?'
        params.append(gravite_filtre)
    
    query += ' ORDER BY a.date_modification DESC, a.gravite ASC LIMIT 500'
    
    anomalies = conn.execute(query, params).fetchall()
    
    # Statistiques
    stats = conn.execute('''
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN gravite = 'critique' THEN 1 ELSE 0 END) as critiques,
            SUM(CASE WHEN gravite = 'alerte' THEN 1 ELSE 0 END) as alertes,
            SUM(CASE WHEN gravite = 'suspect' THEN 1 ELSE 0 END) as suspects,
            SUM(CASE WHEN traitee = 0 THEN 1 ELSE 0 END) as non_traitees
        FROM anomalies
    ''').fetchone()
    
    conn.close()
    
    # Parser les anciennes/nouvelles valeurs JSON
    anomalies_list = []
    for a in anomalies:
        anom_dict = dict(a)
        if anom_dict['ancienne_valeur']:
            try:
                anom_dict['ancienne_valeur_obj'] = json.loads(anom_dict['ancienne_valeur'])
            except (ValueError, json.JSONDecodeError):
                anom_dict['ancienne_valeur_obj'] = None
        else:
            anom_dict['ancienne_valeur_obj'] = None
        
        if anom_dict['nouvelle_valeur']:
            try:
                anom_dict['nouvelle_valeur_obj'] = json.loads(anom_dict['nouvelle_valeur'])
            except (ValueError, json.JSONDecodeError):
                anom_dict['nouvelle_valeur_obj'] = None
        else:
            anom_dict['nouvelle_valeur_obj'] = None
        
        anomalies_list.append(anom_dict)
    
    return render_template('suivi_anomalies.html',
                          anomalies=anomalies_list,
                          stats=dict(stats) if stats else {},
                          gravite_filtre=gravite_filtre,
                          afficher_traitees=afficher_traitees)


@suivi_bp.route('/alertes_surcharge')
@login_required
def alertes_surcharge():
    """Alertes de surcharge de travail pour la direction et la comptabilité."""
    if not _profil_direction_compta():
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    try:
        users = conn.execute('''
            SELECT u.id, u.nom, u.prenom, u.profil, u.solde_initial, s.nom AS secteur_nom
            FROM users u
            LEFT JOIN secteurs s ON s.id = u.secteur_id
            WHERE u.actif = 1 AND u.profil NOT IN ('directeur', 'prestataire')
            ORDER BY s.nom, u.nom, u.prenom
        ''').fetchall()

        today = datetime.now().date()
        feries_set = _get_feries_set(conn)
        planning_cache = {}
        type_periode_cache = {}

        alertes = []
        for user in users:
            alerte = _calculate_surcharge_alert(conn, user, today, feries_set, planning_cache, type_periode_cache)
            if alerte:
                alertes.append(alerte)

        alertes.sort(key=lambda item: (-item['score'], -item['solde_actuel'], item['nom_complet']))
    finally:
        conn.close()

    return render_template(
        'alertes_surcharge.html',
        alertes=alertes,
        today=today,
        mois=today.month,
        annee=today.year,
    )
