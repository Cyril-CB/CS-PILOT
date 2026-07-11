"""
Blueprint dashboard_direction_bp.

« Centre de contrôle » de la direction (accessible au comptable) :
- recherche intelligente avec exemples cliquables ;
- « Votre prochaine action » : l'élément le plus urgent, remplacé dès qu'il
  est traité ;
- KPI par exception : seules les valeurs qui franchissent leur seuil
  (paramétrable) s'affichent — trésorerie, budget consommé, congés
  conventionnels, surcharge ;
- file « À faire maintenant » actionnable en un clic (factures, demandes,
  relances) ;
- « Aller plus loin » : suggestions de modules, renouvelées au hasard.
"""
import json
import logging
import random
from datetime import datetime

from flask import (Blueprint, flash, jsonify, redirect, render_template,
                   request, session, url_for)

from dashboard_actions import construire_actions
from database import get_db
from utils import NOMS_MOIS, get_setting, login_required, save_setting

logger = logging.getLogger(__name__)

dashboard_direction_bp = Blueprint('dashboard_direction_bp', __name__)

JOURS_SEMAINE = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']

# Seuils d'alerte par défaut (modifiables via la fenêtre « Seuils d'alerte »).
SEUILS_DEFAUT = {
    'treso': 50000.0,      # alerte si la trésorerie passe SOUS ce montant (€)
    'budget': 80.0,        # alerte si un budget secteur dépasse ce % consommé
    'conges': 5.0,         # alerte à partir de ce solde de congés conventionnels (j)
    'surcharge': 55.0,     # alerte à partir de ce score de surcharge (/100)
}
_SEUILS_SETTING = 'dashboard_direction_seuils'

# Digest quotidien par email : activé par défaut, désactivable dans la
# fenêtre des seuils. Envoyé au premier accès à l'application après cette
# heure (aucun planificateur externe requis).
DIGEST_DEFAUT = True
DIGEST_HEURE = 8

# Pool de modules mis en avant dans « Aller plus loin » (3 tirés au hasard).
_SUGGESTIONS_MODULES = [
    {'icone': '📊', 'titre': 'Statistiques RH', 'endpoint': 'rh_statistiques_bp.rh_statistiques',
     'detail': "Absentéisme, effectifs et contrats par secteur, sur 12 mois glissants.",
     'action': 'Explorer les stats'},
    {'icone': '🗓️', 'titre': 'Planificateur de tâches', 'endpoint': 'planificateur_bp.planificateur',
     'detail': "Organisez votre semaine en blocs : vos échéances deviennent des tâches planifiées.",
     'action': 'Organiser ma semaine'},
    {'icone': '🏠', 'titre': 'Réservations de salles', 'endpoint': 'salles_bp.salles',
     'detail': "Plannings des salles avec récurrences qui excluent vacances et jours fériés.",
     'action': 'Voir le calendrier'},
    {'icone': '📈', 'titre': 'Trésorerie', 'endpoint': 'tresorerie_bp.tresorerie',
     'detail': "Le solde projeté mois par mois, alimenté par vos imports comptables.",
     'action': 'Projeter le solde'},
    {'icone': '🏕️', 'titre': 'Analyse ALSH', 'endpoint': 'alsh_bp.analyse_alsh',
     'detail': "Croisez les données comptables et la fréquentation de vos accueils de loisirs.",
     'action': "Ouvrir l'analyse"},
    {'icone': '📝', 'titre': 'Génération de contrats', 'endpoint': 'generation_contrats_bp.generation_contrats',
     'detail': "Générez un contrat de travail depuis vos modèles DOCX en quelques clics.",
     'action': 'Générer un contrat'},
    {'icone': '🗓️', 'titre': 'Présence effectif', 'endpoint': 'presence_effectif_bp.presence_effectif',
     'detail': "La présence de l'équipe jour par jour : maladie, congés, récup en un coup d'œil.",
     'action': 'Voir la présence'},
    {'icone': '🧑‍⚖️', 'titre': 'Espace CSE', 'endpoint': 'cse_bp.cse_accueil',
     'detail': "Messages aux salariés (bannière + email) et budget simplifié du comité.",
     'action': "Ouvrir l'espace CSE"},
]

