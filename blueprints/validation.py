"""
Blueprint validation_bp.
"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from datetime import datetime, timedelta
import json
from database import get_db
from utils import (login_required, get_user_info, calculer_heures,
                   get_heures_theoriques_jour, get_type_periode, get_planning_valide_a_date, NOMS_MOIS)

validation_bp = Blueprint('validation_bp', __name__)


@validation_bp.route('/valider_mois', methods=['POST'])
@login_required
def valider_mois():
    """Valider un mois pour un utilisateur"""
    user_id = request.form.get('user_id', type=int)
    mois = request.form.get('mois', type=int)
    annee = request.form.get('annee', type=int)
    
    if not user_id or not mois or not annee:
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
        # Vérifier les droits
        peut_valider = False
        type_validation = None

        if user_id == session['user_id']:
            peut_valider = True
            type_validation = 'salarie'
        elif session.get('profil') == 'responsable':
            user_to_validate = conn.execute('SELECT secteur_id FROM users WHERE id = %s', (user_id,)).fetchone()
            responsable_secteur = conn.execute('SELECT secteur_id FROM users WHERE id = %s', (session['user_id'],)).fetchone()

            if user_to_validate and responsable_secteur and user_to_validate['secteur_id'] == responsable_secteur['secteur_id']:
                peut_valider = True
                type_validation = 'responsable'
        elif session.get('profil') == 'directeur':
            peut_valider = True
            type_validation = 'directeur'

        if not peut_valider:
            flash('Vous n\'avez pas le droit de valider cette fiche', 'error')
            return redirect(url_for('validation_bp.vue_mensuelle'))

        # Récupérer ou créer la validation
        validation = conn.execute('''
            SELECT * FROM validations WHERE user_id = %s AND mois = %s AND annee = %s
        ''', (user_id, mois, annee)).fetchone()

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        user_info = get_user_info(session['user_id'])
        validation_nom = f"{user_info['prenom']} {user_info['nom']}"

        if not validation:
            if type_validation == 'salarie':
                conn.execute('''
                    INSERT INTO validations (user_id, mois, annee, validation_salarie, date_salarie)
                    VALUES (%s, %s, %s, %s, %s)
                ''', (user_id, mois, annee, validation_nom, now))
            elif type_validation == 'responsable':
                conn.execute('''
                    INSERT INTO validations (user_id, mois, annee, validation_responsable, date_responsable)
                    VALUES (%s, %s, %s, %s, %s)
                ''', (user_id, mois, annee, validation_nom, now))
            elif type_validation == 'directeur':
                conn.execute('''
                    INSERT INTO validations (user_id, mois, annee, validation_directeur, date_directeur)
                    VALUES (%s, %s, %s, %s, %s)
                ''', (user_id, mois, annee, validation_nom, now))
        else:
            if type_validation == 'salarie':
                conn.execute('''
                    UPDATE validations
                    SET validation_salarie = %s, date_salarie = %s
                    WHERE user_id = %s AND mois = %s AND annee = %s
                ''', (validation_nom, now, user_id, mois, annee))
            elif type_validation == 'responsable':
                conn.execute('''
                    UPDATE validations
                    SET validation_responsable = %s, date_responsable = %s
                    WHERE user_id = %s AND mois = %s AND annee = %s
                ''', (validation_nom, now, user_id, mois, annee))
            elif type_validation == 'directeur':
                conn.execute('''
                    UPDATE validations
                    SET validation_directeur = %s, date_directeur = %s
                    WHERE user_id = %s AND mois = %s AND annee = %s
                ''', (validation_nom, now, user_id, mois, annee))

        # Vérifier si la fiche doit être verrouillée (responsable + directeur validés)
        validation_updated = conn.execute('''
            SELECT * FROM validations WHERE user_id = %s AND mois = %s AND annee = %s
        ''', (user_id, mois, annee)).fetchone()

        if validation_updated and validation_updated['validation_responsable'] and validation_updated['validation_directeur']:
            conn.execute('''
                UPDATE validations SET bloque = 1
                WHERE user_id = %s AND mois = %s AND annee = %s
            ''', (user_id, mois, annee))
            flash('Fiche validée et verrouillée définitivement', 'success')
        else:
            flash('Validation enregistrée', 'success')

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
    
    if not user_id or not mois or not annee:
        flash('Paramètres invalides', 'error')
        return redirect(url_for('validation_bp.vue_mensuelle'))
    
    if not motif:
        flash('Le motif est obligatoire pour déverrouiller', 'error')
        return redirect(url_for('validation_bp.vue_mensuelle', user_id=user_id, mois=mois, annee=annee))
    
    conn = get_db()

    try:
        # Vérifier que la fiche est bien verrouillée
        validation = conn.execute('''
            SELECT * FROM validations
            WHERE user_id = %s AND mois = %s AND annee = %s
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
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (user_id, f"{annee}-{mois:02d}-01", session['user_id'], 'deverrouillage',
              json.dumps({'motif': motif, 'date': now, 'par': f"{user_info['prenom']} {user_info['nom']}"}), None))

        # Supprimer la validation (réinitialisation complète)
        conn.execute('''
            DELETE FROM validations
            WHERE user_id = %s AND mois = %s AND annee = %s
        ''', (user_id, mois, annee))

        conn.commit()
    finally:
        conn.close()

    flash(f'Fiche déverrouillée. Motif : {motif}', 'success')
    return redirect(url_for('validation_bp.vue_mensuelle', user_id=user_id, mois=mois, annee=annee))

@validation_bp.route('/vue_ensemble_validation')
@login_required
def vue_ensemble_validation():
    """Vue d'ensemble des validations mensuelles (directeur, comptable et responsables)"""
    if session.get('profil') not in ['directeur', 'comptable', 'responsable']:
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
        if session.get('profil') == 'responsable':
            responsable_secteur = conn.execute('SELECT secteur_id FROM users WHERE id = %s', (session['user_id'],)).fetchone()

            if not responsable_secteur or not responsable_secteur['secteur_id']:
                flash('Vous n\'êtes rattaché à aucun secteur', 'error')
                return redirect(url_for('dashboard_bp.dashboard'))

            users = conn.execute('''
                SELECT u.id, u.nom, u.prenom, u.profil,
                       s.nom as secteur_nom,
                       r.nom || ' ' || r.prenom as responsable_nom
                FROM users u
                LEFT JOIN secteurs s ON u.secteur_id = s.id
                LEFT JOIN users r ON u.responsable_id = r.id
                WHERE u.actif = 1 AND u.profil = 'salarie' AND u.secteur_id = %s
                ORDER BY u.nom, u.prenom
            ''', (responsable_secteur['secteur_id'],)).fetchall()
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
                WHERE user_id = %s AND mois = %s AND annee = %s
            ''', (user['id'], mois, annee)).fetchone()

            users_validation.append({
                'user': dict(user),
                'validation': dict(validation) if validation else None
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
    
    return render_template('vue_ensemble_validation.html',
                         users_validation=users_validation,
                         mois=mois,
                         annee=annee,
                         nom_mois=noms_mois[mois],
                         mois_precedent=mois_precedent,
                         annee_precedente=annee_precedente,
                         mois_suivant=mois_suivant,
                         annee_suivante=annee_suivante)

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
    user_id_a_afficher = user_id_param if user_id_param else session['user_id']

    # Controle d'acces
    if user_id_a_afficher != session['user_id']:
        if session.get('profil') == 'directeur' or session.get('profil') == 'comptable':
            pass
        elif session.get('profil') == 'responsable':
            user_to_view = conn.execute('SELECT secteur_id FROM users WHERE id = %s', (user_id_a_afficher,)).fetchone()
            responsable_secteur = conn.execute('SELECT secteur_id FROM users WHERE id = %s', (session['user_id'],)).fetchone()

            if not user_to_view or not responsable_secteur or user_to_view['secteur_id'] != responsable_secteur['secteur_id']:
                flash('Accès non autorisé à cette fiche', 'error')
                return None, redirect(url_for(redirect_route))
        else:
            flash('Accès non autorisé', 'error')
            return None, redirect(url_for(redirect_route))

    user_affiche = conn.execute('SELECT * FROM users WHERE id = %s', (user_id_a_afficher,)).fetchone()
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
        responsable_secteur = conn.execute('SELECT secteur_id FROM users WHERE id = %s', (session['user_id'],)).fetchone()
        if responsable_secteur and responsable_secteur['secteur_id']:
            users_accessibles = conn.execute('''
                SELECT id, nom, prenom, profil FROM users
                WHERE actif = 1 AND secteur_id = %s
                ORDER BY nom, prenom
            ''', (responsable_secteur['secteur_id'],)).fetchall()

    # Premier et dernier jour du mois
    premier_jour = datetime(annee, mois, 1)
    if mois == 12:
        dernier_jour = datetime(annee + 1, 1, 1) - timedelta(days=1)
    else:
        dernier_jour = datetime(annee, mois + 1, 1) - timedelta(days=1)

    # Plannings theoriques
    plannings = {}
    planning_rows = conn.execute('''
        SELECT * FROM planning_theorique
        WHERE user_id = %s
    ''', (user_id_a_afficher,)).fetchall()

    # Heures reelles du mois
    heures_reelles = {}
    heures_rows = conn.execute('''
        SELECT * FROM heures_reelles
        WHERE user_id = %s AND date >= %s AND date <= %s
    ''', (user_id_a_afficher, premier_jour.strftime('%Y-%m-%d'), dernier_jour.strftime('%Y-%m-%d'))).fetchall()

    for h in heures_rows:
        heures_reelles[h['date']] = dict(h)

    # Generer toutes les journees du mois
    journees = []
    jour_actuel = premier_jour
    total_heures_theoriques = 0
    total_heures_reelles = 0

    while jour_actuel <= dernier_jour:
        date_str = jour_actuel.strftime('%Y-%m-%d')
        jour_semaine = jour_actuel.weekday()  # 0=lundi, 6=dimanche

        if jour_semaine < 6:
            if jour_semaine == 5 and date_str not in heures_reelles:
                jour_actuel += timedelta(days=1)
                continue

            type_periode = get_type_periode(date_str)

            heures_theo_jour = 0
            if jour_semaine == 5:
                heures_theo_jour = 0
            else:
                planning = get_planning_valide_a_date(user_id_a_afficher, type_periode, date_str)
                if planning:
                    heures_theo_jour = get_heures_theoriques_jour(planning, jour_semaine)

            heures_reelles_jour = 0
            est_saisi = False
            est_declare = False
            type_saisie = None
            commentaire = None
            non_declare = False

            if date_str in heures_reelles:
                h = heures_reelles[date_str]
                est_declare = bool(h.get('declaration_conforme', 0))

                if est_declare:
                    heures_reelles_jour = heures_theo_jour
                    est_saisi = True
                else:
                    est_saisi = True
                    heures_matin = calculer_heures(h['heure_debut_matin'], h['heure_fin_matin'])
                    heures_aprem = calculer_heures(h['heure_debut_aprem'], h['heure_fin_aprem'])
                    heures_reelles_jour = heures_matin + heures_aprem

                type_saisie = h['type_saisie']
                commentaire = h['commentaire']
            else:
                if jour_actuel.date() < datetime.now().date() and jour_semaine < 5:
                    non_declare = True
                heures_reelles_jour = heures_theo_jour

            ecart = heures_reelles_jour - heures_theo_jour

            total_heures_theoriques += heures_theo_jour
            total_heures_reelles += heures_reelles_jour

            noms_jours = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi']

            journees.append({
                'date': date_str,
                'date_obj': jour_actuel,
                'jour_semaine': noms_jours[jour_semaine],
                'jour_semaine_idx': jour_semaine,
                'est_samedi': jour_semaine == 5,
                'heures_theoriques': heures_theo_jour,
                'heures_reelles': heures_reelles_jour,
                'ecart': ecart,
                'est_saisi': est_saisi,
                'est_declare': est_declare,
                'non_declare': non_declare,
                'type_saisie': type_saisie,
                'commentaire': commentaire,
                'type_periode': type_periode
            })

        jour_actuel += timedelta(days=1)

    # Solde du mois
    solde_mois = total_heures_reelles - total_heures_theoriques

    # Solde anterieur
    try:
        user_data = conn.execute('SELECT solde_initial FROM users WHERE id = %s', (user_id_a_afficher,)).fetchone()
        solde_anterieur = user_data['solde_initial'] if user_data and user_data['solde_initial'] else 0
    except (Exception,):
        solde_anterieur = 0

    heures_anterieures = conn.execute('''
        SELECT date, heure_debut_matin, heure_fin_matin,
               heure_debut_aprem, heure_fin_aprem, declaration_conforme
        FROM heures_reelles
        WHERE user_id = %s AND date < %s
        ORDER BY date
    ''', (user_id_a_afficher, premier_jour.strftime('%Y-%m-%d'))).fetchall()

    for h in heures_anterieures:
        date_obj_ant = datetime.strptime(h['date'], '%Y-%m-%d')
        jour_semaine_ant = date_obj_ant.weekday()

        type_periode = get_type_periode(h['date'])
        total_theorique = 0

        if jour_semaine_ant < 5:
            planning_ant = get_planning_valide_a_date(user_id_a_afficher, type_periode, h['date'])
            if planning_ant:
                total_theorique = get_heures_theoriques_jour(planning_ant, jour_semaine_ant)

        if h['declaration_conforme']:
            total_reel = total_theorique
        else:
            heures_matin = calculer_heures(h['heure_debut_matin'], h['heure_fin_matin'])
            heures_aprem = calculer_heures(h['heure_debut_aprem'], h['heure_fin_aprem'])
            total_reel = heures_matin + heures_aprem

        solde_anterieur += (total_reel - total_theorique)

    solde_cumule = solde_anterieur + solde_mois

    nb_jours_non_declares = sum(1 for j in journees if j.get('non_declare', False))

    validation = conn.execute('''
        SELECT * FROM validations
        WHERE user_id = %s AND mois = %s AND annee = %s
    ''', (user_id_a_afficher, mois, annee)).fetchone()

    today = datetime.now()
    mois_demande = datetime(annee, mois, 1)
    mois_est_termine = not (mois_demande.year == today.year and mois_demande.month >= today.month)

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
            user_to_validate = conn.execute('SELECT secteur_id FROM users WHERE id = %s', (user_id_a_afficher,)).fetchone()
            responsable_secteur = conn.execute('SELECT secteur_id FROM users WHERE id = %s', (session['user_id'],)).fetchone()

            if user_to_validate and responsable_secteur and user_to_validate['secteur_id'] == responsable_secteur['secteur_id']:
                peut_valider_mois = True

    peut_modifier = False
    if not (validation and validation['bloque']):
        if user_id_a_afficher == session['user_id']:
            if session.get('profil') != 'directeur':
                peut_modifier = True
        elif session.get('profil') == 'directeur':
            peut_modifier = True
        elif session.get('profil') == 'responsable':
            user_to_view = conn.execute('SELECT secteur_id FROM users WHERE id = %s', (user_id_a_afficher,)).fetchone()
            responsable_secteur = conn.execute('SELECT secteur_id FROM users WHERE id = %s', (session['user_id'],)).fetchone()

            if user_to_view and responsable_secteur and user_to_view['secteur_id'] == responsable_secteur['secteur_id']:
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

    # Jours feries du mois
    jours_feries_rows = conn.execute('''
        SELECT date, libelle FROM jours_feries
        WHERE date >= %s AND date <= %s
    ''', (premier_jour.strftime('%Y-%m-%d'), dernier_jour.strftime('%Y-%m-%d'))).fetchall()
    jours_feries = {f['date']: f['libelle'] for f in jours_feries_rows}

    noms_mois = ['', 'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
                 'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']

    template_data = dict(
        journees=journees,
        mois=mois,
        annee=annee,
        nom_mois=noms_mois[mois],
        total_heures_theoriques=total_heures_theoriques,
        total_heures_reelles=total_heures_reelles,
        solde_mois=solde_mois,
        solde_anterieur=solde_anterieur,
        solde_cumule=solde_cumule,
        mois_precedent=mois_precedent,
        annee_precedente=annee_precedente,
        mois_suivant=mois_suivant,
        annee_suivante=annee_suivante,
        user_affiche=dict(user_affiche),
        users_accessibles=users_accessibles,
        user_id_a_afficher=user_id_a_afficher,
        peut_modifier=peut_modifier,
        validation=dict(validation) if validation else None,
        peut_valider_mois=peut_valider_mois,
        mois_est_termine=mois_est_termine,
        nb_jours_non_declares=nb_jours_non_declares,
        jours_feries=jours_feries,
        premier_jour_semaine=premier_jour.weekday(),
        nb_jours_mois=dernier_jour.day,
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
