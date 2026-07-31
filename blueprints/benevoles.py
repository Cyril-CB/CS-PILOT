"""
Blueprint benevoles_bp - Liste des benevoles (board style Monday.com).

Accessible aux profils : directeur, comptable, responsable.
Les responsables ne voient que les benevoles auxquels ils sont assignes.

Le suivi des heures de benevolat (page /benevoles/heures) est reserve a la
direction et a la comptabilite : le calendrier des activites (jours de CA,
cafes seniors...) est commun a toute l'association, il n'est pas cloisonne
par responsable.
"""
from datetime import date, datetime
from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, jsonify)
from database import get_db
from utils import login_required

benevoles_bp = Blueprint('benevoles_bp', __name__)

GROUPES = [
    {'key': 'nouveau', 'label': 'Nouveau', 'color': '#579bfc'},
    {'key': 'actif', 'label': 'Actif', 'color': '#00c875'},
    {'key': 'inactif', 'label': 'Inactif', 'color': '#c4c4c4'},
]

GROUPES_MAP = {g['key']: g for g in GROUPES}

HEURES_OPTIONS = [
    {'key': '1-3', 'label': '1-3h', 'color': '#579bfc'},
    {'key': '4-6', 'label': '4-6h', 'color': '#00c875'},
    {'key': '7-10', 'label': '7-10h', 'color': '#fdab3d'},
    {'key': '+10', 'label': '+10h', 'color': '#e2445c'},
]

# Types de benevolat du repertoire. Un benevole peut mener plusieurs missions :
# les combinaisons sont proposees telles quelles pour rester sur une seule
# liste deroulante.
TYPES_BENEVOLAT = [
    {'key': 'gouvernance', 'label': 'Gouvernance', 'color': '#a25ddc'},
    {'key': 'activite', 'label': 'Activité', 'color': '#00c875'},
    {'key': 'coup_de_pouce', 'label': 'Coup de pouce', 'color': '#fdab3d'},
    {'key': 'gouvernance_activite', 'label': 'Gouvernance + Activité', 'color': '#579bfc'},
    {'key': 'gouvernance_coup_de_pouce', 'label': 'Gouvernance + Coup de pouce', 'color': '#e2445c'},
    {'key': 'activite_coup_de_pouce', 'label': 'Activité + Coup de pouce', 'color': '#037f4c'},
    {'key': 'les_trois', 'label': 'Gouvernance + Activité + Coup de pouce', 'color': '#808080'},
]

TYPES_BENEVOLAT_MAP = {t['key']: t for t in TYPES_BENEVOLAT}

# Les gabarits retrouvent l'etiquette et la couleur par cle. Une boucle Jinja ne
# convient pas : un `{% set %}` place dans un `{% for %}` ne survit pas a la
# boucle, la pastille restait donc grise et vide quelle que soit la valeur.
HEURES_MAP = {h['key']: h for h in HEURES_OPTIONS}

# Modes de comptage des heures, repris du classeur tenu jusqu'ici :
# - seance  : on liste les dates (les jours de CA) et on coche les presents ;
# - forfait : l'activite reguliere est budgetee pour un volume annuel
#             (« sur 80 h a l'annee ») dont on retranche les absences.
MODES_ACTIVITE = [
    {'key': 'seance', 'label': 'À la séance (liste de dates)'},
    {'key': 'forfait', 'label': 'Au forfait annuel'},
]

MODES_ACTIVITE_KEYS = {m['key'] for m in MODES_ACTIVITE}


def _peut_voir():
    return session.get('profil') in ('directeur', 'comptable', 'responsable')


def _peut_modifier():
    return session.get('profil') in ('directeur', 'comptable', 'responsable')


def _peut_gerer_heures():
    """Suivi des heures : direction et comptabilite uniquement.

    Le calendrier des activites est commun a l'association ; le confier aux
    responsables, qui ne voient qu'une partie des benevoles, fausserait les
    totaux servant au bilan.
    """
    return session.get('profil') in ('directeur', 'comptable')


def _get_initiales(prenom, nom):
    p = (prenom or '').strip()
    n = (nom or '').strip()
    p_init = (p[0].upper() + p[1].lower()) if len(p) >= 2 else p[:1].upper()
    n_init = (n[0].upper() + n[1].lower()) if len(n) >= 2 else n[:1].upper()
    return f"{p_init}.{n_init}" if p_init and n_init else ''


