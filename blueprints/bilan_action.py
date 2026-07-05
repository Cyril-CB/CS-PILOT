"""
Blueprint bilan_action_bp - Bilan action (budget prévisionnel et réalisé).

Contrairement à la page « Bilan secteurs/actions » (bilan_secteurs_bp) qui est
une photo de la comptabilité détaillée sur une année clôturée avec récupération
analytique, cette page sert à CONSTRUIRE le budget prévisionnel d'une action et
à construire/vérifier son réalisé avant la clôture.

Fonctionnement :
- Sélection d'une action (définie dans le plan comptable analytique) et d'une année.
- Enregistrement par action / année / onglet (prévisionnel, réalisé).
- Onglet PRÉVISIONNEL en 3 parties :
    1. Comptes de charges 60xxxx / 61xxxx / 62xxxx (sections séparées) et comptes
       de produits (70xxxx, 74xxxx, autres) : liste déroulante des comptes, ajout
       de lignes avec montant et commentaire.
    2. Salaires : liste des salariés sous contrat sur l'année (simulateur de paie,
       même principe que budget_previsionnel) ; coût brut au prorata des heures
       passées sur l'action, salaire chargé et taxe sur salaire (calcul simplifié).
    3. Taux de logistique (site1/site2/global, partagé avec bilan_secteurs) et
       bénévoles (liste déroulante + temps + commentaire).
- Onglet RÉALISÉ : reprend le réalisé comptable (import BI) en comparatif avec le
  prévisionnel, reporte salaires et taux de logistique (modifiables) et bénévoles.
- Export PDF (bilan simplifié + récap salariés + bénévoles) pour les deux onglets.
  Les salaires sont regroupés : 641100 (brut), 645100 (charges sociales),
  631100 (taxe sur salaires).

Accès : directeur et comptable (comme Budget prévisionnel).
"""
import io
import json
from datetime import date

from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, jsonify, make_response)

from database import get_db
from utils import login_required
# Réutilise les paramètres et calculs de paie du simulateur (source unique).
from blueprints.budget import PAIE_DEFAULTS, _paie_anciennete_annees

bilan_action_bp = Blueprint('bilan_action_bp', __name__)

# Taux par défaut (modifiables dans l'interface).
TAUX_CHARGE_DEFAUT = 27.0   # charges patronales : coût brut + 27 %
TAUX_TAXE_DEFAUT = 4.25     # taxe sur les salaires (taux de base simplifié)

# Comptes utilisés pour regrouper la masse salariale dans le bilan.
COMPTE_BRUT = '641100'      # rémunérations brutes
COMPTE_TAXE = '631100'      # taxe sur les salaires
COMPTE_CHARGES = '645100'   # charges de sécurité sociale

ONGLETS = ('previsionnel', 'realise')

NOMS_CATEGORIES = {
    '60': 'Achats', '61': 'Services extérieurs', '62': 'Autres services ext.',
    '63': 'Impôts et taxes', '64': 'Charges de personnel',
    '65': 'Autres charges de gestion', '66': 'Charges financières',
    '67': 'Charges exceptionnelles', '68': 'Dotations amort.',
    '70': 'Ventes/prestations', '71': 'Production stockée',
    '72': 'Production immobilisée', '73': 'Produits nets partiels',
    '74': 'Subventions', '75': 'Autres produits de gestion',
    '76': 'Produits financiers', '77': 'Produits exceptionnels',
    '78': 'Reprises amort.', '79': 'Transferts de charges',
}


# ── Permissions ───────────────────────────────────────────────────────────────

def _peut_acceder():
    return session.get('profil') in ('directeur', 'comptable')


def _peut_modifier():
    return session.get('profil') in ('directeur', 'comptable')


# ── Helpers ───────────────────────────────────────────────────────────────────

def _num(value, default=0.0):
    """Convertit une valeur saisie (str/None) en float, avec valeur par défaut."""
    try:
        if value is None or value == '':
            return float(default)
        if isinstance(value, str):
            value = value.replace(',', '.')
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _fmt(n):
    """Formate un nombre en style français : 1 234,56."""
    return f'{n:,.2f}'.replace(',', '\xa0').replace('.', ',')


