"""
Blueprint validation_bp.
"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from datetime import datetime, timedelta
import json
from database import get_db
from sessions_securite import verifier_action
from blueprints.delegations import MISSION_SUIVI_VALIDATIONS_RELANCES, user_has_delegation
from utils import (login_required, get_user_info, est_dans_equipe_responsable,
                   maintenant)
from app_options import get_option_bool
from fiches_contenu import calculer_contenu
from fiches_versions import (enregistrer_version, empreinte, evenement,
                             lire_contenu, presenter_validation)
from access_log import (journaliser_action, ACTION_VALIDATION_MOIS,
                        ACTION_DEVERROUILLAGE_MOIS)

validation_bp = Blueprint('validation_bp', __name__)


@validation_bp.route('/valider_mois', methods=['POST'])
@login_required
def valider_mois():
    """Valider un mois pour un utilisateur"""
    user_id = request.form.get('user_id', type=int)
    mois = request.form.get('mois', type=int)
    annee = request.form.get('annee', type=int)
    
    if not user_id or user_id < 1 or not mois or not annee or not 1 <= mois <= 12 or not 1 <= annee <= 9998:
        flash('Paramètres invalides', 'error')
        return redirect(url_for('validation_bp.vue_mensuelle'))
    
    # VÉRIFICATION CRITIQUE : Le mois doit être terminé pour pouvoir être validé
    today = datetime.now()
    mois_demande = datetime(annee, mois, 1)
    
    # Si le mois demandé est le mois actuel ou dans le futur → BLOQUÉ
    if (annee > today.year) or (annee == today.year and mois >= today.month):
        flash(f'Impossible de valider un mois en cours. Vous pourrez valider {mois}/{annee} à partir du 1er jour du mois suivant.', 'error')
        return redirect(url_for('validation_bp.vue_mensuelle', mois=mois, annee=annee, user_id=user_id))
    
    conn = get_db()

    try:
        conn.execute("BEGIN IMMEDIATE")
        refus = verifier_action(conn)
        if refus is not None:
            return refus
        # Vérifier les droits
        # Un même utilisateur peut cumuler plusieurs rôles de validation.
        # Cas notable : un directeur qui est aussi responsable du secteur du
        # salarié doit poser à la fois la validation responsable ET directeur,
        # sinon la fiche ne se verrouille jamais (cf. verrouillage plus bas).
        types_validation = []
        profil = session.get('profil')

        if user_id == session['user_id']:
            types_validation.append('salarie')
        else:
            # Validation responsable : le valideur est responsable du salarié.
            # Deux façons d'être responsable d'un salarié (helper commun
            # est_dans_equipe_responsable, utilisé par toutes les vues) :
            #  - être responsable de son secteur (même secteur_id) ;
            #  - être son responsable hiérarchique direct (responsable_id).
            # Le second cas couvre un salarié rattaché hors de son secteur
            # analytique (ex. entretien en logistique, encadré par la
            # responsable crèche) et un directeur désigné comme responsable
            # hiérarchique (le champ liste aussi les directeurs, cf. admin.py).
            if profil in ('responsable', 'directeur'):
                if est_dans_equipe_responsable(conn, session['user_id'], user_id):
                    types_validation.append('responsable')

            # Validation directeur : un directeur peut valider toute fiche.
            if profil == 'directeur':
                types_validation.append('directeur')

        if not types_validation:
            flash('Vous n\'avez pas le droit de valider cette fiche', 'error')
            return redirect(url_for('validation_bp.vue_mensuelle'))

        # Récupérer ou créer la validation
        validation = conn.execute('''
            SELECT * FROM validations WHERE user_id = ? AND mois = ? AND annee = ?
        ''', (user_id, mois, annee)).fetchone()

        if validation and validation['bloque']:
            flash('Cette fiche est déjà verrouillée. Une réouverture motivée est nécessaire.', 'info')
            return redirect(url_for('validation_bp.vue_mensuelle', user_id=user_id, mois=mois, annee=annee))

        if not conn.execute('SELECT 1 FROM users WHERE id=?', (user_id,)).fetchone():
            flash('Salarié introuvable.', 'error')
            return redirect(url_for('validation_bp.vue_mensuelle'))
        contenu = calculer_contenu(conn, user_id, mois, annee)
        if contenu['nb_jours_non_declares']:
            flash(f"Fiche incomplète : {contenu['nb_jours_non_declares']} journée(s) "
                  "attendue(s) restent à renseigner. Aucune signature enregistrée.", 'error')
            return redirect(url_for('validation_bp.vue_mensuelle', user_id=user_id, mois=mois, annee=annee))
        reference_affichee = request.form.get('empreinte_fiche')
        if not reference_affichee or reference_affichee != empreinte(contenu):
            flash('La fiche a changé ou sa référence manque. Relisez la fiche actualisée avant de signer.', 'warning')
            return redirect(url_for('validation_bp.vue_mensuelle', user_id=user_id, mois=mois, annee=annee))

        version_id = enregistrer_version(conn, contenu, 'signature')
        now = maintenant().strftime('%Y-%m-%d %H:%M:%S')
        user_info = conn.execute('SELECT prenom, nom FROM users WHERE id=?', (session['user_id'],)).fetchone()
        validation_nom = f"{user_info['prenom']} {user_info['nom']}"

        # Champs (colonne validation, colonne date) par type de validation.
        # Les noms de colonnes proviennent de ce mapping fixe, pas d'une saisie
        # utilisateur : aucun risque d'injection SQL.
        champs_validation = {
            'salarie': ('validation_salarie', 'date_salarie'),
            'responsable': ('validation_responsable', 'date_responsable'),
            'directeur': ('validation_directeur', 'date_directeur'),
        }

        if not validation:
            conn.execute('''
                INSERT INTO validations (user_id, mois, annee)
                VALUES (?, ?, ?)
            ''', (user_id, mois, annee))

        set_clauses = ['version_courante_id = ?']
        params = [version_id]
        for type_validation in types_validation:
            col_validation, col_date = champs_validation[type_validation]
            set_clauses.append(f'{col_validation} = ?')
            set_clauses.append(f'{col_date} = ?')
            set_clauses.append(f'version_{type_validation}_id = ?')
            params.extend([validation_nom, now, version_id])
            evenement(conn, user_id, annee, mois, 'signature', version_id,
                      role=type_validation, auteur_id=session['user_id'], auteur_nom=validation_nom)

        params.extend([user_id, mois, annee])
        conn.execute(f'''
            UPDATE validations
            SET {', '.join(set_clauses)}
            WHERE user_id = ? AND mois = ? AND annee = ?
        ''', params)

        # Vérifier si la fiche doit être verrouillée.
        # Cas général : validation responsable ET directeur.
        # Cas des responsables : ils n'ont pas de supérieur au-dessus d'eux
        # (hormis le directeur), donc la validation directeur suffit à
        # verrouiller leur fiche.
        validation_updated = conn.execute('''
            SELECT * FROM validations WHERE user_id = ? AND mois = ? AND annee = ?
        ''', (user_id, mois, annee)).fetchone()

        user_valide = conn.execute(
            'SELECT profil FROM users WHERE id = ?', (user_id,)
        ).fetchone()
        valide_est_responsable = bool(user_valide and user_valide['profil'] == 'responsable')

        doit_verrouiller = bool(
            validation_updated
            and validation_updated['version_directeur_id'] == version_id
            and (validation_updated['version_responsable_id'] == version_id or valide_est_responsable)
        )

        if doit_verrouiller:
            conn.execute('''
                UPDATE validations SET bloque = 1
                WHERE user_id = ? AND mois = ? AND annee = ?
            ''', (user_id, mois, annee))
            evenement(conn, user_id, annee, mois, 'verrouillage', version_id)
            flash('Fiche validée et verrouillée définitivement', 'success')
        else:
            flash('Validation enregistrée', 'success')

        journaliser_action(
            conn, ACTION_VALIDATION_MOIS,
            cible_type='user', cible_id=user_id,
            details=f"mois={mois}/{annee}, type={','.join(types_validation)}",
        )
        conn.commit()
    finally:
        conn.close()

    return redirect(url_for('validation_bp.vue_mensuelle', user_id=user_id, mois=mois, annee=annee))

@validation_bp.route('/deverrouiller_mois', methods=['POST'])
@login_required
def deverrouiller_mois():
    """Déverrouiller un mois (directeur uniquement) avec motif obligatoire"""
    if session.get('profil') != 'directeur':
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))
    
    user_id = request.form.get('user_id', type=int)
    mois = request.form.get('mois', type=int)
    annee = request.form.get('annee', type=int)
    motif = request.form.get('motif', '').strip()
    
    if not user_id or user_id < 1 or not mois or not annee or not 1 <= mois <= 12 or not 1 <= annee <= 9998:
        flash('Paramètres invalides', 'error')
        return redirect(url_for('validation_bp.vue_mensuelle'))
    
    if not motif:
        flash('Le motif est obligatoire pour déverrouiller', 'error')
        return redirect(url_for('validation_bp.vue_mensuelle', user_id=user_id, mois=mois, annee=annee))
    
    conn = get_db()

    try:
        conn.execute("BEGIN IMMEDIATE")
        refus = verifier_action(conn)
        if refus is not None:
            return refus
        if session.get('profil') != 'directeur':
            flash('Accès non autorisé', 'error')
            return redirect(url_for('dashboard_bp.dashboard'))
        # Vérifier que la fiche est bien verrouillée
        validation = conn.execute('''
            SELECT * FROM validations
            WHERE user_id = ? AND mois = ? AND annee = ?
        ''', (user_id, mois, annee)).fetchone()

        if not validation or not validation['bloque']:
            flash('Cette fiche n\'est pas verrouillée', 'error')
            return redirect(url_for('validation_bp.vue_mensuelle', user_id=user_id, mois=mois, annee=annee))

        # Enregistrer dans l'historique
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        user_info = get_user_info(session['user_id'])

        conn.execute('''
            INSERT INTO historique_modifications
            (user_id_modifie, date_concernee, modifie_par, action, anciennes_valeurs, nouvelles_valeurs)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, f"{annee}-{mois:02d}-01", session['user_id'], 'deverrouillage',
              json.dumps({'motif': motif, 'date': now, 'par': f"{user_info['prenom']} {user_info['nom']}"}), None))

        evenement(conn, user_id, annee, mois, 'reouverture',
                  validation['version_courante_id'], details={'motif': motif})

        # Supprimer la validation (réinitialisation complète)
        conn.execute('''
            DELETE FROM validations
            WHERE user_id = ? AND mois = ? AND annee = ?
        ''', (user_id, mois, annee))

        journaliser_action(
            conn, ACTION_DEVERROUILLAGE_MOIS,
            cible_type='user', cible_id=user_id,
            details=f"mois={mois}/{annee}, motif consigne dans l'historique des modifications",
        )
        conn.commit()
    finally:
        conn.close()

    flash(f'Fiche déverrouillée. Motif : {motif}', 'success')
    return redirect(url_for('validation_bp.vue_mensuelle', user_id=user_id, mois=mois, annee=annee))

@validation_bp.route('/vue_ensemble_validation')
@login_required
def vue_ensemble_validation():
    """Vue d'ensemble des validations mensuelles (directeur, comptable et responsables)"""
    acces_delegation = user_has_delegation(
        session.get('user_id'),
        MISSION_SUIVI_VALIDATIONS_RELANCES,
    )
    profil = session.get('profil')
    if profil not in ['directeur', 'comptable', 'responsable'] and not acces_delegation:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))
    
    # Récupérer le mois/année demandé ou utiliser le mois actuel
    mois_param = request.args.get('mois', type=int)
    annee_param = request.args.get('annee', type=int)
    
    now = datetime.now()
    mois = mois_param if mois_param else now.month
    annee = annee_param if annee_param else now.year
    
    conn = get_db()

    try:
        # Récupérer les utilisateurs selon le profil connecté
        if profil == 'responsable' and not acces_delegation:
            responsable_secteur = conn.execute('SELECT secteur_id FROM users WHERE id = ?', (session['user_id'],)).fetchone()
            secteur_resp = responsable_secteur['secteur_id'] if responsable_secteur else None

            # Équipe = salariés du secteur + rattachés directs (responsable_id),
            # même d'un autre secteur (ex. entretien en secteur logistique
            # encadré par la responsable crèche).
            users = conn.execute('''
                SELECT u.id, u.nom, u.prenom, u.profil,
                       s.nom as secteur_nom,
                       r.nom || ' ' || r.prenom as responsable_nom
                FROM users u
                LEFT JOIN secteurs s ON u.secteur_id = s.id
                LEFT JOIN users r ON u.responsable_id = r.id
                WHERE u.actif = 1 AND u.profil = 'salarie'
                  AND (u.secteur_id = ? OR u.responsable_id = ?)
                ORDER BY u.nom, u.prenom
            ''', (secteur_resp, session['user_id'])).fetchall()

            if not users and not secteur_resp:
                flash('Vous n\'êtes rattaché à aucun secteur', 'error')
                return redirect(url_for('dashboard_bp.dashboard'))
        else:
            users = conn.execute('''
                SELECT u.id, u.nom, u.prenom, u.profil,
                       s.nom as secteur_nom,
                       r.nom || ' ' || r.prenom as responsable_nom
                FROM users u
                LEFT JOIN secteurs s ON u.secteur_id = s.id
                LEFT JOIN users r ON u.responsable_id = r.id
                WHERE u.actif = 1 AND u.profil NOT IN ('directeur', 'prestataire')
                ORDER BY s.nom, u.nom, u.prenom
            ''').fetchall()

        # Pour chaque utilisateur, récupérer l'état de validation
        users_validation = []
        for user in users:
            validation = conn.execute('''
                SELECT * FROM validations
                WHERE user_id = ? AND mois = ? AND annee = ?
            ''', (user['id'], mois, annee)).fetchone()

            users_validation.append({
                'user': dict(user),
                'validation': presenter_validation(validation)
            })
    finally:
        conn.close()
    
    # Calculer les mois précédent et suivant
    if mois == 1:
        mois_precedent = 12
        annee_precedente = annee - 1
    else:
        mois_precedent = mois - 1
        annee_precedente = annee
    
    if mois == 12:
        mois_suivant = 1
        annee_suivante = annee + 1
    else:
        mois_suivant = mois + 1
        annee_suivante = annee
    
    noms_mois = ['', 'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
                 'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']

    peut_relancer_validation = profil == 'directeur' or acces_delegation
    # Les responsables peuvent accéder à la vue d'ensemble, mais leurs droits
    # sur les fiches individuelles restent limités par secteur dans
    # `vue_mensuelle`. Lorsqu'ils arrivent ici via délégation, on masque donc
    # les liens vers les fiches pour éviter d'afficher des accès qui seront
    # refusés ensuite.
    delegation_sans_fiches = acces_delegation and profil not in ['directeur', 'comptable']
    
    return render_template('vue_ensemble_validation.html',
                         users_validation=users_validation,
                         mois=mois,
                         annee=annee,
                         nom_mois=noms_mois[mois],
                         mois_precedent=mois_precedent,
                         annee_precedente=annee_precedente,
                         mois_suivant=mois_suivant,
                         annee_suivante=annee_suivante,
                         peut_relancer_validation=peut_relancer_validation,
                         delegation_sans_fiches=delegation_sans_fiches)

