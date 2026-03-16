"""
Blueprint dashboard_responsable_bp.
Tableau de bord pour les responsables, scope au secteur.
"""
from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from datetime import datetime, timedelta
from database import get_db
from utils import login_required, NOMS_MOIS

dashboard_responsable_bp = Blueprint('dashboard_responsable_bp', __name__)


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


@dashboard_responsable_bp.route('/dashboard_responsable')
@login_required
def dashboard_responsable():
    """Tableau de bord pour les responsables, scope au secteur."""
    if session.get('profil') != 'responsable':
        flash('Acces non autorise', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    today = datetime.now()
    today_str = today.strftime('%Y-%m-%d')
    mois = today.month
    annee = today.year

    # Recuperer le secteur du responsable
    user_row = conn.execute(
        'SELECT secteur_id FROM users WHERE id = ?', (session['user_id'],)
    ).fetchone()
    secteur_id = user_row['secteur_id'] if user_row else None

    if not secteur_id:
        conn.close()
        flash('Aucun secteur associe a votre compte', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    secteur_row = conn.execute(
        'SELECT id, nom FROM secteurs WHERE id = ?', (secteur_id,)
    ).fetchone()
    secteur_nom = secteur_row['nom'] if secteur_row else 'Mon secteur'

    # ── 1. Equipe du secteur ──
    equipe = conn.execute('''
        SELECT u.id, u.nom, u.prenom, u.profil,
               c.type_contrat, c.temps_hebdo, c.date_debut, c.date_fin
        FROM users u
        LEFT JOIN contrats c ON c.user_id = u.id
          AND c.date_debut <= ?
          AND (c.date_fin IS NULL OR c.date_fin >= ?)
        WHERE u.actif = 1 AND u.secteur_id = ?
          AND u.profil NOT IN ('directeur', 'prestataire')
          AND u.id != ?
        GROUP BY u.id
        HAVING c.id IS NULL OR c.id = MAX(c.id)
        ORDER BY u.nom, u.prenom
    ''', (today_str, today_str, secteur_id, session['user_id'])).fetchall()

    nb_salaries = len(equipe)

    # Repartition par type de contrat
    contrats_dict = {}
    total_etp = 0.0
    etp_par_type = {}
    for m in equipe:
        t = m['type_contrat'] or 'Autre'
        contrats_dict[t] = contrats_dict.get(t, 0) + 1
        if m['type_contrat']:
            etp = _calcul_etp(m['type_contrat'], m['temps_hebdo'])
        else:
            etp = 0.0
        total_etp += etp
        etp_par_type[t] = etp_par_type.get(t, 0.0) + etp
    total_etp = round(total_etp, 2)

    # ── 2. Absences en cours du secteur ──
    absences_en_cours = conn.execute('''
        SELECT a.id, a.motif, a.date_debut, a.date_fin, a.jours_ouvres,
               a.date_reprise, a.commentaire,
               u.nom as salarie_nom, u.prenom as salarie_prenom
        FROM absences a
        JOIN users u ON a.user_id = u.id
        WHERE u.secteur_id = ?
          AND a.date_debut <= ? AND a.date_fin >= ?
        ORDER BY u.nom, u.prenom
    ''', (secteur_id, today_str, today_str)).fetchall()

    # Repartition par motif
    repartition_motifs = conn.execute('''
        SELECT a.motif, COUNT(*) as nb
        FROM absences a
        JOIN users u ON a.user_id = u.id
        WHERE u.secteur_id = ?
          AND a.date_debut <= ? AND a.date_fin >= ?
        GROUP BY a.motif
        ORDER BY nb DESC
    ''', (secteur_id, today_str, today_str)).fetchall()

    # Stats absences mois en cours
    premier_jour_mois = today.replace(day=1).strftime('%Y-%m-%d')
    if mois == 12:
        dernier_jour_mois = datetime(annee + 1, 1, 1) - timedelta(days=1)
    else:
        dernier_jour_mois = datetime(annee, mois + 1, 1) - timedelta(days=1)
    dernier_jour_mois_str = dernier_jour_mois.strftime('%Y-%m-%d')

    absences_mois = conn.execute('''
        SELECT COUNT(*) as nb, COALESCE(SUM(a.jours_ouvres), 0) as total_jours
        FROM absences a
        JOIN users u ON a.user_id = u.id
        WHERE u.secteur_id = ?
          AND a.date_debut <= ? AND a.date_fin >= ?
    ''', (secteur_id, dernier_jour_mois_str, premier_jour_mois)).fetchone()

    # ── 3. Validations mensuelles (secteur uniquement) ──
    mois_validation = request.args.get('val_mois', mois, type=int)
    annee_validation = request.args.get('val_annee', annee, type=int)

    if mois_validation < 1:
        mois_validation = 1
    elif mois_validation > 12:
        mois_validation = 12
    if annee_validation < 2020:
        annee_validation = 2020
    elif annee_validation > annee + 1:
        annee_validation = annee + 1

    if mois_validation == 1:
        val_mois_prec, val_annee_prec = 12, annee_validation - 1
    else:
        val_mois_prec, val_annee_prec = mois_validation - 1, annee_validation

    if mois_validation == 12:
        val_mois_suiv, val_annee_suiv = 1, annee_validation + 1
    else:
        val_mois_suiv, val_annee_suiv = mois_validation + 1, annee_validation

    est_mois_courant = (mois_validation == mois and annee_validation == annee)
    peut_avancer = not est_mois_courant and (
        annee_validation < annee or
        (annee_validation == annee and mois_validation < mois)
    )

    users_a_valider = conn.execute('''
        SELECT u.id, u.nom, u.prenom
        FROM users u
        WHERE u.actif = 1 AND u.profil = 'salarie' AND u.secteur_id = ?
        ORDER BY u.nom
    ''', (secteur_id,)).fetchall()

    validations_map = {}
    validations_rows = conn.execute('''
        SELECT v.* FROM validations v
        JOIN users u ON v.user_id = u.id
        WHERE v.mois = ? AND v.annee = ? AND u.secteur_id = ?
    ''', (mois_validation, annee_validation, secteur_id)).fetchall()
    for v in validations_rows:
        validations_map[v['user_id']] = dict(v)

    nb_total_a_valider = 0
    nb_complet = 0
    nb_en_cours = 0
    nb_non_commence = 0

    for u in users_a_valider:
        nb_total_a_valider += 1
        v = validations_map.get(u['id'])
        if v and v['bloque']:
            nb_complet += 1
        elif v and (v['validation_salarie'] or v['validation_responsable'] or v['validation_directeur']):
            nb_en_cours += 1
        else:
            nb_non_commence += 1

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
                'etapes_manquantes': etapes,
            })

    # ── 4. Demandes de recuperation du secteur ──
    demandes_recup = conn.execute('''
        SELECT d.id, d.date_debut, d.date_fin, d.nb_jours, d.nb_heures,
               d.statut, d.date_demande, d.motif_demande,
               u.nom as demandeur_nom, u.prenom as demandeur_prenom
        FROM demandes_recup d
        JOIN users u ON d.user_id = u.id
        WHERE u.secteur_id = ?
          AND d.statut IN ('en_attente_responsable', 'en_attente_direction')
        ORDER BY d.date_demande ASC
    ''', (secteur_id,)).fetchall()

    # ── 5. Conges de l'equipe ──
    conges_equipe = conn.execute('''
        SELECT u.id, u.nom, u.prenom,
               COALESCE(u.cp_a_prendre, 0) as cp_a_prendre,
               COALESCE(u.cp_pris, 0) as cp_pris,
               COALESCE(u.cc_solde, 0) as cc_solde,
               (COALESCE(u.cp_a_prendre, 0) - COALESCE(u.cp_pris, 0) + COALESCE(u.cc_solde, 0)) as total_conges
        FROM users u
        WHERE u.actif = 1 AND u.secteur_id = ?
          AND u.profil NOT IN ('directeur', 'prestataire')
          AND u.id != ?
        ORDER BY total_conges DESC
    ''', (secteur_id, session['user_id'])).fetchall()

    # ── 6. Factures en attente du secteur ──
    factures_en_attente = conn.execute('''
        SELECT f.id, f.numero_facture, f.date_facture, f.montant_ttc,
               f.date_echeance, f.description,
               fr.nom as fournisseur_nom
        FROM factures f
        LEFT JOIN fournisseurs fr ON f.fournisseur_id = fr.id
        WHERE f.secteur_id = ? AND f.approbation = 'en_attente'
        ORDER BY f.date_echeance ASC, f.date_facture ASC
        LIMIT 8
    ''', (secteur_id,)).fetchall()

    nb_factures_attente = conn.execute(
        "SELECT COUNT(*) as nb FROM factures WHERE secteur_id = ? AND approbation = 'en_attente'",
        (secteur_id,)
    ).fetchone()['nb']

    montant_factures_attente = conn.execute(
        "SELECT COALESCE(SUM(montant_ttc), 0) as total FROM factures WHERE secteur_id = ? AND approbation = 'en_attente'",
        (secteur_id,)
    ).fetchone()['total']

    # ── 7. Budget du secteur ──
    budget_secteur = None
    budget_reel = 0
    budget_row = conn.execute('''
        SELECT b.id, b.montant_global
        FROM budgets b
        WHERE b.secteur_id = ? AND b.annee = ?
    ''', (secteur_id, annee)).fetchone()
    if budget_row:
        budget_reel = conn.execute(
            'SELECT COALESCE(SUM(montant), 0) as total FROM budget_reel_lignes WHERE budget_id = ?',
            (budget_row['id'],)
        ).fetchone()['total']
        budget_secteur = {
            'montant_global': budget_row['montant_global'] or 0,
            'montant_reel': budget_reel,
        }

    # ── 8. Subventions ──
    subventions_stats = conn.execute('''
        SELECT groupe,
               COUNT(*) as nb,
               COALESCE(SUM(montant_demande), 0) as total_demande,
               COALESCE(SUM(montant_accorde), 0) as total_accorde
        FROM subventions
        WHERE assignee_1_id = ? OR assignee_2_id = ?
        GROUP BY groupe
    ''', (session['user_id'], session['user_id'])).fetchall()

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
        WHERE (assignee_1_id = ? OR assignee_2_id = ?)
          AND date_echeance IS NOT NULL AND date_echeance != ''
          AND date_echeance >= ?
          AND groupe IN ('nouveau_projet', 'en_cours')
        ORDER BY date_echeance ASC
        LIMIT 5
    ''', (session['user_id'], session['user_id'], today_str)).fetchall()

    conn.close()

    return render_template('dashboard_responsable.html',
                           today=today,
                           mois=mois,
                           annee=annee,
                           nom_mois=NOMS_MOIS[mois],
                           secteur_nom=secteur_nom,
                           secteur_id=secteur_id,
                           nb_salaries=nb_salaries,
                           contrats_dict=contrats_dict,
                           total_etp=total_etp,
                           etp_par_type=etp_par_type,
                           equipe=equipe,
                           absences_en_cours=absences_en_cours,
                           repartition_motifs=repartition_motifs,
                           absences_mois=absences_mois,
                           mois_validation=mois_validation,
                           annee_validation=annee_validation,
                           nom_mois_validation=NOMS_MOIS[mois_validation],
                           val_mois_prec=val_mois_prec,
                           val_annee_prec=val_annee_prec,
                           val_mois_suiv=val_mois_suiv,
                           val_annee_suiv=val_annee_suiv,
                           est_mois_courant=est_mois_courant,
                           peut_avancer=peut_avancer,
                           nb_total_a_valider=nb_total_a_valider,
                           nb_complet=nb_complet,
                           nb_en_cours=nb_en_cours,
                           nb_non_commence=nb_non_commence,
                           fiches_en_attente=fiches_en_attente,
                           demandes_recup=demandes_recup,
                           conges_equipe=conges_equipe,
                           factures_en_attente=factures_en_attente,
                           nb_factures_attente=nb_factures_attente,
                           montant_factures_attente=montant_factures_attente,
                           budget_secteur=budget_secteur,
                           budget_reel=budget_reel,
                           subv_pipeline=subv_pipeline,
                           total_subv_demande=total_subv_demande,
                           total_subv_accorde=total_subv_accorde,
                           subventions_echeance=subventions_echeance)