def _get_libelles_pcg(conn):
    """Retourne un dict {compte_num: libelle} depuis le plan comptable général."""
    rows = conn.execute('SELECT compte_num, libelle FROM plan_comptable_general').fetchall()
    return {row['compte_num']: row['libelle'] for row in rows}


def _calc_salarie(s, params):
    """Calcule la paie d'un salarié pour l'action à partir de ses paramètres.

    Brut mensuel (même formule que le simulateur de paie) :
        (socle + (pesée + ancienneté + compétence) * point) / 12 * ratio_temps
        + maintien
    Coût brut sur l'action (taux horaire annuel) :
        coût brut = (brut mensuel * 12) / (temps hebdo * 52) * heures sur l'action
    Charges sociales = coût brut * taux chargé (ex. 27 %).
    Taxe sur salaire = coût brut * taux taxe (ex. 4,25 %, calcul simplifié).
    """
    socle = _num(params.get('socle'), PAIE_DEFAULTS['salaire_socle'])
    point = _num(params.get('point'), PAIE_DEFAULTS['valeur_point'])
    temps_plein = _num(params.get('temps_plein'), PAIE_DEFAULTS['temps_plein']) or 35.0

    temps_hebdo = _num(s.get('temps_hebdo'), temps_plein)
    if temps_hebdo <= 0:
        temps_hebdo = temps_plein
    pesee = _num(s.get('pesee'))
    anciennete = _num(s.get('anciennete'))
    competence = _num(s.get('competence'))
    maintien = _num(s.get('maintien'))
    heures = _num(s.get('heures_action'))
    taux_charge = _num(s.get('taux_charge'), TAUX_CHARGE_DEFAUT)
    taux_taxe = _num(s.get('taux_taxe'), TAUX_TAXE_DEFAUT)

    ratio = (temps_hebdo / temps_plein) if temps_plein else 1.0
    brut_mensuel = (socle + (pesee + anciennete + competence) * point) / 12.0 * ratio + maintien
    heures_annuelles = temps_hebdo * 52.0
    taux_horaire = (brut_mensuel * 12.0 / heures_annuelles) if heures_annuelles else 0.0
    cout_brut = taux_horaire * heures
    charges_sociales = cout_brut * taux_charge / 100.0
    salaire_charge = cout_brut + charges_sociales
    taxe = cout_brut * taux_taxe / 100.0

    return {
        'brut_mensuel': round(brut_mensuel, 2),
        'taux_horaire': round(taux_horaire, 4),
        'cout_brut': round(cout_brut, 2),
        'charges_sociales': round(charges_sociales, 2),
        'salaire_charge': round(salaire_charge, 2),
        'taxe': round(taxe, 2),
    }


def _employes_actifs_annee(conn, annee):
    """Salariés avec un contrat CDI/CDD valide sur l'année concernée.

    - Année passée ou en cours : tout contrat chevauchant l'année (même terminé).
    - Année à venir (> année courante) : uniquement les contrats actifs aujourd'hui.
    On retient le contrat le plus récent par salarié.
    """
    today = date.today()
    if annee > today.year:
        start = end = today.isoformat()
    else:
        start = f'{annee}-01-01'
        end = f'{annee}-12-31'

    rows = conn.execute('''
        SELECT u.id, u.nom, u.prenom, u.pesee, u.competence, u.maintien,
               c.type_contrat, c.date_debut, c.date_fin, c.temps_hebdo
        FROM users u
        JOIN contrats c ON c.user_id = u.id
        WHERE c.type_contrat IN ('CDI', 'CDD')
          AND (u.profil IS NULL OR u.profil != 'prestataire')
          AND c.date_debut <= ?
          AND (c.date_fin IS NULL OR c.date_fin >= ?)
        ORDER BY u.nom, u.prenom, c.date_debut DESC
    ''', (end, start)).fetchall()

    seen = {}
    for r in rows:
        if r['id'] not in seen:  # premier = contrat le plus récent (ORDER BY date_debut DESC)
            seen[r['id']] = r

    employes = []
    for u in seen.values():
        employes.append({
            'user_id': u['id'],
            'nom': u['nom'] or '',
            'prenom': u['prenom'] or '',
            'pesee': u['pesee'] if u['pesee'] is not None else 0,
            'competence': u['competence'] if u['competence'] is not None else 0,
            'maintien': u['maintien'] if u['maintien'] is not None else 0,
            'temps_hebdo': u['temps_hebdo'],
            'type_contrat': u['type_contrat'],
            'anciennete': _paie_anciennete_annees(u['date_debut'], annee),
        })
    employes.sort(key=lambda e: (e['nom'], e['prenom']))
    return employes