def _get_vue_mensuelle_data(redirect_route='validation_bp.vue_mensuelle'):
    """Calcul partagé des données de la fiche mensuelle (utilisé par vue_mensuelle et vue_calendrier)."""
    mois_param = request.args.get('mois', type=int)
    annee_param = request.args.get('annee', type=int)
    user_id_param = request.args.get('user_id', type=int)

    now = datetime.now()
    mois = mois_param if mois_param else now.month
    annee = annee_param if annee_param else now.year

    conn = get_db()

    try:
        return _get_vue_mensuelle_data_impl(conn, mois, annee, user_id_param, redirect_route)
    finally:
        conn.close()


def _get_vue_mensuelle_data_impl(conn, mois, annee, user_id_param, redirect_route):
    """Implementation interne de _get_vue_mensuelle_data (connexion geree par l'appelant)."""
    # La page et sa référence proviennent de la même lecture SQLite.
    if not conn.in_transaction:
        conn.execute("BEGIN")
    user_id_a_afficher = user_id_param if user_id_param else session['user_id']

    # Controle d'acces
    if user_id_a_afficher != session['user_id']:
        if session.get('profil') == 'directeur' or session.get('profil') == 'comptable':
            pass
        elif session.get('profil') == 'responsable':
            # Équipe du responsable : même secteur OU rattachement hiérarchique
            # direct (salarié d'un autre secteur, ex. entretien en logistique).
            if not est_dans_equipe_responsable(conn, session['user_id'], user_id_a_afficher):
                flash('Accès non autorisé à cette fiche', 'error')
                return None, redirect(url_for(redirect_route))
        else:
            flash('Accès non autorisé', 'error')
            return None, redirect(url_for(redirect_route))

    user_affiche = conn.execute('SELECT * FROM users WHERE id = ?', (user_id_a_afficher,)).fetchone()
    if not user_affiche:
        flash('Utilisateur introuvable', 'error')
        return None, redirect(url_for(redirect_route))

    # Liste des utilisateurs accessibles (pour le selecteur)
    users_accessibles = []
    if session.get('profil') in ['directeur', 'comptable']:
        users_accessibles = conn.execute('''
            SELECT id, nom, prenom, profil FROM users
            WHERE actif = 1 AND profil NOT IN ('directeur', 'prestataire')
            ORDER BY nom, prenom
        ''').fetchall()
    elif session.get('profil') == 'responsable':
        responsable_secteur = conn.execute('SELECT secteur_id FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        secteur_resp = responsable_secteur['secteur_id'] if responsable_secteur else None
        # Secteur + rattachés directs (un secteur NULL ne matche jamais : seuls
        # les rattachés restent alors listés).
        users_accessibles = conn.execute('''
            SELECT id, nom, prenom, profil FROM users
            WHERE actif = 1 AND (secteur_id = ? OR responsable_id = ? OR id = ?)
            ORDER BY nom, prenom
        ''', (secteur_resp, session['user_id'], session['user_id'])).fetchall()

    contenu = lire_contenu(conn, user_id_a_afficher, mois, annee,
                           aujourdhui=datetime.now().date())
    premier_jour = datetime(annee, mois, 1)
    dernier_jour = (datetime(annee + (mois == 12), mois % 12 + 1, 1) - timedelta(days=1))
    nb_jours_non_declares = contenu['nb_jours_non_declares']
    afficher_horaires_vue_mensuelle = get_option_bool('vue_mensuelle_afficher_horaires')

    validation = conn.execute('''
        SELECT * FROM validations
        WHERE user_id = ? AND mois = ? AND annee = ?
    ''', (user_id_a_afficher, mois, annee)).fetchone()

    today = datetime.now()
    mois_demande = datetime(annee, mois, 1)
    mois_est_termine = (annee, mois) < (today.year, today.month)

    peut_valider_mois = False
    if not validation or not validation['bloque']:
        if not mois_est_termine:
            peut_valider_mois = False
        elif nb_jours_non_declares > 0:
            peut_valider_mois = False
        elif user_id_a_afficher == session['user_id'] and session.get('profil') != 'directeur':
            peut_valider_mois = True
        elif session.get('profil') == 'directeur':
            peut_valider_mois = True
        elif session.get('profil') == 'responsable':
            # Même règle que l'action de validation : secteur commun OU
            # rattachement hiérarchique direct.
            if est_dans_equipe_responsable(conn, session['user_id'], user_id_a_afficher):
                peut_valider_mois = True

    peut_modifier = False
    if not (validation and validation['bloque']):
        if user_id_a_afficher == session['user_id']:
            if session.get('profil') != 'directeur':
                peut_modifier = True
        elif session.get('profil') == 'directeur':
            peut_modifier = True
        elif session.get('profil') == 'responsable':
            if est_dans_equipe_responsable(conn, session['user_id'], user_id_a_afficher):
                peut_modifier = True

    if mois == 1:
        mois_precedent = 12
        annee_precedente = annee - 1
    else:
        mois_precedent = mois - 1
        annee_precedente = annee

    if mois == 12:
        mois_suivant = 1
        annee_suivante = annee + 1
    else:
        mois_suivant = mois + 1
        annee_suivante = annee

    noms_mois = ['', 'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
                 'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']

    template_data = dict(
        empreinte_fiche=empreinte(calculer_contenu(conn, user_id_a_afficher, mois, annee)),
        evenements_fiche=conn.execute(
            'SELECT * FROM fiches_evenements WHERE user_id=? AND annee=? AND mois=? ORDER BY id',
            (user_id_a_afficher, annee, mois)).fetchall(),
        journees=contenu['journees'],
        mois=mois,
        annee=annee,
        nom_mois=noms_mois[mois],
        total_heures_theoriques=contenu['total_heures_theoriques'],
        total_heures_reelles=contenu['total_heures_reelles'],
        solde_mois=contenu['solde_mois'],
        solde_anterieur=contenu['solde_anterieur'],
        solde_cumule=contenu['solde_cumule'],
        hs_payees_mois=contenu['hs_payees_mois'],
        mois_precedent=mois_precedent,
        annee_precedente=annee_precedente,
        mois_suivant=mois_suivant,
        annee_suivante=annee_suivante,
        user_affiche={**dict(user_affiche), **contenu['identite']},
        users_accessibles=users_accessibles,
        user_id_a_afficher=user_id_a_afficher,
        peut_modifier=peut_modifier,
        validation=presenter_validation(validation),
        peut_valider_mois=peut_valider_mois,
        mois_est_termine=mois_est_termine,
        nb_jours_non_declares=nb_jours_non_declares,
        # Sans contrat au dossier, la fiche réclame ses journées mais la
        # saisie les refuse : il faut dire pourquoi, et à qui s'adresser.
        aucun_contrat=contenu['aucun_contrat'],
        jours_feries=contenu['jours_feries'],
        premier_jour_semaine=premier_jour.weekday(),
        nb_jours_mois=dernier_jour.day,
        afficher_horaires_vue_mensuelle=afficher_horaires_vue_mensuelle,
        declaration_conforme_active=get_option_bool('saisie_afficher_declaration_conforme'),
    )

    return template_data, None


@validation_bp.route('/vue_mensuelle')
@login_required
def vue_mensuelle():
    """Vue mensuelle de la fiche de temps (tableau)"""
    data, error_redirect = _get_vue_mensuelle_data(redirect_route='validation_bp.vue_mensuelle')
    if error_redirect:
        return error_redirect
    return render_template('vue_mensuelle.html', **data)


@validation_bp.route('/vue_calendrier')
@login_required
def vue_calendrier():
    """Vue calendrier de la fiche de temps (grille calendaire)"""
    data, error_redirect = _get_vue_mensuelle_data(redirect_route='validation_bp.vue_calendrier')
    if error_redirect:
        return error_redirect

    # Construire la grille calendaire complète (tous les jours du mois, y compris weekends)
    mois = data['mois']
    annee = data['annee']
    premier_jour = datetime(annee, mois, 1)
    if mois == 12:
        dernier_jour = datetime(annee + 1, 1, 1) - timedelta(days=1)
    else:
        dernier_jour = datetime(annee, mois + 1, 1) - timedelta(days=1)

    # Indexer les journees existantes par date
    journees_par_date = {j['date']: j for j in data['journees']}

    # Generer tous les jours du mois pour la grille
    jours_calendrier = []
    jour_actuel = premier_jour
    while jour_actuel <= dernier_jour:
        date_str = jour_actuel.strftime('%Y-%m-%d')
        jour_semaine = jour_actuel.weekday()

        jour_data = journees_par_date.get(date_str)
        est_ferie = date_str in data['jours_feries']
        libelle_ferie = data['jours_feries'].get(date_str, '')

        jours_calendrier.append({
            'date': date_str,
            'jour': jour_actuel.day,
            'jour_semaine': jour_semaine,  # 0=lundi, 6=dimanche
            'est_weekend': jour_semaine >= 5,
            'est_dimanche': jour_semaine == 6,
            'est_ferie': est_ferie,
            'libelle_ferie': libelle_ferie,
            'donnees': jour_data,  # None si dimanche/weekend sans saisie
        })
        jour_actuel += timedelta(days=1)

    data['jours_calendrier'] = jours_calendrier

    return render_template('vue_calendrier.html', **data)
