"""
Blueprint compte_resultat_bp - Compte de Résultat / Bilan.

Fonctionnalités :
- Compte de Résultat : charges (6x) vs produits (7x), comparaison N / N-1
- Bilan simplifié : actif (2-5x) vs passif (1x + dettes 4x)
  Nécessite un import BI avec tous les comptes (classes 1-7).
- Sélection de l'année
- Export PDF ReportLab professionnel (C.R. + Bilan)
- Accessible aux profils directeur et comptable
"""
import io
from datetime import datetime
from flask import (Blueprint, render_template, request, session,
                   redirect, url_for, flash, jsonify, make_response)
from database import get_db
from utils import login_required

compte_resultat_bp = Blueprint('compte_resultat_bp', __name__)

# Noms lisibles pour les catégories du Compte de Résultat (2 premiers chiffres)
NOMS_CAT_CR = {
    '60': 'Achats et variations de stocks',
    '61': 'Services extérieurs',
    '62': 'Autres services extérieurs',
    '63': 'Impôts, taxes et vers. assim.',
    '64': 'Charges de personnel',
    '65': 'Autres charges de gestion',
    '66': 'Charges financières',
    '67': 'Charges exceptionnelles',
    '68': 'Dotations aux amortissements',
    '69': 'Participation / Impôt sociétés',
    '70': 'Ventes de produits / services',
    '71': 'Production stockée',
    '72': 'Production immobilisée',
    '73': 'Produits des activités annexes',
    '74': "Subventions d'exploitation",
    '75': 'Autres produits de gestion',
    '76': 'Produits financiers',
    '77': 'Produits exceptionnels',
    '78': 'Reprises sur amortissements',
    '79': 'Transferts de charges',
}

# Noms lisibles pour les catégories du Bilan (2 premiers chiffres)
NOMS_CAT_BILAN = {
    # Actif
    '20': 'Immob. incorporelles',
    '21': 'Immob. corporelles',
    '22': 'Immob. mises en concession',
    '23': 'Immob. en cours',
    '26': 'Participations',
    '27': 'Autres immob. financières',
    '28': 'Amortissements des immob.',
    '29': 'Dépréciations immob.',
    '30': 'Stocks - mat. premières',
    '31': 'Stocks - en cours production',
    '33': 'En-cours de production',
    '35': 'Stocks - produits finis',
    '37': 'Stocks - marchandises',
    '39': 'Dépréciations stocks',
    '40': 'Fournisseurs et cptes rattachés',
    '41': 'Clients et cptes rattachés',
    '42': 'Personnel et cptes rattachés',
    '43': 'Organismes sociaux',
    '44': 'État et collectivités',
    '45': 'Groupe et associés',
    '46': 'Débiteurs / créditeurs divers',
    '47': 'Cptes transitoires ou attente',
    '48': 'Cptes de régularisation',
    '49': 'Dépréciations cptes tiers',
    '50': 'Valeurs mobilières de placement',
    '51': 'Banques, CCP, chèques postaux',
    '52': 'Instruments de trésorerie',
    '53': 'Caisses',
    '54': 'Régies d\'avance / accréditifs',
    '58': 'Virements internes',
    '59': 'Dépréciations trés. / VMP',
    # Passif
    '10': 'Capital et réserves',
    '11': 'Report à nouveau',
    '12': 'Résultat de l\'exercice',
    '13': 'Subventions d\'investissement',
    '14': 'Provisions réglementées',
    '15': 'Provisions pour risques et charges',
    '16': 'Emprunts et dettes financières',
    '17': 'Dettes rattachées à participations',
    '18': 'Comptes de liaison',
    '19': 'Dépréciations',
}


def _peut_acceder():
    return session.get('profil') in ('directeur', 'comptable')


def _get_libelles_pcg(conn):
    rows = conn.execute(
        'SELECT compte_num, libelle FROM plan_comptable_general'
    ).fetchall()
    return {r['compte_num']: r['libelle'] for r in rows}