def _realise_compta(conn, action_id, annee):
    """Charges (6x) et produits (7x) réalisés depuis le FEC, regroupés par compte,
    pour les comptes rattachés à l'action dans le plan comptable analytique."""
    rows = conn.execute('''
        SELECT d.compte_num, d.libelle, SUM(d.montant) AS montant
        FROM bilan_fec_donnees d
        WHERE d.annee = ?
          AND EXISTS (
              SELECT 1 FROM comptabilite_comptes c
              WHERE c.action_id = ?
                AND (d.compte_num LIKE c.compte_num || '%'
                     OR d.code_analytique = c.compte_num)
          )
        GROUP BY d.compte_num, d.libelle
        ORDER BY d.compte_num
    ''', (annee, action_id)).fetchall()

    pcg = _get_libelles_pcg(conn)
    charges, produits = {}, {}
    for d in rows:
        compte = d['compte_num']
        if not compte:
            continue
        cat = compte[:2]
        montant = d['montant'] or 0
        libelle = pcg.get(compte) or d['libelle'] or compte
        # On se limite aux charges 60/61/62 et aux produits 7x, à l'image de la
        # Partie 1 du prévisionnel. Les charges de personnel (64x), la taxe sur
        # salaires (63x) et la logistique sont gérées séparément (section salaires
        # reportée du prévisionnel, taux de logistique) pour éviter un double
        # comptage avec le réalisé comptable importé.
        if cat in ('60', '61', '62'):
            target = charges
        elif compte[0] == '7':
            target = produits
        else:
            continue
        target.setdefault(cat, {'comptes': {}, 'total': 0})
        target[cat]['comptes'].setdefault(compte, {'libelle': libelle, 'total': 0})
        target[cat]['comptes'][compte]['total'] += montant
        target[cat]['total'] += montant

    for groupe in (charges, produits):
        for cat in groupe.values():
            cat['total'] = round(cat['total'], 2)
            for c in cat['comptes'].values():
                c['total'] = round(c['total'], 2)
    return charges, produits


def _taux_logistique_val(conn, annee, selection):
    """Valeur (%) du taux de logistique sélectionné pour l'année."""
    row = conn.execute(
        'SELECT * FROM bilan_taux_logistique WHERE annee = ?', (annee,)
    ).fetchone()
    if not row:
        return 0.0
    if selection == 'site1':
        return row['taux_site1'] or 0.0
    if selection == 'site2':
        return row['taux_site2'] or 0.0
    return row['taux_global'] or 0.0


