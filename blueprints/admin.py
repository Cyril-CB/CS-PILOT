"""
Blueprint admin_bp.
"""
import sqlite3
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash
from datetime import datetime
from database import get_db
from utils import login_required, validate_password_strength

admin_bp = Blueprint('admin_bp', __name__)


@admin_bp.route('/gestion_users')
@login_required
def gestion_users():
    """Gestion des utilisateurs (directeur et comptable)"""
    if session.get('profil') not in ['directeur', 'comptable']:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))
    
    conn = get_db()
    
    # Récupérer tous les utilisateurs avec leurs informations complètes
    users = conn.execute('''
        SELECT 
            u.id, u.nom, u.prenom, u.login, u.profil, u.actif,
            s.nom as secteur_nom,
            r.nom || ' ' || r.prenom as responsable_nom
        FROM users u
        LEFT JOIN secteurs s ON u.secteur_id = s.id
        LEFT JOIN users r ON u.responsable_id = r.id
        ORDER BY u.profil, u.nom, u.prenom
    ''').fetchall()
    
    # Récupérer les secteurs
    secteurs = conn.execute('SELECT * FROM secteurs ORDER BY nom').fetchall()
    
    conn.close()
    
    return render_template('gestion_users.html', users=users, secteurs=secteurs)

@admin_bp.route('/creer_user', methods=['GET', 'POST'])
@login_required
def creer_user():
    """Créer un nouvel utilisateur (directeur et comptable)"""
    if session.get('profil') not in ['directeur', 'comptable']:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))
    
    conn = get_db()

    try:
        if request.method == 'POST':
            nom = request.form.get('nom')
            prenom = request.form.get('prenom')
            login = request.form.get('login')
            password = request.form.get('password')
            profil = request.form.get('profil')
            secteur_id = request.form.get('secteur_id') or None
            responsable_id = request.form.get('responsable_id') or None
            solde_initial = request.form.get('solde_initial', type=float) or 0
            date_entree = request.form.get('date_entree') or None

            # Compteurs conges payes
            cp_acquis = request.form.get('cp_acquis', type=float) or 0
            cp_a_prendre = request.form.get('cp_a_prendre', type=float) or 0
            cp_pris = request.form.get('cp_pris', type=float) or 0
            # Compteur conges conventionnels
            cc_solde = request.form.get('cc_solde', type=float) or 0

            # Validation de la complexité du mot de passe
            password_errors = validate_password_strength(password)
            if password_errors:
                for err in password_errors:
                    flash(err, 'error')
                secteurs = conn.execute('SELECT * FROM secteurs ORDER BY nom').fetchall()
                responsables = conn.execute('''
                    SELECT id, nom, prenom FROM users
                    WHERE profil IN ('directeur', 'responsable') AND actif = 1
                    ORDER BY nom, prenom
                ''').fetchall()
                return render_template('creer_user.html', secteurs=secteurs, responsables=responsables)

            # Hasher le mot de passe
            password_hash = generate_password_hash(password)

            try:
                conn.execute('''
                    INSERT INTO users (nom, prenom, login, password, profil, secteur_id, responsable_id,
                                       solde_initial, date_entree, cp_acquis, cp_a_prendre, cp_pris, cc_solde)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (nom, prenom, login, password_hash, profil, secteur_id, responsable_id,
                      solde_initial, date_entree, cp_acquis, cp_a_prendre, cp_pris, cc_solde))
                conn.commit()
                flash(f'Utilisateur {prenom} {nom} créé avec succès', 'success')
                return redirect(url_for('admin_bp.gestion_users'))
            except Exception as e:
                flash(f'Erreur: {str(e)}', 'error')

        # Récupérer les secteurs et responsables pour les listes déroulantes
        secteurs = conn.execute('SELECT * FROM secteurs ORDER BY nom').fetchall()
        responsables = conn.execute('''
            SELECT id, nom, prenom FROM users
            WHERE profil IN ('directeur', 'responsable') AND actif = 1
            ORDER BY nom, prenom
        ''').fetchall()

        return render_template('creer_user.html', secteurs=secteurs, responsables=responsables)
    finally:
        conn.close()

@admin_bp.route('/modifier_user/<int:user_id>', methods=['GET', 'POST'])
@login_required
def modifier_user(user_id):
    """Modifier un utilisateur existant (directeur et comptable)"""
    if session.get('profil') not in ['directeur', 'comptable']:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))
    
    conn = get_db()

    try:
        if request.method == 'POST':
            nom = request.form.get('nom')
            prenom = request.form.get('prenom')
            login = request.form.get('login')
            profil = request.form.get('profil')
            secteur_id = request.form.get('secteur_id') or None
            responsable_id = request.form.get('responsable_id') or None
            nouveau_password = request.form.get('nouveau_password')
            solde_initial = request.form.get('solde_initial', type=float) or 0
            date_entree = request.form.get('date_entree') or None

            # Compteurs conges payes
            cp_acquis = request.form.get('cp_acquis', type=float) or 0
            cp_a_prendre = request.form.get('cp_a_prendre', type=float) or 0
            cp_pris = request.form.get('cp_pris', type=float) or 0
            # Compteur conges conventionnels
            cc_solde = request.form.get('cc_solde', type=float) or 0

            # Validation de la complexité du nouveau mot de passe
            if nouveau_password:
                password_errors = validate_password_strength(nouveau_password)
                if password_errors:
                    for err in password_errors:
                        flash(err, 'error')
                    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
                    secteurs = conn.execute('SELECT * FROM secteurs ORDER BY nom').fetchall()
                    responsables = conn.execute('''
                        SELECT id, nom, prenom FROM users
                        WHERE profil IN ('directeur', 'responsable') AND actif = 1 AND id != ?
                        ORDER BY nom, prenom
                    ''', (user_id,)).fetchall()
                    return render_template('modifier_user.html', user=dict(user), secteurs=secteurs, responsables=responsables)

            try:
                # Si nouveau mot de passe fourni, le hasher
                if nouveau_password:
                    password_hash = generate_password_hash(nouveau_password)
                    conn.execute('''
                        UPDATE users
                        SET nom=?, prenom=?, login=?, password=?, profil=?, secteur_id=?, responsable_id=?,
                            solde_initial=?, date_entree=?, cp_acquis=?, cp_a_prendre=?, cp_pris=?, cc_solde=?
                        WHERE id=?
                    ''', (nom, prenom, login, password_hash, profil, secteur_id, responsable_id,
                          solde_initial, date_entree, cp_acquis, cp_a_prendre, cp_pris, cc_solde, user_id))
                else:
                    conn.execute('''
                        UPDATE users
                        SET nom=?, prenom=?, login=?, profil=?, secteur_id=?, responsable_id=?,
                            solde_initial=?, date_entree=?, cp_acquis=?, cp_a_prendre=?, cp_pris=?, cc_solde=?
                        WHERE id=?
                    ''', (nom, prenom, login, profil, secteur_id, responsable_id,
                          solde_initial, date_entree, cp_acquis, cp_a_prendre, cp_pris, cc_solde, user_id))

                conn.commit()
                flash(f'Utilisateur {prenom} {nom} modifié avec succès', 'success')
                return redirect(url_for('admin_bp.gestion_users'))
            except Exception as e:
                flash(f'Erreur: {str(e)}', 'error')

        # Récupérer l'utilisateur
        user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        if not user:
            flash('Utilisateur introuvable', 'error')
            return redirect(url_for('admin_bp.gestion_users'))

        # Récupérer les secteurs et responsables
        secteurs = conn.execute('SELECT * FROM secteurs ORDER BY nom').fetchall()
        responsables = conn.execute('''
            SELECT id, nom, prenom FROM users
            WHERE profil IN ('directeur', 'responsable') AND actif = 1 AND id != ?
            ORDER BY nom, prenom
        ''', (user_id,)).fetchall()

        return render_template('modifier_user.html', user=dict(user), secteurs=secteurs, responsables=responsables)
    finally:
        conn.close()

@admin_bp.route('/toggle_user/<int:user_id>', methods=['POST'])
@login_required
def toggle_user(user_id):
    """Activer/Désactiver un utilisateur (directeur et comptable)"""
    if session.get('profil') not in ['directeur', 'comptable']:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    try:
        user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

        if user:
            nouveau_statut = 0 if user['actif'] == 1 else 1
            conn.execute('UPDATE users SET actif = ? WHERE id = ?', (nouveau_statut, user_id))
            conn.commit()
            statut_texte = 'activé' if nouveau_statut == 1 else 'désactivé'
            flash(f'Utilisateur {user["prenom"]} {user["nom"]} {statut_texte}', 'success')
    finally:
        conn.close()
    return redirect(url_for('admin_bp.gestion_users'))

@admin_bp.route('/gestion_secteurs', methods=['GET', 'POST'])
@login_required
def gestion_secteurs():
    """Gestion des secteurs (directeur et comptable)"""
    if session.get('profil') not in ['directeur', 'comptable']:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))
    
    conn = get_db()

    try:
        if request.method == 'POST':
            action = request.form.get('action')

            if action == 'ajouter':
                nom = request.form.get('nom')
                description = request.form.get('description')
                type_secteur = request.form.get('type_secteur') or None

                try:
                    conn.execute('''
                        INSERT INTO secteurs (nom, description, type_secteur)
                        VALUES (?, ?, ?)
                    ''', (nom, description, type_secteur))
                    conn.commit()
                    flash(f'Secteur "{nom}" créé avec succès', 'success')
                except Exception as e:
                    flash(f'Erreur: {str(e)}', 'error')

            elif action == 'modifier':
                secteur_id = request.form.get('secteur_id')
                nom = request.form.get('nom')
                description = request.form.get('description')
                type_secteur = request.form.get('type_secteur') or None

                if not nom:
                    flash('Le nom du secteur est requis', 'error')
                else:
                    try:
                        conn.execute('''
                            UPDATE secteurs SET nom = ?, description = ?, type_secteur = ?
                            WHERE id = ?
                        ''', (nom, description, type_secteur, secteur_id))
                        conn.commit()
                        flash(f'Secteur "{nom}" modifié avec succès', 'success')
                    except Exception as e:
                        flash(f'Erreur: {str(e)}', 'error')

            elif action == 'supprimer':
                secteur_id = request.form.get('secteur_id')
                users_count = conn.execute(
                    'SELECT COUNT(*) as count FROM users WHERE secteur_id = ?',
                    (secteur_id,)
                ).fetchone()['count']

                if users_count > 0:
                    flash(f'Impossible de supprimer : {users_count} utilisateur(s) sont dans ce secteur', 'error')
                else:
                    conn.execute('DELETE FROM secteurs WHERE id = ?', (secteur_id,))
                    conn.commit()
                    flash('Secteur supprimé avec succès', 'success')

        secteurs = conn.execute('''
            SELECT s.*, COUNT(u.id) as nb_users
            FROM secteurs s
            LEFT JOIN users u ON s.id = u.secteur_id
            GROUP BY s.id
            ORDER BY s.nom
        ''').fetchall()

        return render_template('gestion_secteurs.html', secteurs=secteurs)
    finally:
        conn.close()

@admin_bp.route('/gestion_vacances', methods=['GET', 'POST'])
@login_required
def gestion_vacances():
    """Gestion des périodes de vacances scolaires (directeur et comptable)"""
    if session.get('profil') not in ['directeur', 'comptable']:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))
    
    conn = get_db()

    try:
        if request.method == 'POST':
            action = request.form.get('action')

            if action == 'ajouter':
                nom = request.form.get('nom')
                date_debut = request.form.get('date_debut')
                date_fin = request.form.get('date_fin')

                # Validation des dates
                if date_debut > date_fin:
                    flash('La date de fin doit être après la date de début', 'error')
                else:
                    try:
                        conn.execute('''
                            INSERT INTO periodes_vacances (nom, date_debut, date_fin, created_by)
                            VALUES (?, ?, ?, ?)
                        ''', (nom, date_debut, date_fin, session['user_id']))
                        conn.commit()
                        flash(f'Période "{nom}" ajoutée avec succès', 'success')
                    except Exception as e:
                        flash(f'Erreur: {str(e)}', 'error')

            elif action == 'supprimer':
                periode_id = request.form.get('periode_id')
                try:
                    conn.execute('DELETE FROM periodes_vacances WHERE id = ?', (periode_id,))
                    conn.commit()
                    flash('Période supprimée avec succès', 'success')
                except Exception as e:
                    flash(f'Erreur: {str(e)}', 'error')

        # Récupérer toutes les périodes
        periodes = conn.execute('''
            SELECT * FROM periodes_vacances ORDER BY date_debut
        ''').fetchall()

        return render_template('gestion_vacances.html', periodes=periodes)
    finally:
        conn.close()

@admin_bp.route('/gestion_jours_feries', methods=['GET', 'POST'])
@login_required
def gestion_jours_feries():
    """Gestion des jours fériés (directeur/comptable)"""
    if session.get('profil') not in ['directeur', 'comptable']:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'ajouter':
            date = request.form.get('date')
            libelle = request.form.get('libelle')
            
            if not date or not libelle:
                flash('Date et libellé obligatoires', 'error')
                return redirect(url_for('admin_bp.gestion_jours_feries'))
            
            annee = int(date[:4])
            
            conn = get_db()
            try:
                conn.execute('''
                    INSERT INTO jours_feries (annee, date, libelle)
                    VALUES (?, ?, ?)
                ''', (annee, date, libelle))
                conn.commit()
                flash(f'Jour férié ajouté : {libelle}', 'success')
            except sqlite3.IntegrityError:
                flash('Ce jour férié existe déjà', 'error')
            finally:
                conn.close()
        
        elif action == 'supprimer':
            ferie_id = request.form.get('ferie_id', type=int)
            conn = get_db()
            conn.execute('DELETE FROM jours_feries WHERE id = ?', (ferie_id,))
            conn.commit()
            conn.close()
            flash('Jour férié supprimé', 'success')
        
        return redirect(url_for('admin_bp.gestion_jours_feries'))
    
    # GET : afficher la liste
    conn = get_db()
    annee_actuelle = datetime.now().year
    
    jours_feries_raw = conn.execute('''
        SELECT * FROM jours_feries 
        WHERE annee >= ?
        ORDER BY date
    ''', (annee_actuelle,)).fetchall()
    
    # Enrichir avec le jour de la semaine
    jours_semaine = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']
    jours_feries = []
    for f in jours_feries_raw:
        date_obj = datetime.strptime(f['date'], '%Y-%m-%d')
        ferie_dict = dict(f)
        ferie_dict['jour_semaine'] = jours_semaine[date_obj.weekday()]
        jours_feries.append(ferie_dict)
    
    conn.close()
    
    return render_template('gestion_jours_feries.html', jours_feries=jours_feries)
