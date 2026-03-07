"""
Blueprint alsh_bp - Module Analyse ALSH.

Fonctionnalites :
- Configuration des tranches d'age et des periodes
- Mapping des codes analytiques (max 3 par cellule periode × tranche d'age)
- Saisie des donnees NOE (heures de presence, nombre d'enfants differents)
- Tableau de bord : croisement donnees comptables bilan_fec / donnees NOE
- Calcul : heures, enfants, charges, produits, resultat, cout/heure,
           cout/enfant, taux de couverture
- Filtrage par date : si des periodes_vacances sont configurees pour l'annee,
  les donnees FEC sont restreintes aux mois couverts par chaque periode
  (evite le double-comptage quand le meme code analytique est utilise pour
  plusieurs periodes de vacances)
- Comparaison N/N-1/N-2 si les donnees sont disponibles
- Accessible aux profils directeur et comptable
"""
from datetime import datetime, date as _date
from flask import (Blueprint, render_template, request, session,
                   flash, redirect, url_for, jsonify)
from database import get_db
from utils import login_required

alsh_bp = Blueprint('alsh_bp', __name__)


def _peut_acceder():
    return session.get('profil') in ('directeur', 'comptable')


# ── Correspondance periodes vacances (par mots-cles) ─────────────────────────

import unicodedata

_VACATION_KEYWORDS = {
    'hiver':     ['hiver'],
    'printemps': ['printemps', 'paques'],
    'ete':       ['ete', 'estival'],
    'toussaint': ['toussaint', 'automne'],
    'noel':      ['noel'],
}


def _normaliser(s):
    """Normalise une chaîne (minuscules, sans accents) pour la comparaison."""
    return unicodedata.normalize('NFD', s).encode('ascii', 'ignore').decode().lower()


def _detecter_type_vacances(nom):
    """Retourne le type de vacances ('hiver', 'printemps', ...) depuis un nom, ou None."""
    nom_norm = _normaliser(nom)
    for type_vac, kws in _VACATION_KEYWORDS.items():
        if any(kw in nom_norm for kw in kws):
            return type_vac
    return None


def _mois_couverts_annee(date_debut_str, date_fin_str, annee):
    """Retourne le set des mois (1-12) couverts par une plage de dates dans l'annee donnee."""
    try:
        debut = _date.fromisoformat(date_debut_str)
        fin = _date.fromisoformat(date_fin_str)
    except (ValueError, TypeError, AttributeError):
        return set()
    if debut > fin:
        return set()
    mois = set()
    y, m = debut.year, debut.month
    end_y, end_m = fin.year, fin.month
    while (y, m) <= (end_y, end_m):
        if y == annee:
            mois.add(m)
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return mois


def _build_periode_mois_filter(conn, periodes, annee):
    """
    Construit un dict {periode_id: (set_of_months_or_None, label_or_None)}.

    Pour chaque alsh_periode de type 'vacances' dont le nom correspond a une
    periodes_vacances de la BD (via mots-cles), retourne les mois couverts
    par cette vacation pour l'annee donnee.

    Pour les autres periodes (Mercredis, custom, ou vacances sans correspondance),
    retourne (None, None) = pas de filtre de date.
    """
    # Chercher les periodes_vacances proches de l'annee (annee-1 a annee+1 pour
    # les vacances de Noel qui chevauchent deux annees civiles)
    years = (str(annee - 1), str(annee), str(annee + 1))
    ph = ','.join('?' * len(years))
    rows = conn.execute(
        "SELECT nom, date_debut, date_fin FROM periodes_vacances "
        f"WHERE strftime('%Y', date_debut) IN ({ph}) "
        f"  OR strftime('%Y', date_fin)   IN ({ph})",
        years * 2
    ).fetchall()

    # Regrouper par type, en ne gardant que les mois dans l'annee cible
    vacances_par_type = {}  # {type_vac: {mois, date_debut, date_fin}}
    for row in rows:
        tv = _detecter_type_vacances(row['nom'])
        if not tv:
            continue
        mois = _mois_couverts_annee(row['date_debut'], row['date_fin'], annee)
        if not mois:
            continue
        if tv not in vacances_par_type:
            vacances_par_type[tv] = {
                'mois': set(),
                'date_debut': row['date_debut'],
                'date_fin': row['date_fin'],
            }
        vacances_par_type[tv]['mois'] |= mois

    result = {}
    for p in periodes:
        if p['type'] == 'vacances':
            tv = _detecter_type_vacances(p['nom'])
            if tv and tv in vacances_par_type:
                vd = vacances_par_type[tv]
                try:
                    d_debut = _date.fromisoformat(vd['date_debut'])
                    d_fin = _date.fromisoformat(vd['date_fin'])
                    label = (
                        f"{d_debut.day:02d}/{d_debut.month:02d}"
                        f" – {d_fin.day:02d}/{d_fin.month:02d}/{d_fin.year}"
                    )
                except Exception:
                    label = None
                result[p['id']] = (vd['mois'], label)
            else:
                result[p['id']] = (None, None)
        else:
            result[p['id']] = (None, None)
    return result


