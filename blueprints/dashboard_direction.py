"""
Blueprint dashboard_direction_bp.
Tableau de bord global pour la direction avec vue d'ensemble quotidienne.
"""
from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from datetime import datetime, timedelta
from database import get_db
from utils import login_required, NOMS_MOIS

dashboard_direction_bp = Blueprint('dashboard_direction_bp', __name__)


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
        LIMIT 10
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

    conn.close()

    return render_template('dashboard_direction.html',
                           today=today,
                           mois=mois,
                           annee=annee,
                           nom_mois=NOMS_MOIS[mois],
                           total_salaries=total_salaries,
                           contrats_dict=contrats_dict,
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
                           absences_mois=absences_mois)
