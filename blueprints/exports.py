"""
Blueprint exports_bp.
"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, make_response
from datetime import datetime, timedelta
from io import BytesIO
from database import get_db
from utils import (login_required, get_user_info, calculer_heures,
                   get_heures_theoriques_jour, get_type_periode, get_planning_valide_a_date, NOMS_MOIS)

exports_bp = Blueprint('exports_bp', __name__)


@exports_bp.route('/export_pdf_mensuel')
@login_required
def export_pdf_mensuel():
    """Export PDF de la fiche mensuelle (uniquement si verrouillée)"""
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, KeepTogether
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER

    user_id_param = request.args.get('user_id', type=int)
    mois = request.args.get('mois', type=int)
    annee = request.args.get('annee', type=int)
    
    if not user_id_param or not mois or not annee:
        flash('Paramètres manquants', 'error')
        return redirect(url_for('validation_bp.vue_mensuelle'))
    
    conn = get_db()
    
    # Vérifier que la fiche est verrouillée
    validation = conn.execute('''
        SELECT * FROM validations 
        WHERE user_id = ? AND mois = ? AND annee = ?
    ''', (user_id_param, mois, annee)).fetchone()
    
    if not validation or not validation['bloque']:
        flash('Le PDF n\'est disponible qu\'après verrouillage complet de la fiche', 'error')
        conn.close()
        return redirect(url_for('validation_bp.vue_mensuelle', user_id=user_id_param, mois=mois, annee=annee))
    
    # Récupérer les infos de l'utilisateur
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id_param,)).fetchone()
    if not user:
        flash('Utilisateur introuvable', 'error')
        conn.close()
        return redirect(url_for('validation_bp.vue_mensuelle'))
    
    # Récupérer les données du mois (même logique que vue_mensuelle)
    premier_jour = datetime(annee, mois, 1)
    if mois == 12:
        dernier_jour = datetime(annee + 1, 1, 1) - timedelta(days=1)
    else:
        dernier_jour = datetime(annee, mois + 1, 1) - timedelta(days=1)
    
    # Récupérer les heures réelles
    heures_reelles = {}
    heures_rows = conn.execute('''
        SELECT * FROM heures_reelles
        WHERE user_id = ? AND date >= ? AND date <= ?
    ''', (user_id_param, premier_jour.strftime('%Y-%m-%d'), dernier_jour.strftime('%Y-%m-%d'))).fetchall()
    
    for h in heures_rows:
        heures_reelles[h['date']] = dict(h)
    
    # Générer les journées
    journees = []
    jour_actuel = premier_jour
    total_heures_theoriques = 0
    total_heures_reelles = 0
    
    while jour_actuel <= dernier_jour:
        date_str = jour_actuel.strftime('%Y-%m-%d')
        jour_semaine = jour_actuel.weekday()
        
        if jour_semaine < 6:
            if jour_semaine == 5 and date_str not in heures_reelles:
                jour_actuel += timedelta(days=1)
                continue
            
            type_periode = get_type_periode(date_str)
            
            # Récupérer le planning valide à cette date (gère historisation + alternance)
            planning = get_planning_valide_a_date(user_id_param, type_periode, date_str)
            
            # Horaires théoriques
            noms_jours_minuscule = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi']
            jour_nom = noms_jours_minuscule[jour_semaine] if jour_semaine < 5 else None
            
            horaires_theo_str = ""
            heures_theo_jour = 0
            
            if jour_semaine == 5:
                horaires_theo_str = "Samedi"
                heures_theo_jour = 0
            elif planning and jour_nom:
                # Convertir Row en dict pour utiliser .get()
                planning_dict = dict(planning)
                matin_debut = planning_dict.get(f'{jour_nom}_matin_debut')
                matin_fin = planning_dict.get(f'{jour_nom}_matin_fin')
                aprem_debut = planning_dict.get(f'{jour_nom}_aprem_debut')
                aprem_fin = planning_dict.get(f'{jour_nom}_aprem_fin')
                
                # Formater les horaires théoriques
                horaires_parts = []
                if matin_debut and matin_fin:
                    horaires_parts.append(f"{matin_debut}-{matin_fin}")
                    heures_theo_jour += calculer_heures(matin_debut, matin_fin)
                if aprem_debut and aprem_fin:
                    horaires_parts.append(f"{aprem_debut}-{aprem_fin}")
                    heures_theo_jour += calculer_heures(aprem_debut, aprem_fin)
                
                if horaires_parts:
                    horaires_theo_str = " / ".join(horaires_parts)
                else:
                    horaires_theo_str = "Repos"
            else:
                horaires_theo_str = "Non défini"
            
            # Horaires réels
            horaires_reels_str = ""
            heures_reelles_jour = 0
            type_saisie = ""
            
            if date_str in heures_reelles:
                h = heures_reelles[date_str]
                type_saisie = h.get('type_saisie', '')
                
                if type_saisie == 'recup_journee':
                    horaires_reels_str = "🏖️ Récupération"
                    heures_reelles_jour = 0
                elif h.get('declaration_conforme'):
                    horaires_reels_str = "✓ Conforme"
                    heures_reelles_jour = heures_theo_jour
                else:
                    # Horaires saisis manuellement
                    horaires_parts_reelles = []
                    if h['heure_debut_matin'] and h['heure_fin_matin']:
                        horaires_parts_reelles.append(f"{h['heure_debut_matin']}-{h['heure_fin_matin']}")
                        heures_reelles_jour += calculer_heures(h['heure_debut_matin'], h['heure_fin_matin'])
                    if h['heure_debut_aprem'] and h['heure_fin_aprem']:
                        horaires_parts_reelles.append(f"{h['heure_debut_aprem']}-{h['heure_fin_aprem']}")
                        heures_reelles_jour += calculer_heures(h['heure_debut_aprem'], h['heure_fin_aprem'])
                    
                    if horaires_parts_reelles:
                        horaires_reels_str = " / ".join(horaires_parts_reelles)
                    else:
                        horaires_reels_str = "Non saisi"
            else:
                # Pas de saisie = considéré conforme
                horaires_reels_str = "✓ Conforme"
                heures_reelles_jour = heures_theo_jour
            
            ecart = heures_reelles_jour - heures_theo_jour
            
            total_heures_theoriques += heures_theo_jour
            total_heures_reelles += heures_reelles_jour
            
            noms_jours = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi']
            
            journees.append({
                'date': jour_actuel.strftime('%d/%m/%Y'),
                'jour': noms_jours[jour_semaine],
                'horaires_theo': horaires_theo_str,
                'heures_theo': heures_theo_jour,
                'horaires_reels': horaires_reels_str,
                'heures_reelles': heures_reelles_jour,
                'ecart': ecart
            })
        
        jour_actuel += timedelta(days=1)
    
    solde_mois = total_heures_reelles - total_heures_theoriques
    
    # Calculer solde antérieur
    solde_anterieur = 0
    heures_anterieures = conn.execute('''
        SELECT date, heure_debut_matin, heure_fin_matin,
               heure_debut_aprem, heure_fin_aprem, declaration_conforme, type_saisie
        FROM heures_reelles 
        WHERE user_id = ? AND date < ?
        ORDER BY date
    ''', (user_id_param, premier_jour.strftime('%Y-%m-%d'))).fetchall()
    
    for h in heures_anterieures:
        date_obj_ant_pdf = datetime.strptime(h['date'], '%Y-%m-%d')
        jour_semaine_ant_pdf = date_obj_ant_pdf.weekday()
        
        # Ignorer weekends
        if jour_semaine_ant_pdf >= 5:
            continue
        
        type_periode = get_type_periode(h['date'])
        
        # Récupérer le planning valide à cette date (gère historisation + alternance)
        planning_ant = get_planning_valide_a_date(user_id_param, type_periode, h['date'])
        
        total_theorique = 0
        if planning_ant:
            # Convertir Row en dict
            planning_ant_dict = dict(planning_ant)
            noms_jours_minuscule = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi']
            jour_nom = noms_jours_minuscule[jour_semaine_ant_pdf]
            
            matin_debut = planning_ant_dict.get(f'{jour_nom}_matin_debut')
            matin_fin = planning_ant_dict.get(f'{jour_nom}_matin_fin')
            aprem_debut = planning_ant_dict.get(f'{jour_nom}_aprem_debut')
            aprem_fin = planning_ant_dict.get(f'{jour_nom}_aprem_fin')
            
            if matin_debut and matin_fin:
                total_theorique += calculer_heures(matin_debut, matin_fin)
            if aprem_debut and aprem_fin:
                total_theorique += calculer_heures(aprem_debut, aprem_fin)
        
        # Calculer les heures réelles
        if h.get('type_saisie') == 'recup_journee':
            # Récupération = 0h réelles
            total_reel = 0
        elif h['declaration_conforme']:
            # Déclaration conforme = heures théoriques
            total_reel = total_theorique
        else:
            # Saisie manuelle
            heures_matin = calculer_heures(h['heure_debut_matin'], h['heure_fin_matin'])
            heures_aprem = calculer_heures(h['heure_debut_aprem'], h['heure_fin_aprem'])
            total_reel = heures_matin + heures_aprem
        
        solde_anterieur += (total_reel - total_theorique)
    
    solde_cumule = solde_anterieur + solde_mois
    
    conn.close()
    
    # Générer le PDF en paysage (optimisé pour 2 pages max)
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), 
                           topMargin=1*cm, bottomMargin=1*cm,
                           leftMargin=1.5*cm, rightMargin=1.5*cm)
    elements = []
    
    styles = getSampleStyleSheet()
    # Réduire l'espace après le titre pour gagner de la place
    title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], 
                                alignment=TA_CENTER, fontSize=16, spaceAfter=15)
    # Style compact pour la légende
    compact_style = ParagraphStyle('Compact', parent=styles['Normal'], fontSize=9, leading=11)
    normal_style = styles['Normal']
    
    # Titre
    noms_mois = ['', 'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
                 'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']
    
    elements.append(Paragraph(f"FEUILLE DE TEMPS - {noms_mois[mois].upper()} {annee}", title_style))
    elements.append(Paragraph(f"<b>Salarié :</b> {user['prenom']} {user['nom']}", normal_style))
    elements.append(Spacer(1, 0.3*cm))
    
    # Légende compacte
    legende_text = """<b>Légende :</b> 
    <b>✓ Conforme</b> = Conforme au planning • 
    <b>🏖️ Récupération</b> = Récup validée • 
    Horaires théoriques en <font color="darkblue"><b>bleu</b></font>, réels en <font color="darkgreen"><b>vert</b></font>"""
    elements.append(Paragraph(legende_text, compact_style))
    elements.append(Spacer(1, 0.2*cm))
    
    # Tableau des journées
    data = [['Date', 'Jour', 'Horaires théoriques', 'Horaires réels', 'Écart']]
    
    for j in journees:
        ecart_str = f"+{j['ecart']:.2f}" if j['ecart'] > 0 else f"{j['ecart']:.2f}"
        
        # Formater les horaires avec total entre parenthèses
        horaires_theo_display = j['horaires_theo']
        if j['heures_theo'] > 0 and j['horaires_theo'] not in ['Repos', 'Non défini', 'Samedi']:
            horaires_theo_display += f"\n({j['heures_theo']:.1f}h)"
        
        horaires_reels_display = j['horaires_reels']
        if j['horaires_reels'] not in ['✓ Conforme', '🏖️ Récupération', 'Non saisi']:
            horaires_reels_display += f"\n({j['heures_reelles']:.1f}h)"
        
        data.append([
            j['date'],
            j['jour'],
            horaires_theo_display,
            horaires_reels_display,
            f"{ecart_str}h"
        ])
    
    # Ligne de total
    solde_str = f"+{solde_mois:.2f}" if solde_mois > 0 else f"{solde_mois:.2f}"
    data.append(['', 'TOTAL', f"{total_heures_theoriques:.2f}h", f"{total_heures_reelles:.2f}h", f"{solde_str}h"])
    
    # Table avec colonnes plus larges en paysage (A4 landscape = 29.7cm de large)
    # Total utilisable : ~26cm (marges 1.5cm x2)
    # Répartition : Date(3) + Jour(3) + Théo(8) + Réel(8) + Écart(3) = 25cm
    table = Table(data, colWidths=[3*cm, 3*cm, 8*cm, 8*cm, 3*cm])
    
    # Couleurs personnalisées
    couleur_theo = colors.HexColor('#E3F2FD')  # Bleu clair
    couleur_reel = colors.HexColor('#E8F5E9')  # Vert clair
    
    table.setStyle(TableStyle([
        # En-tête
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),  # Réduit de 12 à 8
        ('TOPPADDING', (0, 0), (-1, 0), 6),
        
        # Colonnes colorées
        ('BACKGROUND', (2, 1), (2, -2), couleur_theo),  # Colonne théo en bleu
        ('BACKGROUND', (3, 1), (3, -2), couleur_reel),  # Colonne réel en vert
        
        # Alignement et police
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTSIZE', (0, 1), (-1, -2), 8.5),  # Réduit légèrement de 9 à 8.5
        ('TOPPADDING', (0, 1), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
        
        # Ligne de total
        ('BACKGROUND', (0, -1), (-1, -1), colors.beige),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, -1), (-1, -1), 10),
        
        # Bordures
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('BOX', (0, 0), (-1, -1), 2, colors.black)
    ]))
    
    elements.append(table)
    elements.append(Spacer(1, 0.3*cm))
    
    # Créer un bloc "bas de page" qui reste ensemble (soldes + signatures)
    bas_page = []
    
    # Soldes sur une seule ligne pour gagner de la place
    soldes_text = f"""<b>Solde du mois :</b> {'+' if solde_mois > 0 else ''}{solde_mois:.2f}h  •  
    <b>Solde antérieur :</b> {'+' if solde_anterieur > 0 else ''}{solde_anterieur:.2f}h  •  
    <b>Solde cumulé :</b> {'+' if solde_cumule > 0 else ''}{solde_cumule:.2f}h"""
    bas_page.append(Paragraph(soldes_text, normal_style))
    bas_page.append(Spacer(1, 0.4*cm))
    
    # Zones de signatures (hauteur réduite)
    sig_data = [
        ['Signature Salarié', 'Signature Responsable', 'Signature Directeur'],
        [f"{validation['validation_salarie'] or ''}\n{validation['date_salarie'] or ''}", 
         f"{validation['validation_responsable']}\n{validation['date_responsable']}", 
         f"{validation['validation_directeur']}\n{validation['date_directeur']}"]
    ]
    
    sig_table = Table(sig_data, colWidths=[8*cm, 8*cm, 8*cm], rowHeights=[0.8*cm, 2.5*cm])
    sig_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
        ('VALIGN', (0, 1), (-1, 1), 'TOP'),
        ('BOX', (0, 0), (-1, -1), 2, colors.black),
        ('INNERGRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    
    bas_page.append(sig_table)
    
    # Ajouter le bloc bas_page avec KeepTogether pour éviter la coupure
    elements.append(KeepTogether(bas_page))
    
    # Construire le PDF
    doc.build(elements)
    buffer.seek(0)
    
    # Créer la réponse
    response = make_response(buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=fiche_temps_{user["nom"]}_{user["prenom"]}_{noms_mois[mois]}_{annee}.pdf'
    
    return response

# ==================== DEMANDES DE RÉCUPÉRATION ====================
