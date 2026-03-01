"""
Blueprint planning_bp.
"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from datetime import datetime
from database import get_db
from utils import login_required, calculer_heures, get_semaine_alternance

planning_bp = Blueprint('planning_bp', __name__)


@planning_bp.route('/planning_theorique', methods=['GET', 'POST'])
@login_required
def planning_theorique():
    """Gestion du planning théorique avec historisation et alternance"""
    if request.method == 'POST':
        type_periode = request.form.get('type_periode')
        date_debut_validite = request.form.get('date_debut_validite')
        type_alternance = request.form.get('type_alternance', 'fixe')
        date_reference = request.form.get('date_reference')
        
        if not date_debut_validite:
            flash('Vous devez spécifier une date de début de validité', 'error')
            return redirect(url_for('planning_bp.planning_theorique'))
        
        # Vérifier la cohérence alternance
        if type_alternance in ['semaine_1', 'semaine_2'] and not date_reference:
            flash('Vous devez spécifier une date de référence pour l\'alternance', 'error')
            return redirect(url_for('planning_bp.planning_theorique'))
        
        # Vérifier que la date de référence est un lundi
        if date_reference:
            date_ref_obj = datetime.strptime(date_reference, '%Y-%m-%d')
            if date_ref_obj.weekday() != 0:  # 0 = lundi
                flash('⚠️ La date de référence doit être un lundi', 'error')
                return redirect(url_for('planning_bp.planning_theorique'))
        
        # Vérifier si date dans le passé → warning
        date_validite_obj = datetime.strptime(date_debut_validite, '%Y-%m-%d')
        aujourdhui = datetime.now().date()
        
        if date_validite_obj.date() < aujourdhui:
            # Vérifier s'il y a des heures saisies après cette date
            conn = get_db()
            heures_apres = conn.execute('''
                SELECT COUNT(*) as nb FROM heures_reelles 
                WHERE user_id = ? AND date >= ?
            ''', (session['user_id'], date_debut_validite)).fetchone()
            
            if heures_apres and heures_apres['nb'] > 0:
                flash(f'⚠️ ATTENTION : {heures_apres["nb"]} jour(s) avec des heures saisies après le {date_debut_validite}. Les calculs de solde seront recalculés avec ce nouveau planning !', 'warning')
            conn.close()
        
        # Récupérer tous les horaires des 5 jours
        jours = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi']
        horaires = {}
        total_hebdo = 0
        
        for jour in jours:
            matin_debut = request.form.get(f'{jour}_matin_debut') or None
            matin_fin = request.form.get(f'{jour}_matin_fin') or None
            aprem_debut = request.form.get(f'{jour}_aprem_debut') or None
            aprem_fin = request.form.get(f'{jour}_aprem_fin') or None
            
            horaires[f'{jour}_matin_debut'] = matin_debut
            horaires[f'{jour}_matin_fin'] = matin_fin
            horaires[f'{jour}_aprem_debut'] = aprem_debut
            horaires[f'{jour}_aprem_fin'] = aprem_fin
            
            # Calculer les heures du jour
            if matin_debut and matin_fin:
                total_hebdo += calculer_heures(matin_debut, matin_fin)
            if aprem_debut and aprem_fin:
                total_hebdo += calculer_heures(aprem_debut, aprem_fin)
        
        conn = get_db()
        try:
            # CRÉER un nouveau planning (historisation) avec type_alternance
            conn.execute('''
                INSERT INTO planning_theorique
                (user_id, type_periode, date_debut_validite, type_alternance,
                 lundi_matin_debut, lundi_matin_fin, lundi_aprem_debut, lundi_aprem_fin,
                 mardi_matin_debut, mardi_matin_fin, mardi_aprem_debut, mardi_aprem_fin,
                 mercredi_matin_debut, mercredi_matin_fin, mercredi_aprem_debut, mercredi_aprem_fin,
                 jeudi_matin_debut, jeudi_matin_fin, jeudi_aprem_debut, jeudi_aprem_fin,
                 vendredi_matin_debut, vendredi_matin_fin, vendredi_aprem_debut, vendredi_aprem_fin,
                 total_hebdo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (session['user_id'], type_periode, date_debut_validite, type_alternance,
                  horaires['lundi_matin_debut'], horaires['lundi_matin_fin'], 
                  horaires['lundi_aprem_debut'], horaires['lundi_aprem_fin'],
                  horaires['mardi_matin_debut'], horaires['mardi_matin_fin'],
                  horaires['mardi_aprem_debut'], horaires['mardi_aprem_fin'],
                  horaires['mercredi_matin_debut'], horaires['mercredi_matin_fin'],
                  horaires['mercredi_aprem_debut'], horaires['mercredi_aprem_fin'],
                  horaires['jeudi_matin_debut'], horaires['jeudi_matin_fin'],
                  horaires['jeudi_aprem_debut'], horaires['jeudi_aprem_fin'],
                  horaires['vendredi_matin_debut'], horaires['vendredi_matin_fin'],
                  horaires['vendredi_aprem_debut'], horaires['vendredi_aprem_fin'],
                  total_hebdo))
            
            # Si alternance, enregistrer la date de référence
            if type_alternance in ['semaine_1', 'semaine_2'] and date_reference:
                # Vérifier si on a déjà une référence pour cette date
                ref_existante = conn.execute('''
                    SELECT id FROM alternance_reference
                    WHERE user_id = ? AND date_debut_validite = ?
                ''', (session['user_id'], date_debut_validite)).fetchone()
                
                if not ref_existante:
                    conn.execute('''
                        INSERT INTO alternance_reference (user_id, date_reference, date_debut_validite)
                        VALUES (?, ?, ?)
                    ''', (session['user_id'], date_reference, date_debut_validite))
            
            conn.commit()
            
            if type_alternance == 'fixe':
                flash(f'✅ Nouveau planning {type_periode} créé ({total_hebdo:.2f}h/semaine), valable à partir du {date_debut_validite}', 'success')
            else:
                flash(f'✅ Planning {type_alternance} - {type_periode} créé ({total_hebdo:.2f}h/semaine), valable à partir du {date_debut_validite}', 'success')
        except Exception as e:
            flash(f'Erreur: {str(e)}', 'error')
        finally:
            conn.close()
        
        return redirect(url_for('planning_bp.planning_theorique'))
    
    # GET: afficher tous les plannings (historique complet) + infos alternance
    conn = get_db()
    plannings = conn.execute('''
        SELECT * FROM planning_theorique 
        WHERE user_id = ?
        ORDER BY type_alternance, type_periode, date_debut_validite DESC
    ''', (session['user_id'],)).fetchall()
    
    # Récupérer les dates de référence alternance
    references = conn.execute('''
        SELECT * FROM alternance_reference
        WHERE user_id = ?
        ORDER BY date_debut_validite DESC
    ''', (session['user_id'],)).fetchall()
    
    # Calculer la semaine actuelle si alternance configurée
    semaine_actuelle = None
    if references:
        semaine_actuelle = get_semaine_alternance(session['user_id'], datetime.now().strftime('%Y-%m-%d'))
    
    conn.close()
    
    return render_template('planning_theorique.html', 
                         plannings=plannings,
                         references=references,
                         semaine_actuelle=semaine_actuelle,
                         date_actuelle=datetime.now().strftime('%Y-%m-%d'))
