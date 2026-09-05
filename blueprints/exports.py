"""
Blueprint exports_bp.
"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, make_response
from datetime import datetime, timedelta
from io import BytesIO
from database import get_db
from utils import login_required, est_dans_equipe_responsable

exports_bp = Blueprint('exports_bp', __name__)


def _peut_exporter_pdf_mensuel(conn, user_id_cible):
    """Vérifie que l'utilisateur connecté peut exporter la fiche PDF cible.

    Le PDF mensuel contient des informations RH nominatives : il doit suivre
    le même modèle d'accès que la vue mensuelle.
    """
    if user_id_cible == session.get('user_id'):
        return True

    profil = session.get('profil')
    if profil in ('directeur', 'comptable'):
        return conn.execute(
            "SELECT 1 FROM users WHERE id = ? AND actif = 1 AND profil != 'prestataire'",
            (user_id_cible,)
        ).fetchone() is not None

    if profil == 'responsable':
        # Même périmètre que la vue mensuelle : secteur commun OU rattachement
        # hiérarchique direct (est_dans_equipe_responsable), salarié actif.
        actif = conn.execute(
            "SELECT 1 FROM users WHERE id = ? AND actif = 1 AND profil != 'prestataire'",
            (user_id_cible,)
        ).fetchone() is not None
        return actif and est_dans_equipe_responsable(conn, session['user_id'], user_id_cible)

    return False


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
    conn.execute("BEGIN")

    if not _peut_exporter_pdf_mensuel(conn, user_id_param):
        flash('Accès non autorisé à cette fiche', 'error')
        conn.close()
        return redirect(url_for('validation_bp.vue_mensuelle'))
    
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
    
    # Le document reproduit exactement le contenu conservé, sans second calcul.
    from fiches_versions import lire_contenu, presenter_validation
    contenu = lire_contenu(conn, user_id_param, mois, annee)
    validation = presenter_validation(validation)
    user = {**dict(user), **contenu['identite']}
    journees = []
    for jour in contenu['journees']:
        horaires_theo = jour['horaires_theoriques']
        if jour['hors_contrat']:
            horaires_theo = 'Hors contrat'
        elif jour['est_samedi']:
            horaires_theo = 'Samedi'
        elif jour['est_repos_habituel']:
            horaires_theo = 'Repos'
        horaires_reels = jour['horaires_reels']
        if jour['type_saisie'] == 'recup_journee':
            horaires_reels = 'Récupération'
        elif jour['est_declare']:
            horaires_reels = 'Conforme'
        elif jour['hors_contrat']:
            horaires_reels = '—'
        if jour['pause_remuneree']:
            horaires_reels += ' (+ pause)'
        journees.append(dict(
            date=jour['date_obj'].strftime('%d/%m/%Y'), jour=jour['jour_semaine'],
            horaires_theo=horaires_theo, heures_theo=jour['heures_theoriques'],
            horaires_reels=horaires_reels, heures_reelles=jour['heures_reelles'],
            ecart=jour['ecart'],
        ))
    total_heures_theoriques = contenu['total_heures_theoriques']
    total_heures_reelles = contenu['total_heures_reelles']
    solde_mois = contenu['solde_mois']
    solde_anterieur = contenu['solde_anterieur']
    hs_payees_mois = contenu['hs_payees_mois']
    solde_cumule = contenu['solde_cumule']

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
    hs_payees_txt = (f"  •  <b>H. supp payées ce mois :</b> -{hs_payees_mois:.2f}h"
                     if hs_payees_mois else "")
    soldes_text = f"""<b>Solde du mois :</b> {'+' if solde_mois > 0 else ''}{solde_mois:.2f}h  •
    <b>Solde antérieur :</b> {'+' if solde_anterieur > 0 else ''}{solde_anterieur:.2f}h{hs_payees_txt}  •
    <b>Solde cumulé :</b> {'+' if solde_cumule > 0 else ''}{solde_cumule:.2f}h"""
    bas_page.append(Paragraph(soldes_text, normal_style))
    bas_page.append(Spacer(1, 0.4*cm))
    
    # Zones de signatures (hauteur réduite)
    sig_data = [
        ['Signature Salarié', 'Signature Responsable', 'Signature Directeur'],
        [f"{validation['validation_salarie'] or ''}\n{validation['date_salarie'] or ''}", 
         f"{validation['validation_responsable'] or ''}\n{validation['date_responsable'] or ''}",
         f"{validation['validation_directeur'] or ''}\n{validation['date_directeur'] or ''}"]
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
    if validation['historique_non_versionne']:
        bas_page.append(Paragraph(
            "Fiche historique conservée : contenu figé lors de la mise à jour. "
            "Le contenu exact des signatures antérieures n'est pas vérifiable.",
            normal_style,
        ))
    
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