# ── Page principale ──────────────────────────────────────────────────────────

@alsh_bp.route('/analyse-alsh')
@login_required
def analyse_alsh():
    """Affiche le module Analyse ALSH."""
    if not _peut_acceder():
        flash('Accès non autorisé.', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    now = datetime.now()
    annee_courante = now.year
    annees = list(range(annee_courante - 3, annee_courante + 2))

    conn = get_db()
    try:
        annees_noe = conn.execute(
            'SELECT DISTINCT annee FROM alsh_saisie_noe ORDER BY annee DESC'
        ).fetchall()
        annees_fec = conn.execute(
            'SELECT DISTINCT annee FROM bilan_fec_imports ORDER BY annee DESC'
        ).fetchall()
        return render_template(
            'alsh.html',
            annees=annees,
            annee_courante=annee_courante,
            annees_noe=[r['annee'] for r in annees_noe],
            annees_fec=[r['annee'] for r in annees_fec],
        )
    finally:
        conn.close()


# ── Configuration : lecture ───────────────────────────────────────────────────

@alsh_bp.route('/api/alsh/config')
@login_required
def api_alsh_config():
    """Retourne la config globale : tranches d'age et periodes."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    conn = get_db()
    try:
        tranches = conn.execute(
            'SELECT id, libelle, ordre, active FROM alsh_tranches_age ORDER BY ordre, id'
        ).fetchall()
        periodes = conn.execute(
            'SELECT id, nom, type, ordre, active FROM alsh_periodes ORDER BY ordre, id'
        ).fetchall()
        return jsonify({
            'tranches': [dict(r) for r in tranches],
            'periodes': [dict(r) for r in periodes],
        })
    finally:
        conn.close()


# ── Configuration : tranches d'age ───────────────────────────────────────────

@alsh_bp.route('/api/alsh/tranches-age', methods=['POST'])
@login_required
def api_alsh_ajouter_tranche():
    """Ajoute une tranche d'age."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    libelle = (request.json or {}).get('libelle', '').strip()
    if not libelle:
        return jsonify({'error': 'Le libellé est requis.'}), 400

    conn = get_db()
    try:
        max_ordre = conn.execute(
            'SELECT COALESCE(MAX(ordre), 0) FROM alsh_tranches_age'
        ).fetchone()[0]
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO alsh_tranches_age (libelle, ordre) VALUES (?, ?)',
            (libelle, max_ordre + 1)
        )
        conn.commit()
        return jsonify({'success': True, 'id': cursor.lastrowid, 'libelle': libelle})
    finally:
        conn.close()


