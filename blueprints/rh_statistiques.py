"""
Blueprint rh_statistiques_bp.
Page de statistiques RH : effectifs actifs, ETP, arrêts maladie, heures supplémentaires.
"""
from flask import Blueprint, render_template, session, redirect, url_for, flash
from datetime import datetime, date
from database import get_db
from utils import login_required
from blueprints.worktime_metrics import compute_day_metrics

rh_statistiques_bp = Blueprint('rh_statistiques_bp', __name__)

ETP_CEE = 0.12      # Un CEE compte 0.12 ETP (équivalent temps plein)


def _calcul_etp(type_contrat, temps_hebdo):
    """Calcule l'ETP d'un salarié selon son type de contrat et temps hebdo."""
    if type_contrat == 'CEE':
        return ETP_CEE
    if temps_hebdo and temps_hebdo > 0:
        return round(temps_hebdo / 35.0, 4)
    return 1.0


def _periode_12_mois():
    """Retourne la date de début de la période de 12 mois glissants."""
    from datetime import timedelta
    return (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')


@rh_statistiques_bp.route('/rh/statistiques')
@login_required
def rh_statistiques():
    """Page de statistiques RH."""
    if session.get('profil') not in ('directeur', 'comptable'):
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    today_str = date.today().strftime('%Y-%m-%d')
    debut_12_mois = _periode_12_mois()

    # ── 1. Salariés actifs avec contrat actif ──
    # On prend le contrat le plus récent actif par salarié
    actifs_raw = conn.execute('''
        SELECT
            u.id as user_id,
            u.nom, u.prenom,
            s.id as secteur_id,
            s.nom as secteur_nom,
            c.type_contrat,
            c.temps_hebdo
        FROM users u
        JOIN secteurs s ON u.secteur_id = s.id
        JOIN contrats c ON c.user_id = u.id
        WHERE u.actif = 1
          AND u.profil NOT IN ('directeur', 'prestataire')
          AND c.date_debut <= ?
          AND (c.date_fin IS NULL OR c.date_fin >= ?)
        GROUP BY u.id
        HAVING c.id = MAX(c.id)
        ORDER BY s.nom, u.nom, u.prenom
    ''', (today_str, today_str)).fetchall()

    # ── 2. Absences maladie sur 12 mois ──
    absences_maladie = conn.execute('''
        SELECT u.id as user_id, u.secteur_id, SUM(a.jours_ouvres) as nb_jours
        FROM absences a
        JOIN users u ON a.user_id = u.id
        WHERE a.motif = 'Arrêt maladie'
          AND a.date_debut >= ?
        GROUP BY u.id
    ''', (debut_12_mois,)).fetchall()
    maladie_par_user = {r['user_id']: r['nb_jours'] or 0 for r in absences_maladie}

    # ── 3. Heures supplémentaires effectuées sur 12 mois ──
    # On somme, jour par jour, le surplus d'heures réellement travaillées
    # par rapport au planning théorique (delta positif). Les jours en déficit
    # (récup) ne viennent pas diminuer ce total d'heures supp effectuées.
    heures_rows = conn.execute('''
        SELECT hr.user_id, hr.date,
               hr.heure_debut_matin, hr.heure_fin_matin,
               hr.heure_debut_aprem, hr.heure_fin_aprem,
               hr.heure_debut_soir, hr.heure_fin_soir,
               hr.declaration_conforme, hr.pause_remuneree
        FROM heures_reelles hr
        JOIN users u ON hr.user_id = u.id
        WHERE hr.date >= ?
          AND u.actif = 1
          AND u.profil NOT IN ('directeur', 'prestataire')
        ORDER BY hr.user_id, hr.date
    ''', (debut_12_mois,)).fetchall()

    supp_par_user = {}
    planning_cache = {}
    type_periode_cache = {}
    for row in heures_rows:
        metrics = compute_day_metrics(conn, row['user_id'], row,
                                      planning_cache, type_periode_cache)
        delta = metrics['delta']
        if delta > 0:
            supp_par_user[row['user_id']] = supp_par_user.get(row['user_id'], 0) + delta

    conn.close()

    # ── Agréger par secteur et type de contrat ──
    types_contrat = ['CDI', 'CDD', 'CEE', 'Autre']

    # Données globales
    stats_global = {tc: {'nb': 0, 'etp': 0.0} for tc in types_contrat}
    total_maladie_global = 0.0
    total_supp_global = 0.0

    # Données par secteur
    secteurs_dict = {}
    for sal in actifs_raw:
        sid = sal['secteur_id']
        snom = sal['secteur_nom']
        tc = sal['type_contrat'] if sal['type_contrat'] in types_contrat else 'Autre'
        etp = _calcul_etp(sal['type_contrat'], sal['temps_hebdo'])
        maladie = maladie_par_user.get(sal['user_id'], 0)
        supp = supp_par_user.get(sal['user_id'], 0)

        # Global
        stats_global[tc]['nb'] += 1
        stats_global[tc]['etp'] = round(stats_global[tc]['etp'] + etp, 4)
        total_maladie_global += maladie
        total_supp_global += supp

        # Par secteur
        if sid not in secteurs_dict:
            secteurs_dict[sid] = {
                'nom': snom,
                'types': {tc2: {'nb': 0, 'etp': 0.0} for tc2 in types_contrat},
                'total_nb': 0,
                'total_etp': 0.0,
                'maladie_jours': 0.0,
                'supp_heures': 0.0,
            }
        secteurs_dict[sid]['types'][tc]['nb'] += 1
        secteurs_dict[sid]['types'][tc]['etp'] = round(secteurs_dict[sid]['types'][tc]['etp'] + etp, 4)
        secteurs_dict[sid]['total_nb'] += 1
        secteurs_dict[sid]['total_etp'] = round(secteurs_dict[sid]['total_etp'] + etp, 4)
        secteurs_dict[sid]['maladie_jours'] += maladie
        secteurs_dict[sid]['supp_heures'] += supp

    # Totaux globaux
    total_nb_global = sum(v['nb'] for v in stats_global.values())
    total_etp_global = round(sum(v['etp'] for v in stats_global.values()), 4)

    # Données pour les graphiques (JSON-friendly)
    chart_labels_type = types_contrat
    chart_nb_type = [stats_global[tc]['nb'] for tc in types_contrat]
    chart_etp_type = [round(stats_global[tc]['etp'], 2) for tc in types_contrat]

    chart_labels_secteur = [v['nom'] for v in secteurs_dict.values()]
    chart_maladie_secteur = [round(v['maladie_jours'], 1) for v in secteurs_dict.values()]
    chart_supp_secteur = [round(v['supp_heures'], 1) for v in secteurs_dict.values()]

    secteurs_list = list(secteurs_dict.values())

    return render_template(
        'rh_statistiques.html',
        today=date.today(),
        types_contrat=types_contrat,
        stats_global=stats_global,
        total_nb_global=total_nb_global,
        total_etp_global=total_etp_global,
        total_maladie_global=total_maladie_global,
        total_supp_global=total_supp_global,
        secteurs_list=secteurs_list,
        chart_labels_type=chart_labels_type,
        chart_nb_type=chart_nb_type,
        chart_etp_type=chart_etp_type,
        chart_labels_secteur=chart_labels_secteur,
        chart_maladie_secteur=chart_maladie_secteur,
        chart_supp_secteur=chart_supp_secteur,
        debut_12_mois=debut_12_mois,
    )