def _summary(conn, donnees, annee, action_id, onglet):
    """Calcule l'ensemble des totaux d'un onglet (source de vérité serveur).

    Charges totales = comptes (60/61/62) + masse salariale chargée
    (coût brut + charges sociales + taxe). La logistique s'applique sur ce total.
    """
    donnees = donnees or {}
    params = donnees.get('salaire_params') or {}

    # --- Salaires ---
    salaries_out = []
    tot_brut = tot_charges_soc = tot_taxe = 0.0
    for s in (donnees.get('salaries') or []):
        calc = _calc_salarie(s, params)
        tot_brut += calc['cout_brut']
        tot_charges_soc += calc['charges_sociales']
        tot_taxe += calc['taxe']
        out = dict(s)
        out.update(calc)
        salaries_out.append(out)
    masse_salariale = tot_brut + tot_charges_soc + tot_taxe

    # --- Comptes de charges / produits ---
    if onglet == 'realise':
        charges_cat, produits_cat = _realise_compta(conn, action_id, annee)
        charges_comptes = sum(c['total'] for c in charges_cat.values())
        produits_total = sum(p['total'] for p in produits_cat.values())
        for m in (donnees.get('comptes_manuels') or []):
            montant = _num(m.get('montant'))
            num = str(m.get('compte_num') or '')
            if num[:1] == '7':
                produits_total += montant
            else:
                charges_comptes += montant
    else:
        charges_comptes = 0.0
        for key in ('charges_60', 'charges_61', 'charges_62'):
            for ligne in (donnees.get(key) or []):
                charges_comptes += _num(ligne.get('montant'))
        produits_total = sum(_num(ligne.get('montant')) for ligne in (donnees.get('produits') or []))

    charges_comptes = round(charges_comptes, 2)
    produits_total = round(produits_total, 2)

    # --- Logistique ---
    selection = (donnees.get('logistique') or {}).get('selection', 'global')
    taux_val = _taux_logistique_val(conn, annee, selection)
    total_charges = round(charges_comptes + masse_salariale, 2)   # base de la logistique
    logistique = round(total_charges * taux_val / 100.0, 2)
    resultat_sans = round(produits_total - total_charges, 2)
    resultat_avec = round(produits_total - total_charges - logistique, 2)

    return {
        'salaries': salaries_out,
        'total_brut': round(tot_brut, 2),
        'total_charges_sociales': round(tot_charges_soc, 2),
        'total_taxe': round(tot_taxe, 2),
        'masse_salariale': round(masse_salariale, 2),
        'charges_comptes': charges_comptes,
        'produits_total': produits_total,
        'taux_selection': selection,
        'taux_logistique': taux_val,
        'logistique': logistique,
        'total_charges': total_charges,
        'total_produits': produits_total,
        'resultat_sans': resultat_sans,
        'resultat_avec': resultat_avec,
    }


# ── Page principale ───────────────────────────────────────────────────────────