# Exemples affichés sous la barre de recherche (vérifiés par les tests du
# moteur : chacun conduit à la bonne page).
_EXEMPLES_RECHERCHE = ['budget prévisionnel', 'CDD en cours',
                       'facture à valider', 'arrêts maladies']


def _lire_seuils():
    """Seuils d'alerte : valeurs enregistrées, complétées par les défauts."""
    seuils = dict(SEUILS_DEFAUT)
    seuils['digest'] = DIGEST_DEFAUT
    brut = get_setting(_SEUILS_SETTING)
    if brut:
        try:
            for cle, val in (json.loads(brut) or {}).items():
                if cle == 'digest':
                    seuils['digest'] = bool(val)
                elif cle in SEUILS_DEFAUT:
                    seuils[cle] = float(val)
        except (ValueError, TypeError):
            logger.warning("Seuils dashboard direction illisibles, défauts utilisés")
    return seuils


def _calcul_etp(type_contrat, temps_hebdo):
    """Calcule l'ETP d'un salarie selon son type de contrat.

    - CEE (Contrat d'Engagement Educatif) : forfait fixe 0.12 ETP
    - Autres : temps_hebdo / 35h (duree legale hebdomadaire), defaut 1.0 ETP
    """
    if type_contrat == 'CEE':
        return 0.12
    if temps_hebdo and temps_hebdo > 0:
        return round(temps_hebdo / 35.0, 4)
    return 1.0


def _calculer_surcharges(conn, seuil):
    """Salariés dont le score de surcharge atteint le seuil (tri décroissant).

    Réutilise le calcul de la page « Alertes surcharge » (source unique).
    """
    from blueprints.suivi import _calculate_surcharge_alert
    from blueprints.worktime_metrics import get_feries_set

    users = conn.execute('''
        SELECT u.id, u.nom, u.prenom, u.profil, u.solde_initial, s.nom AS secteur_nom
        FROM users u
        LEFT JOIN secteurs s ON s.id = u.secteur_id
        WHERE u.actif = 1 AND u.profil NOT IN ('directeur', 'prestataire')
        ORDER BY u.nom, u.prenom
    ''').fetchall()

    today = datetime.now().date()
    feries_set = get_feries_set(conn)
    planning_cache = {}
    type_periode_cache = {}

    surcharges = []
    for user in users:
        try:
            alerte = _calculate_surcharge_alert(conn, user, today, feries_set,
                                                planning_cache, type_periode_cache)
        except Exception:
            logger.exception("Calcul surcharge impossible pour user %s", user['id'])
            continue
        if alerte and alerte['score'] >= seuil:
            surcharges.append(alerte)
    surcharges.sort(key=lambda a: (-a['score'], -a['solde_actuel']))
    return surcharges


def _fmt_euro(valeur):
    return f"{valeur:,.0f}".replace(',', ' ') + ' €'


def _construire_file_actions(conn, profil, user_id, seuils):
    """File d'actions étendue + liste des surcharges (partagé page / fragment).

    Le calcul de surcharge lit tout l'historique d'heures : en cas d'erreur il
    est neutralisé plutôt que de faire tomber le tableau de bord.
    """
    try:
        surcharges = _calculer_surcharges(conn, seuils['surcharge'])
    except Exception:
        logger.exception("Calcul des surcharges impossible")
        surcharges = []
    actions = construire_actions(conn, profil, user_id,
                                 etendu=True, seuils=seuils, surcharges=surcharges)
    return actions, surcharges


