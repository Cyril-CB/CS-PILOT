"""
Blueprint Dashboard : tableau de bord salarié.
"""
from flask import Blueprint, render_template, session, redirect, url_for, request
from datetime import datetime
from database import get_db
from blueprints.prevention_sante import compute_prevention_messages
from utils import (login_required, get_user_info, calculer_heures,
                   calculer_heures_reelles_jour,
                   get_heures_theoriques_jour, get_type_periode, get_planning_valide_a_date,
                   calculer_solde_recup)

dashboard_bp = Blueprint('dashboard_bp', __name__)
MAX_PREVENTION_DISMISS_KEYS = 50


@dashboard_bp.route('/dashboard')
@login_required
def dashboard():
    """Tableau de bord selon le profil"""
    profil = session.get('profil')
    user = None
    if profil == 'directeur':
        return redirect(url_for('dashboard_direction_bp.dashboard_direction'))
    if profil == 'responsable':
        user = get_user_info(session['user_id'])
        if user and user['secteur_id']:
            return redirect(url_for('dashboard_responsable_bp.dashboard_responsable'))
        # Sans secteur mais avec des rattachés directs (responsable_id), le
        # tableau de bord responsable reste pertinent : même règle d'équipe.
        if user:
            conn = get_db()
            a_rattaches = conn.execute(
                'SELECT 1 FROM users WHERE responsable_id = ? AND actif = 1 LIMIT 1',
                (session['user_id'],)
            ).fetchone()
            conn.close()
            if a_rattaches:
                return redirect(url_for('dashboard_responsable_bp.dashboard_responsable'))
    if profil == 'comptable':
        return redirect(url_for('dashboard_comptable_bp.dashboard_comptable'))

    if user is None:
        user = get_user_info(session['user_id'])
    conn = get_db()

    try:
        prevention_messages = compute_prevention_messages(conn, session['user_id'])

        heures = conn.execute('''
            SELECT date, heure_debut_matin, heure_fin_matin,
                   heure_debut_aprem, heure_fin_aprem,
                   heure_debut_soir, heure_fin_soir,
                   commentaire, type_saisie, declaration_conforme, pause_remuneree
            FROM heures_reelles
            WHERE user_id = ?
            ORDER BY date DESC
            LIMIT 10
        ''', (session['user_id'],)).fetchall()

        heures_enrichies = []

        for h in heures:
            date_obj = datetime.strptime(h['date'], '%Y-%m-%d')
            if date_obj.weekday() == 6:
                continue

            type_periode = get_type_periode(h['date'])
            total_theorique = 0

            if date_obj.weekday() == 5:
                total_theorique = 0
            else:
                planning = get_planning_valide_a_date(session['user_id'], type_periode, h['date'])
                if planning:
                    total_theorique = get_heures_theoriques_jour(planning, date_obj.weekday())

            if h['declaration_conforme']:
                total_reel = total_theorique
            else:
                total_reel = calculer_heures_reelles_jour(h)

            ecart = total_reel - total_theorique

            heures_enrichies.append({
                'date': h['date'],
                'heure_debut_matin': h['heure_debut_matin'],
                'heure_fin_matin': h['heure_fin_matin'],
                'heure_debut_aprem': h['heure_debut_aprem'],
                'heure_fin_aprem': h['heure_fin_aprem'],
                'heure_debut_soir': h['heure_debut_soir'],
                'heure_fin_soir': h['heure_fin_soir'],
                'commentaire': h['commentaire'],
                'total_reel': total_reel,
                'total_theorique': total_theorique,
                'ecart': ecart
            })

        # Solde de recuperation calcule sur TOUT l'historique
        solde_recup = calculer_solde_recup(session['user_id'])

        # Compteurs de conges
        conges_user = conn.execute('''
            SELECT cp_acquis, cp_a_prendre, cp_pris, cc_solde
            FROM users WHERE id = ?
        ''', (session['user_id'],)).fetchone()

        cp_acquis = (conges_user['cp_acquis'] or 0) if conges_user else 0
        cp_a_prendre = (conges_user['cp_a_prendre'] or 0) if conges_user else 0
        cp_pris = (conges_user['cp_pris'] or 0) if conges_user else 0
        cp_solde = cp_a_prendre - cp_pris
        cc_solde = (conges_user['cc_solde'] or 0) if conges_user else 0

        # Statut des notifications email (uniquement pour salarie/prestataire)
        notif_email_off = False
        if session.get('profil') in ('salarie', 'prestataire'):
            try:
                notif_row = conn.execute(
                    'SELECT email_notifications_enabled FROM users WHERE id = ?',
                    (session['user_id'],)
                ).fetchone()
                if notif_row and not notif_row['email_notifications_enabled']:
                    notif_email_off = True
            except Exception:
                pass
    finally:
        conn.close()

    return render_template('dashboard.html',
                         user=user,
                         prevention_messages=prevention_messages,
                         heures=heures_enrichies,
                         solde_recup=solde_recup,
                         cp_acquis=cp_acquis,
                         cp_a_prendre=cp_a_prendre,
                         cp_pris=cp_pris,
                         cp_solde=cp_solde,
                         cc_solde=cc_solde,
                         notif_email_off=notif_email_off)


@dashboard_bp.route('/dashboard/prevention_dismiss', methods=['POST'])
@login_required
def prevention_dismiss():
    keys = []
    seen = set()
    for key in request.form.getlist('keys'):
        if not key or not key.startswith('prev:') or len(key) > 200:
            continue
        if key in seen:
            continue
        seen.add(key)
        keys.append(key)
        if len(keys) >= MAX_PREVENTION_DISMISS_KEYS:
            break

    if not keys:
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    try:
        conn.executemany(
            """
            INSERT INTO prevention_dismissals (user_id, message_key)
            VALUES (?, ?)
            ON CONFLICT(user_id, message_key) DO UPDATE SET dismissed_at = CURRENT_TIMESTAMP
            """,
            [(session['user_id'], key) for key in keys],
        )
        conn.commit()
    finally:
        conn.close()

    return redirect(url_for('dashboard_bp.dashboard'))
