"""
Blueprint dashboard_direction_bp.
Tableau de bord global pour la direction avec vue d'ensemble quotidienne.
"""
from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from datetime import datetime, timedelta
from database import get_db
from utils import login_required, NOMS_MOIS
import logging

logger = logging.getLogger(__name__)

dashboard_direction_bp = Blueprint('dashboard_direction_bp', __name__)


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


@dashboard_direction_bp.route('/dashboard_direction')
@login_required
def dashboard_direction():
    """Tableau de bord global pour la direction."""
    if session.get('profil') not in ('directeur', 'comptable'):
        flash('Acces non autorise', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    today = datetime.now()
    today_str = today.strftime('%Y-%m-%d')
    mois = today.month
    annee = today.year

    # ── 1. Effectifs par secteur ──
    effectifs = conn.execute('''
        SELECT s.id as secteur_id, s.nom as secteur_nom,
               COUNT(u.id) as nb_salaries
        FROM secteurs s
        LEFT JOIN users u ON u.secteur_id = s.id AND u.actif = 1
            AND u.profil NOT IN ('directeur', 'prestataire')
        GROUP BY s.id
        ORDER BY s.nom
    ''').fetchall()

    total_salaries = conn.execute('''
        SELECT COUNT(*) as nb FROM users
        WHERE actif = 1 AND profil NOT IN ('directeur', 'prestataire')
    ''').fetchone()['nb']

    # Repartition par type de contrat actif
    contrats_par_type = conn.execute('''
        SELECT c.type_contrat, COUNT(DISTINCT c.user_id) as nb
        FROM contrats c
        JOIN users u ON c.user_id = u.id
        WHERE u.actif = 1 AND u.profil NOT IN ('directeur', 'prestataire')
          AND c.date_debut <= ?
          AND (c.date_fin IS NULL OR c.date_fin >= ?)
        GROUP BY c.type_contrat
        ORDER BY c.type_contrat
    ''', (today_str, today_str)).fetchall()
    contrats_dict = {row['type_contrat']: row['nb'] for row in contrats_par_type}

    # ── 1b. ETP par type de contrat ──
    salaries_contrats = conn.execute('''
        SELECT u.id, c.type_contrat, c.temps_hebdo
        FROM users u
        JOIN contrats c ON c.user_id = u.id
        WHERE u.actif = 1 AND u.profil NOT IN ('directeur', 'prestataire')
          AND c.date_debut <= ?
          AND (c.date_fin IS NULL OR c.date_fin >= ?)
        GROUP BY u.id
        HAVING c.id = MAX(c.id)
    ''', (today_str, today_str)).fetchall()

    total_etp = 0.0
    etp_par_type = {}
    for sc in salaries_contrats:
        etp = _calcul_etp(sc['type_contrat'], sc['temps_hebdo'])
        total_etp += etp
        t = sc['type_contrat'] or 'Autre'
        etp_par_type[t] = etp_par_type.get(t, 0.0) + etp
    total_etp = round(total_etp, 2)

    # ── 2. Absences en cours (chevauchant aujourd'hui) ──
    absences_en_cours = conn.execute('''
        SELECT a.id, a.motif, a.date_debut, a.date_fin, a.jours_ouvres,
               a.date_reprise, a.commentaire,
               u.nom as salarie_nom, u.prenom as salarie_prenom,
               s.nom as secteur_nom
        FROM absences a
        JOIN users u ON a.user_id = u.id
        LEFT JOIN secteurs s ON u.secteur_id = s.id
        WHERE a.date_debut <= ? AND a.date_fin >= ?
        ORDER BY s.nom, u.nom, u.prenom
    ''', (today_str, today_str)).fetchall()

    # Regrouper absences par secteur
    absences_par_secteur = {}
    for ab in absences_en_cours:
        sect = ab['secteur_nom'] or 'Non affecte'
        if sect not in absences_par_secteur:
            absences_par_secteur[sect] = []
        absences_par_secteur[sect].append(dict(ab))

    # Repartition par motif (pour le graphique)
    repartition_motifs = conn.execute('''
        SELECT a.motif, COUNT(*) as nb
        FROM absences a
        WHERE a.date_debut <= ? AND a.date_fin >= ?
        GROUP BY a.motif
        ORDER BY nb DESC
    ''', (today_str, today_str)).fetchall()

    # ── 3. Validations mensuelles (mois en cours par defaut, navigable) ──
    mois_validation = request.args.get('val_mois', mois, type=int)
    annee_validation = request.args.get('val_annee', annee, type=int)

    # Borner les valeurs
    if mois_validation < 1:
        mois_validation = 1
    elif mois_validation > 12:
        mois_validation = 12
    if annee_validation < 2020:
        annee_validation = 2020
    elif annee_validation > annee + 1:
        annee_validation = annee + 1

    # Calculer mois precedent / suivant pour la navigation
    if mois_validation == 1:
        val_mois_prec, val_annee_prec = 12, annee_validation - 1
    else:
        val_mois_prec, val_annee_prec = mois_validation - 1, annee_validation

    if mois_validation == 12:
        val_mois_suiv, val_annee_suiv = 1, annee_validation + 1
    else:
        val_mois_suiv, val_annee_suiv = mois_validation + 1, annee_validation

    # Ne pas permettre de naviguer au-dela du mois en cours
    est_mois_courant = (mois_validation == mois and annee_validation == annee)
    peut_avancer = not est_mois_courant and (
        annee_validation < annee or
        (annee_validation == annee and mois_validation < mois)
    )

    users_a_valider = conn.execute('''
        SELECT u.id, u.nom, u.prenom, s.nom as secteur_nom
        FROM users u
        LEFT JOIN secteurs s ON u.secteur_id = s.id
        WHERE u.actif = 1 AND u.profil NOT IN ('directeur', 'prestataire')
        ORDER BY s.nom, u.nom
    ''').fetchall()

    validations_map = {}
    validations_rows = conn.execute('''
        SELECT * FROM validations
        WHERE mois = ? AND annee = ?
    ''', (mois_validation, annee_validation)).fetchall()
    for v in validations_rows:
        validations_map[v['user_id']] = dict(v)

    # Stats de validation par secteur
    validation_par_secteur = {}
    nb_total_a_valider = 0
    nb_complet = 0
    nb_en_cours = 0
    nb_non_commence = 0

    for u in users_a_valider:
        sect = u['secteur_nom'] or 'Non affecte'
        if sect not in validation_par_secteur:
            validation_par_secteur[sect] = {
                'total': 0, 'complet': 0, 'en_cours': 0, 'non_commence': 0
            }

        validation_par_secteur[sect]['total'] += 1
        nb_total_a_valider += 1

        v = validations_map.get(u['id'])
        if v and v['bloque']:
            validation_par_secteur[sect]['complet'] += 1
            nb_complet += 1
        elif v and (v['validation_salarie'] or v['validation_responsable'] or v['validation_directeur']):
            validation_par_secteur[sect]['en_cours'] += 1
            nb_en_cours += 1
        else:
            validation_par_secteur[sect]['non_commence'] += 1
            nb_non_commence += 1

    # Liste des fiches non completement validees (pour le detail)
    fiches_en_attente = []
    for u in users_a_valider:
        v = validations_map.get(u['id'])
        if not v or not v['bloque']:
            etapes = []
            if v:
                if not v['validation_salarie']:
                    etapes.append('Salarie')
                if not v['validation_responsable']:
                    etapes.append('Responsable')
                if not v['validation_directeur']:
                    etapes.append('Directeur')
            else:
                etapes = ['Salarie', 'Responsable', 'Directeur']

            fiches_en_attente.append({
                'user_id': u['id'],
                'nom': u['nom'],
                'prenom': u['prenom'],
                'secteur': u['secteur_nom'] or 'Non affecte',
                'etapes_manquantes': etapes,
            })

    # ── 4. Demandes de recuperation en attente ──
    demandes_recup = conn.execute('''
        SELECT d.id, d.date_debut, d.date_fin, d.nb_jours, d.nb_heures,
               d.statut, d.date_demande, d.motif_demande,
               u.nom as demandeur_nom, u.prenom as demandeur_prenom,
               s.nom as secteur_nom
        FROM demandes_recup d
        JOIN users u ON d.user_id = u.id
        LEFT JOIN secteurs s ON u.secteur_id = s.id
        WHERE d.statut IN ('en_attente_responsable', 'en_attente_direction')
        ORDER BY d.date_demande ASC
    ''').fetchall()

    # ── 5. Anomalies non traitees ──
    anomalies_non_traitees = conn.execute('''
        SELECT a.id, a.type_anomalie, a.gravite, a.description,
               a.date_modification, a.date_concernee,
               u.nom as salarie_nom, u.prenom as salarie_prenom
        FROM anomalies a
        JOIN users u ON a.user_id = u.id
        WHERE a.traitee = 0
        ORDER BY
            CASE a.gravite WHEN 'critique' THEN 1 WHEN 'alerte' THEN 2 WHEN 'suspect' THEN 3 ELSE 4 END,
            a.date_modification DESC
        LIMIT 5
    ''').fetchall()

    nb_anomalies = conn.execute(
        'SELECT COUNT(*) as nb FROM anomalies WHERE traitee = 0'
    ).fetchone()['nb']

    # ── 6. Top salaries avec le plus de conges cumules ──
    top_conges = conn.execute('''
        SELECT u.id, u.nom, u.prenom,
               COALESCE(s.nom, 'Non affecte') as secteur_nom,
               COALESCE(u.cp_a_prendre, 0) as cp_a_prendre,
               COALESCE(u.cp_pris, 0) as cp_pris,
               COALESCE(u.cc_solde, 0) as cc_solde,
               (COALESCE(u.cp_a_prendre, 0) - COALESCE(u.cp_pris, 0) + COALESCE(u.cc_solde, 0)) as total_conges
        FROM users u
        LEFT JOIN secteurs s ON u.secteur_id = s.id
        WHERE u.actif = 1 AND u.profil NOT IN ('directeur', 'prestataire')
        ORDER BY total_conges DESC
        LIMIT 6
    ''').fetchall()

    # ── 7. Stats absences sur le mois en cours ──
    premier_jour_mois = today.replace(day=1).strftime('%Y-%m-%d')
    if mois == 12:
        dernier_jour_mois = datetime(annee + 1, 1, 1) - timedelta(days=1)
    else:
        dernier_jour_mois = datetime(annee, mois + 1, 1) - timedelta(days=1)
    dernier_jour_mois_str = dernier_jour_mois.strftime('%Y-%m-%d')

    absences_mois = conn.execute('''
        SELECT COUNT(*) as nb, COALESCE(SUM(jours_ouvres), 0) as total_jours
        FROM absences
        WHERE date_debut <= ? AND date_fin >= ?
    ''', (dernier_jour_mois_str, premier_jour_mois)).fetchone()

    # ── 8. Factures en attente d'approbation ──
    factures_en_attente = conn.execute('''
        SELECT f.id, f.numero_facture, f.date_facture, f.montant_ttc,
               f.date_echeance, f.description,
               fr.nom as fournisseur_nom,
               s.nom as secteur_nom
        FROM factures f
        LEFT JOIN fournisseurs fr ON f.fournisseur_id = fr.id
        LEFT JOIN secteurs s ON f.secteur_id = s.id
        WHERE f.approbation = 'en_attente'
        ORDER BY f.date_echeance ASC, f.date_facture ASC
        LIMIT 8
    ''').fetchall()

    nb_factures_attente = conn.execute(
        "SELECT COUNT(*) as nb FROM factures WHERE approbation = 'en_attente'"
    ).fetchone()['nb']

    montant_factures_attente = conn.execute(
        "SELECT COALESCE(SUM(montant_ttc), 0) as total FROM factures WHERE approbation = 'en_attente'"
    ).fetchone()['total']

    # ── 9. Subventions (pipeline) ──
    subventions_stats = conn.execute('''
        SELECT groupe,
               COUNT(*) as nb,
               COALESCE(SUM(montant_demande), 0) as total_demande,
               COALESCE(SUM(montant_accorde), 0) as total_accorde
        FROM subventions
        GROUP BY groupe
    ''').fetchall()

    subv_pipeline = {}
    total_subv_demande = 0
    total_subv_accorde = 0
    for s in subventions_stats:
        subv_pipeline[s['groupe']] = {
            'nb': s['nb'],
            'total_demande': s['total_demande'],
            'total_accorde': s['total_accorde']
        }
        total_subv_demande += s['total_demande']
        total_subv_accorde += s['total_accorde']

    subventions_echeance = conn.execute('''
        SELECT id, nom, groupe, montant_demande, montant_accorde, date_echeance
        FROM subventions
        WHERE date_echeance IS NOT NULL AND date_echeance != ''
          AND date_echeance >= ?
          AND groupe IN ('nouveau_projet', 'en_cours')
        ORDER BY date_echeance ASC
        LIMIT 5
    ''', (today_str,)).fetchall()

    # ── 10. Budget de l'annee en cours ──
    budgets_annee = conn.execute('''
        SELECT b.id, b.secteur_id, b.montant_global,
               s.nom as secteur_nom
        FROM budgets b
        JOIN secteurs s ON b.secteur_id = s.id
        WHERE b.annee = ?
        ORDER BY s.nom
    ''', (annee,)).fetchall()

    total_budget_global = 0
    total_budget_reel = 0
    budget_par_secteur = []
    for b in budgets_annee:
        reel = conn.execute(
            'SELECT COALESCE(SUM(montant), 0) as total FROM budget_reel_lignes WHERE budget_id = ?',
            (b['id'],)
        ).fetchone()['total']
        total_budget_global += b['montant_global'] or 0
        total_budget_reel += reel
        budget_par_secteur.append({
            'secteur_nom': b['secteur_nom'],
            'montant_global': b['montant_global'] or 0,
            'montant_reel': reel,
        })

    # ── 11. Tresorerie (solde actuel) ──
    solde_treso = None
    try:
        solde_row = conn.execute(
            'SELECT montant, annee_ref, mois_ref FROM tresorerie_solde_initial ORDER BY id DESC LIMIT 1'
        ).fetchone()
        if solde_row:
            solde_initial = solde_row['montant']
            # Cumuler les donnees depuis le mois de reference
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
            solde_treso = round(solde_initial + cumul, 2)
    except Exception:
        logger.exception("Erreur lors du calcul du solde de trésorerie")
        solde_treso = None

    conn.close()

    return render_template('dashboard_direction.html',
                           today=today,
                           mois=mois,
                           annee=annee,
                           nom_mois=NOMS_MOIS[mois],
                           total_salaries=total_salaries,
                           contrats_dict=contrats_dict,
                           total_etp=total_etp,
                           etp_par_type=etp_par_type,
                           effectifs=effectifs,
                           absences_en_cours=absences_en_cours,
                           absences_par_secteur=absences_par_secteur,
                           repartition_motifs=repartition_motifs,
                           mois_validation=mois_validation,
                           annee_validation=annee_validation,
                           nom_mois_validation=NOMS_MOIS[mois_validation],
                           val_mois_prec=val_mois_prec,
                           val_annee_prec=val_annee_prec,
                           val_mois_suiv=val_mois_suiv,
                           val_annee_suiv=val_annee_suiv,
                           est_mois_courant=est_mois_courant,
                           peut_avancer=peut_avancer,
                           validation_par_secteur=validation_par_secteur,
                           nb_total_a_valider=nb_total_a_valider,
                           nb_complet=nb_complet,
                           nb_en_cours=nb_en_cours,
                           nb_non_commence=nb_non_commence,
                           fiches_en_attente=fiches_en_attente,
                           demandes_recup=demandes_recup,
                           anomalies_non_traitees=anomalies_non_traitees,
                           nb_anomalies=nb_anomalies,
                           top_conges=top_conges,
                           absences_mois=absences_mois,
                           factures_en_attente=factures_en_attente,
                           nb_factures_attente=nb_factures_attente,
                           montant_factures_attente=montant_factures_attente,
                           subv_pipeline=subv_pipeline,
                           total_subv_demande=total_subv_demande,
                           total_subv_accorde=total_subv_accorde,
                           subventions_echeance=subventions_echeance,
                           budget_par_secteur=budget_par_secteur,
                           total_budget_global=total_budget_global,
                           total_budget_reel=total_budget_reel,
                           solde_treso=solde_treso)