def _annee_demandee(defaut=None):
    """Annee de suivi passee en parametre, l'annee courante par defaut."""
    brut = request.args.get('annee') or (request.get_json(silent=True) or {}).get('annee')
    try:
        annee = int(brut)
    except (TypeError, ValueError):
        return defaut if defaut is not None else datetime.now().year
    # Bornes larges : on refuse seulement les valeurs aberrantes.
    return annee if 1900 <= annee <= 2200 else datetime.now().year


def _num(valeur, defaut=0.0):
    try:
        n = float(valeur)
    except (TypeError, ValueError):
        return defaut
    return n if n >= 0 else defaut


def _date_de_seance(valeur, annee):
    """(date ISO, None) si la date est valide et tombe dans l'annee, (None, message).

    Le total annuel regroupe les seances par l'annee de l'ACTIVITE, pas par la
    date de la seance : une date d'un autre exercice serait comptee dans le
    mauvais bilan. Le format est verifie au passage, un 31 fevrier etant
    accepte tel quel par SQLite.
    """
    texte = (valeur or '').strip()
    if not texte:
        return None, 'Date requise'
    try:
        jour = date.fromisoformat(texte[:10])
    except ValueError:
        return None, 'Date invalide (format attendu : AAAA-MM-JJ)'
    if jour.year != int(annee):
        return None, f"La date doit être dans l'année {annee} de l'activité"
    return jour.isoformat(), None


def _heures_forfait(volume_annuel, nb_seances, absences):
    """Heures retenues sur une activite au forfait.

    Le volume annuel est reduit au prorata des seances manquees. Sans nombre
    de seances renseigne, aucune deduction n'est possible : le volume entier
    est retenu (et la page le signale).
    """
    volume = _num(volume_annuel)
    seances = int(nb_seances or 0)
    if seances <= 0:
        return round(volume, 2)
    presentes = max(0, seances - int(absences or 0))
    return round(volume * presentes / seances, 2)


def _heures_par_benevole(conn, annee):
    """Total d'heures de benevolat de l'annee, par benevole."""
    totaux = {}

    def _ajouter(bid, heures):
        totaux[bid] = round(totaux.get(bid, 0.0) + heures, 2)

    # Activites a la seance : somme des seances reellement suivies.
    for r in conn.execute('''
        SELECT p.benevole_id AS bid, SUM(s.heures) AS heures
        FROM benevoles_presences p
        JOIN benevoles_seances s ON s.id = p.seance_id
        JOIN benevoles_activites a ON a.id = s.activite_id
        WHERE p.present = 1 AND a.annee = ? AND a.mode = 'seance'
        GROUP BY p.benevole_id
    ''', (annee,)).fetchall():
        _ajouter(r['bid'], _num(r['heures']))

    # Activites au forfait : volume annuel moins les absences.
    for r in conn.execute('''
        SELECT pa.benevole_id AS bid, a.volume_annuel, a.nb_seances, pa.absences
        FROM benevoles_participations pa
        JOIN benevoles_activites a ON a.id = pa.activite_id
        WHERE a.annee = ? AND a.mode = 'forfait'
    ''', (annee,)).fetchall():
        _ajouter(r['bid'], _heures_forfait(r['volume_annuel'], r['nb_seances'], r['absences']))

    # Heures ponctuelles hors activite suivie.
    for r in conn.execute('''
        SELECT benevole_id AS bid, SUM(heures) AS heures
        FROM benevoles_heures_autres WHERE annee = ? GROUP BY benevole_id
    ''', (annee,)).fetchall():
        _ajouter(r['bid'], _num(r['heures']))

    return totaux


# ── Vue principale ──

