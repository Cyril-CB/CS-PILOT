"""
Blueprint indicateurs_financiers_bp - Indicateurs financiers.

Calcule, pour chaque année disponible en base (import BI) :
  - Capitaux permanents          : somme des comptes 1x (crédit-normal) + résultat (7x−6x)
  - Immobilisations nettes       : somme des comptes 2x (débit-normal, amortiss. inclus)
  - Fonds de roulement (FR)      : capitaux permanents − immobilisations nettes
  - FR en mois de charges        : FR / (total charges annuelles / 12)
  - Trésorerie nette             : somme des comptes 5x (débit-normal)
  - Trésorerie en mois           : trésorerie / (total charges / 12)
  - % Masse salariale            : somme 64xxxx / total charges 6x × 100

Onglet "Fonds de roulement" : détail du calcul pour une année sélectionnée.

Accessible aux profils directeur et comptable.
"""
import io
from datetime import datetime
from flask import (Blueprint, render_template, request, session,
                   redirect, url_for, flash, jsonify, make_response)
from database import get_db
from utils import login_required

indicateurs_financiers_bp = Blueprint('indicateurs_financiers_bp', __name__)


def _peut_acceder():
    return session.get('profil') in ('directeur', 'comptable')


def _compute_indicateurs(conn, annee):
    """Calcule les indicateurs financiers pour une année."""
    rows = conn.execute(
        'SELECT compte_num, SUM(montant) as montant FROM bilan_fec_donnees '
        'WHERE annee = ? GROUP BY compte_num',
        (annee,)
    ).fetchall()

    capitaux = 0.0
    immos = 0.0
    tresorerie = 0.0
    total_charges = 0.0
    total_produits = 0.0
    masse_salariale = 0.0

    for r in rows:
        compte = r['compte_num']
        montant = float(r['montant'] or 0)
        if not compte:
            continue
        premier = compte[0]
        if premier == '1':
            capitaux += montant          # crédit-normal : positif = capital/dette LT
        elif premier == '2':
            immos += montant             # débit-normal  : positif = immobilisation nette
        elif premier == '5':
            tresorerie += montant        # débit-normal  : positif = disponibilités
        elif premier == '6':
            total_charges += montant     # débit-normal  : positif = charge
            if compte.startswith('64'):
                masse_salariale += montant
        elif premier == '7':
            total_produits += montant    # crédit-normal : positif = produit

    # Le résultat de l'exercice (7x − 6x) appartient aux capitaux permanents (12x).
    # Il n'est pas dans les comptes 1x du BI (entrée de clôture), on l'injecte ici.
    resultat = total_produits - total_charges
    capitaux += resultat

    charges_mensuelles = total_charges / 12 if total_charges else 0
    fonds_roulement = capitaux - immos
    fr_mois = (round(fonds_roulement / charges_mensuelles, 2)
               if charges_mensuelles else None)
    tres_mois = (round(tresorerie / charges_mensuelles, 2)
                 if charges_mensuelles else None)
    pct_masse_sal = (round(masse_salariale / total_charges * 100, 1)
                     if total_charges else None)

    return {
        'annee': annee,
        'capitaux_permanents': round(capitaux, 2),
        'immobilisations_nettes': round(immos, 2),
        'fonds_roulement': round(fonds_roulement, 2),
        'fr_mois': fr_mois,
        'tresorerie': round(tresorerie, 2),
        'tresorerie_mois': tres_mois,
        'pct_masse_salariale': pct_masse_sal,
        'total_charges': round(total_charges, 2),
        'masse_salariale': round(masse_salariale, 2),
    }


# ── Page principale ──────────────────────────────────────────────────────────