@alsh_bp.route('/api/alsh/tranches-age/<int:tranche_id>', methods=['DELETE'])
@login_required
def api_alsh_supprimer_tranche(tranche_id):
    """Supprime une tranche d'age (si non utilisee)."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    conn = get_db()
    try:
        # Verifier si utilisee dans les codes ou les donnees NOE
        nb_codes = conn.execute(
            'SELECT COUNT(*) FROM alsh_config_codes WHERE tranche_age_id = ?', (tranche_id,)
        ).fetchone()[0]
        nb_noe = conn.execute(
            'SELECT COUNT(*) FROM alsh_saisie_noe WHERE tranche_age_id = ?', (tranche_id,)
        ).fetchone()[0]
        if nb_codes + nb_noe > 0:
            return jsonify({
                'error': 'Cette tranche d\'âge est utilisée dans des données existantes.'
            }), 400

        conn.execute('DELETE FROM alsh_tranches_age WHERE id = ?', (tranche_id,))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


# ── Configuration : periodes ─────────────────────────────────────────────────

@alsh_bp.route('/api/alsh/periodes', methods=['POST'])
@login_required
def api_alsh_ajouter_periode():
    """Ajoute une ligne/periode."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    data = request.json or {}
    nom = data.get('nom', '').strip()
    if not nom:
        return jsonify({'error': 'Le nom est requis.'}), 400

    conn = get_db()
    try:
        max_ordre = conn.execute(
            'SELECT COALESCE(MAX(ordre), 0) FROM alsh_periodes'
        ).fetchone()[0]
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO alsh_periodes (nom, type, ordre) VALUES (?, ?, ?)',
            (nom, 'custom', max_ordre + 1)
        )
        conn.commit()
        return jsonify({'success': True, 'id': cursor.lastrowid, 'nom': nom})
    finally:
        conn.close()


@alsh_bp.route('/api/alsh/periodes/<int:periode_id>', methods=['DELETE'])
@login_required
def api_alsh_supprimer_periode(periode_id):
    """Supprime une periode personnalisee."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    conn = get_db()
    try:
        periode = conn.execute(
            'SELECT type FROM alsh_periodes WHERE id = ?', (periode_id,)
        ).fetchone()
        if not periode:
            return jsonify({'error': 'Période introuvable.'}), 404

        nb_codes = conn.execute(
            'SELECT COUNT(*) FROM alsh_config_codes WHERE periode_id = ?', (periode_id,)
        ).fetchone()[0]
        nb_noe = conn.execute(
            'SELECT COUNT(*) FROM alsh_saisie_noe WHERE periode_id = ?', (periode_id,)
        ).fetchone()[0]
        if nb_codes + nb_noe > 0:
            return jsonify({
                'error': 'Cette période est utilisée dans des données existantes.'
            }), 400

        conn.execute('DELETE FROM alsh_periodes WHERE id = ?', (periode_id,))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


# ── Codes analytiques ────────────────────────────────────────────────────────

@alsh_bp.route('/api/alsh/codes')
@login_required
def api_alsh_get_codes():
    """Retourne les codes analytiques mappes pour une annee."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    annee = request.args.get('annee', type=int)
    if not annee:
        return jsonify({'error': 'Année requise.'}), 400

    conn = get_db()
    try:
        rows = conn.execute('''
            SELECT periode_id, tranche_age_id, code1, code2, code3
            FROM alsh_config_codes
            WHERE annee = ?
        ''', (annee,)).fetchall()
        return jsonify({'codes': [dict(r) for r in rows]})
    finally:
        conn.close()