@benevoles_bp.route('/benevoles')
@login_required
def gestion_benevoles():
    if not _peut_voir():
        flash("Acces non autorise.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))

    annee = _annee_demandee()
    conn = get_db()
    try:
        users = conn.execute(
            'SELECT id, nom, prenom, profil FROM users WHERE actif = 1 ORDER BY nom, prenom'
        ).fetchall()
        users_map = {}
        for u in users:
            users_map[u['id']] = {
                'nom': u['nom'], 'prenom': u['prenom'],
                'initiales': _get_initiales(u['prenom'], u['nom']),
            }

        is_responsable = session.get('profil') == 'responsable'
        user_id = session.get('user_id')

        if is_responsable:
            benevoles = conn.execute(
                'SELECT * FROM benevoles WHERE responsable_id = ? ORDER BY ordre, id',
                (user_id,)
            ).fetchall()
        else:
            benevoles = conn.execute(
                'SELECT * FROM benevoles ORDER BY ordre, id'
            ).fetchall()

        heures_totales = _heures_par_benevole(conn, annee)

        groupes_data = []
        for g in GROUPES:
            lignes = [b for b in benevoles if b['groupe'] == g['key']]
            groupes_data.append({
                'key': g['key'],
                'label': g['label'],
                'color': g['color'],
                'lignes': lignes,
            })

    finally:
        conn.close()

    return render_template(
        'benevoles.html',
        groupes=groupes_data,
        users=users,
        users_map=users_map,
        groupes_config=GROUPES,
        heures_config=HEURES_OPTIONS,
        heures_map=HEURES_MAP,
        types_config=TYPES_BENEVOLAT,
        types_map=TYPES_BENEVOLAT_MAP,
        heures_totales=heures_totales,
        annee=annee,
        is_responsable=is_responsable,
        peut_gerer_heures=_peut_gerer_heures(),
    )


# ── API : Benevoles CRUD ──

@benevoles_bp.route('/api/benevoles/ajouter', methods=['POST'])
@login_required
def api_ajouter_benevole():
    if not _peut_modifier():
        return jsonify({'ok': False, 'error': 'Non autorise'}), 403

    data = request.get_json(silent=True) or {}
    nom = (data.get('nom') or '').strip()
    groupe = data.get('groupe', 'nouveau')

    if not nom:
        return jsonify({'ok': False, 'error': 'Nom requis'}), 400
    if groupe not in GROUPES_MAP:
        groupe = 'nouveau'

    conn = get_db()
    try:
        cursor = conn.execute(
            'INSERT INTO benevoles (nom, groupe) VALUES (?, ?)',
            (nom, groupe)
        )
        conn.commit()
        return jsonify({'ok': True, 'id': cursor.lastrowid})
    finally:
        conn.close()


@benevoles_bp.route('/api/benevoles/<int:ben_id>/modifier', methods=['POST'])
@login_required
def api_modifier_benevole(ben_id):
    if not _peut_modifier():
        return jsonify({'ok': False, 'error': 'Non autorise'}), 403

    data = request.get_json(silent=True) or {}
    field = data.get('field')
    value = data.get('value')

    allowed_fields = {
        'nom', 'groupe', 'responsable_id', 'date_debut', 'date_fin',
        'email', 'telephone', 'adresse', 'competences',
        'heures_semaine', 'type_benevolat', 'charte_signee',
    }

    if field not in allowed_fields:
        return jsonify({'ok': False, 'error': f'Champ non autorise: {field}'}), 400

    if field == 'responsable_id':
        value = int(value) if value else None
    # Case a cocher : on n'enregistre que 0 ou 1, jamais la valeur brute du
    # navigateur (une chaine vide ou 'false' vaudrait « vrai » en SQLite).
    if field == 'charte_signee':
        value = 1 if value in (True, 1, '1', 'true', 'on') else 0
    # Liste fermee : une valeur inconnue viderait la colonne au lieu de
    # laisser une etiquette qui ne correspond a aucun type.
    if field == 'type_benevolat' and value not in TYPES_BENEVOLAT_MAP:
        value = ''

    conn = get_db()
    try:
        conn.execute(
            f'UPDATE benevoles SET {field} = ?, updated_at = ? WHERE id = ?',
            (value, datetime.now().isoformat(), ben_id)
        )
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()


@benevoles_bp.route('/api/benevoles/<int:ben_id>/supprimer', methods=['POST'])
@login_required
def api_supprimer_benevole(ben_id):
    if not _peut_modifier():
        return jsonify({'ok': False, 'error': 'Non autorise'}), 403

    conn = get_db()
    try:
        # Les cles etrangeres ne sont pas activees : on nettoie a la main le
        # suivi des heures, sinon presences et participations survivraient au
        # benevole et fausseraient les totaux.
        conn.execute('''
            DELETE FROM benevoles_presences WHERE benevole_id = ?
        ''', (ben_id,))
        conn.execute('DELETE FROM benevoles_participations WHERE benevole_id = ?', (ben_id,))
        conn.execute('DELETE FROM benevoles_heures_autres WHERE benevole_id = ?', (ben_id,))
        conn.execute('DELETE FROM benevoles WHERE id = ?', (ben_id,))
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()


# ── Suivi des heures ──

@benevoles_bp.route('/benevoles/heures')
@login_required
def suivi_heures():
    """Calendrier des activites et totaux d'heures par benevole."""
    if not _peut_gerer_heures():
        flash("Acces non autorise.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))

    annee = _annee_demandee()
    conn = get_db()
    try:
        benevoles = conn.execute(
            'SELECT id, nom, groupe, type_benevolat FROM benevoles ORDER BY nom'
        ).fetchall()
        benevoles_map = {b['id']: b['nom'] for b in benevoles}

        activites = []
        for a in conn.execute(
            'SELECT * FROM benevoles_activites WHERE annee = ? ORDER BY ordre, id', (annee,)
        ).fetchall():
            seances = conn.execute(
                'SELECT * FROM benevoles_seances WHERE activite_id = ? ORDER BY date, id',
                (a['id'],)
            ).fetchall()
            participations = conn.execute('''
                SELECT p.*, b.nom AS benevole_nom
                FROM benevoles_participations p
                JOIN benevoles b ON b.id = p.benevole_id
                WHERE p.activite_id = ? ORDER BY b.nom
            ''', (a['id'],)).fetchall()
            presences = {
                (r['seance_id'], r['benevole_id']): r['present']
                for r in conn.execute('''
                    SELECT pr.seance_id, pr.benevole_id, pr.present
                    FROM benevoles_presences pr
                    JOIN benevoles_seances s ON s.id = pr.seance_id
                    WHERE s.activite_id = ?
                ''', (a['id'],)).fetchall()
            }
            lignes = []
            for p in participations:
                if a['mode'] == 'forfait':
                    total = _heures_forfait(a['volume_annuel'], a['nb_seances'], p['absences'])
                else:
                    total = round(sum(
                        _num(s['heures']) for s in seances
                        if presences.get((s['id'], p['benevole_id']))
                    ), 2)
                lignes.append({
                    'participation_id': p['id'],
                    'benevole_id': p['benevole_id'],
                    'nom': p['benevole_nom'],
                    'absences': p['absences'],
                    'presences': {s['id']: bool(presences.get((s['id'], p['benevole_id'])))
                                  for s in seances},
                    'total': total,
                })
            activites.append({
                'id': a['id'], 'nom': a['nom'], 'mode': a['mode'],
                'heures_seance': a['heures_seance'],
                'volume_annuel': a['volume_annuel'], 'nb_seances': a['nb_seances'],
                'seances': seances, 'lignes': lignes,
                'total': round(sum(l['total'] for l in lignes), 2),
            })

        autres = conn.execute('''
            SELECT h.*, b.nom AS benevole_nom
            FROM benevoles_heures_autres h
            JOIN benevoles b ON b.id = h.benevole_id
            WHERE h.annee = ? ORDER BY h.date, h.id
        ''', (annee,)).fetchall()

        # Le recapitulatif liste tout benevole suivi cette annee, meme a zero
        # heure : la ligne existe donc des qu'une case a cocher existe pour lui,
        # et le total se met a jour sans recharger la page.
        totaux = _heures_par_benevole(conn, annee)
        suivis = set(totaux)
        for r in conn.execute('''
            SELECT p.benevole_id AS bid FROM benevoles_participations p
            JOIN benevoles_activites a ON a.id = p.activite_id WHERE a.annee = ?
        ''', (annee,)).fetchall():
            suivis.add(r['bid'])
        recap = sorted(
            ({'id': bid, 'nom': benevoles_map.get(bid, '?'), 'total': totaux.get(bid, 0)}
             for bid in suivis if bid in benevoles_map),
            key=lambda r: r['nom']
        )
    finally:
        conn.close()

    return render_template(
        'benevoles_heures.html',
        annee=annee,
        activites=activites,
        autres=autres,
        benevoles=benevoles,
        recap=recap,
        total_general=round(sum(r['total'] for r in recap), 2),
        modes_config=MODES_ACTIVITE,
    )


def _refus_heures():
    """Reponse de refus commune aux API du suivi des heures."""
    return jsonify({'ok': False, 'error': 'Non autorise'}), 403


def _totaux_apres_pointage(conn, seance_id, benevole_id):
    """Totaux a rafraichir apres une case cochee, sans recharger la page.

    Pointer une presence est le geste principal de la page : recharger a
    chaque clic rendrait la saisie d'un CA a douze administrateurs penible.
    """
    ligne = conn.execute('''
        SELECT a.id AS activite_id, a.annee
        FROM benevoles_seances s JOIN benevoles_activites a ON a.id = s.activite_id
        WHERE s.id = ?
    ''', (seance_id,)).fetchone()
    if not ligne:
        return {}
    benevole = conn.execute('''
        SELECT COALESCE(SUM(s.heures), 0) AS h
        FROM benevoles_presences p JOIN benevoles_seances s ON s.id = p.seance_id
        WHERE p.present = 1 AND p.benevole_id = ? AND s.activite_id = ?
    ''', (benevole_id, ligne['activite_id'])).fetchone()['h']
    activite = conn.execute('''
        SELECT COALESCE(SUM(s.heures), 0) AS h
        FROM benevoles_presences p JOIN benevoles_seances s ON s.id = p.seance_id
        WHERE p.present = 1 AND s.activite_id = ?
    ''', (ligne['activite_id'],)).fetchone()['h']
    totaux_annee = _heures_par_benevole(conn, ligne['annee'])
    return {
        'activite_id': ligne['activite_id'],
        'total_benevole_activite': round(_num(benevole), 2),
        'total_activite': round(_num(activite), 2),
        'total_benevole_annee': totaux_annee.get(benevole_id, 0),
        'total_annee': round(sum(totaux_annee.values()), 2),
    }


@benevoles_bp.route('/api/benevoles/activites/ajouter', methods=['POST'])
@login_required
def api_ajouter_activite():
    if not _peut_gerer_heures():
        return _refus_heures()

    data = request.get_json(silent=True) or {}
    nom = (data.get('nom') or '').strip()
    if not nom:
        return jsonify({'ok': False, 'error': 'Nom requis'}), 400
    mode = data.get('mode') if data.get('mode') in MODES_ACTIVITE_KEYS else 'seance'
    annee = _annee_demandee()

    conn = get_db()
    try:
        ordre = conn.execute(
            'SELECT COALESCE(MAX(ordre), 0) + 1 AS o FROM benevoles_activites WHERE annee = ?',
            (annee,)
        ).fetchone()['o']
        cur = conn.execute('''
            INSERT INTO benevoles_activites
            (nom, annee, mode, heures_seance, volume_annuel, nb_seances, ordre)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (nom, annee, mode, _num(data.get('heures_seance')),
              _num(data.get('volume_annuel')), int(_num(data.get('nb_seances'))), ordre))
        conn.commit()
        return jsonify({'ok': True, 'id': cur.lastrowid})
    finally:
        conn.close()


@benevoles_bp.route('/api/benevoles/activites/<int:act_id>/modifier', methods=['POST'])
@login_required
def api_modifier_activite(act_id):
    if not _peut_gerer_heures():
        return _refus_heures()

    data = request.get_json(silent=True) or {}
    field = data.get('field')
    value = data.get('value')
    if field not in {'nom', 'mode', 'heures_seance', 'volume_annuel', 'nb_seances'}:
        return jsonify({'ok': False, 'error': f'Champ non autorise: {field}'}), 400
    if field == 'mode' and value not in MODES_ACTIVITE_KEYS:
        return jsonify({'ok': False, 'error': 'Mode inconnu'}), 400
    if field in ('heures_seance', 'volume_annuel'):
        value = _num(value)
    if field == 'nb_seances':
        value = int(_num(value))

    conn = get_db()
    try:
        if not conn.execute('SELECT id FROM benevoles_activites WHERE id = ?',
                            (act_id,)).fetchone():
            return jsonify({'ok': False, 'error': 'Activité introuvable'}), 404
        conn.execute(f'UPDATE benevoles_activites SET {field} = ? WHERE id = ?',
                     (value, act_id))
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()


@benevoles_bp.route('/api/benevoles/activites/<int:act_id>/supprimer', methods=['POST'])
@login_required
def api_supprimer_activite(act_id):
    if not _peut_gerer_heures():
        return _refus_heures()

    conn = get_db()
    try:
        conn.execute('''
            DELETE FROM benevoles_presences WHERE seance_id IN
            (SELECT id FROM benevoles_seances WHERE activite_id = ?)
        ''', (act_id,))
        conn.execute('DELETE FROM benevoles_seances WHERE activite_id = ?', (act_id,))
        conn.execute('DELETE FROM benevoles_participations WHERE activite_id = ?', (act_id,))
        conn.execute('DELETE FROM benevoles_activites WHERE id = ?', (act_id,))
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()


@benevoles_bp.route('/api/benevoles/activites/<int:act_id>/seances/ajouter', methods=['POST'])
@login_required
def api_ajouter_seance(act_id):
    if not _peut_gerer_heures():
        return _refus_heures()

    data = request.get_json(silent=True) or {}

    conn = get_db()
    try:
        activite = conn.execute('SELECT * FROM benevoles_activites WHERE id = ?',
                                (act_id,)).fetchone()
        if not activite:
            return jsonify({'ok': False, 'error': 'Activité introuvable'}), 404
        date_seance, erreur = _date_de_seance(data.get('date'), activite['annee'])
        if erreur:
            return jsonify({'ok': False, 'error': erreur}), 400
        # Duree par defaut : celle de l'activite (2 h pour un CA par exemple).
        heures = data.get('heures')
        heures = _num(heures) if heures not in (None, '') else _num(activite['heures_seance'])
        cur = conn.execute(
            'INSERT INTO benevoles_seances (activite_id, date, heures) VALUES (?, ?, ?)',
            (act_id, date_seance, heures))
        conn.commit()
        return jsonify({'ok': True, 'id': cur.lastrowid})
    finally:
        conn.close()


@benevoles_bp.route('/api/benevoles/seances/<int:seance_id>/modifier', methods=['POST'])
@login_required
def api_modifier_seance(seance_id):
    if not _peut_gerer_heures():
        return _refus_heures()

    data = request.get_json(silent=True) or {}
    field = data.get('field')
    value = data.get('value')
    if field not in {'date', 'heures'}:
        return jsonify({'ok': False, 'error': f'Champ non autorise: {field}'}), 400
    if field == 'heures':
        value = _num(value)

    conn = get_db()
    try:
        seance = conn.execute('''
            SELECT s.id, a.annee FROM benevoles_seances s
            JOIN benevoles_activites a ON a.id = s.activite_id WHERE s.id = ?
        ''', (seance_id,)).fetchone()
        if not seance:
            return jsonify({'ok': False, 'error': 'Séance introuvable'}), 404
        if field == 'date':
            # Meme controle qu'a l'ajout : sinon la correction d'une date
            # permettrait de sortir la seance de l'annee de l'activite.
            value, erreur = _date_de_seance(value, seance['annee'])
            if erreur:
                return jsonify({'ok': False, 'error': erreur}), 400
        conn.execute(f'UPDATE benevoles_seances SET {field} = ? WHERE id = ?',
                     (value, seance_id))
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()


@benevoles_bp.route('/api/benevoles/seances/<int:seance_id>/supprimer', methods=['POST'])
@login_required
def api_supprimer_seance(seance_id):
    if not _peut_gerer_heures():
        return _refus_heures()

    conn = get_db()
    try:
        conn.execute('DELETE FROM benevoles_presences WHERE seance_id = ?', (seance_id,))
        conn.execute('DELETE FROM benevoles_seances WHERE id = ?', (seance_id,))
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()


@benevoles_bp.route('/api/benevoles/activites/<int:act_id>/participants/ajouter',
                    methods=['POST'])
@login_required
def api_ajouter_participant(act_id):
    if not _peut_gerer_heures():
        return _refus_heures()

    data = request.get_json(silent=True) or {}
    try:
        benevole_id = int(data.get('benevole_id'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'Bénévole requis'}), 400

    conn = get_db()
    try:
        if not conn.execute('SELECT id FROM benevoles_activites WHERE id = ?',
                            (act_id,)).fetchone():
            return jsonify({'ok': False, 'error': 'Activité introuvable'}), 404
        if not conn.execute('SELECT id FROM benevoles WHERE id = ?',
                            (benevole_id,)).fetchone():
            return jsonify({'ok': False, 'error': 'Bénévole introuvable'}), 404
        conn.execute('''
            INSERT INTO benevoles_participations (activite_id, benevole_id)
            VALUES (?, ?) ON CONFLICT(activite_id, benevole_id) DO NOTHING
        ''', (act_id, benevole_id))
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()


@benevoles_bp.route('/api/benevoles/participations/<int:part_id>/modifier', methods=['POST'])
@login_required
def api_modifier_participation(part_id):
    """Nombre de seances manquees (activites au forfait)."""
    if not _peut_gerer_heures():
        return _refus_heures()

    data = request.get_json(silent=True) or {}
    absences = int(_num(data.get('absences')))

    conn = get_db()
    try:
        if not conn.execute('SELECT id FROM benevoles_participations WHERE id = ?',
                            (part_id,)).fetchone():
            return jsonify({'ok': False, 'error': 'Participation introuvable'}), 404
        conn.execute('UPDATE benevoles_participations SET absences = ? WHERE id = ?',
                     (absences, part_id))
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()


@benevoles_bp.route('/api/benevoles/participations/<int:part_id>/supprimer', methods=['POST'])
@login_required
def api_supprimer_participation(part_id):
    if not _peut_gerer_heures():
        return _refus_heures()

    conn = get_db()
    try:
        ligne = conn.execute(
            'SELECT activite_id, benevole_id FROM benevoles_participations WHERE id = ?',
            (part_id,)).fetchone()
        if ligne:
            conn.execute('''
                DELETE FROM benevoles_presences
                WHERE benevole_id = ? AND seance_id IN
                (SELECT id FROM benevoles_seances WHERE activite_id = ?)
            ''', (ligne['benevole_id'], ligne['activite_id']))
            conn.execute('DELETE FROM benevoles_participations WHERE id = ?', (part_id,))
            conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()


@benevoles_bp.route('/api/benevoles/presences', methods=['POST'])
@login_required
def api_presence():
    """Coche ou decoche la presence d'un benevole a une seance."""
    if not _peut_gerer_heures():
        return _refus_heures()

    data = request.get_json(silent=True) or {}
    try:
        seance_id = int(data.get('seance_id'))
        benevole_id = int(data.get('benevole_id'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'Séance et bénévole requis'}), 400
    present = 1 if data.get('present') else 0

    conn = get_db()
    try:
        if not conn.execute('SELECT id FROM benevoles_seances WHERE id = ?',
                            (seance_id,)).fetchone():
            return jsonify({'ok': False, 'error': 'Séance introuvable'}), 404
        if not conn.execute('SELECT id FROM benevoles WHERE id = ?',
                            (benevole_id,)).fetchone():
            return jsonify({'ok': False, 'error': 'Bénévole introuvable'}), 404
        conn.execute('''
            INSERT INTO benevoles_presences (seance_id, benevole_id, present)
            VALUES (?, ?, ?)
            ON CONFLICT(seance_id, benevole_id) DO UPDATE SET present = excluded.present
        ''', (seance_id, benevole_id, present))
        conn.commit()
        reponse = {'ok': True, 'benevole_id': benevole_id}
        reponse.update(_totaux_apres_pointage(conn, seance_id, benevole_id))
        return jsonify(reponse)
    finally:
        conn.close()


@benevoles_bp.route('/api/benevoles/heures-autres/ajouter', methods=['POST'])
@login_required
def api_ajouter_heures_autres():
    if not _peut_gerer_heures():
        return _refus_heures()

    data = request.get_json(silent=True) or {}
    try:
        benevole_id = int(data.get('benevole_id'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'Bénévole requis'}), 400
    heures = _num(data.get('heures'))
    if heures <= 0:
        return jsonify({'ok': False, 'error': "Nombre d'heures requis"}), 400
    annee = _annee_demandee()

    conn = get_db()
    try:
        if not conn.execute('SELECT id FROM benevoles WHERE id = ?',
                            (benevole_id,)).fetchone():
            return jsonify({'ok': False, 'error': 'Bénévole introuvable'}), 404
        cur = conn.execute('''
            INSERT INTO benevoles_heures_autres (benevole_id, annee, date, libelle, heures)
            VALUES (?, ?, ?, ?, ?)
        ''', (benevole_id, annee, (data.get('date') or '').strip(),
              (data.get('libelle') or '').strip(), heures))
        conn.commit()
        return jsonify({'ok': True, 'id': cur.lastrowid})
    finally:
        conn.close()


@benevoles_bp.route('/api/benevoles/heures-autres/<int:ligne_id>/supprimer', methods=['POST'])
@login_required
def api_supprimer_heures_autres(ligne_id):
    if not _peut_gerer_heures():
        return _refus_heures()

    conn = get_db()
    try:
        conn.execute('DELETE FROM benevoles_heures_autres WHERE id = ?', (ligne_id,))
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()
