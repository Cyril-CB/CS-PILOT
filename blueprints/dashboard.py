"""
Blueprint Dashboard : tableau de bord salarié.
"""
from flask import Blueprint, render_template, session, redirect, url_for
from datetime import datetime
from database import get_db
from utils import (login_required, get_user_info, calculer_heures,
                   get_heures_theoriques_jour, get_type_periode, get_planning_valide_a_date,
                   calculer_solde_recup)

dashboard_bp = Blueprint('dashboard_bp', __name__)


@dashboard_bp.route('/dashboard')
@login_required
def dashboard():
    """Tableau de bord selon le profil"""
    if session.get('profil') == 'directeur':
        return redirect(url_for('dashboard_direction_bp.dashboard_direction'))

    user = get_user_info(session['user_id'])
    conn = get_db()

    try:
        heures = conn.execute('''
            SELECT date, heure_debut_matin, heure_fin_matin,
                   heure_debut_aprem, heure_fin_aprem,
                   commentaire, type_saisie, declaration_conforme
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
                heures_matin = calculer_heures(h['heure_debut_matin'], h['heure_fin_matin'])
                heures_aprem = calculer_heures(h['heure_debut_aprem'], h['heure_fin_aprem'])
                total_reel = heures_matin + heures_aprem

            ecart = total_reel - total_theorique

            heures_enrichies.append({
                'date': h['date'],
                'heure_debut_matin': h['heure_debut_matin'],
                'heure_fin_matin': h['heure_fin_matin'],
                'heure_debut_aprem': h['heure_debut_aprem'],
                'heure_fin_aprem': h['heure_fin_aprem'],
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
                         heures=heures_enrichies,
                         solde_recup=solde_recup,
                         cp_acquis=cp_acquis,
                         cp_a_prendre=cp_a_prendre,
                         cp_pris=cp_pris,
                         cp_solde=cp_solde,
                         cc_solde=cc_solde,
                         notif_email_off=notif_email_off)