@alsh_bp.route('/api/alsh/codes', methods=['POST'])
@login_required
def api_alsh_save_codes():
    """Sauvegarde le mapping codes analytiques pour une cellule (annee, periode, tranche)."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    data = request.json or {}
    annee = data.get('annee')
    periode_id = data.get('periode_id')
    tranche_age_id = data.get('tranche_age_id')
    code1 = (data.get('code1') or '').strip() or None
    code2 = (data.get('code2') or '').strip() or None
    code3 = (data.get('code3') or '').strip() or None

    if not all([annee, periode_id, tranche_age_id]):
        return jsonify({'error': 'Paramètres incomplets.'}), 400

    conn = get_db()
    try:
        conn.execute('''
            INSERT INTO alsh_config_codes (annee, periode_id, tranche_age_id, code1, code2, code3, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(annee, periode_id, tranche_age_id) DO UPDATE SET
                code1 = excluded.code1,
                code2 = excluded.code2,
                code3 = excluded.code3,
                updated_at = CURRENT_TIMESTAMP
        ''', (annee, periode_id, tranche_age_id, code1, code2, code3))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


# ── Saisie donnees NOE ────────────────────────────────────────────────────────

@alsh_bp.route('/api/alsh/noe')
@login_required
def api_alsh_get_noe():
    """Retourne les donnees NOE pour une annee."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    annee = request.args.get('annee', type=int)
    if not annee:
        return jsonify({'error': 'Année requise.'}), 400

    conn = get_db()
    try:
        rows = conn.execute('''
            SELECT periode_id, tranche_age_id, heures_presence, nb_enfants
            FROM alsh_saisie_noe
            WHERE annee = ?
        ''', (annee,)).fetchall()
        return jsonify({'noe': [dict(r) for r in rows]})
    finally:
        conn.close()