def _aggregate_by_cat(rows, premiers, pcg):
    """Agrège les lignes par catégorie (2 premiers chiffres) pour les classes données."""
    cats = {}
    for r in rows:
        compte = r['compte_num']
        if not compte or compte[0] not in premiers:
            continue
        cat = compte[:2]
        montant = float(r['montant'] or 0)
        lib = pcg.get(compte) or r['libelle'] or compte
        if cat not in cats:
            cats[cat] = {'comptes': {}, 'total': 0.0}
        if compte not in cats[cat]['comptes']:
            cats[cat]['comptes'][compte] = {'libelle': lib, 'total': 0.0}
        cats[cat]['comptes'][compte]['total'] += montant
        cats[cat]['total'] += montant
    for cat in cats.values():
        cat['total'] = round(cat['total'], 2)
        for c in cat['comptes'].values():
            c['total'] = round(c['total'], 2)
    return cats


def _cr_for_year(conn, annee, pcg):
    """Calcule le Compte de Résultat pour une année."""
    rows = conn.execute(
        """SELECT compte_num, libelle, SUM(montant) as montant
           FROM bilan_fec_donnees
           WHERE annee = ? AND (compte_num LIKE '6%' OR compte_num LIKE '7%')
           GROUP BY compte_num""",
        (annee,)
    ).fetchall()
    charges = _aggregate_by_cat(rows, {'6'}, pcg)
    produits = _aggregate_by_cat(rows, {'7'}, pcg)
    total_charges = round(sum(c['total'] for c in charges.values()), 2)
    total_produits = round(sum(p['total'] for p in produits.values()), 2)
    return {
        'charges': charges,
        'produits': produits,
        'total_charges': total_charges,
        'total_produits': total_produits,
        'resultat': round(total_produits - total_charges, 2),
    }


def _inject_resultat_exercice(bilan, resultat):
    """Injecte le résultat de l'exercice (compte 12x) dans le passif du bilan.

    120000 – Résultat exercice créditeur (bénéfice) : montant positif → augmente le passif.
    129000 – Résultat exercice débiteur  (déficit)  : montant négatif → réduit le passif.
    Les deux sont dans la catégorie '12' (capitaux permanents).
    """
    if resultat == 0:
        return
    compte = '120000' if resultat > 0 else '129000'
    libelle = ('Résultat exercice créditeur' if resultat > 0
               else 'Résultat exercice débiteur')
    cat = '12'
    if cat not in bilan['passif_capitaux']:
        bilan['passif_capitaux'][cat] = {'comptes': {}, 'total': 0.0}
    bilan['passif_capitaux'][cat]['comptes'][compte] = {
        'libelle': libelle,
        'total': round(resultat, 2),
    }
    bilan['passif_capitaux'][cat]['total'] = round(
        bilan['passif_capitaux'][cat]['total'] + resultat, 2
    )
    bilan['total_passif_capitaux'] = round(bilan['total_passif_capitaux'] + resultat, 2)
    bilan['total_passif'] = round(bilan['total_passif'] + resultat, 2)