@dashboard_direction_bp.route('/dashboard_direction')
@login_required
def dashboard_direction():
    """Centre de contrôle de la direction."""
    if session.get('profil') not in ('directeur', 'comptable'):
        flash('Acces non autorise', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    seuils = _lire_seuils()
    conn = get_db()
    today = datetime.now()
    today_str = today.strftime('%Y-%m-%d')
    mois, annee = today.month, today.year

    try:
        # ── Effectif / ETP ──
        total_salaries = conn.execute('''
            SELECT COUNT(*) as nb FROM users
            WHERE actif = 1 AND profil NOT IN ('directeur', 'prestataire')
        ''').fetchone()['nb']

        salaries_contrats = conn.execute('''
            WITH last_active_contract AS (
                SELECT c.user_id, MAX(c.id) AS last_contract_id
                FROM contrats c
                JOIN users u ON c.user_id = u.id
                WHERE u.actif = 1 AND u.profil NOT IN ('directeur', 'prestataire')
                  AND c.date_debut <= ?
                  AND (c.date_fin IS NULL OR c.date_fin >= ?)
                GROUP BY c.user_id
            )
            SELECT c.type_contrat, c.temps_hebdo
            FROM last_active_contract lac
            JOIN contrats c ON c.id = lac.last_contract_id
        ''', (today_str, today_str)).fetchall()
        total_etp = round(sum(_calcul_etp(sc['type_contrat'], sc['temps_hebdo'])
                              for sc in salaries_contrats), 2)

        # ── Absences en cours aujourd'hui ──
        nb_absents = conn.execute('''
            SELECT COUNT(*) AS nb FROM absences
            WHERE date_debut <= ? AND date_fin >= ?
        ''', (today_str, today_str)).fetchone()['nb']

        # ── Anomalies non traitées ──
        nb_anomalies = conn.execute(
            'SELECT COUNT(*) as nb FROM anomalies WHERE traitee = 0'
        ).fetchone()['nb']

        # ── Subventions accordées (montants) ──
        total_subv_accorde = conn.execute(
            'SELECT COALESCE(SUM(montant_accorde), 0) AS total FROM subventions'
        ).fetchone()['total']

        # ── Fiches du mois précédent (complètes / total) ──
        mois_prec = mois - 1 or 12
        annee_prec = annee if mois > 1 else annee - 1
        fiches = conn.execute('''
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN v.bloque = 1 THEN 1 ELSE 0 END) AS complet
            FROM users u
            LEFT JOIN validations v ON v.user_id = u.id AND v.mois = ? AND v.annee = ?
            WHERE u.actif = 1 AND u.profil NOT IN ('directeur', 'prestataire')
        ''', (mois_prec, annee_prec)).fetchone()
        fiches_complet = fiches['complet'] or 0
        fiches_total = fiches['total'] or 0

        # ── Budgets de l'année : % consommé par secteur ──
        budgets = conn.execute('''
            SELECT s.nom AS secteur_nom, b.montant_global,
                   COALESCE(SUM(brl.montant), 0) AS montant_reel
            FROM budgets b
            JOIN secteurs s ON b.secteur_id = s.id
            LEFT JOIN budget_reel_lignes brl ON brl.budget_id = b.id
            WHERE b.annee = ?
            GROUP BY b.id, s.nom, b.montant_global
        ''', (annee,)).fetchall()
        budgets_depasses = []
        budget_max_pct = 0.0
        for b in budgets:
            if not b['montant_global']:
                continue
            pct = b['montant_reel'] / b['montant_global'] * 100
            budget_max_pct = max(budget_max_pct, pct)
            if pct >= seuils['budget']:
                budgets_depasses.append({'secteur': b['secteur_nom'], 'pct': round(pct),
                                         'reel': b['montant_reel'], 'global': b['montant_global']})
        budgets_depasses.sort(key=lambda b: -b['pct'])

        # ── Trésorerie (solde actuel) ──
        solde_treso = None
        try:
            solde_row = conn.execute(
                'SELECT montant, annee_ref, mois_ref FROM tresorerie_solde_initial ORDER BY id DESC LIMIT 1'
            ).fetchone()
            if solde_row:
                cumul = conn.execute('''
                    SELECT COALESCE(SUM(td.montant), 0) as total
                    FROM tresorerie_donnees td
                    JOIN tresorerie_comptes tc ON td.compte_num = tc.compte_num
                    WHERE tc.actif = 1
                      AND td.compte_num NOT LIKE '512%'
                      AND td.compte_num NOT LIKE '531%'
                      AND td.compte_num NOT LIKE '580%'
                      AND td.compte_num NOT LIKE '471%'
                      AND (td.annee > ? OR (td.annee = ? AND td.mois >= ?))
                      AND (td.annee < ? OR (td.annee = ? AND td.mois <= ?))
                ''', (solde_row['annee_ref'], solde_row['annee_ref'], solde_row['mois_ref'],
                      annee, annee, mois)).fetchone()['total']
                solde_treso = round(solde_row['montant'] + cumul, 2)
        except Exception:
            logger.exception("Erreur lors du calcul du solde de trésorerie")
            solde_treso = None

        # ── Congés conventionnels au-dessus du seuil ──
        conges_hauts = conn.execute('''
            SELECT COUNT(*) AS nb, MAX(COALESCE(cc_solde, 0)) AS maxi
            FROM users
            WHERE actif = 1 AND profil NOT IN ('directeur', 'prestataire')
              AND COALESCE(cc_solde, 0) >= ?
        ''', (seuils['conges'],)).fetchone()
        cc_max = conn.execute('''
            SELECT MAX(COALESCE(cc_solde, 0)) AS maxi FROM users
            WHERE actif = 1 AND profil NOT IN ('directeur', 'prestataire')
        ''').fetchone()['maxi'] or 0

        # ── File d'actions (étendue) + surcharges + prochaine action ──
        actions, surcharges = _construire_file_actions(
            conn, session.get('profil'), session.get('user_id'), seuils)
    finally:
        conn.close()

    prochaine = actions[0] if actions else None

    # ── KPI par exception : seules les valeurs hors seuil apparaissent ──
    alertes_seuil = []
    if solde_treso is not None and solde_treso < seuils['treso']:
        alertes_seuil.append({
            'etiquette': 'Trésorerie sous le seuil', 'couleur': '#bf4444', 'icone': '📉',
            'valeur': _fmt_euro(solde_treso),
            'detail': f"seuil fixé à {_fmt_euro(seuils['treso'])}",
            'lien': url_for('tresorerie_bp.tresorerie'), 'lien_texte': 'Ouvrir la trésorerie',
        })
    if budgets_depasses:
        pire = budgets_depasses[0]
        autres = f" (+{len(budgets_depasses) - 1} autre(s))" if len(budgets_depasses) > 1 else ''
        alertes_seuil.append({
            'etiquette': 'Budget presque épuisé', 'couleur': '#ba7a2a', 'icone': '💰',
            'valeur': f"{pire['secteur']} — {pire['pct']} %",
            'detail': f"{_fmt_euro(pire['reel'])} consommés sur {_fmt_euro(pire['global'])}"
                      f" (seuil {seuils['budget']:g} %){autres}",
            'lien': url_for('budget_bp.gestion_budgets'), 'lien_texte': 'Voir les budgets',
        })
    if conges_hauts['nb'] > 0:
        maxi = f"{conges_hauts['maxi']:g}".replace('.', ',')
        alertes_seuil.append({
            'etiquette': 'Congés conventionnels à planifier', 'couleur': '#8b5cf6', 'icone': '🏖️',
            'valeur': f"{conges_hauts['nb']} salarié(s)",
            'detail': f"solde ≥ {seuils['conges']:g} j (max : {maxi} j)".replace('.', ','),
            'lien': url_for('infos_salaries_bp.infos_salaries'), 'lien_texte': 'Voir les soldes',
        })
    if surcharges:
        alertes_seuil.append({
            'etiquette': 'Surcharge de travail', 'couleur': '#bf4444', 'icone': '🚨',
            'valeur': f"{len(surcharges)} salarié(s)",
            'detail': f"score ≥ {seuils['surcharge']:g}/100 — max {surcharges[0]['score']}/100"
                      f" ({surcharges[0]['nom_complet']})",
            'lien': url_for('suivi_bp.alertes_surcharge'), 'lien_texte': 'Alertes surcharge',
        })

    # ── Indicateurs dans la normale (repliés) ──
    indicateurs_ok = [
        {'valeur': str(total_salaries), 'libelle': 'Effectif actif'},
        {'valeur': f"{total_etp:g}".replace('.', ','), 'libelle': 'ETP total'},
        {'valeur': str(nb_absents), 'libelle': "Absences aujourd'hui"},
        {'valeur': str(nb_anomalies), 'libelle': 'Anomalies non traitées'},
        {'valeur': _fmt_euro(total_subv_accorde), 'libelle': 'Subventions accordées'},
        {'valeur': f"{fiches_complet}/{fiches_total}",
         'libelle': f"Fiches de {NOMS_MOIS[mois_prec].lower()} complètes"},
    ]
    if solde_treso is not None and solde_treso >= seuils['treso']:
        indicateurs_ok.append({'valeur': _fmt_euro(solde_treso), 'libelle': 'Trésorerie'})
    if budgets and not budgets_depasses:
        indicateurs_ok.append({'valeur': f"{budget_max_pct:.0f} %",
                               'libelle': 'Budget le plus consommé'})
    if conges_hauts['nb'] == 0:
        indicateurs_ok.append({'valeur': f"{cc_max:g} j".replace('.', ','),
                               'libelle': 'Congés conv. max'})
    if not surcharges:
        indicateurs_ok.append({'valeur': '0', 'libelle': 'Salarié en surcharge'})

    suggestions = [
        dict(s, lien=url_for(s['endpoint']))
        for s in random.sample(_SUGGESTIONS_MODULES, k=3)
    ]

    return render_template(
        'dashboard_direction.html',
        date_longue=f"{JOURS_SEMAINE[today.weekday()]} {today.day} {NOMS_MOIS[mois].lower()} {annee}",
        actions=actions,
        nb_actions=len(actions),
        prochaine=prochaine,
        alertes_seuil=alertes_seuil,
        indicateurs_ok=indicateurs_ok,
        suggestions=suggestions,
        exemples_recherche=_EXEMPLES_RECHERCHE,
        seuils=seuils,
    )


@dashboard_direction_bp.route('/api/dashboard-direction/seuils', methods=['POST'])
@login_required
def api_seuils_save():
    """Enregistre les seuils d'alerte du centre de contrôle."""
    if session.get('profil') not in ('directeur', 'comptable'):
        return jsonify({'error': 'Accès non autorisé'}), 403
    data = request.get_json(silent=True) or {}
    seuils = _lire_seuils()
    for cle in SEUILS_DEFAUT:
        if cle in data:
            try:
                valeur = float(data[cle])
            except (TypeError, ValueError):
                return jsonify({'error': f"Seuil « {cle} » invalide"}), 400
            if valeur < 0:
                return jsonify({'error': f"Seuil « {cle} » invalide"}), 400
            seuils[cle] = valeur
    if 'digest' in data:
        seuils['digest'] = bool(data['digest'])
    save_setting(_SEUILS_SETTING, json.dumps(seuils))
    return jsonify({'success': True, 'seuils': seuils})


@dashboard_direction_bp.route('/api/dashboard-direction/actions-fragment')
@login_required
def api_actions_fragment():
    """Fragment HTML de la file d'actions (rafraîchissement automatique)."""
    if session.get('profil') not in ('directeur', 'comptable'):
        return jsonify({'error': 'Accès non autorisé'}), 403
    seuils = _lire_seuils()
    conn = get_db()
    try:
        actions, _ = _construire_file_actions(
            conn, session.get('profil'), session.get('user_id'), seuils)
    finally:
        conn.close()
    return render_template('_cc_actions_liste.html', actions=actions)


# ══════════════════════════════════════════════════════════════════════════
#  Digest quotidien par email (premier accès après DIGEST_HEURE)
# ══════════════════════════════════════════════════════════════════════════

# Mémo processus : dernière date pour laquelle le digest a été vérifié — évite
# une requête en base à chaque hit une fois le digest du jour traité.
_digest_date_traitee = None


def _destinataires_digest(conn, date_str):
    """Direction et comptabilité, hors personnes en congé ce jour-là.

    Exclut toute personne ayant une absence couvrant la date, ainsi que les
    journées posées directement au calendrier forfait jour (congé, repos
    forfait, maladie… — tout sauf « travaille » et « ferie »).
    """
    return conn.execute('''
        SELECT u.id, u.prenom, u.email
        FROM users u
        WHERE u.actif = 1 AND u.profil IN ('directeur', 'comptable')
          AND u.email IS NOT NULL AND TRIM(u.email) != ''
          AND NOT EXISTS (
              SELECT 1 FROM absences a
              WHERE a.user_id = u.id AND a.date_debut <= ? AND a.date_fin >= ?
          )
          AND NOT EXISTS (
              SELECT 1 FROM presence_forfait_jour p
              WHERE p.user_id = u.id AND p.date = ?
                AND p.type_journee NOT IN ('travaille', 'ferie')
          )
        ORDER BY u.nom
    ''', (date_str, date_str, date_str)).fetchall()


def _composer_digest(actions, quand):
    """(sujet, contenu HTML) du digest à partir de la file d'actions."""
    import html as html_module
    _e = html_module.escape
    nb = len(actions)
    en_retard = sum(1 for a in actions if a['urgence'] == 'retard')
    urgents = sum(1 for a in actions if a['urgence'] == 'urgent')

    lignes = ''.join(
        f'<li style="margin:4px 0;">{a["icone"]} <strong>{_e(a["titre"])}</strong>'
        f'<br><span style="color:#786b60;font-size:13px;">{_e(a["detail"])}</span></li>'
        for a in actions[:8]
    )
    reste = f'<p style="color:#786b60;">… et {nb - 8} autre(s) action(s).</p>' if nb > 8 else ''
    lien = url_for('dashboard_direction_bp.dashboard_direction', _external=True)

    contenu = f"""
    <h3 style="color:#667eea;margin:0 0 12px;font-size:16px;">Votre journée CS-PILOT</h3>
    <p><strong>{nb} action(s)</strong> vous attendent ce
       {JOURS_SEMAINE[quand.weekday()].lower()} {quand.day} {NOMS_MOIS[quand.month].lower()}
       — dont <strong style="color:#dc2626;">{en_retard} en retard</strong>
       et <strong style="color:#d97706;">{urgents} urgente(s)</strong>.</p>
    <ul style="padding-left:18px;">{lignes}</ul>
    {reste}
    <p style="margin-top:16px;"><a href="{lien}">Ouvrir le centre de contrôle</a>
       pour les traiter en un clic.</p>
    """
    sujet = f"Votre journée CS-PILOT — {nb} action(s) en attente"
    return sujet, contenu


def _envoyer_digest_du_jour(quand):
    """Compose et envoie le digest aux destinataires présents. Retourne le
    nombre d'emails envoyés (0 si rien à faire)."""
    from email_service import envoyer_email

    conn = get_db()
    try:
        date_str = quand.strftime('%Y-%m-%d')
        destinataires = _destinataires_digest(conn, date_str)
        if not destinataires:
            return 0
        seuils = _lire_seuils()
        actions, _ = _construire_file_actions(conn, 'directeur', None, seuils)
        if not actions:
            return 0
        sujet, contenu = _composer_digest(actions, quand)
    finally:
        conn.close()

    nb_envoyes = 0
    for dest in destinataires:
        ok, _msg = envoyer_email(dest['email'], sujet, contenu, dest['prenom'])
        if ok:
            nb_envoyes += 1
    logger.info("Digest direction envoyé à %s destinataire(s)", nb_envoyes)
    return nb_envoyes


@dashboard_direction_bp.before_app_request
def _digest_tick():
    """Déclenche le digest au premier accès après DIGEST_HEURE.

    Sans planificateur externe : n'importe quelle requête applicative après
    l'heure cible déclenche l'envoi, une seule fois par jour (réclamation
    atomique en base — INSERT OR IGNORE sur une clé datée — pour rester sûr
    avec plusieurs workers). Ne doit jamais faire échouer la requête en cours.
    """
    global _digest_date_traitee
    try:
        from utils import maintenant
        quand = maintenant()
        date_str = quand.strftime('%Y-%m-%d')
        if _digest_date_traitee == date_str or quand.hour < DIGEST_HEURE:
            return
        if request.endpoint in (None, 'static'):
            return

        from email_service import is_email_configured
        if not is_email_configured() or not _lire_seuils().get('digest', DIGEST_DEFAUT):
            _digest_date_traitee = date_str   # rien à envoyer aujourd'hui
            return

        # Réclamation atomique : un seul processus/worker envoie le digest.
        conn = get_db()
        try:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, 'envoye')",
                (f'digest_direction_{date_str}',))
            conn.commit()
            gagne = cursor.rowcount > 0
        finally:
            conn.close()
        _digest_date_traitee = date_str
        if gagne:
            _envoyer_digest_du_jour(quand)
    except Exception:
        logger.exception("Digest quotidien : erreur ignorée")