@alsh_bp.route('/api/alsh/noe', methods=['POST'])
@login_required
def api_alsh_save_noe():
    """Sauvegarde une saisie NOE pour une cellule (annee, periode, tranche)."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    data = request.json or {}
    annee = data.get('annee')
    periode_id = data.get('periode_id')
    tranche_age_id = data.get('tranche_age_id')

    try:
        heures = float(data.get('heures_presence') or 0)
        enfants = int(data.get('nb_enfants') or 0)
    except (ValueError, TypeError):
        return jsonify({'error': 'Valeurs numériques invalides.'}), 400

    if not all([annee, periode_id, tranche_age_id]):
        return jsonify({'error': 'Paramètres incomplets.'}), 400

    conn = get_db()
    try:
        conn.execute('''
            INSERT INTO alsh_saisie_noe
                (annee, periode_id, tranche_age_id, heures_presence, nb_enfants, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(annee, periode_id, tranche_age_id) DO UPDATE SET
                heures_presence = excluded.heures_presence,
                nb_enfants = excluded.nb_enfants,
                updated_at = CURRENT_TIMESTAMP
        ''', (annee, periode_id, tranche_age_id, heures, enfants))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


# ── Tableau de bord ──────────────────────────────────────────────────────────

def _build_tableau(conn, annee):
    """Construit les donnees du tableau de bord pour une annee.

    - Charge les filtres de mois par periode depuis periodes_vacances (si disponibles).
    - Pour les periodes de type 'vacances' dont le nom correspond a une entree
      periodes_vacances, les donnees FEC sont restreintes aux mois couverts,
      ce qui evite le double-comptage quand le meme code analytique est partage
      entre plusieurs periodes (ex. meme code pour hiver et printemps).
    - Les periodes sans correspondance (Mercredis, custom) utilisent toute l'annee.
    - Utilise deux requetes SQL pre-agregees (par code+mois) pour eviter le N+1.
    """
    periodes = conn.execute(
        'SELECT id, nom, type, ordre FROM alsh_periodes WHERE active = 1 ORDER BY ordre, id'
    ).fetchall()
    tranches = conn.execute(
        'SELECT id, libelle, ordre FROM alsh_tranches_age WHERE active = 1 ORDER BY ordre, id'
    ).fetchall()

    # Charger les codes analytiques de l'annee
    codes_rows = conn.execute(
        'SELECT periode_id, tranche_age_id, code1, code2, code3 FROM alsh_config_codes WHERE annee = ?',
        (annee,)
    ).fetchall()
    codes_map = {(r['periode_id'], r['tranche_age_id']): [r['code1'], r['code2'], r['code3']]
                 for r in codes_rows}

    # Charger les donnees NOE de l'annee
    noe_rows = conn.execute(
        'SELECT periode_id, tranche_age_id, heures_presence, nb_enfants FROM alsh_saisie_noe WHERE annee = ?',
        (annee,)
    ).fetchall()
    noe_map = {(r['periode_id'], r['tranche_age_id']): (r['heures_presence'], r['nb_enfants'])
               for r in noe_rows}

    # Calculer les filtres de mois par periode (vacances → mois scolaires)
    periode_mois_filter = _build_periode_mois_filter(conn, periodes, annee)

    # Collecter tous les codes analytiques utilises pour cette annee
    tous_les_codes = set()
    for codes in codes_map.values():
        tous_les_codes.update(c for c in codes if c)

    # Agreger par (code_analytique, mois) ET par code seul (pour periodes sans filtre)
    charges_by_code_mois = {}   # {(code, mois): total}
    produits_by_code_mois = {}  # {(code, mois): total}
    charges_by_code = {}        # {code: total annee}
    produits_by_code = {}       # {code: total annee}

    if tous_les_codes:
        codes_list = list(tous_les_codes)
        placeholders = ','.join('?' * len(codes_list))
        params = [annee] + codes_list

        charges_rows = conn.execute(
            'SELECT code_analytique, mois, COALESCE(SUM(montant), 0) as total'
            ' FROM bilan_fec_donnees'
            " WHERE annee = ? AND compte_num LIKE '6%'"
            ' AND code_analytique IN (' + placeholders + ')'
            ' GROUP BY code_analytique, mois',
            params
        ).fetchall()
        for r in charges_rows:
            km = (r['code_analytique'], r['mois'])
            charges_by_code_mois[km] = r['total']
            c = r['code_analytique']
            charges_by_code[c] = charges_by_code.get(c, 0.0) + r['total']

        produits_rows = conn.execute(
            'SELECT code_analytique, mois, COALESCE(SUM(montant), 0) as total'
            ' FROM bilan_fec_donnees'
            " WHERE annee = ? AND compte_num LIKE '7%'"
            ' AND code_analytique IN (' + placeholders + ')'
            ' GROUP BY code_analytique, mois',
            params
        ).fetchall()
        for r in produits_rows:
            km = (r['code_analytique'], r['mois'])
            produits_by_code_mois[km] = r['total']
            c = r['code_analytique']
            produits_by_code[c] = produits_by_code.get(c, 0.0) + r['total']

    lignes = []
    total_charges = 0.0
    total_produits = 0.0
    total_heures = 0.0
    total_enfants = 0

    for periode in periodes:
        mois_filter, date_label = periode_mois_filter.get(periode['id'], (None, None))
        for tranche in tranches:
            key = (periode['id'], tranche['id'])
            codes = codes_map.get(key, [None, None, None])
            heures, enfants = noe_map.get(key, (0.0, 0))

            # Sommer les montants depuis les dicts pre-calcules
            codes_valides = [c for c in codes if c]

            if mois_filter is not None:
                # Filtrer par mois : evite le double-comptage sur code partage
                charges = round(sum(
                    charges_by_code_mois.get((c, m), 0.0)
                    for c in codes_valides
                    for m in mois_filter
                ), 2)
                produits = round(sum(
                    produits_by_code_mois.get((c, m), 0.0)
                    for c in codes_valides
                    for m in mois_filter
                ), 2)
            else:
                # Pas de filtre de date (Mercredis, custom, ou vacances sans dates connues)
                charges = round(sum(charges_by_code.get(c, 0.0) for c in codes_valides), 2)
                produits = round(sum(produits_by_code.get(c, 0.0) for c in codes_valides), 2)

            resultat = produits - charges
            cout_heure = (charges / heures) if heures > 0 else None
            cout_enfant = (charges / enfants) if enfants > 0 else None
            taux_couverture = ((produits / charges) * 100) if charges > 0 else None

            ligne = {
                'periode_id': periode['id'],
                'periode_nom': periode['nom'],
                'periode_type': periode['type'],
                'periode_date_label': date_label,
                'tranche_id': tranche['id'],
                'tranche_libelle': tranche['libelle'],
                'codes': [c for c in codes if c],
                'heures_presence': heures,
                'nb_enfants': enfants,
                'charges': charges,
                'produits': produits,
                'resultat': round(resultat, 2),
                'cout_heure': round(cout_heure, 2) if cout_heure is not None else None,
                'cout_enfant': round(cout_enfant, 2) if cout_enfant is not None else None,
                'taux_couverture': round(taux_couverture, 1) if taux_couverture is not None else None,
            }
            lignes.append(ligne)
            total_charges += charges
            total_produits += produits
            total_heures += heures
            total_enfants += enfants

    total_resultat = total_produits - total_charges
    total_taux = ((total_produits / total_charges) * 100) if total_charges > 0 else None

    return {
        'annee': annee,
        'periodes': [dict(p) for p in periodes],
        'tranches': [dict(t) for t in tranches],
        'lignes': lignes,
        'totaux': {
            'heures_presence': round(total_heures, 2),
            'nb_enfants': total_enfants,
            'charges': round(total_charges, 2),
            'produits': round(total_produits, 2),
            'resultat': round(total_resultat, 2),
            'taux_couverture': round(total_taux, 1) if total_taux is not None else None,
        },
    }


@alsh_bp.route('/api/alsh/tableau')
@login_required
def api_alsh_tableau():
    """Retourne les donnees du tableau de bord pour une annee."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    annee = request.args.get('annee', type=int)
    if not annee:
        return jsonify({'error': 'Année requise.'}), 400

    conn = get_db()
    try:
        data = _build_tableau(conn, annee)
        return jsonify(data)
    finally:
        conn.close()


