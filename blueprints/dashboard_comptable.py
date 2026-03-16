"""
Blueprint dashboard_comptable_bp.
Tableau de bord specifique pour le comptable.
"""
from flask import Blueprint, render_template, session, redirect, url_for, flash
from datetime import datetime
from database import get_db
from utils import (login_required, NOMS_MOIS, get_user_info, calculer_heures,
                   get_heures_theoriques_jour, get_type_periode,
                   get_planning_valide_a_date, calculer_solde_recup)

dashboard_comptable_bp = Blueprint('dashboard_comptable_bp', __name__)

# Documents obligatoires a verifier (au minimum)
DOCS_OBLIGATOIRES = ['CARTE-ID-RECTO', 'CARTE-VITALE']


@dashboard_comptable_bp.route('/dashboard_comptable')
@login_required
def dashboard_comptable():
    """Tableau de bord specifique pour le comptable."""
    if session.get('profil') != 'comptable':
        flash('Acces non autorise', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    today = datetime.now()
    today_str = today.strftime('%Y-%m-%d')
    mois = today.month
    annee = today.year
    user_id = session['user_id']

    # ── 1. Ma fiche d'heures (dernieres saisies) ──
    user = get_user_info(user_id)

    heures = conn.execute('''
        SELECT date, heure_debut_matin, heure_fin_matin,
               heure_debut_aprem, heure_fin_aprem,
               commentaire, type_saisie, declaration_conforme
        FROM heures_reelles
        WHERE user_id = ?
        ORDER BY date DESC
        LIMIT 5
    ''', (user_id,)).fetchall()

    heures_enrichies = []
    for h in heures:
        date_obj = datetime.strptime(h['date'], '%Y-%m-%d')
        if date_obj.weekday() == 6:
            continue
        type_periode = get_type_periode(h['date'])
        total_theorique = 0
        if date_obj.weekday() != 5:
            planning = get_planning_valide_a_date(user_id, type_periode, h['date'])
            if planning:
                total_theorique = get_heures_theoriques_jour(planning, date_obj.weekday())
        if h['declaration_conforme']:
            total_reel = total_theorique
        else:
            heures_matin = calculer_heures(h['heure_debut_matin'], h['heure_fin_matin'])
            heures_aprem = calculer_heures(h['heure_debut_aprem'], h['heure_fin_aprem'])
            total_reel = heures_matin + heures_aprem
        heures_enrichies.append({
            'date': h['date'],
            'total_reel': total_reel,
            'total_theorique': total_theorique,
            'ecart': total_reel - total_theorique,
        })

    solde_recup = calculer_solde_recup(user_id)

    conges_user = conn.execute(
        'SELECT cp_a_prendre, cp_pris, cc_solde FROM users WHERE id = ?', (user_id,)
    ).fetchone()
    cp_solde = ((conges_user['cp_a_prendre'] or 0) - (conges_user['cp_pris'] or 0)) if conges_user else 0
    cc_solde = (conges_user['cc_solde'] or 0) if conges_user else 0

    # Nombre de jours saisis ce mois
    premier_jour = today.replace(day=1).strftime('%Y-%m-%d')
    nb_saisies_mois = conn.execute(
        "SELECT COUNT(*) as nb FROM heures_reelles WHERE user_id = ? AND date >= ?",
        (user_id, premier_jour)
    ).fetchone()['nb']

    # ── 2. Documents obligatoires manquants ──
    salaries_avec_contrat = conn.execute('''
        WITH derniers_contrats AS (
            SELECT user_id, MAX(id) AS contrat_id
            FROM contrats
            WHERE date_debut <= ?
              AND (date_fin IS NULL OR date_fin >= ?)
            GROUP BY user_id
        )
        SELECT u.id, u.nom, u.prenom,
               c.type_contrat, c.fichier_path AS contrat_fichier
        FROM users u
        JOIN derniers_contrats dc ON dc.user_id = u.id
        JOIN contrats c ON c.id = dc.contrat_id
        WHERE u.actif = 1
          AND u.profil NOT IN ('directeur', 'prestataire')
        ORDER BY u.nom, u.prenom
    ''', (today_str, today_str)).fetchall()

    docs_existants = conn.execute('''
        SELECT user_id, type_document
        FROM documents_salaries
    ''').fetchall()

    docs_map = {}
    for d in docs_existants:
        uid = d['user_id']
        if uid not in docs_map:
            docs_map[uid] = set()
        docs_map[uid].add(d['type_document'])

    salaries_docs_manquants = []
    for sal in salaries_avec_contrat:
        manquants = []
        if not sal['contrat_fichier']:
            manquants.append('Contrat (PDF)')
        user_docs = docs_map.get(sal['id'], set())
        for doc_type in DOCS_OBLIGATOIRES:
            if doc_type not in user_docs:
                label = "Carte d'identite" if 'CARTE-ID' in doc_type else 'Carte vitale'
                manquants.append(label)
        if manquants:
            salaries_docs_manquants.append({
                'id': sal['id'],
                'nom': sal['nom'],
                'prenom': sal['prenom'],
                'type_contrat': sal['type_contrat'],
                'manquants': manquants,
            })

    nb_docs_manquants = len(salaries_docs_manquants)

    # ── 3. Cloture des conges : verification mois M-1 ──
    if mois == 1:
        mois_cloture = 12
        annee_cloture = annee - 1
    else:
        mois_cloture = mois - 1
        annee_cloture = annee

    users_a_valider = conn.execute('''
        SELECT u.id, u.nom, u.prenom, s.nom as secteur_nom
        FROM users u
        LEFT JOIN secteurs s ON u.secteur_id = s.id
        WHERE u.actif = 1 AND u.profil NOT IN ('directeur', 'prestataire')
        ORDER BY s.nom, u.nom
    ''').fetchall()

    validations_cloture = conn.execute('''
        SELECT * FROM validations
        WHERE mois = ? AND annee = ?
    ''', (mois_cloture, annee_cloture)).fetchall()

    val_map = {v['user_id']: dict(v) for v in validations_cloture}

    nb_total_cloture = len(users_a_valider)
    nb_valide_cloture = 0
    nb_en_cours_cloture = 0
    nb_non_commence_cloture = 0
    fiches_non_validees = []

    for u in users_a_valider:
        v = val_map.get(u['id'])
        if v and v['bloque']:
            nb_valide_cloture += 1
        else:
            if v and (v['validation_salarie'] or v['validation_responsable'] or v['validation_directeur']):
                nb_en_cours_cloture += 1
            else:
                nb_non_commence_cloture += 1
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
            fiches_non_validees.append({
                'user_id': u['id'],
                'nom': u['nom'],
                'prenom': u['prenom'],
                'secteur': u['secteur_nom'] or 'Non affecte',
                'etapes_manquantes': etapes,
            })

    cloture_ok = (nb_total_cloture > 0 and nb_valide_cloture == nb_total_cloture)

    # ── 4. Rappel prepa paie ──
    rappel_prepa_paie = (today.day >= 18)

    # ── 5. Factures, ecritures brouillon, ecritures pretes a exporter ──
    nb_factures_attente = conn.execute(
        "SELECT COUNT(*) as nb FROM factures WHERE approbation = 'en_attente'"
    ).fetchone()['nb']

    montant_factures_attente = conn.execute(
        "SELECT COALESCE(SUM(montant_ttc), 0) as total FROM factures WHERE approbation = 'en_attente'"
    ).fetchone()['total']

    nb_ecritures_brouillon = conn.execute(
        "SELECT COUNT(*) as nb FROM ecritures_comptables WHERE statut = 'brouillon'"
    ).fetchone()['nb']

    nb_ecritures_a_exporter = conn.execute(
        "SELECT COUNT(*) as nb FROM ecritures_comptables WHERE statut = 'validee'"
    ).fetchone()['nb']

    # ── 6. Donnees importees (Bilan secteurs et Budget previsionnel) ──
    # Bilan FEC imports
    bilan_imports = conn.execute('''
        SELECT annee, MIN(mois_min) as mois_min, MAX(mois_max) as mois_max, SUM(nb) as nb_ecritures
        FROM (
            SELECT
                bi.annee,
                MIN(bd.mois) as mois_min,
                MAX(bd.mois) as mois_max,
                bi.nb_ecritures as nb
            FROM bilan_fec_imports bi
            LEFT JOIN bilan_fec_donnees bd ON bd.import_id = bi.id
            GROUP BY bi.id
        )
        GROUP BY annee
        ORDER BY annee DESC
        LIMIT 4
    ''').fetchall()

    # Tresorerie imports (donnees pour Budget previsionnel / tresorerie)
    treso_imports = conn.execute('''
        SELECT annee, MIN(mois) as mois_min, MAX(mois) as mois_max, COUNT(*) as nb_lignes
        FROM tresorerie_donnees
        GROUP BY annee
        ORDER BY annee DESC
        LIMIT 4
    ''').fetchall()

    # ── 7. Effectif rapide ──
    total_salaries = conn.execute('''
        SELECT COUNT(*) as nb FROM users
        WHERE actif = 1 AND profil NOT IN ('directeur', 'prestataire')
    ''').fetchone()['nb']

    conn.close()

    return render_template('dashboard_comptable.html',
                           today=today,
                           mois=mois,
                           annee=annee,
                           nom_mois=NOMS_MOIS[mois],
                           user=user,
                           heures=heures_enrichies,
                           solde_recup=solde_recup,
                           cp_solde=cp_solde,
                           cc_solde=cc_solde,
                           nb_saisies_mois=nb_saisies_mois,
                           salaries_docs_manquants=salaries_docs_manquants,
                           nb_docs_manquants=nb_docs_manquants,
                           mois_cloture=mois_cloture,
                           annee_cloture=annee_cloture,
                           nom_mois_cloture=NOMS_MOIS[mois_cloture],
                           nb_total_cloture=nb_total_cloture,
                           nb_valide_cloture=nb_valide_cloture,
                           nb_en_cours_cloture=nb_en_cours_cloture,
                           nb_non_commence_cloture=nb_non_commence_cloture,
                           fiches_non_validees=fiches_non_validees,
                           cloture_ok=cloture_ok,
                           rappel_prepa_paie=rappel_prepa_paie,
                           nb_factures_attente=nb_factures_attente,
                           montant_factures_attente=montant_factures_attente,
                           nb_ecritures_brouillon=nb_ecritures_brouillon,
                           nb_ecritures_a_exporter=nb_ecritures_a_exporter,
                           bilan_imports=bilan_imports,
                           treso_imports=treso_imports,
                           total_salaries=total_salaries)
