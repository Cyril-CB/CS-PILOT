"""
Blueprint forfait_bp.
"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, make_response
from datetime import datetime, timedelta
from io import BytesIO
from database import get_db
from utils import login_required, get_user_info, calculer_stats_forfait_jour

forfait_bp = Blueprint('forfait_bp', __name__)


@forfait_bp.route('/dashboard_forfait_jour')
@login_required
def dashboard_forfait_jour():
    """Dashboard forfait jour pour les directeurs"""
    if session.get('profil') != 'directeur':
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))
    
    annee = request.args.get('annee', datetime.now().year, type=int)
    
    # Calculer les statistiques
    stats = calculer_stats_forfait_jour(session['user_id'], annee)
    
    return render_template('dashboard_forfait_jour.html', stats=stats, annee=annee)

@forfait_bp.route('/calendrier_forfait_jour', methods=['GET', 'POST'])
@login_required
def calendrier_forfait_jour():
    """Calendrier de saisie des présences forfait jour"""
    if session.get('profil') != 'directeur':
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))
    
    if request.method == 'POST':
        date = request.form.get('date')
        type_journee = request.form.get('type_journee')
        commentaire = request.form.get('commentaire', '').strip()
        
        if not date or not type_journee:
            flash('Date et type obligatoires', 'error')
            return redirect(url_for('forfait_bp.calendrier_forfait_jour'))
        
        conn = get_db()
        try:
            conn.execute('''
                INSERT INTO presence_forfait_jour 
                (user_id, date, type_journee, commentaire)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id, date) DO UPDATE SET type_journee=EXCLUDED.type_journee, commentaire=EXCLUDED.commentaire
            ''', (session['user_id'], date, type_journee, commentaire))
            conn.commit()
            flash('Journée enregistrée', 'success')
        except Exception as e:
            flash(f'Erreur : {str(e)}', 'error')
        finally:
            conn.close()
        
        return redirect(url_for('forfait_bp.calendrier_forfait_jour'))
    
    # GET : afficher le calendrier
    mois = request.args.get('mois', datetime.now().month, type=int)
    annee = request.args.get('annee', datetime.now().year, type=int)
    
    # Récupérer les présences du mois
    conn = get_db()
    presences = conn.execute('''
        SELECT date, type_journee, commentaire
        FROM presence_forfait_jour
        WHERE user_id = %s AND strftime('%Y', date) = %s AND strftime('%m', date) = %s
    ''', (session['user_id'], str(annee), f'{mois:02d}')).fetchall()
    
    # Convertir en dictionnaire
    presences_dict = {p['date']: {'type': p['type_journee'], 'commentaire': p['commentaire']} for p in presences}
    
    # Récupérer les jours fériés du mois
    jours_feries = conn.execute('''
        SELECT date, libelle FROM jours_feries
        WHERE strftime('%Y', date) = %s AND strftime('%m', date) = %s
    ''', (str(annee), f'{mois:02d}')).fetchall()
    
    jours_feries_dict = {f['date']: f['libelle'] for f in jours_feries}
    
    conn.close()
    
    # Construire le calendrier du mois
    premier_jour = datetime(annee, mois, 1)
    if mois == 12:
        dernier_jour = datetime(annee + 1, 1, 1) - timedelta(days=1)
    else:
        dernier_jour = datetime(annee, mois + 1, 1) - timedelta(days=1)
    
    jours_du_mois = []
    jour_actuel = premier_jour
    while jour_actuel <= dernier_jour:
        date_str = jour_actuel.strftime('%Y-%m-%d')
        jours_du_mois.append({
            'date': date_str,
            'jour': jour_actuel.day,
            'jour_semaine': jour_actuel.weekday(),
            'presence': presences_dict.get(date_str),
            'ferie': jours_feries_dict.get(date_str)
        })
        jour_actuel += timedelta(days=1)
    
    # Navigation mois
    mois_precedent = mois - 1 if mois > 1 else 12
    annee_precedente = annee if mois > 1 else annee - 1
    mois_suivant = mois + 1 if mois < 12 else 1
    annee_suivante = annee if mois < 12 else annee + 1
    
    noms_mois = {1: 'Janvier', 2: 'Février', 3: 'Mars', 4: 'Avril', 5: 'Mai', 6: 'Juin',
                 7: 'Juillet', 8: 'Août', 9: 'Septembre', 10: 'Octobre', 11: 'Novembre', 12: 'Décembre'}
    
    return render_template('calendrier_forfait_jour.html', 
                         jours=jours_du_mois,
                         mois=mois,
                         annee=annee,
                         nom_mois=noms_mois[mois],
                         mois_precedent=mois_precedent,
                         annee_precedente=annee_precedente,
                         mois_suivant=mois_suivant,
                         annee_suivante=annee_suivante)

@forfait_bp.route('/rapport_forfait_jour_pdf/<int:mois>/<int:annee>')
@login_required
def rapport_forfait_jour_pdf(mois, annee):
    """Génère le rapport PDF mensuel forfait jour"""
    if session.get('profil') != 'directeur':
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))
    
    conn = get_db()
    user = get_user_info(session['user_id'])
    
    # Récupérer les présences du mois
    presences = conn.execute('''
        SELECT date, type_journee, commentaire
        FROM presence_forfait_jour
        WHERE user_id = %s AND strftime('%Y', date) = %s AND strftime('%m', date) = %s
        ORDER BY date
    ''', (session['user_id'], str(annee), f'{mois:02d}')).fetchall()
    
    # Calculer les stats du mois
    stats_mois = {
        'travaille': 0,
        'conge_paye': 0,
        'conge_conv': 0,
        'repos_forfait': 0,
        'ferie': 0,
        'maladie': 0,
        'sans_solde': 0,
        'autre': 0
    }
    
    for p in presences:
        if p['type_journee'] in stats_mois:
            stats_mois[p['type_journee']] += 1
    
    # Stats cumulées année
    stats_annee = calculer_stats_forfait_jour(session['user_id'], annee)
    
    conn.close()
    
    # Créer le PDF
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from io import BytesIO
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm)
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=colors.HexColor('#1e40af'),
        spaceAfter=20,
        alignment=TA_CENTER
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=12,
        textColor=colors.HexColor('#1e40af'),
        spaceAfter=10,
        spaceBefore=15
    )
    
    noms_mois = {1: 'Janvier', 2: 'Février', 3: 'Mars', 4: 'Avril', 5: 'Mai', 6: 'Juin',
                 7: 'Juillet', 8: 'Août', 9: 'Septembre', 10: 'Octobre', 11: 'Novembre', 12: 'Décembre'}
    
    # Titre
    elements.append(Paragraph(f"RAPPORT MENSUEL FORFAIT JOUR", title_style))
    elements.append(Paragraph(f"{noms_mois[mois]} {annee}", title_style))
    elements.append(Spacer(1, 0.5*cm))
    
    # Infos employé
    elements.append(Paragraph(f"<b>Directeur :</b> {user['prenom']} {user['nom']}", styles['Normal']))
    elements.append(Paragraph(f"<b>Contrat :</b> Forfait jour - 210 jours/an", styles['Normal']))
    elements.append(Spacer(1, 0.5*cm))
    
    # Détail du mois
    elements.append(Paragraph("DÉTAIL DU MOIS", heading_style))
    
    types_labels = {
        'travaille': 'Travaillé',
        'conge_paye': 'Congé payé',
        'conge_conv': 'Congé conventionnel',
        'repos_forfait': 'Repos forfait jour',
        'ferie': 'Jour férié',
        'maladie': 'Arrêt maladie',
        'sans_solde': 'Sans solde',
        'autre': 'Autre'
    }
    
    if presences:
        data = [['Date', 'Type', 'Commentaire']]
        for p in presences:
            data.append([
                datetime.strptime(p['date'], '%Y-%m-%d').strftime('%d/%m/%Y'),
                types_labels.get(p['type_journee'], p['type_journee']),
                p['commentaire'] or '-'
            ])
        
        table = Table(data, colWidths=[3*cm, 5*cm, 9*cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#334155')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e2e8f0'))
        ]))
        elements.append(table)
    else:
        elements.append(Paragraph("Aucune saisie pour ce mois", styles['Normal']))
    
    elements.append(Spacer(1, 0.5*cm))
    
    # Bilan du mois
    elements.append(Paragraph("BILAN DU MOIS", heading_style))
    data_bilan = [
        ['Type', 'Nombre de jours'],
        ['Jours travaillés', str(stats_mois['travaille'])],
        ['Congés payés', str(stats_mois['conge_paye'])],
        ['Congés conventionnels', str(stats_mois['conge_conv'])],
        ['Repos forfait jour', str(stats_mois['repos_forfait'])],
        ['Jours fériés', str(stats_mois['ferie'])],
        ['Arrêts maladie', str(stats_mois['maladie'])],
        ['Sans solde', str(stats_mois['sans_solde'])],
        ['Autre', str(stats_mois['autre'])]
    ]
    
    table_bilan = Table(data_bilan, colWidths=[10*cm, 4*cm])
    table_bilan.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#334155')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e2e8f0'))
    ]))
    elements.append(table_bilan)
    elements.append(Spacer(1, 0.5*cm))
    
    # Soldes cumulés année
    elements.append(Paragraph("SOLDES CUMULÉS (ANNÉE)", heading_style))
    data_cumul = [
        ['Indicateur', 'Réalisé', 'Objectif', 'Restant'],
        ['Jours travaillés', str(stats_annee['travaille']), '210', str(stats_annee['soldes']['jours_a_travailler'])],
        ['Congés payés pris', str(stats_annee['conge_paye']), '25', str(stats_annee['soldes']['conges_payes_restants'])],
        ['Congés conv. pris', str(stats_annee['conge_conv']), '8', str(stats_annee['soldes']['conges_conv_restants'])],
        ['Repos forfait pris', str(stats_annee['repos_forfait']), str(stats_annee['config']['jours_repos_forfait']), 
         str(stats_annee['soldes']['repos_forfait_restants'])]
    ]
    
    table_cumul = Table(data_cumul, colWidths=[7*cm, 3*cm, 3*cm, 3*cm])
    table_cumul.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#334155')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e2e8f0'))
    ]))
    elements.append(table_cumul)
    elements.append(Spacer(1, 1*cm))
    
    # Signatures
    elements.append(Paragraph("SIGNATURES", heading_style))
    elements.append(Spacer(1, 0.3*cm))
    
    data_signatures = [
        ['Directeur', 'Comité de présidence', 'Date'],
        ['', '', ''],
        ['', '', ''],
        ['', '', '']
    ]
    
    table_sig = Table(data_signatures, colWidths=[6*cm, 6*cm, 4*cm], rowHeights=[0.5*cm, 2*cm, 0.3*cm, 0.5*cm])
    table_sig.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('LINEBELOW', (0, 1), (-1, 1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'TOP')
    ]))
    elements.append(table_sig)
    
    # Construire le PDF
    doc.build(elements)
    buffer.seek(0)
    
    # Créer la réponse
    response = make_response(buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=rapport_forfait_jour_{user["nom"]}_{noms_mois[mois]}_{annee}.pdf'
    
    return response