@bilan_action_bp.route('/bilan-action')
@login_required
def bilan_action():
    """Affiche la page Bilan action."""
    if not _peut_acceder():
        flash('Accès non autorisé.', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    try:
        actions = conn.execute(
            'SELECT id, nom FROM comptabilite_actions ORDER BY nom'
        ).fetchall()
        annee_courante = date.today().year
        annees = list(range(annee_courante + 1, annee_courante - 5, -1))
        # Présélection via query (lien depuis subventions / barre de recherche) :
        # ?action_id= (+ ?annee= et ?onglet=previsionnel|realise).
        action_preselect = request.args.get('action_id', type=int)
        annee_preselect = request.args.get('annee', type=int)
        if annee_preselect not in annees:
            annee_preselect = None
        onglet_preselect = request.args.get('onglet')
        if onglet_preselect not in ('previsionnel', 'realise'):
            onglet_preselect = 'previsionnel'
        return render_template(
            'bilan_action.html',
            actions=actions,
            annees=annees,
            annee_courante=annee_courante,
            action_preselect=action_preselect,
            annee_preselect=annee_preselect,
            onglet_preselect=onglet_preselect,
        )
    finally:
        conn.close()


# ── API : contexte (salariés, bénévoles, taux, comptes) ───────────────────────

@bilan_action_bp.route('/api/bilan-action/contexte')
@login_required
def api_contexte():
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé.'}), 403
    annee = request.args.get('annee', type=int)
    if not annee:
        return jsonify({'error': 'Année requise.'}), 400

    conn = get_db()
    try:
        employes = _employes_actifs_annee(conn, annee)
        benevoles = [dict(r) for r in conn.execute(
            'SELECT id, nom FROM benevoles ORDER BY nom'
        ).fetchall()]
        taux_row = conn.execute(
            'SELECT * FROM bilan_taux_logistique WHERE annee = ?', (annee,)
        ).fetchone()
        taux = {
            'taux_site1': taux_row['taux_site1'] if taux_row else 0,
            'taux_site2': taux_row['taux_site2'] if taux_row else 0,
            'taux_global': taux_row['taux_global'] if taux_row else 0,
        }
        import_existe = conn.execute(
            'SELECT COUNT(*) AS n FROM bilan_fec_imports WHERE annee = ?', (annee,)
        ).fetchone()['n'] > 0
        comptes_pcg = [dict(r) for r in conn.execute(
            'SELECT compte_num, libelle FROM plan_comptable_general ORDER BY compte_num'
        ).fetchall()]
        return jsonify({
            'employes': employes,
            'benevoles': benevoles,
            'taux': taux,
            'import_existe': import_existe,
            'comptes_pcg': comptes_pcg,
            'defaults': {
                'socle': PAIE_DEFAULTS['salaire_socle'],
                'point': PAIE_DEFAULTS['valeur_point'],
                'temps_plein': PAIE_DEFAULTS['temps_plein'],
                'taux_charge': TAUX_CHARGE_DEFAUT,
                'taux_taxe': TAUX_TAXE_DEFAUT,
            },
            'comptes_salaire': {
                'brut': COMPTE_BRUT, 'taxe': COMPTE_TAXE, 'charges': COMPTE_CHARGES,
            },
        })
    finally:
        conn.close()


# ── API : chargement des données d'un onglet ──────────────────────────────────

@bilan_action_bp.route('/api/bilan-action/donnees')
@login_required
def api_donnees():
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé.'}), 403
    annee = request.args.get('annee', type=int)
    action_id = request.args.get('action_id', type=int)
    onglet = request.args.get('onglet', 'previsionnel')
    if not annee or not action_id:
        return jsonify({'error': 'Action et année requises.'}), 400
    if onglet not in ONGLETS:
        onglet = 'previsionnel'

    conn = get_db()
    try:
        row = conn.execute(
            'SELECT donnees FROM bilan_action_data WHERE action_id = ? AND annee = ? AND onglet = ?',
            (action_id, annee, onglet)
        ).fetchone()
        donnees = json.loads(row['donnees']) if row and row['donnees'] else None

        # Le réalisé reprend le prévisionnel (salaires, logistique, comparatif).
        previsionnel = None
        if onglet == 'realise':
            prev_row = conn.execute(
                'SELECT donnees FROM bilan_action_data WHERE action_id = ? AND annee = ? AND onglet = ?',
                (action_id, annee, 'previsionnel')
            ).fetchone()
            previsionnel = json.loads(prev_row['donnees']) if prev_row and prev_row['donnees'] else None

        summary = _summary(conn, donnees, annee, action_id, onglet) if donnees else None
        return jsonify({
            'found': donnees is not None,
            'donnees': donnees,
            'previsionnel': previsionnel,
            'summary': summary,
        })
    finally:
        conn.close()


# ── API : sauvegarde d'un onglet ──────────────────────────────────────────────

@bilan_action_bp.route('/api/bilan-action/save', methods=['POST'])
@login_required
def api_save():
    if not _peut_modifier():
        return jsonify({'error': 'Accès non autorisé.'}), 403
    data = request.get_json(silent=True) or {}
    annee = data.get('annee')
    action_id = data.get('action_id')
    onglet = data.get('onglet', 'previsionnel')
    donnees = data.get('donnees') or {}
    try:
        annee = int(annee)
        action_id = int(action_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'Action et année requises.'}), 400
    if onglet not in ONGLETS:
        return jsonify({'error': 'Onglet invalide.'}), 400

    conn = get_db()
    try:
        action = conn.execute(
            'SELECT id FROM comptabilite_actions WHERE id = ?', (action_id,)
        ).fetchone()
        if not action:
            return jsonify({'error': 'Action introuvable.'}), 404

        summary = _summary(conn, donnees, annee, action_id, onglet)
        conn.execute('''
            INSERT INTO bilan_action_data
                (action_id, annee, onglet, donnees, total_charges, total_produits, updated_by, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(action_id, annee, onglet) DO UPDATE SET
                donnees = excluded.donnees,
                total_charges = excluded.total_charges,
                total_produits = excluded.total_produits,
                updated_by = excluded.updated_by,
                updated_at = CURRENT_TIMESTAMP
        ''', (action_id, annee, onglet, json.dumps(donnees, ensure_ascii=False),
              summary['total_charges'], summary['total_produits'],
              session.get('user_id')))
        conn.commit()
        return jsonify({'success': True, 'summary': summary})
    finally:
        conn.close()


