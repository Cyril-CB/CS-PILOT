"""
Blueprint suivi_bp.
"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from datetime import datetime
import json
from database import get_db
from utils import login_required

suivi_bp = Blueprint('suivi_bp', __name__)


@suivi_bp.route('/historique_modifications')
@login_required
def historique_modifications():
    """Historique des modifications (directeur uniquement)"""
    if session.get('profil') != 'directeur':
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))
    
    # Filtres optionnels
    user_id_filtre = request.args.get('user_id', type=int)
    date_debut = request.args.get('date_debut')
    date_fin = request.args.get('date_fin')
    
    conn = get_db()
    
    # Construire la requête avec filtres
    query = '''
        SELECT h.*,
               u_modifie.nom || ' ' || u_modifie.prenom as nom_modifie,
               u_par.nom || ' ' || u_par.prenom as nom_modificateur
        FROM historique_modifications h
        JOIN users u_modifie ON h.user_id_modifie = u_modifie.id
        JOIN users u_par ON h.modifie_par = u_par.id
        WHERE 1=1
    '''
    params = []
    
    if user_id_filtre:
        query += ' AND h.user_id_modifie = %s'
        params.append(user_id_filtre)
    
    if date_debut:
        query += ' AND h.date_concernee >= %s'
        params.append(date_debut)
    
    if date_fin:
        query += ' AND h.date_concernee <= %s'
        params.append(date_fin)
    
    query += ' ORDER BY h.date_modification DESC LIMIT 200'
    
    modifications = conn.execute(query, params).fetchall()
    
    # Récupérer la liste des utilisateurs pour le filtre
    users = conn.execute('''
        SELECT id, nom, prenom FROM users 
        WHERE actif = 1 AND profil NOT IN ('directeur', 'prestataire')
        ORDER BY nom, prenom
    ''').fetchall()
    
    conn.close()
    
    # Convertir les modifications en dictionnaires avec parsing JSON
    modifications_list = []
    for m in modifications:
        mod_dict = dict(m)
        if mod_dict['anciennes_valeurs']:
            mod_dict['anciennes_valeurs_obj'] = json.loads(mod_dict['anciennes_valeurs'])
        else:
            mod_dict['anciennes_valeurs_obj'] = None
        
        if mod_dict['nouvelles_valeurs']:
            mod_dict['nouvelles_valeurs_obj'] = json.loads(mod_dict['nouvelles_valeurs'])
        else:
            mod_dict['nouvelles_valeurs_obj'] = None
        
        modifications_list.append(mod_dict)
    
    return render_template('historique_modifications.html',
                         modifications=modifications_list,
                         users=users,
                         user_id_filtre=user_id_filtre,
                         date_debut=date_debut,
                         date_fin=date_fin)

@suivi_bp.route('/suivi_anomalies', methods=['GET', 'POST'])
@login_required
def suivi_anomalies():
    """Suivi des anomalies et modifications suspectes (direction uniquement)"""
    if session.get('profil') not in ['directeur', 'comptable']:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))
    
    conn = get_db()
    
    # POST : Marquer une anomalie comme traitée
    if request.method == 'POST':
        anomalie_id = request.form.get('anomalie_id', type=int)
        action = request.form.get('action')
        
        if anomalie_id and action == 'traiter':
            conn.execute('UPDATE anomalies SET traitee = 1 WHERE id = %s', (anomalie_id,))
            conn.commit()
            flash('Anomalie marquée comme traitée', 'success')
        
        conn.close()
        return redirect(url_for('suivi_bp.suivi_anomalies'))
    
    # GET : Afficher les anomalies
    gravite_filtre = request.args.get('gravite', 'toutes')
    afficher_traitees = request.args.get('traitees', '0') == '1'
    
    # Construire la requête
    query = '''
        SELECT a.*,
               u.nom || ' ' || u.prenom as nom_salarie,
               u.profil
        FROM anomalies a
        JOIN users u ON a.user_id = u.id
        WHERE 1=1
    '''
    params = []
    
    if not afficher_traitees:
        query += ' AND a.traitee = 0'
    
    if gravite_filtre != 'toutes':
        query += ' AND a.gravite = %s'
        params.append(gravite_filtre)
    
    query += ' ORDER BY a.date_modification DESC, a.gravite ASC LIMIT 500'
    
    anomalies = conn.execute(query, params).fetchall()
    
    # Statistiques
    stats = conn.execute('''
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN gravite = 'critique' THEN 1 ELSE 0 END) as critiques,
            SUM(CASE WHEN gravite = 'alerte' THEN 1 ELSE 0 END) as alertes,
            SUM(CASE WHEN gravite = 'suspect' THEN 1 ELSE 0 END) as suspects,
            SUM(CASE WHEN traitee = 0 THEN 1 ELSE 0 END) as non_traitees
        FROM anomalies
    ''').fetchone()
    
    conn.close()
    
    # Parser les anciennes/nouvelles valeurs JSON
    anomalies_list = []
    for a in anomalies:
        anom_dict = dict(a)
        if anom_dict['ancienne_valeur']:
            try:
                anom_dict['ancienne_valeur_obj'] = json.loads(anom_dict['ancienne_valeur'])
            except (ValueError, json.JSONDecodeError):
                anom_dict['ancienne_valeur_obj'] = None
        else:
            anom_dict['ancienne_valeur_obj'] = None
        
        if anom_dict['nouvelle_valeur']:
            try:
                anom_dict['nouvelle_valeur_obj'] = json.loads(anom_dict['nouvelle_valeur'])
            except (ValueError, json.JSONDecodeError):
                anom_dict['nouvelle_valeur_obj'] = None
        else:
            anom_dict['nouvelle_valeur_obj'] = None
        
        anomalies_list.append(anom_dict)
    
    return render_template('suivi_anomalies.html',
                         anomalies=anomalies_list,
                         stats=dict(stats) if stats else {},
                         gravite_filtre=gravite_filtre,
                         afficher_traitees=afficher_traitees)
