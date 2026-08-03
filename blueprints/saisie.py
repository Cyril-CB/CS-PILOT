"""
Blueprint saisie_bp.
"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from datetime import datetime, timedelta
import json
from database import get_db
from utils import (login_required, get_user_info, calculer_heures,
                    calculer_heures_reelles_jour, slot_horaire,
                    get_heures_theoriques_jour, get_type_periode, get_planning_valide_a_date,
                    calculer_solde_recup, est_dans_equipe_responsable,
                    periodes_contrat, est_couvert_par_contrat)
from app_options import get_option_bool

saisie_bp = Blueprint('saisie_bp', __name__)
SEUIL_ECART_ANOMALIE_HEURES = 3


# Lignes de `heures_reelles` écrites par les circuits absences et récup, et
# non par quelqu'un venu saisir ses heures ici.
_TYPES_GENERES = ('absence', 'recup_journee', 'recup_partielle')


def _saisie_sans_contrat(conn, user_id_cible, date_str, saisie_existante):
    """La saisie doit-elle être refusée faute de contrat couvrant ce jour ?

    Un contrat est désormais obligatoire pour saisir des heures : c'est lui
    qui alimente la paie, et une journée sans contrat n'est due à personne.
    L'absence de contrat au dossier vaut donc refus — c'est ce qui pousse à
    l'enregistrer plutôt que de le remettre à plus tard.

    Une **saisie manuelle** déjà enregistrée échappe à la règle : les heures
    posées avant qu'elle n'existe restent modifiables, on ne fige pas des
    données que leur auteur pourrait avoir à corriger.

    Une ligne **générée** (absence, récupération) ne rouvre en revanche pas la
    porte. Ces circuits écrivent librement hors contrat — une absence se
    régularise parfois après la fin d'un contrat — et leur ligne servirait
    sinon de laissez-passer : il suffirait d'ouvrir le jour d'une absence pour
    y substituer des heures travaillées sur une période sans contrat. Corriger
    l'absence elle-même se fait sur la page Absences, pas ici.

    Le planning théorique, lui, n'est pas exigé : s'il arrive plus tard, les
    heures supplémentaires se recalculent d'elles-mêmes.
    """
    if saisie_existante and saisie_existante['type_saisie'] not in _TYPES_GENERES:
        return False
    return not est_couvert_par_contrat(periodes_contrat(conn, user_id_cible), date_str)


def _message_sans_contrat(date_str, pour_soi):
    """Refus de saisie : dire quoi faire, et à qui."""
    try:
        jour = datetime.strptime(date_str, '%Y-%m-%d').strftime('%d/%m/%Y')
    except (ValueError, TypeError):
        jour = date_str
    if pour_soi:
        return (f"Aucun contrat enregistré au {jour} : la saisie est impossible. "
                "Signalez-le à la direction pour que le contrat soit ajouté à votre dossier.")
    return (f"Aucun contrat enregistré au {jour} pour ce salarié : la saisie est "
            "impossible. Ajoutez le contrat depuis Infos Salariés → Contrats.")


@saisie_bp.route('/saisie_heures', methods=['GET', 'POST'])
@login_required
def saisie_heures():
    """Saisie des heures réelles"""
    # Récupérer le user_id cible (par défaut = soi-même)
    user_id_param = request.args.get('user_id', type=int) if request.method == 'GET' else request.form.get('user_id', type=int)
    user_id_cible = user_id_param if user_id_param else session['user_id']
    
    conn = get_db()
    declaration_conforme_active = get_option_bool('saisie_afficher_declaration_conforme')
    
    # Vérifier les droits de modification
    peut_modifier = False
    if user_id_cible == session['user_id']:
        # Peut modifier sa propre fiche (sauf directeur)
        if session.get('profil') != 'directeur':
            peut_modifier = True
    elif session.get('profil') == 'directeur':
        # Directeur peut modifier toutes les fiches
        peut_modifier = True
    elif session.get('profil') == 'responsable':
        # Responsable : fiches de son secteur OU de ses rattachés directs
        # (salarié d'un autre secteur analytique, ex. entretien en logistique).
        if est_dans_equipe_responsable(conn, session['user_id'], user_id_cible):
            peut_modifier = True
    
    if not peut_modifier:
        flash('Vous n\'avez pas le droit de modifier cette fiche', 'error')
        conn.close()
        return redirect(url_for('dashboard_bp.dashboard'))
    
    if request.method == 'POST':
        date = request.form.get('date')
        next_page = request.form.get('next', '')

        # Vérifier si le mois est verrouillé
        date_obj = datetime.strptime(date, '%Y-%m-%d')
        mois = date_obj.month
        annee = date_obj.year
        
        validation = conn.execute('''
            SELECT bloque FROM validations 
            WHERE user_id = ? AND mois = ? AND annee = ?
        ''', (user_id_cible, mois, annee)).fetchone()
        
        if validation and validation['bloque']:
            flash('Impossible de modifier : la fiche est verrouillée (validée par responsable et directeur)', 'error')
            conn.close()
            if user_id_cible != session['user_id']:
                return redirect(url_for('validation_bp.vue_mensuelle', user_id=user_id_cible))
            else:
                return redirect(url_for('dashboard_bp.dashboard'))
        
        recup_journee = request.form.get('recup_journee')
        commentaire = request.form.get('commentaire')

        anciennes_donnees = conn.execute('''
            SELECT * FROM heures_reelles WHERE user_id = ? AND date = ?
        ''', (user_id_cible, date)).fetchone()

        if _saisie_sans_contrat(conn, user_id_cible, date, anciennes_donnees):
            flash(_message_sans_contrat(date, user_id_cible == session['user_id']), 'error')
            conn.close()
            if next_page == 'calendrier':
                return redirect(url_for('validation_bp.vue_calendrier',
                                        user_id=user_id_cible, mois=mois, annee=annee))
            if next_page == 'mensuelle' or user_id_cible != session['user_id']:
                return redirect(url_for('validation_bp.vue_mensuelle',
                                        user_id=user_id_cible, mois=mois, annee=annee))
            return redirect(url_for('saisie_bp.saisie_heures', date=date))

        preserve_declaration_conforme = (
            not declaration_conforme_active
            and anciennes_donnees is not None
            and anciennes_donnees['declaration_conforme'] == 1
            and anciennes_donnees['type_saisie'] == 'declaration_conforme'
            and recup_journee != '1'
            and not any(request.form.get(field) for field in (
                'heure_debut_matin',
                'heure_fin_matin',
                'heure_debut_aprem',
                'heure_fin_aprem',
                'heure_debut_soir',
                'heure_fin_soir',
            ))
        )
        declaration_conforme = request.form.get('declaration_conforme') if declaration_conforme_active else (
            '1' if preserve_declaration_conforme else None
        )
        
        # Si déclaration conforme, on ne stocke pas d'heures (appliquera le planning théo)
        if declaration_conforme == '1':
            heure_debut_matin = None
            heure_fin_matin = None
            heure_debut_aprem = None
            heure_fin_aprem = None
            heure_debut_soir = None
            heure_fin_soir = None
            type_saisie = 'declaration_conforme'
            if not commentaire:
                commentaire = 'Déclaration conforme au planning'
            declaration_conforme_val = 1
            pause_remuneree_val = 0
        # Si récupération journée complète, on met tout à vide
        elif recup_journee == '1':
            heure_debut_matin = None
            heure_fin_matin = None
            heure_debut_aprem = None
            heure_fin_aprem = None
            heure_debut_soir = None
            heure_fin_soir = None
            type_saisie = 'recup_journee'
            if not commentaire:
                commentaire = 'Récupération journée complète'
            declaration_conforme_val = 0
            pause_remuneree_val = 0
        else:
            heure_debut_matin = request.form.get('heure_debut_matin') or None
            heure_fin_matin = request.form.get('heure_fin_matin') or None
            heure_debut_aprem = request.form.get('heure_debut_aprem') or None
            heure_fin_aprem = request.form.get('heure_fin_aprem') or None
            # Créneau soir optionnel (proposé uniquement en période de vacances).
            heure_debut_soir = request.form.get('heure_debut_soir') or None
            heure_fin_soir = request.form.get('heure_fin_soir') or None
            type_saisie = 'heures_modifiees'
            declaration_conforme_val = 0
            # Pause méridienne rémunérée : prise sur place en restant à
            # disposition (temps de travail effectif, art. L3121-2).
            pause_remuneree_val = 1 if request.form.get('pause_remuneree') == '1' else 0
        
        try:
            action = 'modification' if anciennes_donnees else 'creation'
            
            anciennes_valeurs = None
            if anciennes_donnees:
                anciennes_valeurs = json.dumps({
                    'heure_debut_matin': anciennes_donnees['heure_debut_matin'],
                    'heure_fin_matin': anciennes_donnees['heure_fin_matin'],
                    'heure_debut_aprem': anciennes_donnees['heure_debut_aprem'],
                    'heure_fin_aprem': anciennes_donnees['heure_fin_aprem'],
                    'heure_debut_soir': slot_horaire(anciennes_donnees, 'heure_debut_soir'),
                    'heure_fin_soir': slot_horaire(anciennes_donnees, 'heure_fin_soir'),
                    'commentaire': anciennes_donnees['commentaire'],
                    'type_saisie': anciennes_donnees['type_saisie'],
                    'pause_remuneree': slot_horaire(anciennes_donnees, 'pause_remuneree')
                })

            nouvelles_valeurs = json.dumps({
                'heure_debut_matin': heure_debut_matin,
                'heure_fin_matin': heure_fin_matin,
                'heure_debut_aprem': heure_debut_aprem,
                'heure_fin_aprem': heure_fin_aprem,
                'heure_debut_soir': heure_debut_soir,
                'heure_fin_soir': heure_fin_soir,
                'commentaire': commentaire,
                'type_saisie': type_saisie,
                'pause_remuneree': pause_remuneree_val
            })
            
            # DÉTECTION DES ANOMALIES
            if anciennes_donnees:
                # 1. Détection récup validée modifiée/supprimée
                if anciennes_donnees['type_saisie'] in ('recup_journee', 'recup_partielle'):
                    # Vérifier si c'était une récup validée (commentaire contient "Demande #")
                    if anciennes_donnees['commentaire'] and 'Demande #' in anciennes_donnees['commentaire']:
                        # ANOMALIE CRITIQUE : Récup validée modifiée
                        conn.execute('''
                            INSERT INTO anomalies 
                            (user_id, date_modification, date_concernee, type_anomalie, gravite, description, ancienne_valeur, nouvelle_valeur)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (user_id_cible, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), date,
                              'recup_validee_modifiee', 'critique',
                              f"Récupération validée modifiée/supprimée : {anciennes_donnees['commentaire']}",
                              anciennes_valeurs, nouvelles_valeurs))
                
                # 2. Détection gros changement d'heures
                if anciennes_donnees['type_saisie'] != 'recup_journee' and type_saisie != 'recup_journee':
                    # Calculer les heures avant et après (3 créneaux inclus)
                    heures_avant = calculer_heures_reelles_jour(anciennes_donnees)
                    heures_apres = calculer_heures_reelles_jour({
                        'heure_debut_matin': heure_debut_matin, 'heure_fin_matin': heure_fin_matin,
                        'heure_debut_aprem': heure_debut_aprem, 'heure_fin_aprem': heure_fin_aprem,
                        'heure_debut_soir': heure_debut_soir, 'heure_fin_soir': heure_fin_soir,
                        'pause_remuneree': pause_remuneree_val,
                    })

                    ecart = abs(heures_apres - heures_avant)
                    if ecart > SEUIL_ECART_ANOMALIE_HEURES:
                        # ANOMALIE ALERTE : Gros changement d'heures
                        conn.execute('''
                            INSERT INTO anomalies 
                            (user_id, date_modification, date_concernee, type_anomalie, gravite, description, ancienne_valeur, nouvelle_valeur)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (user_id_cible, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), date,
                              'gros_changement_heures', 'alerte',
                              f"Changement important : {heures_avant:.2f}h → {heures_apres:.2f}h (écart: {ecart:.2f}h)",
                              anciennes_valeurs, nouvelles_valeurs))
                
                # 3. Détection modification après validation
                validation = conn.execute('''
                    SELECT * FROM validations 
                    WHERE user_id = ? AND mois = ? AND annee = ?
                ''', (user_id_cible, mois, annee)).fetchone()
                
                if validation:
                    if validation['validation_responsable'] and not validation['bloque']:
                        # ANOMALIE SUSPECT : Modification après validation responsable
                        conn.execute('''
                            INSERT INTO anomalies 
                            (user_id, date_modification, date_concernee, type_anomalie, gravite, description, ancienne_valeur, nouvelle_valeur)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (user_id_cible, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), date,
                              'modification_apres_validation', 'suspect',
                              f"Modification après validation par {validation['validation_responsable']}",
                              anciennes_valeurs, nouvelles_valeurs))
            else:
                # 4. Détection gros écart à la création (vs planning théorique)
                est_declaration_conforme = declaration_conforme_val == 1
                if type_saisie != 'recup_journee' and not est_declaration_conforme:
                    date_saisie = datetime.strptime(date, '%Y-%m-%d')
                    total_theorique = 0

                    if date_saisie.weekday() != 6:  # Exclure dimanche
                        type_periode = get_type_periode(date)
                        planning = get_planning_valide_a_date(user_id_cible, type_periode, date)
                        if planning:
                            total_theorique = get_heures_theoriques_jour(planning, date_saisie.weekday())

                    heures_apres = calculer_heures_reelles_jour({
                        'heure_debut_matin': heure_debut_matin, 'heure_fin_matin': heure_fin_matin,
                        'heure_debut_aprem': heure_debut_aprem, 'heure_fin_aprem': heure_fin_aprem,
                        'heure_debut_soir': heure_debut_soir, 'heure_fin_soir': heure_fin_soir,
                        'pause_remuneree': pause_remuneree_val,
                    })

                    ecart = abs(heures_apres - total_theorique)
                    if ecart > SEUIL_ECART_ANOMALIE_HEURES:
                        conn.execute('''
                            INSERT INTO anomalies 
                            (user_id, date_modification, date_concernee, type_anomalie, gravite, description, ancienne_valeur, nouvelle_valeur)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (user_id_cible, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), date,
                              'gros_changement_heures', 'alerte',
                              f"Écart important à la création : {total_theorique:.2f}h théoriques → {heures_apres:.2f}h saisies (écart: {ecart:.2f}h)",
                              anciennes_valeurs, nouvelles_valeurs))
            
            # Enregistrer la modification
            conn.execute('''
                INSERT OR REPLACE INTO heures_reelles
                (user_id, date, heure_debut_matin, heure_fin_matin,
                 heure_debut_aprem, heure_fin_aprem, heure_debut_soir, heure_fin_soir,
                 commentaire, type_saisie, declaration_conforme, pause_remuneree)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id_cible, date, heure_debut_matin, heure_fin_matin,
                  heure_debut_aprem, heure_fin_aprem, heure_debut_soir, heure_fin_soir,
                  commentaire, type_saisie, declaration_conforme_val, pause_remuneree_val))
            
            # Enregistrer dans l'historique
            conn.execute('''
                INSERT INTO historique_modifications
                (user_id_modifie, date_concernee, modifie_par, action, anciennes_valeurs, nouvelles_valeurs)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id_cible, date, session['user_id'], action, anciennes_valeurs, nouvelles_valeurs))
            
            conn.commit()
            flash('Heures enregistrées avec succès', 'success')
        except Exception as e:
            flash(f'Erreur: {str(e)}', 'error')
        finally:
            conn.close()
        
        # Rediriger selon la page d'origine
        if next_page == 'calendrier':
            return redirect(url_for('validation_bp.vue_calendrier',
                                    user_id=user_id_cible, mois=mois, annee=annee))
        elif next_page == 'mensuelle':
            return redirect(url_for('validation_bp.vue_mensuelle',
                                    user_id=user_id_cible, mois=mois, annee=annee))
        elif user_id_cible != session['user_id']:
            # Si on modifie quelqu'un d'autre → vue mensuelle
            return redirect(url_for('validation_bp.vue_mensuelle', user_id=user_id_cible))
        else:
            # Si on modifie sa propre fiche → rester sur saisie_heures pour faciliter multi-saisies
            return redirect(url_for('saisie_bp.saisie_heures'))
    
    # GET: afficher le formulaire
    date_param = request.args.get('date')
    heures_existantes = None
    
    if date_param:
        date_defaut = date_param
    else:
        # Si pas de paramètre, utiliser la date du jour
        date_defaut = datetime.now().strftime('%Y-%m-%d')
    
    # Charger les données existantes pour la date (pour l'utilisateur cible)
    row = conn.execute('''
        SELECT * FROM heures_reelles 
        WHERE user_id = ? AND date = ?
    ''', (user_id_cible, date_defaut)).fetchone()
    
    # Convertir le Row en dictionnaire pour le template
    if row:
        heures_existantes = dict(row)
    
    # Récupérer les infos de l'utilisateur cible
    user_cible = conn.execute('SELECT * FROM users WHERE id = ?', (user_id_cible,)).fetchone()

    # Solde de récupération
    solde_recup = calculer_solde_recup(user_id_cible)

    # Vérifier si le mois est verrouillé
    date_obj = datetime.strptime(date_defaut, '%Y-%m-%d')
    validation = conn.execute('''
        SELECT bloque FROM validations
        WHERE user_id = ? AND mois = ? AND annee = ?
    ''', (user_id_cible, date_obj.month, date_obj.year)).fetchone()
    mois_verrouille = validation and validation['bloque']

    sans_contrat = _saisie_sans_contrat(conn, user_id_cible, date_defaut, row)
    message_sans_contrat = _message_sans_contrat(
        date_defaut, user_id_cible == session['user_id']) if sans_contrat else None

    conn.close()

    next_page = request.args.get('next', '')

    # Le 3e créneau « soir » n'est proposé qu'en période de vacances (personnel
    # d'entretien). On l'affiche aussi si une saisie soir existe déjà pour ce jour.
    est_vacances = get_type_periode(date_defaut) == 'vacances'
    a_soir = bool(heures_existantes and (heures_existantes.get('heure_debut_soir')
                                         or heures_existantes.get('heure_fin_soir')))

    return render_template('saisie_heures.html',
                          date_defaut=date_defaut,
                          heures_existantes=heures_existantes,
                          user_cible=dict(user_cible) if user_cible else None,
                          user_id_cible=user_id_cible,
                          next_page=next_page,
                          solde_recup=solde_recup,
                          mois_verrouille=mois_verrouille,
                          sans_contrat=sans_contrat,
                          message_sans_contrat=message_sans_contrat,
                          soir_disponible=est_vacances or a_soir,
                          soir_rempli=a_soir,
                          declaration_conforme_active=declaration_conforme_active)