# ── API : réalisé comptable (import BI) ───────────────────────────────────────

@bilan_action_bp.route('/api/bilan-action/realise-compta')
@login_required
def api_realise_compta():
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé.'}), 403
    annee = request.args.get('annee', type=int)
    action_id = request.args.get('action_id', type=int)
    if not annee or not action_id:
        return jsonify({'error': 'Action et année requises.'}), 400

    conn = get_db()
    try:
        import_existe = conn.execute(
            'SELECT COUNT(*) AS n FROM bilan_fec_imports WHERE annee = ?', (annee,)
        ).fetchone()['n'] > 0
        if not import_existe:
            return jsonify({'import_existe': False, 'charges': {}, 'produits': {}})
        charges, produits = _realise_compta(conn, action_id, annee)
        return jsonify({
            'import_existe': True,
            'charges': charges,
            'produits': produits,
        })
    finally:
        conn.close()


# ── API : taux de logistique (valeurs partagées par année) ────────────────────

@bilan_action_bp.route('/api/bilan-action/taux-logistique', methods=['POST'])
@login_required
def api_taux_logistique():
    if not _peut_modifier():
        return jsonify({'error': 'Accès non autorisé.'}), 403
    data = request.get_json(silent=True) or {}
    annee = data.get('annee')
    try:
        annee = int(annee)
    except (TypeError, ValueError):
        return jsonify({'error': 'Année requise.'}), 400

    conn = get_db()
    try:
        # Met à jour les valeurs (partagées avec bilan_secteurs) sans toucher à
        # la sélection propre à la page bilan_secteurs (taux_selectionne).
        conn.execute('''
            INSERT INTO bilan_taux_logistique (annee, taux_site1, taux_site2, taux_global)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(annee) DO UPDATE SET
                taux_site1 = excluded.taux_site1,
                taux_site2 = excluded.taux_site2,
                taux_global = excluded.taux_global,
                updated_at = CURRENT_TIMESTAMP
        ''', (annee, _num(data.get('taux_site1')), _num(data.get('taux_site2')),
              _num(data.get('taux_global'))))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


# ── API : export PDF ──────────────────────────────────────────────────────────

@bilan_action_bp.route('/api/bilan-action/export-pdf')
@login_required
def api_export_pdf():
    if not _peut_acceder():
        flash('Accès non autorisé.', 'error')
        return redirect(url_for('bilan_action_bp.bilan_action'))
    annee = request.args.get('annee', type=int)
    action_id = request.args.get('action_id', type=int)
    onglet = request.args.get('onglet', 'previsionnel')
    if onglet not in ONGLETS:
        onglet = 'previsionnel'
    if not annee or not action_id:
        flash('Action et année requises.', 'error')
        return redirect(url_for('bilan_action_bp.bilan_action'))

    conn = get_db()
    try:
        row = conn.execute(
            'SELECT donnees FROM bilan_action_data WHERE action_id = ? AND annee = ? AND onglet = ?',
            (action_id, annee, onglet)
        ).fetchone()
        donnees = json.loads(row['donnees']) if row and row['donnees'] else {}
        action = conn.execute(
            'SELECT nom FROM comptabilite_actions WHERE id = ?', (action_id,)
        ).fetchone()
        action_nom = action['nom'] if action else f'#{action_id}'

        summary = _summary(conn, donnees, annee, action_id, onglet)

        # Détail des comptes pour le bilan simplifié.
        charges_cat, produits_cat = _bilan_categories(conn, donnees, summary, annee, action_id, onglet)

        pdf_bytes = _build_pdf(action_nom, annee, onglet, donnees, summary,
                               charges_cat, produits_cat)
        response = make_response(pdf_bytes)
        response.headers['Content-Type'] = 'application/pdf'
        filename = f'bilan_action_{action_id}_{annee}_{onglet}.pdf'
        response.headers['Content-Disposition'] = f'attachment; filename={filename}'
        return response
    finally:
        conn.close()