@alsh_bp.route('/api/alsh/comparaison')
@login_required
def api_alsh_comparaison():
    """Retourne les donnees comparatives N / N-1 / N-2."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    annee = request.args.get('annee', type=int)
    if not annee:
        return jsonify({'error': 'Année requise.'}), 400

    conn = get_db()
    try:
        # Annees ayant des donnees FEC ou NOE
        annees_fec = {r['annee'] for r in conn.execute(
            'SELECT DISTINCT annee FROM bilan_fec_imports'
        ).fetchall()}
        annees_noe = {r['annee'] for r in conn.execute(
            'SELECT DISTINCT annee FROM alsh_saisie_noe'
        ).fetchall()}
        annees_dispo = sorted(annees_fec | annees_noe, reverse=True)

        resultats = {}
        for a in [annee, annee - 1, annee - 2]:
            if a in annees_dispo or a == annee:
                resultats[str(a)] = _build_tableau(conn, a)

        return jsonify({
            'annees_dispo': annees_dispo,
            'comparaison': resultats,
        })
    finally:
        conn.close()


# ── Codes analytiques disponibles (pour autocomplete) ────────────────────────

@alsh_bp.route('/api/alsh/codes-disponibles')
@login_required
def api_alsh_codes_disponibles():
    """Retourne la liste des codes analytiques disponibles dans les donnees FEC."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    annee = request.args.get('annee', type=int)
    conn = get_db()
    try:
        if annee:
            rows = conn.execute('''
                SELECT DISTINCT code_analytique
                FROM bilan_fec_donnees
                WHERE annee = ? AND code_analytique IS NOT NULL AND code_analytique != ''
                ORDER BY code_analytique
            ''', (annee,)).fetchall()
        else:
            rows = conn.execute('''
                SELECT DISTINCT code_analytique
                FROM bilan_fec_donnees
                WHERE code_analytique IS NOT NULL AND code_analytique != ''
                ORDER BY code_analytique
            ''').fetchall()
        return jsonify({'codes': [r['code_analytique'] for r in rows]})
    finally:
        conn.close()