def _bilan_for_year(conn, annee, pcg):
    """Calcule le Bilan simplifié pour une année."""
    rows = conn.execute(
        """SELECT compte_num, libelle, SUM(montant) as montant
           FROM bilan_fec_donnees
           WHERE annee = ? AND compte_num NOT LIKE '6%' AND compte_num NOT LIKE '7%'
           GROUP BY compte_num""",
        (annee,)
    ).fetchall()

    # Actif immobilisé : 2x  (montant = debit − credit, positif = actif)
    actif_immo = _aggregate_by_cat(rows, {'2'}, pcg)
    # Actif circulant : 3x (stocks) + 5x (trésorerie)
    actif_stocks = _aggregate_by_cat(rows, {'3'}, pcg)
    actif_tresorerie = _aggregate_by_cat(rows, {'5'}, pcg)
    # Tiers (4x) : montant positif → créance (actif), négatif → dette (passif)
    tiers_rows_actif = [
        {'compte_num': r['compte_num'], 'libelle': r['libelle'],
         'montant': r['montant']}
        for r in rows
        if r['compte_num'] and r['compte_num'][0] == '4' and (r['montant'] or 0) >= 0
    ]
    tiers_rows_passif = [
        {'compte_num': r['compte_num'], 'libelle': r['libelle'],
         'montant': abs(r['montant'] or 0)}
        for r in rows
        if r['compte_num'] and r['compte_num'][0] == '4' and (r['montant'] or 0) < 0
    ]
    actif_tiers = _aggregate_by_cat(tiers_rows_actif, {'4'}, pcg)
    passif_dettes_expl = _aggregate_by_cat(tiers_rows_passif, {'4'}, pcg)

    # Passif : 1x  (montant = credit − debit, positif = passif)
    passif_capitaux = _aggregate_by_cat(rows, {'1'}, pcg)

    total_actif_immo = round(sum(c['total'] for c in actif_immo.values()), 2)
    total_actif_stocks = round(sum(c['total'] for c in actif_stocks.values()), 2)
    total_actif_tiers = round(sum(c['total'] for c in actif_tiers.values()), 2)
    total_actif_tresorerie = round(sum(c['total'] for c in actif_tresorerie.values()), 2)
    total_passif_capitaux = round(sum(c['total'] for c in passif_capitaux.values()), 2)
    total_passif_dettes = round(sum(c['total'] for c in passif_dettes_expl.values()), 2)

    return {
        'actif_immo': actif_immo,
        'actif_stocks': actif_stocks,
        'actif_tiers': actif_tiers,
        'actif_tresorerie': actif_tresorerie,
        'passif_capitaux': passif_capitaux,
        'passif_dettes_expl': passif_dettes_expl,
        'total_actif_immo': total_actif_immo,
        'total_actif_stocks': total_actif_stocks,
        'total_actif_tiers': total_actif_tiers,
        'total_actif_tresorerie': total_actif_tresorerie,
        'total_passif_capitaux': total_passif_capitaux,
        'total_passif_dettes': total_passif_dettes,
        'total_actif': round(
            total_actif_immo + total_actif_stocks
            + total_actif_tiers + total_actif_tresorerie, 2),
        'total_passif': round(total_passif_capitaux + total_passif_dettes, 2),
    }


# ── Page principale ──────────────────────────────────────────────────────────