def _bilan_categories(conn, donnees, summary, annee, action_id, onglet):
    """Construit les catégories charges/produits (style bilan_secteurs) pour le PDF,
    en intégrant les lignes de salaires (641100 / 645100 / 631100)."""
    charges, produits = {}, {}

    def _add(groupe, compte, libelle, montant):
        if not compte:
            return
        cat = str(compte)[:2]
        groupe.setdefault(cat, {'comptes': {}, 'total': 0})
        groupe[cat]['comptes'].setdefault(compte, {'libelle': libelle, 'total': 0})
        groupe[cat]['comptes'][compte]['total'] += montant
        groupe[cat]['total'] += montant

    pcg = _get_libelles_pcg(conn)

    if onglet == 'realise':
        rc, rp = _realise_compta(conn, action_id, annee)
        charges, produits = rc, rp
        for m in (donnees.get('comptes_manuels') or []):
            num = str(m.get('compte_num') or '')
            lib = m.get('libelle') or pcg.get(num) or num
            montant = _num(m.get('montant'))
            _add(produits if num[:1] == '7' else charges, num, lib, montant)
    else:
        for key in ('charges_60', 'charges_61', 'charges_62'):
            for ligne in (donnees.get(key) or []):
                num = str(ligne.get('compte_num') or '')
                lib = ligne.get('libelle') or pcg.get(num) or num
                _add(charges, num, lib, _num(ligne.get('montant')))
        for ligne in (donnees.get('produits') or []):
            num = str(ligne.get('compte_num') or '')
            lib = ligne.get('libelle') or pcg.get(num) or num
            _add(produits, num, lib, _num(ligne.get('montant')))

    # Lignes de salaires regroupées.
    if summary['total_brut']:
        _add(charges, COMPTE_BRUT, 'Rémunérations brutes', summary['total_brut'])
    if summary['total_charges_sociales']:
        _add(charges, COMPTE_CHARGES, 'Charges de sécurité sociale', summary['total_charges_sociales'])
    if summary['total_taxe']:
        _add(charges, COMPTE_TAXE, 'Taxe sur les salaires', summary['total_taxe'])

    for groupe in (charges, produits):
        for cat in groupe.values():
            cat['total'] = round(cat['total'], 2)
            for c in cat['comptes'].values():
                c['total'] = round(c['total'], 2)
    return charges, produits


