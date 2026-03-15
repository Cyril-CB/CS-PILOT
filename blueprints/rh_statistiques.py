"""
Blueprint rh_statistiques_bp.
Page de statistiques RH : effectifs actifs, ETP, arrêts maladie, heures supplémentaires.
"""
from flask import Blueprint, render_template, session, redirect, url_for, flash
from datetime import datetime, date
from database import get_db
from utils import login_required

rh_statistiques_bp = Blueprint('rh_statistiques_bp', __name__)

ETP_CEE = 0.12      # Un CEE compte 0.12 ETP (équivalent temps plein)
HEURES_JOUR = 7.0   # Nombre d'heures par jour ouvré (pour convertir cc_solde en heures)


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
            c.temps_hebdo,
            u.cc_solde
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

    # ── 3. Heures supplémentaires sur 12 mois ──
    # On filtre par (annee * 100 + mois) >= cutoff
    cutoff_annee = int(debut_12_mois[:4])
    cutoff_mois = int(debut_12_mois[5:7])
    cutoff_num = cutoff_annee * 100 + cutoff_mois

    heures_supp_rows = conn.execute('''
        SELECT u.id as user_id, u.secteur_id,
               SUM(CASE WHEN vp.heures_supps > 0 THEN vp.heures_supps ELSE 0 END) as total_supp
        FROM variables_paie vp
        JOIN users u ON vp.user_id = u.id
        WHERE (vp.annee * 100 + vp.mois) >= ?
        GROUP BY u.id
    ''', (cutoff_num,)).fetchall()
    supp_par_user = {r['user_id']: r['total_supp'] or 0 for r in heures_supp_rows}

    conn.close()

    # ── Agréger par secteur et type de contrat ──
    types_contrat = ['CDI', 'CDD', 'CEE', 'Autre']

    # Données globales
    stats_global = {tc: {'nb': 0, 'etp': 0.0} for tc in types_contrat}
    total_maladie_global = 0.0
    total_supp_global = 0.0
    total_recup_global = 0.0

    # Données par secteur
    secteurs_dict = {}
    for sal in actifs_raw:
        sid = sal['secteur_id']
        snom = sal['secteur_nom']
        tc = sal['type_contrat'] if sal['type_contrat'] in types_contrat else 'Autre'
        etp = _calcul_etp(sal['type_contrat'], sal['temps_hebdo'])
        maladie = maladie_par_user.get(sal['user_id'], 0)
        supp = supp_par_user.get(sal['user_id'], 0)
        recup = (sal['cc_solde'] or 0) * HEURES_JOUR  # cc_solde en jours -> heures

        # Global
        stats_global[tc]['nb'] += 1
        stats_global[tc]['etp'] = round(stats_global[tc]['etp'] + etp, 4)
        total_maladie_global += maladie
        total_supp_global += supp
        total_recup_global += recup

        # Par secteur
        if sid not in secteurs_dict:
            secteurs_dict[sid] = {
                'nom': snom,
                'types': {tc2: {'nb': 0, 'etp': 0.0} for tc2 in types_contrat},
                'total_nb': 0,
                'total_etp': 0.0,
                'maladie_jours': 0.0,
                'supp_heures': 0.0,
                'recup_heures': 0.0,
            }
        secteurs_dict[sid]['types'][tc]['nb'] += 1
        secteurs_dict[sid]['types'][tc]['etp'] = round(secteurs_dict[sid]['types'][tc]['etp'] + etp, 4)
        secteurs_dict[sid]['total_nb'] += 1
        secteurs_dict[sid]['total_etp'] = round(secteurs_dict[sid]['total_etp'] + etp, 4)
        secteurs_dict[sid]['maladie_jours'] += maladie
        secteurs_dict[sid]['supp_heures'] += supp
        secteurs_dict[sid]['recup_heures'] += recup

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
        total_recup_global=total_recup_global,
        secteurs_list=secteurs_list,
        chart_labels_type=chart_labels_type,
        chart_nb_type=chart_nb_type,
        chart_etp_type=chart_etp_type,
        chart_labels_secteur=chart_labels_secteur,
        chart_maladie_secteur=chart_maladie_secteur,
        chart_supp_secteur=chart_supp_secteur,
        debut_12_mois=debut_12_mois,
    )