@indicateurs_financiers_bp.route('/indicateurs-financiers')
@login_required
def indicateurs_financiers():
    """Affiche la page Indicateurs financiers."""
    if not _peut_acceder():
        flash('Accès non autorisé.', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    try:
        annees_importees = conn.execute(
            'SELECT DISTINCT annee FROM bilan_fec_imports ORDER BY annee DESC'
        ).fetchall()
        annees_list = [r['annee'] for r in annees_importees]
        return render_template(
            'indicateurs_financiers.html',
            annees_importees=annees_list,
        )
    finally:
        conn.close()


# ── API tableau des indicateurs ──────────────────────────────────────────────

@indicateurs_financiers_bp.route('/api/indicateurs/donnees')
@login_required
def api_indicateurs_donnees():
    """Retourne les indicateurs pour toutes les années disponibles."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    conn = get_db()
    try:
        annees = conn.execute(
            'SELECT DISTINCT annee FROM bilan_fec_imports ORDER BY annee'
        ).fetchall()
        result = [_compute_indicateurs(conn, r['annee']) for r in annees]
        return jsonify({'indicateurs': result})
    finally:
        conn.close()


# ── API détail Fonds de Roulement ────────────────────────────────────────────

@indicateurs_financiers_bp.route('/api/indicateurs/fonds-roulement')
@login_required
def api_fonds_roulement_detail():
    """Retourne le détail du calcul du Fonds de Roulement pour une année."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    annee = request.args.get('annee', type=int)
    if not annee:
        return jsonify({'error': 'Année requise.'}), 400

    conn = get_db()
    try:
        pcg = {r['compte_num']: r['libelle']
               for r in conn.execute(
                   'SELECT compte_num, libelle FROM plan_comptable_general'
               ).fetchall()}

        rows = conn.execute(
            """SELECT compte_num, libelle, SUM(montant) as montant
               FROM bilan_fec_donnees
               WHERE annee = ? AND (compte_num LIKE '1%' OR compte_num LIKE '2%')
               GROUP BY compte_num
               ORDER BY compte_num""",
            (annee,)
        ).fetchall()

        capitaux_rows = []
        immo_rows = []
        for r in rows:
            compte = r['compte_num']
            if not compte:
                continue
            lib = pcg.get(compte) or r['libelle'] or compte
            entry = {
                'compte_num': compte,
                'libelle': lib,
                'montant': round(float(r['montant'] or 0), 2),
            }
            if compte[0] == '1':
                capitaux_rows.append(entry)
            elif compte[0] == '2':
                immo_rows.append(entry)

        total_capitaux = round(sum(r['montant'] for r in capitaux_rows), 2)
        total_immos = round(sum(r['montant'] for r in immo_rows), 2)

        # Charges et produits pour le résultat de l'exercice
        row_charges = conn.execute(
            "SELECT SUM(montant) as total FROM bilan_fec_donnees "
            "WHERE annee = ? AND compte_num LIKE '6%'",
            (annee,)
        ).fetchone()
        total_charges = float(row_charges['total'] or 0)

        row_produits = conn.execute(
            "SELECT SUM(montant) as total FROM bilan_fec_donnees "
            "WHERE annee = ? AND compte_num LIKE '7%'",
            (annee,)
        ).fetchone()
        total_produits = float(row_produits['total'] or 0)

        # Le résultat (7x − 6x) s'ajoute aux capitaux permanents (compte 12x)
        resultat = round(total_produits - total_charges, 2)
        if resultat != 0:
            compte_res = '120000' if resultat > 0 else '129000'
            lib_res = ('Résultat exercice créditeur' if resultat > 0
                       else 'Résultat exercice débiteur')
            capitaux_rows.append({
                'compte_num': compte_res,
                'libelle': lib_res,
                'montant': resultat,
            })
            total_capitaux = round(total_capitaux + resultat, 2)

        fonds_roulement = round(total_capitaux - total_immos, 2)
        charges_mensuelles = round(total_charges / 12, 2) if total_charges else 0
        fr_mois = (round(fonds_roulement / charges_mensuelles, 2)
                   if charges_mensuelles else None)

        return jsonify({
            'annee': annee,
            'capitaux_rows': capitaux_rows,
            'immo_rows': immo_rows,
            'total_capitaux': total_capitaux,
            'total_immos': total_immos,
            'fonds_roulement': fonds_roulement,
            'total_charges': round(total_charges, 2),
            'charges_mensuelles': charges_mensuelles,
            'fr_mois': fr_mois,
        })
    finally:
        conn.close()


# ── Export PDF Indicateurs (paysage) ─────────────────────────────────────────

def _fmt_pdf(v):
    try:
        n = float(v or 0)
    except (ValueError, TypeError):
        return '—'
    return f'{n:,.2f}'.replace(',', ' ').replace('.', ',')


def _fmt_mois(v):
    if v is None:
        return 'N/D'
    try:
        return f'{float(v):.1f}'.replace('.', ',') + ' m'
    except (ValueError, TypeError):
        return 'N/D'


def _fmt_pct(v):
    if v is None:
        return 'N/D'
    try:
        return f'{float(v):.1f}'.replace('.', ',') + ' %'
    except (ValueError, TypeError):
        return 'N/D'


@indicateurs_financiers_bp.route('/api/indicateurs/export-pdf')
@login_required
def api_indicateurs_export_pdf():
    """Génère un PDF ReportLab professionnel des indicateurs financiers (paysage)."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    conn = get_db()
    try:
        annees = conn.execute(
            'SELECT DISTINCT annee FROM bilan_fec_imports ORDER BY annee'
        ).fetchall()
        indicateurs = [_compute_indicateurs(conn, r['annee']) for r in annees]
    finally:
        conn.close()

    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import (SimpleDocTemplate, Table as RLTable,
                                    TableStyle, Paragraph, Spacer, HRFlowable)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER

    buf = io.BytesIO()
    PAGE = landscape(A4)
    doc = SimpleDocTemplate(buf, pagesize=PAGE,
                            topMargin=1.5 * cm, bottomMargin=1.5 * cm,
                            leftMargin=1.5 * cm, rightMargin=1.5 * cm)
    styles = getSampleStyleSheet()
    W = PAGE[0] - 3 * cm

    BLUE = colors.HexColor('#1a56a0')
    GREEN = colors.HexColor('#27ae60')
    RED = colors.HexColor('#c0392b')
    GRAY_HDR = colors.HexColor('#f0f3f7')
    GRAY_EVEN = colors.HexColor('#fafbfc')

    title_st = ParagraphStyle('T', parent=styles['Heading1'],
                              fontSize=16, textColor=BLUE, alignment=TA_CENTER,
                              spaceAfter=4)
    sub_st = ParagraphStyle('S', parent=styles['Normal'],
                            fontSize=10, textColor=colors.grey, alignment=TA_CENTER,
                            spaceAfter=14)

    elements = []
    elements.append(Paragraph('Indicateurs Financiers', title_st))
    elements.append(Paragraph(
        f'Toutes les années disponibles  –  Généré le {datetime.now().strftime("%d/%m/%Y")}',
        sub_st))
    elements.append(HRFlowable(width='100%', thickness=1.5, color=BLUE, spaceAfter=12))

    if not indicateurs:
        elements.append(Paragraph('Aucune donnée disponible.', styles['Normal']))
    else:
        # En-têtes sur 2 lignes pour tenir en paysage
        headers = [
            ['Année',
             'Capitaux\npermanents (€)',
             'Immob.\nnettes (€)',
             'Fonds de\nroulement (€)',
             'FR en mois\nde charges',
             'Trésorerie\n(€)',
             'Tréso en\nmois',
             '% Masse\nsalariale'],
        ]
        # Données (plus récent en premier)
        for r in reversed(indicateurs):
            fr = r['fonds_roulement']
            cap = r['capitaux_permanents']
            immo = r['immobilisations_nettes']

            def _badge(val, is_pos):
                return _fmt_pdf(val) if is_pos else f'({_fmt_pdf(abs(val))})'

            row = [
                str(r['annee']),
                _fmt_pdf(cap) if abs(cap) > 0.01 else 'N/D',
                _fmt_pdf(immo) if abs(immo) > 0.01 else 'N/D',
                _fmt_pdf(fr) if (abs(cap) > 0.01 or abs(immo) > 0.01) else 'N/D',
                _fmt_mois(r['fr_mois']),
                _fmt_pdf(r['tresorerie']) if abs(r['tresorerie']) > 0.01 else 'N/D',
                _fmt_mois(r['tresorerie_mois']),
                _fmt_pct(r['pct_masse_salariale']),
            ]
            headers.append(row)

        # Largeurs colonnes adaptées à la largeur utile paysage
        col_widths = [
            W * 0.07,   # Année
            W * 0.14,   # Capitaux permanents
            W * 0.12,   # Immob. nettes
            W * 0.13,   # Fonds de roulement
            W * 0.12,   # FR en mois
            W * 0.13,   # Trésorerie
            W * 0.12,   # Tréso en mois
            W * 0.17,   # % Masse salariale
        ]

        t = RLTable(headers, colWidths=col_widths, repeatRows=1)

        cmds = [
            # En-tête
            ('BACKGROUND', (0, 0), (-1, 0), BLUE),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, 0), 5),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 5),
            # Corps
            ('FONTSIZE', (0, 1), (-1, -1), 8.5),
            ('ALIGN', (0, 1), (0, -1), 'CENTER'),   # Année centré
            ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),  # Année en gras
            ('TOPPADDING', (0, 1), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.lightgrey),
            ('BOX', (0, 0), (-1, -1), 1, BLUE),
        ]
        # Alternance de couleurs pour les lignes de données
        for i in range(1, len(headers)):
            if i % 2 == 0:
                cmds.append(('BACKGROUND', (0, i), (-1, i), GRAY_EVEN))

        # Couleur fonds de roulement (col 3)
        for i, r in enumerate(reversed(indicateurs), start=1):
            fr = r['fonds_roulement']
            cap = r['capitaux_permanents']
            immo = r['immobilisations_nettes']
            if abs(cap) > 0.01 or abs(immo) > 0.01:
                fc = GREEN if fr >= 0 else RED
                cmds.append(('TEXTCOLOR', (3, i), (3, i), fc))
                cmds.append(('TEXTCOLOR', (4, i), (4, i), fc))

        t.setStyle(TableStyle(cmds))
        elements.append(t)

        # Légende
        elements.append(Spacer(1, 0.5 * cm))
        legend = ('N/D = donnée non disponible (import BI sans comptes de bilan). '
                  'Capitaux permanents = comptes 1x + résultat de l\'exercice (12x). '
                  'Masse salariale = comptes 64x (bruts + charges sociales).')
        elements.append(Paragraph(legend, ParagraphStyle(
            'leg', parent=styles['Normal'],
            fontSize=7, textColor=colors.grey)))

    elements.append(Spacer(1, 0.4 * cm))
    elements.append(HRFlowable(width='100%', thickness=0.5, color=colors.lightgrey))
    elements.append(Paragraph(
        f'Document généré le {datetime.now().strftime("%d/%m/%Y à %H:%M")} – CS-PILOT',
        ParagraphStyle('foot', parent=styles['Normal'],
                       fontSize=7, textColor=colors.grey, alignment=TA_CENTER,
                       spaceBefore=4)))

    doc.build(elements)
    buf.seek(0)
    resp = make_response(buf.getvalue())
    resp.headers['Content-Type'] = 'application/pdf'
    resp.headers['Content-Disposition'] = 'attachment; filename=indicateurs_financiers.pdf'
    return resp