def _build_pdf(action_nom, annee, onglet, donnees, summary, charges, produits):
    """Génère le PDF : bilan simplifié + récap salariés + récap bénévoles."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import (SimpleDocTemplate, Table as RLTable,
                                    TableStyle, Paragraph, Spacer, PageBreak)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            topMargin=1.5 * cm, bottomMargin=1.5 * cm,
                            leftMargin=1.5 * cm, rightMargin=1.5 * cm)
    elements = []
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('T', parent=styles['Heading1'],
                                 alignment=TA_CENTER, fontSize=14, spaceAfter=6)
    subtitle_style = ParagraphStyle('S', parent=styles['Normal'],
                                    alignment=TA_CENTER, fontSize=10, spaceAfter=14)
    section_style = ParagraphStyle('Sec', parent=styles['Heading2'],
                                   fontSize=12, spaceAfter=6, spaceBefore=12)
    normal = styles['Normal']

    libelle_onglet = 'Prévisionnel' if onglet == 'previsionnel' else 'Réalisé'
    elements.append(Paragraph('BILAN ACTION', title_style))
    elements.append(Paragraph(
        f'Action : {action_nom} — Année {annee} — {libelle_onglet}', subtitle_style))

    def _section(categories, label, color_header):
        elements.append(Paragraph(label, section_style))
        if not categories:
            elements.append(Paragraph('Aucune donnée.', normal))
            return
        data = [['Compte', 'Libellé', 'Montant']]
        cat_rows = []
        for cat_code in sorted(categories.keys()):
            cat = categories[cat_code]
            cat_name = NOMS_CATEGORIES.get(cat_code, f'Catégorie {cat_code}')
            cat_rows.append(len(data))
            data.append([f'{cat_code} - {cat_name}', '', _fmt(cat['total']) + ' €'])
            for cpt_num in sorted(cat['comptes'].keys()):
                cpt = cat['comptes'][cpt_num]
                data.append([f'   {cpt_num}', cpt['libelle'], _fmt(cpt['total']) + ' €'])
        t = RLTable(data, colWidths=[4 * cm, 9 * cm, 4 * cm], repeatRows=1)
        style_cmds = [
            ('BACKGROUND', (0, 0), (-1, 0), color_header),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('TOPPADDING', (0, 0), (-1, 0), 6),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('TOPPADDING', (0, 1), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 3),
            ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
        ]
        for ri in cat_rows:
            style_cmds.append(('FONTNAME', (0, ri), (-1, ri), 'Helvetica-Bold'))
            style_cmds.append(('BACKGROUND', (0, ri), (-1, ri), colors.HexColor('#F0F0F0')))
        t.setStyle(TableStyle(style_cmds))
        elements.append(t)

    _section(charges, 'Charges', colors.HexColor('#C0392B'))
    _section(produits, 'Produits', colors.HexColor('#27AE60'))

    # Résumé.
    elements.append(Spacer(1, 0.5 * cm))
    summary_data = [
        ['Total charges (comptes + salaires)', _fmt(summary['total_charges']) + ' €'],
        ['Total produits', _fmt(summary['total_produits']) + ' €'],
        [f"Logistique ({_fmt(summary['taux_logistique'])} % — {summary['taux_selection']})",
         _fmt(summary['logistique']) + ' €'],
        ['Résultat sans logistique', _fmt(summary['resultat_sans']) + ' €'],
        ['Résultat avec logistique', _fmt(summary['resultat_avec']) + ' €'],
    ]
    summary_t = RLTable(summary_data, colWidths=[11 * cm, 6 * cm])
    summary_t.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
        ('BACKGROUND', (0, 3), (-1, 4), colors.HexColor('#FFF9C4')),
    ]))
    elements.append(summary_t)

    # Page récap salariés.
    salaries = summary.get('salaries') or []
    if salaries:
        elements.append(PageBreak())
        elements.append(Paragraph('Récapitulatif des salariés', section_style))
        data = [['Salarié', 'Temps hebdo', 'Brut mensuel', 'Heures action',
                 'Coût brut', 'Charges soc.', 'Taxe', 'Salaire chargé']]
        for s in salaries:
            nom = (str(s.get('nom') or '') + ' ' + str(s.get('prenom') or '')).strip() or 'Salarié'
            data.append([
                nom,
                _fmt(_num(s.get('temps_hebdo'))),
                _fmt(s.get('brut_mensuel', 0)),
                _fmt(_num(s.get('heures_action'))),
                _fmt(s.get('cout_brut', 0)),
                _fmt(s.get('charges_sociales', 0)),
                _fmt(s.get('taxe', 0)),
                _fmt(s.get('salaire_charge', 0)),
            ])
        data.append(['TOTAL', '', '', '',
                     _fmt(summary['total_brut']),
                     _fmt(summary['total_charges_sociales']),
                     _fmt(summary['total_taxe']),
                     _fmt(round(summary['total_brut'] + summary['total_charges_sociales'], 2))])
        t = RLTable(data, repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495E')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#F0F0F0')),
            ('FONTSIZE', (0, 0), (-1, -1), 7.5),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        elements.append(t)

    # Page récap bénévoles.
    benevoles = donnees.get('benevoles') or []
    if benevoles:
        elements.append(PageBreak())
        elements.append(Paragraph('Récapitulatif des bénévoles', section_style))
        data = [['Bénévole', 'Heures', 'Commentaire']]
        total_h = 0.0
        for b in benevoles:
            h = _num(b.get('heures'))
            total_h += h
            data.append([b.get('nom') or 'Bénévole', _fmt(h), b.get('commentaire') or ''])
        data.append(['TOTAL', _fmt(total_h), ''])
        t = RLTable(data, colWidths=[6 * cm, 3 * cm, 8 * cm], repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#16A085')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#F0F0F0')),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        elements.append(t)

    doc.build(elements)
    buffer.seek(0)
    return buffer.getvalue()