@compte_resultat_bp.route('/compte-resultat')
@login_required
def compte_resultat():
    """Affiche la page Compte de Résultat / Bilan."""
    if not _peut_acceder():
        flash('Accès non autorisé.', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    now = datetime.now()
    conn = get_db()
    try:
        annees_importees = conn.execute(
            'SELECT DISTINCT annee FROM bilan_fec_imports ORDER BY annee DESC'
        ).fetchall()
        annees_list = [r['annee'] for r in annees_importees]
        annee_courante = annees_list[0] if annees_list else now.year
        return render_template(
            'compte_resultat.html',
            annee_courante=annee_courante,
            annees_importees=annees_list,
            noms_cat_json={**NOMS_CAT_CR, **NOMS_CAT_BILAN},
        )
    finally:
        conn.close()


# ── API Compte de Résultat ────────────────────────────────────────────────────

@compte_resultat_bp.route('/api/cr/donnees')
@login_required
def api_cr_donnees():
    """Retourne le Compte de Résultat pour l'année N (et N-1 si disponible)."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    annee = request.args.get('annee', type=int)
    if not annee:
        return jsonify({'error': 'Année requise.'}), 400

    conn = get_db()
    try:
        pcg = _get_libelles_pcg(conn)
        data_n = _cr_for_year(conn, annee, pcg)
        data_n1 = _cr_for_year(conn, annee - 1, pcg)
        has_n1 = bool(data_n1['charges'] or data_n1['produits'])
        return jsonify({
            'annee': annee,
            'n': data_n,
            'n1': data_n1 if has_n1 else None,
            'noms_cat': NOMS_CAT_CR,
        })
    finally:
        conn.close()


# ── API Bilan ─────────────────────────────────────────────────────────────────

@compte_resultat_bp.route('/api/cr/bilan-donnees')
@login_required
def api_bilan_donnees():
    """Retourne le Bilan simplifié pour l'année N (et N-1 si disponible)."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    annee = request.args.get('annee', type=int)
    if not annee:
        return jsonify({'error': 'Année requise.'}), 400

    conn = get_db()
    try:
        pcg = _get_libelles_pcg(conn)
        data_n = _bilan_for_year(conn, annee, pcg)
        data_n1 = _bilan_for_year(conn, annee - 1, pcg)

        # has_bilan = True uniquement s'il y a des comptes de bilan réels (1x-5x)
        # dans le BI importé — évalué avant l'injection du résultat synthétique.
        has_n = bool(
            data_n['actif_immo'] or data_n['actif_stocks']
            or data_n['actif_tiers'] or data_n['actif_tresorerie']
            or data_n['passif_capitaux'] or data_n['passif_dettes_expl']
        )
        has_n1 = bool(
            data_n1['actif_immo'] or data_n1['actif_stocks']
            or data_n1['actif_tiers'] or data_n1['actif_tresorerie']
            or data_n1['passif_capitaux'] or data_n1['passif_dettes_expl']
        )

        # Injecter le résultat de l'exercice dans le passif (compte 12x)
        # pour équilibrer actif = passif — seulement si le bilan existe.
        if has_n:
            cr_n = _cr_for_year(conn, annee, pcg)
            _inject_resultat_exercice(data_n, cr_n['resultat'])
        if has_n1:
            cr_n1 = _cr_for_year(conn, annee - 1, pcg)
            _inject_resultat_exercice(data_n1, cr_n1['resultat'])

        return jsonify({
            'annee': annee,
            'n': data_n,
            'n1': data_n1 if has_n1 else None,
            'has_bilan': has_n,
            'noms_cat': NOMS_CAT_BILAN,
        })
    finally:
        conn.close()


# ── Export PDF ────────────────────────────────────────────────────────────────

def _fmt_pdf(v):
    """Formate un nombre pour le PDF (séparateur de milliers français)."""
    try:
        n = float(v or 0)
    except (ValueError, TypeError):
        return '0,00'
    return f'{n:,.2f}'.replace(',', ' ').replace('.', ',')


@compte_resultat_bp.route('/api/cr/export-pdf')
@login_required
def api_cr_export_pdf():
    """Génère un PDF ReportLab professionnel du C.R. et du Bilan."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    annee = request.args.get('annee', type=int)
    if not annee:
        flash('Année requise.', 'error')
        return redirect(url_for('compte_resultat_bp.compte_resultat'))

    conn = get_db()
    try:
        pcg = _get_libelles_pcg(conn)
        cr = _cr_for_year(conn, annee, pcg)
        bilan = _bilan_for_year(conn, annee, pcg)
        has_bilan = bool(
            bilan['actif_immo'] or bilan['actif_stocks']
            or bilan['actif_tiers'] or bilan['actif_tresorerie']
            or bilan['passif_capitaux'] or bilan['passif_dettes_expl']
        )
        if has_bilan:
            _inject_resultat_exercice(bilan, cr['resultat'])
    finally:
        conn.close()

    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import (SimpleDocTemplate, Table as RLTable,
                                    TableStyle, Paragraph, Spacer, HRFlowable)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            topMargin=1.5 * cm, bottomMargin=1.5 * cm,
                            leftMargin=1.5 * cm, rightMargin=1.5 * cm)
    styles = getSampleStyleSheet()
    W = A4[0] - 3 * cm  # largeur utile

    BLUE = colors.HexColor('#1a56a0')
    RED = colors.HexColor('#c0392b')
    GREEN = colors.HexColor('#27ae60')
    GRAY_HDR = colors.HexColor('#f0f3f7')
    GRAY_CAT = colors.HexColor('#e8ecf0')

    title_st = ParagraphStyle('T', parent=styles['Heading1'],
                              fontSize=16, textColor=BLUE, alignment=TA_CENTER,
                              spaceAfter=4)
    sub_st = ParagraphStyle('S', parent=styles['Normal'],
                            fontSize=10, textColor=colors.grey, alignment=TA_CENTER,
                            spaceAfter=16)
    section_st = ParagraphStyle('Sec', parent=styles['Heading2'],
                                fontSize=12, textColor=colors.white,
                                spaceBefore=14, spaceAfter=4)
    normal_st = styles['Normal']

    elements = []

    # ── En-tête ──
    elements.append(Paragraph(f'Compte de Résultat &amp; Bilan', title_st))
    elements.append(Paragraph(f'Exercice {annee}', sub_st))
    elements.append(HRFlowable(width='100%', thickness=1.5, color=BLUE, spaceAfter=12))

    def _section_table(cats, noms, color_hdr, col_w=None):
        """Construit une RLTable charges ou produits."""
        if col_w is None:
            col_w = [W * 0.55, W * 0.45]
        data = [['Compte / Libellé', 'Montant (€)']]
        for cat_key in sorted(cats.keys()):
            cat = cats[cat_key]
            cat_name = noms.get(cat_key, cat_key)
            data.append([f'{cat_key}x – {cat_name}', _fmt_pdf(cat['total'])])
            for num in sorted(cat['comptes'].keys()):
                cpt = cat['comptes'][num]
                data.append([f'   {num}  {cpt["libelle"]}', _fmt_pdf(cpt['total'])])
        data.append(['Total', _fmt_pdf(sum(c['total'] for c in cats.values()))])

        t = RLTable(data, colWidths=col_w, repeatRows=1)
        cmds = [
            ('BACKGROUND', (0, 0), (-1, 0), color_hdr),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('GRID', (0, 0), (-1, -1), 0.3, colors.lightgrey),
            ('BOX', (0, 0), (-1, -1), 0.8, color_hdr),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('BACKGROUND', (0, -1), (-1, -1), GRAY_HDR),
            ('LINEABOVE', (0, -1), (-1, -1), 1, color_hdr),
        ]
        # Lignes de catégorie en gras + fond gris clair
        idx = 1
        for cat_key in sorted(cats.keys()):
            cmds.append(('FONTNAME', (0, idx), (-1, idx), 'Helvetica-Bold'))
            cmds.append(('BACKGROUND', (0, idx), (-1, idx), GRAY_CAT))
            idx += 1 + len(cats[cat_key]['comptes'])
        t.setStyle(TableStyle(cmds))
        return t

    # ── Compte de Résultat ──
    elements.append(Paragraph('COMPTE DE RÉSULTAT', ParagraphStyle(
        'CRHead', parent=styles['Heading2'], fontSize=13, textColor=BLUE,
        spaceBefore=4, spaceAfter=8)))

    # Charges et produits côte à côte
    half = (W - 0.5 * cm) / 2

    def _mini_table(cats, noms, color_hdr, total_label, total_val):
        col_w = [half * 0.6, half * 0.4]
        data = [['Libellé', 'Montant (€)']]
        for cat_key in sorted(cats.keys()):
            cat = cats[cat_key]
            cat_name = noms.get(cat_key, cat_key)
            data.append([f'{cat_key}x – {cat_name}', _fmt_pdf(cat['total'])])
            for num in sorted(cat['comptes'].keys()):
                cpt = cat['comptes'][num]
                lib = f'   {num}'
                data.append([lib, _fmt_pdf(cpt['total'])])
        data.append([total_label, _fmt_pdf(total_val)])
        t = RLTable(data, colWidths=col_w, repeatRows=1)
        cmds = [
            ('BACKGROUND', (0, 0), (-1, 0), color_hdr),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTSIZE', (0, 1), (-1, -1), 7.5),
            ('TOPPADDING', (0, 0), (-1, -1), 2.5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
            ('GRID', (0, 0), (-1, -1), 0.3, colors.lightgrey),
            ('BOX', (0, 0), (-1, -1), 0.8, color_hdr),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('BACKGROUND', (0, -1), (-1, -1), GRAY_HDR),
            ('LINEABOVE', (0, -1), (-1, -1), 1, color_hdr),
        ]
        idx = 1
        for cat_key in sorted(cats.keys()):
            cmds.append(('FONTNAME', (0, idx), (-1, idx), 'Helvetica-Bold'))
            cmds.append(('BACKGROUND', (0, idx), (-1, idx), GRAY_CAT))
            idx += 1 + len(cats[cat_key]['comptes'])
        t.setStyle(TableStyle(cmds))
        return t

    t_charges = _mini_table(cr['charges'], NOMS_CAT_CR, RED,
                             'Total charges', cr['total_charges'])
    t_produits = _mini_table(cr['produits'], NOMS_CAT_CR, GREEN,
                              'Total produits', cr['total_produits'])

    # Titres charges/produits
    hdr_ch = RLTable([[
        Paragraph('<b>CHARGES</b>', ParagraphStyle('ch', parent=styles['Normal'],
                   textColor=RED, fontSize=10)),
        Paragraph('<b>PRODUITS</b>', ParagraphStyle('pr', parent=styles['Normal'],
                   textColor=GREEN, fontSize=10)),
    ]], colWidths=[half, half])
    hdr_ch.setStyle(TableStyle([('TOPPADDING', (0, 0), (-1, -1), 2),
                                 ('BOTTOMPADDING', (0, 0), (-1, -1), 2)]))
    elements.append(hdr_ch)

    side_by_side = RLTable([[t_charges, t_produits]],
                           colWidths=[half, half])
    side_by_side.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (0, -1), 0),
        ('RIGHTPADDING', (0, 0), (0, -1), 6),
        ('LEFTPADDING', (1, 0), (1, -1), 6),
        ('RIGHTPADDING', (1, 0), (1, -1), 0),
    ]))
    elements.append(side_by_side)

    # Résultat
    res = cr['resultat']
    res_color = GREEN if res >= 0 else RED
    res_label = 'Excédent' if res > 0 else ('Déficit' if res < 0 else 'Équilibre')
    res_data = [[f'{res_label} {annee}', _fmt_pdf(res) + ' €']]
    res_t = RLTable(res_data, colWidths=[W * 0.7, W * 0.3])
    res_t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), res_color),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (0, -1), 10),
        ('BOX', (0, 0), (-1, -1), 1, res_color),
        ('ROUNDEDCORNERS', [4]),
    ]))
    elements.append(Spacer(1, 0.3 * cm))
    elements.append(res_t)

    # ── Bilan ──
    if has_bilan:
        elements.append(Spacer(1, 0.5 * cm))
        elements.append(HRFlowable(width='100%', thickness=1, color=colors.lightgrey,
                                   spaceAfter=8))
        elements.append(Paragraph('BILAN', ParagraphStyle(
            'BHead', parent=styles['Heading2'], fontSize=13, textColor=BLUE,
            spaceBefore=4, spaceAfter=8)))

        def _bilan_col(sections, color_hdr, total_label, total_val):
            """Construit une colonne du bilan (actif ou passif)."""
            col_w = [half * 0.6, half * 0.4]
            data = [['Libellé', 'Montant (€)']]
            for sec_label, cats in sections:
                if not cats:
                    continue
                data.append([sec_label, ''])
                for cat_key in sorted(cats.keys()):
                    cat = cats[cat_key]
                    cat_name = NOMS_CAT_BILAN.get(cat_key, cat_key)
                    data.append([f'  {cat_key}x – {cat_name}', _fmt_pdf(cat['total'])])
                    for num in sorted(cat['comptes'].keys()):
                        cpt = cat['comptes'][num]
                        data.append([f'    {num}', _fmt_pdf(cpt['total'])])
            data.append([total_label, _fmt_pdf(total_val)])
            t = RLTable(data, colWidths=col_w, repeatRows=1)

            cmds = [
                ('BACKGROUND', (0, 0), (-1, 0), color_hdr),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 8),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('FONTSIZE', (0, 1), (-1, -1), 7.5),
                ('TOPPADDING', (0, 0), (-1, -1), 2.5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
                ('GRID', (0, 0), (-1, -1), 0.3, colors.lightgrey),
                ('BOX', (0, 0), (-1, -1), 0.8, color_hdr),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('BACKGROUND', (0, -1), (-1, -1), GRAY_HDR),
                ('LINEABOVE', (0, -1), (-1, -1), 1, color_hdr),
            ]
            # Lignes de section (titres intermédiaires)
            idx = 1
            for sec_label, cats in sections:
                if not cats:
                    continue
                cmds.append(('FONTNAME', (0, idx), (-1, idx), 'Helvetica-Bold'))
                cmds.append(('BACKGROUND', (0, idx), (-1, idx), BLUE))
                cmds.append(('TEXTCOLOR', (0, idx), (-1, idx), colors.white))
                cmds.append(('SPAN', (0, idx), (-1, idx)))
                idx += 1
                for cat_key in sorted(cats.keys()):
                    cmds.append(('FONTNAME', (0, idx), (-1, idx), 'Helvetica-Bold'))
                    cmds.append(('BACKGROUND', (0, idx), (-1, idx), GRAY_CAT))
                    idx += 1 + len(cats[cat_key]['comptes'])
            t.setStyle(TableStyle(cmds))
            return t

        actif_sections = [
            ('Actif immobilisé', bilan['actif_immo']),
            ('Stocks', bilan['actif_stocks']),
            ('Créances tiers', bilan['actif_tiers']),
            ('Trésorerie', bilan['actif_tresorerie']),
        ]
        passif_sections = [
            ('Capitaux permanents', bilan['passif_capitaux']),
            ('Dettes exploitation', bilan['passif_dettes_expl']),
        ]

        t_actif = _bilan_col(actif_sections, BLUE, 'Total Actif', bilan['total_actif'])
        t_passif = _bilan_col(passif_sections, GREEN, 'Total Passif', bilan['total_passif'])

        hdr_bp = RLTable([[
            Paragraph('<b>ACTIF</b>', ParagraphStyle('ac', parent=styles['Normal'],
                       textColor=BLUE, fontSize=10)),
            Paragraph('<b>PASSIF</b>', ParagraphStyle('pa', parent=styles['Normal'],
                       textColor=GREEN, fontSize=10)),
        ]], colWidths=[half, half])
        hdr_bp.setStyle(TableStyle([('TOPPADDING', (0, 0), (-1, -1), 2),
                                     ('BOTTOMPADDING', (0, 0), (-1, -1), 2)]))
        elements.append(hdr_bp)

        bilan_grid = RLTable([[t_actif, t_passif]], colWidths=[half, half])
        bilan_grid.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (0, -1), 0),
            ('RIGHTPADDING', (0, 0), (0, -1), 6),
            ('LEFTPADDING', (1, 0), (1, -1), 6),
            ('RIGHTPADDING', (1, 0), (1, -1), 0),
        ]))
        elements.append(bilan_grid)

        # Équilibre
        diff = round(abs(bilan['total_actif'] - bilan['total_passif']), 2)
        if diff <= 0.02:
            eq_color = GREEN
            eq_text = f'✓ Bilan équilibré  –  Total Actif = Total Passif = {_fmt_pdf(bilan["total_actif"])} €'
        else:
            eq_color = colors.HexColor('#e67e22')
            eq_text = (f'⚠ Écart Actif / Passif : {_fmt_pdf(diff)} €  '
                       f'(Actif {_fmt_pdf(bilan["total_actif"])} €  |  '
                       f'Passif {_fmt_pdf(bilan["total_passif"])} €)')
        eq_data = [[eq_text]]
        eq_t = RLTable(eq_data, colWidths=[W])
        eq_t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), eq_color),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(Spacer(1, 0.3 * cm))
        elements.append(eq_t)

    # ── Pied de page ──
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
    resp.headers['Content-Disposition'] = f'attachment; filename=cr_bilan_{annee}.pdf'
    return resp
