"""
Blueprint forfait_bp.
"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, make_response
from datetime import datetime, timedelta
from io import BytesIO
from database import get_db
from utils import login_required, get_user_info, calculer_stats_forfait_jour, calculer_heures

forfait_bp = Blueprint('forfait_bp', __name__)


def initialiser_annee_forfait_jour(conn, user_id, annee, commit=True):
    """Pré-remplit le calendrier forfait jour d'une année.

    Par défaut, chaque jour ouvré (lundi → vendredi) qui n'est pas férié est
    marqué comme « travaillé ». Les week-ends et les jours fériés sont laissés
    de côté. La direction n'a donc plus qu'à modifier les jours d'absence
    (congés, RTT, maladie…), y compris pour des dates futures, afin d'établir
    un prévisionnel et de se projeter sur l'année.

    L'initialisation n'a lieu qu'une seule fois par utilisateur et par année,
    lorsque celle-ci est encore vierge de toute saisie : les saisies déjà
    existantes ne sont jamais écrasées (INSERT OR IGNORE + garde « année vide »).

    Retourne True si l'année vient d'être initialisée, False sinon.
    """
    deja_initialisee = conn.execute(
        "SELECT 1 FROM presence_forfait_jour "
        "WHERE user_id = ? AND strftime('%Y', date) = ? LIMIT 1",
        (user_id, str(annee))
    ).fetchone()
    if deja_initialisee:
        return False

    feries = conn.execute(
        "SELECT date FROM jours_feries WHERE annee = ?", (annee,)
    ).fetchall()
    feries_set = {f['date'] for f in feries}

    jours_a_inserer = []
    jour = datetime(annee, 1, 1)
    fin = datetime(annee, 12, 31)
    while jour <= fin:
        date_str = jour.strftime('%Y-%m-%d')
        # weekday() : 0 = lundi … 4 = vendredi ; on exclut les fériés
        if jour.weekday() < 5 and date_str not in feries_set:
            jours_a_inserer.append((user_id, date_str, 'travaille'))
        jour += timedelta(days=1)

    if jours_a_inserer:
        conn.executemany(
            "INSERT OR IGNORE INTO presence_forfait_jour "
            "(user_id, date, type_journee) VALUES (?, ?, ?)",
            jours_a_inserer
        )
        if commit:
            conn.commit()
    return True


@forfait_bp.route('/dashboard_forfait_jour')
@login_required
def dashboard_forfait_jour():
    """Dashboard forfait jour pour les directeurs"""
    if session.get('profil') != 'directeur':
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))
    
    annee = request.args.get('annee', datetime.now().year, type=int)

    # Pré-remplir l'année (jours ouvrés = travaillé) si elle est encore vierge,
    # afin que les statistiques reflètent le calendrier par défaut.
    conn = get_db()
    initialiser_annee_forfait_jour(conn, session['user_id'], annee)
    conn.close()

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

        # Horaires facultatifs (le forfait jour n'impose pas d'horaire, mais la
        # direction peut noter les heures travaillées matin / après-midi)
        matin_debut = request.form.get('matin_debut', '').strip() or None
        matin_fin = request.form.get('matin_fin', '').strip() or None
        aprem_debut = request.form.get('aprem_debut', '').strip() or None
        aprem_fin = request.form.get('aprem_fin', '').strip() or None

        if not date or not type_journee:
            flash('Date et type obligatoires', 'error')
            return redirect(url_for('forfait_bp.calendrier_forfait_jour'))

        conn = get_db()
        try:
            conn.execute('''
                INSERT OR REPLACE INTO presence_forfait_jour
                (user_id, date, type_journee, commentaire,
                 matin_debut, matin_fin, aprem_debut, aprem_fin)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (session['user_id'], date, type_journee, commentaire,
                  matin_debut, matin_fin, aprem_debut, aprem_fin))
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

    conn = get_db()

    # Pré-remplir l'année (jours ouvrés = travaillé, hors fériés) si elle est
    # encore vierge. La direction peut ensuite poser à l'avance ses absences
    # (congés, RTT…), y compris sur des dates futures, pour un prévisionnel.
    initialiser_annee_forfait_jour(conn, session['user_id'], annee)

    # Récupérer les présences du mois
    presences = conn.execute('''
        SELECT date, type_journee, commentaire,
               matin_debut, matin_fin, aprem_debut, aprem_fin
        FROM presence_forfait_jour
        WHERE user_id = ? AND strftime('%Y', date) = ? AND strftime('%m', date) = ?
    ''', (session['user_id'], str(annee), f'{mois:02d}')).fetchall()

    # Convertir en dictionnaire (avec horaires et total d'heures calculé)
    presences_dict = {}
    for p in presences:
        heures = calculer_heures(p['matin_debut'], p['matin_fin']) + \
                 calculer_heures(p['aprem_debut'], p['aprem_fin'])
        parts = []
        if p['matin_debut'] and p['matin_fin']:
            parts.append(f"{p['matin_debut']}-{p['matin_fin']}")
        if p['aprem_debut'] and p['aprem_fin']:
            parts.append(f"{p['aprem_debut']}-{p['aprem_fin']}")
        presences_dict[p['date']] = {
            'type': p['type_journee'],
            'commentaire': p['commentaire'] or '',
            'matin_debut': p['matin_debut'] or '',
            'matin_fin': p['matin_fin'] or '',
            'aprem_debut': p['aprem_debut'] or '',
            'aprem_fin': p['aprem_fin'] or '',
            'horaire_str': ' / '.join(parts),
            'heures': round(heures, 2),
            'heures_str': f"{heures:g}h" if heures else '',
        }
    
    # Récupérer les jours fériés du mois
    jours_feries = conn.execute('''
        SELECT date, libelle FROM jours_feries
        WHERE strftime('%Y', date) = ? AND strftime('%m', date) = ?
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
        SELECT date, type_journee, commentaire,
               matin_debut, matin_fin, aprem_debut, aprem_fin
        FROM presence_forfait_jour
        WHERE user_id = ? AND strftime('%Y', date) = ? AND strftime('%m', date) = ?
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

    # Total des heures travaillées saisies et nombre de jours renseignés
    total_heures = 0
    nb_jours_horaires = 0

    for p in presences:
        # « Forfait jour » consomme le quota de repos forfait : on l'y agrège
        # (le libellé distinct reste visible dans le détail jour par jour).
        type_j = 'repos_forfait' if p['type_journee'] == 'forfait_jour' else p['type_journee']
        if type_j in stats_mois:
            stats_mois[type_j] += 1
        heures_jour = calculer_heures(p['matin_debut'], p['matin_fin']) + \
                      calculer_heures(p['aprem_debut'], p['aprem_fin'])
        if heures_jour > 0:
            total_heures += heures_jour
            nb_jours_horaires += 1
    total_heures = round(total_heures, 2)

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
        'forfait_jour': 'Forfait jour',
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

    # Total des heures travaillées saisies (suivi facultatif des horaires)
    if nb_jours_horaires > 0:
        jours_label = 'jour' if nb_jours_horaires == 1 else 'jours'
        elements.append(Spacer(1, 0.3*cm))
        elements.append(Paragraph(
            f"<b>Heures travaillées :</b> {total_heures:g} heures "
            f"({nb_jours_horaires} {jours_label} avec horaires saisies)",
            styles['Normal']
        ))

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
