"""
Blueprint recup_bp.
"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from datetime import datetime, timedelta
import sqlite3
from database import get_db
from utils import (login_required, get_user_info, calculer_heures,
                   get_heures_theoriques_jour, get_type_periode, get_planning_valide_a_date,
                   calculer_jours_ouvres, calculer_solde_recup)
from email_service import (
    is_email_configured, peut_envoyer_email, notifier_nouvelle_demande_recup,
    notifier_demande_recup_validee_responsable, notifier_demande_recup_decision,
)

recup_bp = Blueprint('recup_bp', __name__)


def _safe_nb_heures(row):
    """Retourne nb_heures d'un Row ou 0 si la colonne n'existe pas."""
    try:
        return row['nb_heures'] or 0
    except (IndexError, KeyError):
        return 0


def _creer_absence_depuis_conge(conn, demande, demande_id, saisi_par):
    """Crée une entrée dans la table absences quand un congé est validé.

    Reporte aussi le congé sur le calendrier (heures_reelles) et actualise
    les compteurs de congés du salarié.
    """
    import json
    from blueprints.absences import (
        _reporter_absence_sur_calendrier, _actualiser_compteurs_conges,
    )

    type_conge = demande['type_conge']
    user_id = demande['user_id']
    date_debut = demande['date_debut']
    date_fin = demande['date_fin']
    nb_jours = demande['nb_jours']

    # Insérer dans la table absences
    conn.execute('''
        INSERT INTO absences
        (user_id, motif, date_debut, date_fin, commentaire, jours_ouvres, saisi_par)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, type_conge, date_debut, date_fin,
          f"Congé validé - Demande #{demande_id}", nb_jours, saisi_par))
    absence_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]

    # Reporter sur le calendrier
    _reporter_absence_sur_calendrier(conn, absence_id, user_id, date_debut, date_fin, type_conge)

    # Actualiser les compteurs de congés
    _actualiser_compteurs_conges(conn, user_id, type_conge, nb_jours, ajout=True)


@recup_bp.route('/demande_recup', methods=['GET', 'POST'])
@login_required
def demande_recup():
    """Créer une demande de récupération"""
    if request.method == 'POST':
        date_debut = request.form.get('date_debut')
        date_fin = request.form.get('date_fin')
        motif_demande = request.form.get('motif_demande', '').strip()
        
        if not date_debut or not date_fin:
            flash('Les dates sont obligatoires', 'error')
            return redirect(url_for('recup_bp.demande_recup'))
        
        # Calculer le nombre de jours ouvrés
        nb_jours = calculer_jours_ouvres(date_debut, date_fin)
        
        if nb_jours <= 0:
            flash('Période invalide', 'error')
            return redirect(url_for('recup_bp.demande_recup'))
        
        # Récupérer le solde de récup disponible
        conn = get_db()
        
        # Calculer le solde (similaire au dashboard)
        heures = conn.execute('''
            SELECT date, heure_debut_matin, heure_fin_matin,
                   heure_debut_aprem, heure_fin_aprem, declaration_conforme
            FROM heures_reelles 
            WHERE user_id = ?
            ORDER BY date
        ''', (session['user_id'],)).fetchall()
        
        # Récupérer le solde initial
        try:
            user_data = conn.execute('SELECT solde_initial FROM users WHERE id = ?', (session['user_id'],)).fetchone()
            solde_recup = user_data['solde_initial'] if user_data and user_data['solde_initial'] else 0
        except (sqlite3.OperationalError, KeyError, TypeError):
            solde_recup = 0
        
        for h in heures:
            date_obj = datetime.strptime(h['date'], '%Y-%m-%d')
            if date_obj.weekday() == 6:  # Dimanche
                continue
            
            type_periode = get_type_periode(h['date'])
            jour_semaine = date_obj.weekday()
            
            # Heures théoriques - UTILISER LE BON PLANNING À CETTE DATE
            total_theorique = 0
            if jour_semaine == 5:  # Samedi
                total_theorique = 0
            else:
                planning = get_planning_valide_a_date(session['user_id'], type_periode, h['date'])
                if planning:
                    total_theorique = get_heures_theoriques_jour(planning, jour_semaine)
            
            # Heures réelles
            if h['declaration_conforme']:
                total_reel = total_theorique
            else:
                heures_matin = calculer_heures(h['heure_debut_matin'], h['heure_fin_matin'])
                heures_aprem = calculer_heures(h['heure_debut_aprem'], h['heure_fin_aprem'])
                total_reel = heures_matin + heures_aprem
            
            solde_recup += (total_reel - total_theorique)
        
        # Calculer les heures EXACTES pour chaque jour de la période
        nb_heures = 0
        date_actuelle = datetime.strptime(date_debut, '%Y-%m-%d')
        date_fin_obj = datetime.strptime(date_fin, '%Y-%m-%d')
        
        while date_actuelle <= date_fin_obj:
            jour_semaine = date_actuelle.weekday()
            
            # Ne compter que les jours ouvrés (lundi-vendredi)
            if jour_semaine < 5:
                # Déterminer le type de période
                date_str = date_actuelle.strftime('%Y-%m-%d')
                type_periode = get_type_periode(date_str)
                
                # Récupérer les heures théoriques exactes pour ce jour - BON PLANNING
                planning = get_planning_valide_a_date(session['user_id'], type_periode, date_str)
                if planning:
                    heures_jour = get_heures_theoriques_jour(planning, jour_semaine)
                    nb_heures += heures_jour
            
            date_actuelle += timedelta(days=1)
        
        # Vérifier le solde (autoriser négatif mais avec warning)
        if nb_heures > solde_recup:
            solde_apres = solde_recup - nb_heures
            flash(f'⚠️ Attention : votre solde passera à {solde_apres:.2f}h (solde négatif). La demande doit être justifiée auprès de votre responsable.', 'warning')
        
        # Déterminer le statut initial selon le profil
        if session.get('profil') == 'responsable':
            statut_initial = 'en_attente_direction'
        else:
            statut_initial = 'en_attente_responsable'
        
        # Créer la demande
        try:
            conn.execute('''
                INSERT INTO demandes_recup
                (user_id, date_debut, date_fin, nb_jours, nb_heures, motif_demande, statut)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (session['user_id'], date_debut, date_fin, nb_jours, nb_heures, motif_demande, statut_initial))
            conn.commit()
            flash(f'Demande créée : {nb_jours} jour(s) = {nb_heures:.2f}h', 'success')

            # Notification email au responsable (si configure)
            if is_email_configured() and statut_initial == 'en_attente_responsable':
                demandeur = conn.execute('SELECT nom, prenom, responsable_id FROM users WHERE id = ?',
                                         (session['user_id'],)).fetchone()
                if demandeur and demandeur['responsable_id']:
                    resp = conn.execute('SELECT prenom, email FROM users WHERE id = ?',
                                        (demandeur['responsable_id'],)).fetchone()
                    if resp and resp['email']:
                        demandeur_nom = f"{demandeur['prenom']} {demandeur['nom']}"
                        notifier_nouvelle_demande_recup(
                            demandeur_nom, resp['email'], resp['prenom'],
                            date_debut, date_fin, nb_jours, nb_heures
                        )

            # Si responsable -> notifier directement la direction
            if is_email_configured() and statut_initial == 'en_attente_direction':
                demandeur = conn.execute('SELECT nom, prenom FROM users WHERE id = ?',
                                         (session['user_id'],)).fetchone()
                if demandeur:
                    demandeur_nom = f"{demandeur['prenom']} {demandeur['nom']}"
                    directeurs = conn.execute(
                        "SELECT prenom, email FROM users WHERE profil = 'directeur' AND actif = 1 AND email IS NOT NULL AND email != ''",
                    ).fetchall()
                    for d in directeurs:
                        notifier_demande_recup_validee_responsable(
                            d['email'], d['prenom'], demandeur_nom, demandeur_nom,
                            date_debut, date_fin, nb_jours
                        )

        except Exception as e:
            flash(f'Erreur : {str(e)}', 'error')
        finally:
            conn.close()
        
        return redirect(url_for('recup_bp.mes_demandes_recup'))
    
    # GET : afficher le formulaire
    conn = get_db()
    
    # Calculer le solde disponible (même logique que ci-dessus)
    heures = conn.execute('''
        SELECT date, heure_debut_matin, heure_fin_matin,
               heure_debut_aprem, heure_fin_aprem, declaration_conforme
        FROM heures_reelles 
        WHERE user_id = ?
        ORDER BY date
    ''', (session['user_id'],)).fetchall()
    
    # Récupérer le solde initial
    try:
        user_data = conn.execute('SELECT solde_initial FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        solde_recup = user_data['solde_initial'] if user_data and user_data['solde_initial'] else 0
    except (sqlite3.OperationalError, KeyError, TypeError):
        solde_recup = 0
    
    for h in heures:
        date_obj = datetime.strptime(h['date'], '%Y-%m-%d')
        if date_obj.weekday() == 6:  # Dimanche
            continue
        
        type_periode = get_type_periode(h['date'])
        jour_semaine = date_obj.weekday()
        
        # Heures théoriques - UTILISER LE BON PLANNING À CETTE DATE
        total_theorique = 0
        if jour_semaine == 5:
            total_theorique = 0
        else:
            planning = get_planning_valide_a_date(session['user_id'], type_periode, h['date'])
            if planning:
                total_theorique = get_heures_theoriques_jour(planning, jour_semaine)
        
        # Heures réelles
        if h['declaration_conforme']:
            total_reel = total_theorique
        else:
            heures_matin = calculer_heures(h['heure_debut_matin'], h['heure_fin_matin'])
            heures_aprem = calculer_heures(h['heure_debut_aprem'], h['heure_fin_aprem'])
            total_reel = heures_matin + heures_aprem
        
        solde_recup += (total_reel - total_theorique)
    
    conn.close()
    
    return render_template('demande_recup.html', solde_recup=solde_recup)

@recup_bp.route('/mes_demandes_recup')
@login_required
def mes_demandes_recup():
    """Liste des demandes de récupération du salarié"""
    conn = get_db()
    
    demandes = conn.execute('''
        SELECT d.*,
               u.nom || ' ' || u.prenom as demandeur_nom
        FROM demandes_recup d
        JOIN users u ON d.user_id = u.id
        WHERE d.user_id = ?
        ORDER BY d.date_demande DESC
    ''', (session['user_id'],)).fetchall()
    
    conn.close()
    
    return render_template('mes_demandes_recup.html', demandes=demandes)

@recup_bp.route('/validation_demandes_recup', methods=['GET', 'POST'])
@login_required
def validation_demandes_recup():
    """Validation des demandes de récupération et de congés (responsable et direction)"""
    if session.get('profil') not in ['responsable', 'directeur', 'comptable']:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))
    
    if request.method == 'POST':
        demande_id = request.form.get('demande_id', type=int)
        action = request.form.get('action')  # 'valider' ou 'refuser'
        motif_refus = request.form.get('motif_refus', '').strip()
        demande_type = request.form.get('demande_type', 'recup')  # 'recup' ou 'conge'
        
        if not demande_id or not action:
            flash('Paramètres invalides', 'error')
            return redirect(url_for('recup_bp.validation_demandes_recup'))

        table = 'demandes_conges' if demande_type == 'conge' else 'demandes_recup'
        
        conn = get_db()

        try:
            # Récupérer la demande
            demande = conn.execute(f'SELECT * FROM {table} WHERE id = ?', (demande_id,)).fetchone()

            if not demande:
                flash('Demande introuvable', 'error')
                return redirect(url_for('recup_bp.validation_demandes_recup'))

            user_info = get_user_info(session['user_id'])
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            if action == 'refuser':
                if not motif_refus:
                    flash('Le motif de refus est obligatoire', 'error')
                    return redirect(url_for('recup_bp.validation_demandes_recup'))

                # Refuser la demande
                conn.execute(f'''
                    UPDATE {table}
                    SET statut = 'refusee', motif_refus = ?, refuse_par = ?, date_refus = ?
                    WHERE id = ?
                ''', (motif_refus, session['user_id'], now, demande_id))
                conn.commit()
                flash('Demande refusée', 'success')

                # Notification email au salarie (si consentement donne)
                if is_email_configured():
                    peut, email_sal = peut_envoyer_email(demande['user_id'])
                    if peut:
                        salarie = conn.execute('SELECT prenom FROM users WHERE id = ?',
                                                (demande['user_id'],)).fetchone()
                        if salarie:
                            notifier_demande_recup_decision(
                                email_sal, salarie['prenom'], 'refusee',
                                demande['date_debut'], demande['date_fin'],
                                demande['nb_jours'], motif_refus
                            )

            elif action == 'valider':
                # Valider selon le profil
                if session.get('profil') == 'responsable':
                    # Responsable valide → passe à en_attente_direction
                    conn.execute(f'''
                        UPDATE {table}
                        SET statut = 'en_attente_direction',
                            validation_responsable = ?,
                            date_validation_responsable = ?
                        WHERE id = ?
                    ''', (f"{user_info['prenom']} {user_info['nom']}", now, demande_id))
                    conn.commit()
                    flash('Demande validée, en attente de la direction', 'success')

                    # Notification email a la direction
                    if is_email_configured():
                        demandeur = conn.execute('SELECT nom, prenom FROM users WHERE id = ?',
                                                 (demande['user_id'],)).fetchone()
                        if demandeur:
                            demandeur_nom = f"{demandeur['prenom']} {demandeur['nom']}"
                            responsable_nom = f"{user_info['prenom']} {user_info['nom']}"
                            directeurs = conn.execute(
                                "SELECT prenom, email FROM users WHERE profil = 'directeur' AND actif = 1 AND email IS NOT NULL AND email != ''",
                            ).fetchall()
                            for d in directeurs:
                                notifier_demande_recup_validee_responsable(
                                    d['email'], d['prenom'], demandeur_nom, responsable_nom,
                                    demande['date_debut'], demande['date_fin'], demande['nb_jours']
                                )

                elif session.get('profil') in ['directeur', 'comptable']:
                    # Direction valide → statut = validee
                    conn.execute(f'''
                        UPDATE {table}
                        SET statut = 'validee',
                            validation_direction = ?,
                            date_validation_direction = ?
                        WHERE id = ?
                    ''', (f"{user_info['prenom']} {user_info['nom']}", now, demande_id))

                    if demande_type == 'conge':
                        # Créer une entrée dans la table absences
                        type_conge = demande['type_conge']
                        nb_jours = demande['nb_jours']
                        _creer_absence_depuis_conge(conn, demande, demande_id, session['user_id'])
                        conn.commit()
                        flash(f'Demande de congé validée définitivement - {nb_jours:.0f} jour(s) ajouté(s) à l\'historique des absences', 'success')
                    else:
                        # Créer automatiquement les entrées de récupération dans heures_reelles
                        date_debut = datetime.strptime(demande['date_debut'], '%Y-%m-%d')
                        date_fin = datetime.strptime(demande['date_fin'], '%Y-%m-%d')

                        jour_actuel = date_debut
                        nb_jours_crees = 0

                        while jour_actuel <= date_fin:
                            jour_semaine = jour_actuel.weekday()

                            # Ne créer que pour les jours ouvrés (lundi-vendredi)
                            if jour_semaine < 5:
                                date_str = jour_actuel.strftime('%Y-%m-%d')

                                # Vérifier si le mois n'est pas verrouillé
                                mois = jour_actuel.month
                                annee = jour_actuel.year
                                validation = conn.execute('''
                                    SELECT bloque FROM validations
                                    WHERE user_id = ? AND mois = ? AND annee = ?
                                ''', (demande['user_id'], mois, annee)).fetchone()

                                if not validation or not validation['bloque']:
                                    # Supprimer entrée existante si présente
                                    conn.execute('DELETE FROM heures_reelles WHERE user_id = ? AND date = ?',
                                               (demande['user_id'], date_str))

                                    # Créer la nouvelle entrée de récupération
                                    conn.execute('''
                                        INSERT INTO heures_reelles
                                        (user_id, date, type_saisie, commentaire, declaration_conforme,
                                         heure_debut_matin, heure_fin_matin, heure_debut_aprem, heure_fin_aprem)
                                        VALUES (?, ?, 'recup_journee', ?, 0, NULL, NULL, NULL, NULL)
                                    ''', (demande['user_id'], date_str, f"Récupération - Demande #{demande_id} validée"))

                                    nb_jours_crees += 1

                            jour_actuel += timedelta(days=1)

                        conn.commit()
                        flash(f'Demande validée définitivement - {nb_jours_crees} jour(s) de récupération ajouté(s) automatiquement au calendrier', 'success')

                    # Notification email au salarie (si consentement donne)
                    if is_email_configured():
                        peut, email_sal = peut_envoyer_email(demande['user_id'])
                        if peut:
                            salarie = conn.execute('SELECT prenom FROM users WHERE id = ?',
                                                    (demande['user_id'],)).fetchone()
                            if salarie:
                                notifier_demande_recup_decision(
                                    email_sal, salarie['prenom'], 'validee',
                                    demande['date_debut'], demande['date_fin'],
                                    demande['nb_jours']
                                )
        finally:
            conn.close()
        return redirect(url_for('recup_bp.validation_demandes_recup'))

    # GET : afficher les demandes à valider (récupérations + congés)
    conn = get_db()
    
    if session.get('profil') == 'responsable':
        # Responsable : demandes de son secteur en attente_responsable
        responsable_secteur = conn.execute('SELECT secteur_id FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        
        if responsable_secteur and responsable_secteur['secteur_id']:
            sid = responsable_secteur['secteur_id']
            demandes_recup = conn.execute('''
                SELECT d.*, 'recup' as demande_type,
                       u.nom || ' ' || u.prenom as demandeur_nom,
                       s.nom as secteur_nom
                FROM demandes_recup d
                JOIN users u ON d.user_id = u.id
                LEFT JOIN secteurs s ON u.secteur_id = s.id
                WHERE u.secteur_id = ? AND d.statut = 'en_attente_responsable'
                ORDER BY d.date_demande ASC
            ''', (sid,)).fetchall()
            demandes_conges = conn.execute('''
                SELECT d.*, 'conge' as demande_type,
                       u.nom || ' ' || u.prenom as demandeur_nom,
                       s.nom as secteur_nom
                FROM demandes_conges d
                JOIN users u ON d.user_id = u.id
                LEFT JOIN secteurs s ON u.secteur_id = s.id
                WHERE u.secteur_id = ? AND d.statut = 'en_attente_responsable'
                ORDER BY d.date_demande ASC
            ''', (sid,)).fetchall()
        else:
            demandes_recup = []
            demandes_conges = []
    
    elif session.get('profil') in ['directeur', 'comptable']:
        # Direction : toutes les demandes en attente
        demandes_recup = conn.execute('''
            SELECT d.*, 'recup' as demande_type,
                   u.nom || ' ' || u.prenom as demandeur_nom,
                   s.nom as secteur_nom
            FROM demandes_recup d
            JOIN users u ON d.user_id = u.id
            LEFT JOIN secteurs s ON u.secteur_id = s.id
            WHERE d.statut = 'en_attente_direction' OR d.statut = 'en_attente_responsable'
            ORDER BY d.date_demande ASC
        ''').fetchall()
        demandes_conges = conn.execute('''
            SELECT d.*, 'conge' as demande_type,
                   u.nom || ' ' || u.prenom as demandeur_nom,
                   s.nom as secteur_nom
            FROM demandes_conges d
            JOIN users u ON d.user_id = u.id
            LEFT JOIN secteurs s ON u.secteur_id = s.id
            WHERE d.statut = 'en_attente_direction' OR d.statut = 'en_attente_responsable'
            ORDER BY d.date_demande ASC
        ''').fetchall()
    else:
        demandes_recup = []
        demandes_conges = []
    
    conn.close()
    
    return render_template('validation_demandes_recup.html',
                           demandes_recup=demandes_recup,
                           demandes_conges=demandes_conges)

@recup_bp.route('/historique_demandes_recup')
@login_required
def historique_demandes_recup():
    """Historique de toutes les demandes validées (comptable et direction)"""
    if session.get('profil') not in ['directeur', 'comptable']:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))
    
    conn = get_db()
    
    # Demandes de récupération (validées et refusées)
    demandes_recup = conn.execute('''
        SELECT d.*, 'recup' as demande_type,
               u.nom || ' ' || u.prenom as demandeur_nom,
               s.nom as secteur_nom,
               r.nom || ' ' || r.prenom as refuse_par_nom
        FROM demandes_recup d
        JOIN users u ON d.user_id = u.id
        LEFT JOIN secteurs s ON u.secteur_id = s.id
        LEFT JOIN users r ON d.refuse_par = r.id
        WHERE d.statut IN ('validee', 'refusee')
        ORDER BY d.date_demande DESC
    ''').fetchall()

    # Demandes de congés (validées et refusées)
    demandes_conges = conn.execute('''
        SELECT d.*, 'conge' as demande_type,
               u.nom || ' ' || u.prenom as demandeur_nom,
               s.nom as secteur_nom,
               r.nom || ' ' || r.prenom as refuse_par_nom
        FROM demandes_conges d
        JOIN users u ON d.user_id = u.id
        LEFT JOIN secteurs s ON u.secteur_id = s.id
        LEFT JOIN users r ON d.refuse_par = r.id
        WHERE d.statut IN ('validee', 'refusee')
        ORDER BY d.date_demande DESC
    ''').fetchall()

    demandes = list(demandes_recup) + list(demandes_conges)
    demandes.sort(key=lambda d: d['date_demande'], reverse=True)
    
    # Statistiques
    stats = {
        'total': len(demandes),
        'validees': sum(1 for d in demandes if d['statut'] == 'validee'),
        'refusees': sum(1 for d in demandes if d['statut'] == 'refusee'),
        'total_jours_valides': sum(d['nb_jours'] for d in demandes if d['statut'] == 'validee'),
        'total_heures_valides': sum(_safe_nb_heures(d) for d in demandes if d['statut'] == 'validee')
    }
    
    conn.close()
    
    return render_template('historique_demandes_recup.html', demandes=demandes, stats=stats)


# ==================== DEMANDES DE CONGES ====================

TYPES_CONGE = ['Congé payé', 'Congé conventionnel']


@recup_bp.route('/demande_conge', methods=['GET', 'POST'])
@login_required
def demande_conge():
    """Créer une demande de congé (payé ou conventionnel)"""
    if request.method == 'POST':
        type_conge = request.form.get('type_conge', '').strip()
        date_debut = request.form.get('date_debut')
        date_fin = request.form.get('date_fin')
        motif_demande = request.form.get('motif_demande', '').strip()

        if not type_conge or type_conge not in TYPES_CONGE:
            flash('Type de congé invalide', 'error')
            return redirect(url_for('recup_bp.demande_conge'))

        if not date_debut or not date_fin:
            flash('Les dates sont obligatoires', 'error')
            return redirect(url_for('recup_bp.demande_conge'))

        nb_jours = calculer_jours_ouvres(date_debut, date_fin)

        if nb_jours <= 0:
            flash('Période invalide', 'error')
            return redirect(url_for('recup_bp.demande_conge'))

        conn = get_db()

        # Récupérer le solde de congés
        user_data = conn.execute('SELECT cp_a_prendre, cp_pris, cc_solde FROM users WHERE id = ?',
                                 (session['user_id'],)).fetchone()
        if type_conge == 'Congé payé':
            solde = (user_data['cp_a_prendre'] or 0) - (user_data['cp_pris'] or 0) if user_data else 0
        else:
            solde = user_data['cc_solde'] or 0 if user_data else 0

        # Alerter si solde négatif après la demande
        solde_apres = solde - nb_jours
        if solde_apres < 0:
            flash(f'⚠️ Attention : votre solde passera à {solde_apres:.1f} jour(s) (congé pris par anticipation). '
                  f'Ce congé peut être refusé si les jours en cours d\'acquisition sont insuffisants.', 'warning')

        # Déterminer le statut initial selon le profil
        if session.get('profil') == 'responsable':
            statut_initial = 'en_attente_direction'
        else:
            statut_initial = 'en_attente_responsable'

        try:
            conn.execute('''
                INSERT INTO demandes_conges
                (user_id, type_conge, date_debut, date_fin, nb_jours, motif_demande, statut)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (session['user_id'], type_conge, date_debut, date_fin, nb_jours, motif_demande, statut_initial))
            conn.commit()
            flash(f'Demande de {type_conge.lower()} créée : {nb_jours} jour(s)', 'success')

            # Notification email au responsable (si configuré)
            if is_email_configured() and statut_initial == 'en_attente_responsable':
                demandeur = conn.execute('SELECT nom, prenom, responsable_id FROM users WHERE id = ?',
                                         (session['user_id'],)).fetchone()
                if demandeur and demandeur['responsable_id']:
                    resp = conn.execute('SELECT prenom, email FROM users WHERE id = ?',
                                        (demandeur['responsable_id'],)).fetchone()
                    if resp and resp['email']:
                        demandeur_nom = f"{demandeur['prenom']} {demandeur['nom']}"
                        notifier_nouvelle_demande_recup(
                            demandeur_nom, resp['email'], resp['prenom'],
                            date_debut, date_fin, nb_jours, 0
                        )

            # Si responsable -> notifier directement la direction
            if is_email_configured() and statut_initial == 'en_attente_direction':
                demandeur = conn.execute('SELECT nom, prenom FROM users WHERE id = ?',
                                         (session['user_id'],)).fetchone()
                if demandeur:
                    demandeur_nom = f"{demandeur['prenom']} {demandeur['nom']}"
                    directeurs = conn.execute(
                        "SELECT prenom, email FROM users WHERE profil = 'directeur' AND actif = 1 AND email IS NOT NULL AND email != ''",
                    ).fetchall()
                    for d in directeurs:
                        notifier_demande_recup_validee_responsable(
                            d['email'], d['prenom'], demandeur_nom, demandeur_nom,
                            date_debut, date_fin, nb_jours
                        )

        except Exception as e:
            flash(f'Erreur : {str(e)}', 'error')
        finally:
            conn.close()

        return redirect(url_for('recup_bp.mes_demandes_conges'))

    # GET : afficher le formulaire
    conn = get_db()
    user_data = conn.execute('SELECT cp_a_prendre, cp_pris, cc_solde FROM users WHERE id = ?',
                             (session['user_id'],)).fetchone()
    solde_cp = (user_data['cp_a_prendre'] or 0) - (user_data['cp_pris'] or 0) if user_data else 0
    solde_cc = user_data['cc_solde'] or 0 if user_data else 0
    conn.close()

    return render_template('demande_conge.html',
                           types_conge=TYPES_CONGE,
                           solde_cp=solde_cp,
                           solde_cc=solde_cc)


@recup_bp.route('/mes_demandes_conges')
@login_required
def mes_demandes_conges():
    """Liste des demandes de congé du salarié"""
    conn = get_db()

    demandes = conn.execute('''
        SELECT d.*,
               u.nom || ' ' || u.prenom as demandeur_nom
        FROM demandes_conges d
        JOIN users u ON d.user_id = u.id
        WHERE d.user_id = ?
        ORDER BY d.date_demande DESC
    ''', (session['user_id'],)).fetchall()

    conn.close()

    return render_template('mes_demandes_conges.html', demandes=demandes)


# ==================== FORFAIT JOUR (DIRECTEURS) ====================
