"""
Blueprint subventions_bp - Gestion des subventions (board style Monday.com).

Accessible aux profils : directeur, comptable, responsable.
Les responsables ne voient que les subventions auxquelles ils sont assignes.
"""
import os
import re
import json
import sqlite3
import unicodedata
from datetime import datetime
from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, jsonify, send_file)
from database import get_db, DATA_DIR
from utils import login_required, aujourd_hui

subventions_bp = Blueprint('subventions_bp', __name__)

DOCUMENTS_DIR = os.path.join(DATA_DIR, 'documents', 'subventions')

# Statuts d'avancement d'une subvention (conserves pour les tableaux de bord :
# pipeline, echeances a venir, exclusion des refusees). Sur la page subventions,
# ce statut est affiche comme une petite etiquette editable par ligne — le
# regroupement principal se fait desormais par type de subvention.
STATUTS = [
    {'key': 'nouveau_projet', 'label': 'Nouveau projet', 'color': '#579bfc'},
    {'key': 'en_cours', 'label': 'En cours', 'color': '#fdab3d'},
    {'key': 'acceptee', 'label': 'Acceptée', 'color': '#00c875'},
    {'key': 'refusee', 'label': 'Refusée', 'color': '#e2445c'},
]

STATUTS_MAP = {s['key']: s for s in STATUTS}

# Groupe (statut) par defaut a la creation d'une subvention.
STATUT_DEFAUT = 'nouveau_projet'

# Palette de couleurs attribuee aux nouveaux types de subvention crees par
# l'utilisateur (cyclee selon le nombre de types existants).
TYPE_COULEURS = [
    '#579bfc', '#00c875', '#a25ddc', '#fdab3d', '#e2445c',
    '#037f4c', '#ff7575', '#9d99b9', '#66ccff', '#bb3354',
    '#ffcb00', '#7f5347',
]

# Couleur affichee pour le groupe « Sans type » (subventions non classees).
TYPE_COULEUR_SANS = '#c4c4c4'

SOUS_ELEMENT_STATUTS = [
    {'key': 'non_commence', 'label': 'Non commencé', 'color': '#c4c4c4'},
    {'key': 'en_cours', 'label': 'En cours', 'color': '#fdab3d'},
    {'key': 'fait', 'label': 'Fait', 'color': '#00c875'},
    {'key': 'blocage', 'label': 'Blocage', 'color': '#e2445c'},
]

SOUS_ELEMENT_STATUTS_KEYS = {s['key'] for s in SOUS_ELEMENT_STATUTS}
SOUS_ELEMENT_STATUTS_ALIASES = {
    'non_commence': 'non_commence',
    'non commence': 'non_commence',
    'non commencé': 'non_commence',
    'en_cours': 'en_cours',
    'en cours': 'en_cours',
    'fait': 'fait',
    'blocage': 'blocage',
}

DEFAULT_SOUS_ELEMENTS = [
    'Préparer le dossier',
    'Soumettre le dossier',
    'Envoyer le bilan qualitatif',
    'Envoyer le bilan financier',
]


def _peut_voir():
    return session.get('profil') in ('directeur', 'comptable', 'responsable')


def _peut_modifier():
    return session.get('profil') in ('directeur', 'comptable', 'responsable')


def _peut_gerer_types():
    """La gestion des types (creation / renommage / suppression) est une action
    globale : elle modifie le classement de toutes les subventions. Elle est donc
    reservee a la direction et a la comptabilite — en coherence avec l'interface
    qui masque « Gerer les types » aux responsables."""
    return session.get('profil') in ('directeur', 'comptable')


def _refus_acces_subvention(conn, sub_id):
    """Controle le perimetre d'une action portant sur la subvention `sub_id`.

    Retourne None quand l'action est autorisee, sinon la reponse JSON a renvoyer
    telle quelle : 404 si la subvention n'existe pas, 403 si le profil n'a pas le
    droit d'agir dessus.

    La direction et la comptabilite agissent sur toutes les subventions. Un
    responsable n'agit que sur celles qui lui sont assignees — exactement le
    perimetre de la page de consultation : assigne principal ou secondaire de la
    subvention, ou assigne de l'un de ses sous-elements. Sans ce controle, un
    responsable pourrait modifier ou supprimer par ID les subventions d'un autre
    secteur. Les autres profils sont refuses.
    """
    profil = session.get('profil')
    if profil not in ('directeur', 'comptable', 'responsable'):
        return jsonify({'ok': False, 'error': 'Non autorisé'}), 403

    existe = conn.execute('SELECT 1 FROM subventions WHERE id = ?', (sub_id,)).fetchone()
    if not existe:
        return jsonify({'ok': False, 'error': 'Subvention introuvable'}), 404

    if profil in ('directeur', 'comptable'):
        return None

    user_id = session.get('user_id')
    assignee = conn.execute(
        '''SELECT 1 FROM subventions
           WHERE id = ?
             AND (assignee_1_id = ? OR assignee_2_id = ?
                  OR id IN (
                      SELECT subvention_id FROM subventions_sous_elements
                      WHERE assignee_id = ?
                  ))''',
        (sub_id, user_id, user_id, user_id)
    ).fetchone()
    if not assignee:
        return jsonify({'ok': False, 'error': 'Non autorisé'}), 403
    return None


def _refus_acces_sous_element(conn, se_id):
    """Meme controle que `_refus_acces_subvention`, a partir d'un sous-element :
    le droit s'evalue toujours sur la subvention parente. Retourne None si
    l'action est autorisee, 404 si le sous-element est introuvable."""
    se = conn.execute(
        'SELECT subvention_id FROM subventions_sous_elements WHERE id = ?', (se_id,)
    ).fetchone()
    if not se:
        return jsonify({'ok': False, 'error': 'Sous-élément introuvable'}), 404
    return _refus_acces_subvention(conn, se['subvention_id'])


def _peut_telecharger_piece_subvention(conn, sub_id):
    """Vrai si le profil courant peut telecharger une piece de la subvention.

    Applique exactement le meme perimetre que les routes de modification (en
    reutilisant `_refus_acces_subvention`, pour que les deux ne divergent
    jamais). Sans ce controle, un responsable non assigne pourrait recuperer,
    en devinant l'identifiant, le justificatif d'une subvention d'un autre
    secteur — alors que la page de consultation ne la lui montre pas.
    """
    return _refus_acces_subvention(conn, sub_id) is None


def _peut_telecharger_piece_sous_element(conn, se_id):
    """Meme controle que ci-dessus, a partir d'un sous-element."""
    return _refus_acces_sous_element(conn, se_id) is None


def _get_initiales(prenom, nom):
    p = (prenom or '').strip()
    n = (nom or '').strip()
    p_init = (p[0].upper() + p[1].lower()) if len(p) >= 2 else p[:1].upper()
    n_init = (n[0].upper() + n[1].lower()) if len(n) >= 2 else n[:1].upper()
    return f"{p_init}.{n_init}" if p_init and n_init else ''


def _normalize_sous_element_statut(statut):
    """Normalise un statut de sous-élément vers une clé attendue par l'UI."""
    if not statut:
        return 'non_commence'
    statut_str = str(statut).strip().lower()
    if statut_str in SOUS_ELEMENT_STATUTS_KEYS:
        return statut_str
    return SOUS_ELEMENT_STATUTS_ALIASES.get(statut_str, 'non_commence')


def _parse_benevoles_ids(raw_value):
    """Parse une liste JSON d'IDs de bénévoles en IDs entiers dédupliqués."""
    if raw_value is None:
        return []

    values = raw_value
    if isinstance(raw_value, str):
        try:
            values = json.loads(raw_value)
        except (TypeError, ValueError):
            return []

    if not isinstance(values, list):
        return []

    ids = []
    seen_ids = set()
    for value in values:
        try:
            ben_id = int(value)
        except (TypeError, ValueError):
            continue
        if ben_id not in seen_ids:
            seen_ids.add(ben_id)
            ids.append(ben_id)
    return ids


# ── Vue principale ──

@subventions_bp.route('/subventions')
@login_required
def gestion_subventions():
    if not _peut_voir():
        flash("Accès non autorisé.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))

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

        # Actions du plan comptable analytique (= actions de bilan-action), pour
        # la colonne « Budget » : rattachement direct + lien vers bilan-action.
        actions_budget = conn.execute(
            'SELECT id, nom FROM comptabilite_actions ORDER BY nom'
        ).fetchall()

        benevoles_list = conn.execute(
            'SELECT id, nom FROM benevoles ORDER BY nom'
        ).fetchall()

        is_responsable = session.get('profil') == 'responsable'
        user_id = session.get('user_id')

        # Filtre par année de l'action : plage N-3 à N+2, année courante par
        # défaut. La valeur spéciale « toutes » désactive le filtre (utile pour
        # retrouver les subventions hors plage ou sans année renseignée).
        # L'année est bornée au menu affiché : une année hors plage passée en URL
        # retombe sur l'année courante (filtre affiché et données cohérents).
        annee_courante = aujourd_hui().year
        annees = [str(annee_courante + delta) for delta in range(-3, 3)]  # N-3 … N+2
        annee_param = (request.args.get('annee') or '').strip()
        if annee_param == 'toutes':
            annee_selected = 'toutes'
            annee_filter = None
        elif annee_param in annees:
            annee_selected = annee_param
            annee_filter = annee_param
        else:
            annee_selected = str(annee_courante)
            annee_filter = str(annee_courante)

        if is_responsable:
            # Le responsable voit les subventions dont il est assigné (parent) et
            # celles dont un sous-élément lui est directement attribué.
            base_sql = (
                '''SELECT * FROM subventions
                   WHERE (assignee_1_id = ? OR assignee_2_id = ?
                          OR id IN (
                              SELECT subvention_id FROM subventions_sous_elements
                              WHERE assignee_id = ?
                          ))'''
            )
            params = [user_id, user_id, user_id]
            if annee_filter is not None:
                base_sql += ' AND annee_action = ?'
                params.append(annee_filter)
            base_sql += ' ORDER BY ordre, id'
            subventions = conn.execute(base_sql, params).fetchall()
        else:
            if annee_filter is not None:
                subventions = conn.execute(
                    'SELECT * FROM subventions WHERE annee_action = ? ORDER BY ordre, id',
                    (annee_filter,)
                ).fetchall()
            else:
                subventions = conn.execute(
                    'SELECT * FROM subventions ORDER BY ordre, id'
                ).fetchall()

        subventions_data = []
        for s in subventions:
            s_dict = dict(s)
            parsed_benevoles_ids = _parse_benevoles_ids(s_dict.get('benevoles_ids'))
            s_dict['benevoles_ids_json'] = json.dumps(parsed_benevoles_ids)
            s_dict['benevoles_ids_parsed'] = parsed_benevoles_ids
            subventions_data.append(s_dict)

        sub_ids = [s['id'] for s in subventions_data]
        sous_elements = {}
        if sub_ids:
            placeholders = ','.join('?' * len(sub_ids))
            rows = conn.execute(
                f'SELECT * FROM subventions_sous_elements WHERE subvention_id IN ({placeholders}) ORDER BY ordre, id',
                sub_ids
            ).fetchall()
            for r in rows:
                r_dict = dict(r)
                r_dict['statut'] = _normalize_sous_element_statut(r_dict.get('statut'))
                sous_elements.setdefault(r['subvention_id'], []).append(r_dict)

        # Types de subvention = groupes (swimlanes) de la page. Charges depuis la
        # base pour permettre la creation / suppression par l'utilisateur.
        types_rows = conn.execute(
            'SELECT id, nom, couleur, ordre FROM subventions_types ORDER BY ordre, nom'
        ).fetchall()
        types_list = [dict(t) for t in types_rows]
        types_map = {t['id']: t for t in types_list}

        # Un groupe par type, dans l'ordre defini.
        groupes_data = []
        for t in types_list:
            lignes = [s for s in subventions_data if s.get('type_id') == t['id']]
            groupes_data.append({
                'key': 'type_%d' % t['id'],
                'type_id': t['id'],
                'label': t['nom'],
                'color': t['couleur'] or '#579bfc',
                'lignes': lignes,
                'is_type': True,
            })

        # Groupe « Sans type » : subventions non classees (type_id NULL ou type
        # supprime). Affiche uniquement s'il contient des elements.
        sans_type = [
            s for s in subventions_data
            if not s.get('type_id') or s.get('type_id') not in types_map
        ]
        if sans_type:
            groupes_data.append({
                'key': 'sans_type',
                'type_id': None,
                'label': 'Sans type',
                'color': TYPE_COULEUR_SANS,
                'lignes': sans_type,
                'is_type': False,
            })

    finally:
        conn.close()

    return render_template(
        'subventions.html',
        groupes=groupes_data,
        sous_elements=sous_elements,
        users=users,
        users_map=users_map,
        actions_budget=actions_budget,
        benevoles_list=benevoles_list,
        types_config=types_list,
        types_map=types_map,
        statuts_config=STATUTS,
        statuts_se_config=SOUS_ELEMENT_STATUTS,
        is_responsable=is_responsable,
        annees=annees,
        annee_selected=annee_selected,
        annee_courante=str(annee_courante),
    )


# ── API : Subventions CRUD ──

@subventions_bp.route('/api/subventions/ajouter', methods=['POST'])
@login_required
def api_ajouter_subvention():
    if not _peut_modifier():
        return jsonify({'ok': False, 'error': 'Non autorisé'}), 403

    data = request.get_json(silent=True) or {}
    nom = (data.get('nom') or '').strip()
    groupe = data.get('groupe') or STATUT_DEFAUT
    annee_action = (data.get('annee_action') or '').strip()

    if not nom:
        return jsonify({'ok': False, 'error': 'Nom requis'}), 400
    if groupe not in STATUTS_MAP:
        groupe = STATUT_DEFAUT

    # Type de subvention (defini a la creation, modifiable ensuite).
    type_id = data.get('type_id')
    try:
        type_id = int(type_id) if type_id not in (None, '', 'null') else None
    except (ValueError, TypeError):
        type_id = None

    conn = get_db()
    try:
        if type_id is not None:
            exists = conn.execute(
                'SELECT 1 FROM subventions_types WHERE id = ?', (type_id,)
            ).fetchone()
            if not exists:
                type_id = None

        cursor = conn.execute(
            'INSERT INTO subventions (nom, groupe, annee_action, type_id) VALUES (?, ?, ?, ?)',
            (nom, groupe, annee_action or None, type_id)
        )
        sub_id = cursor.lastrowid

        for i, se_nom in enumerate(DEFAULT_SOUS_ELEMENTS):
            conn.execute(
                'INSERT INTO subventions_sous_elements (subvention_id, nom, ordre) VALUES (?, ?, ?)',
                (sub_id, se_nom, i)
            )

        conn.commit()
        return jsonify({'ok': True, 'id': sub_id})
    finally:
        conn.close()


def _notifier_attribution(conn, assignee_id, subvention_nom, annee_effective, sous_element_nom=None):
    """Notifie par e-mail la personne nouvellement assignee a une subvention ou a
    l'un de ses sous-elements. Silencieux : une notification ne doit jamais faire
    echouer l'action (e-mail non configure, consentement absent, erreur SMTP...)."""
    if not assignee_id:
        return
    try:
        from email_service import (is_email_configured, peut_envoyer_email,
                                    notifier_subvention_assignee)
        if not is_email_configured():
            return
        peut, email = peut_envoyer_email(assignee_id)
        if not peut or not email:
            return
        row = conn.execute('SELECT prenom FROM users WHERE id = ?', (assignee_id,)).fetchone()
        notifier_subvention_assignee(
            email, row['prenom'] if row else '', subvention_nom,
            annee_effective, sous_element_nom
        )
    except Exception:
        pass


@subventions_bp.route('/api/subventions/<int:sub_id>/modifier', methods=['POST'])
@login_required
def api_modifier_subvention(sub_id):
    if not _peut_modifier():
        return jsonify({'ok': False, 'error': 'Non autorisé'}), 403

    data = request.get_json(silent=True) or {}
    field = data.get('field')
    value = data.get('value')

    allowed_fields = {
        'nom', 'groupe', 'type_id', 'assignee_1_id', 'assignee_2_id',
        'date_echeance', 'montant_demande', 'montant_accorde',
        'date_notification', 'analytique_id', 'contact_email',
        'compte_comptable', 'annee_action',
        'compte_comptable_1_id', 'compte_comptable_2_id',
        'benevoles_ids', 'action_budget_id',
    }

    if field not in allowed_fields:
        return jsonify({'ok': False, 'error': f'Champ non autorisé: {field}'}), 400

    if field == 'groupe' and value not in STATUTS_MAP:
        return jsonify({'ok': False, 'error': 'Statut invalide'}), 400

    if field in ('assignee_1_id', 'assignee_2_id', 'analytique_id',
                 'compte_comptable_1_id', 'compte_comptable_2_id',
                 'action_budget_id', 'type_id'):
        value = int(value) if value else None
    elif field in ('montant_demande', 'montant_accorde'):
        try:
            value = float(value) if value else 0
        except (ValueError, TypeError):
            value = 0

    conn = get_db()
    try:
        refus = _refus_acces_subvention(conn, sub_id)
        if refus:
            return refus

        # Coherence avec la creation : refuser un type inexistant plutot que de
        # laisser une reference orpheline (les FK ne sont pas activees).
        if field == 'type_id' and value is not None:
            if not conn.execute(
                'SELECT 1 FROM subventions_types WHERE id = ?', (value,)
            ).fetchone():
                return jsonify({'ok': False, 'error': 'Type introuvable'}), 404

        # Detecter un changement d'assignation pour notifier le nouvel assigne.
        infos_notif = None
        if field in ('assignee_1_id', 'assignee_2_id') and value:
            avant = conn.execute(
                f'SELECT {field} AS ancien, nom, annee_action FROM subventions WHERE id = ?',
                (sub_id,)
            ).fetchone()
            if avant and value != avant['ancien']:
                infos_notif = (avant['nom'], avant['annee_action'])
        conn.execute(
            f'UPDATE subventions SET {field} = ?, updated_at = ? WHERE id = ?',
            (value, datetime.now().isoformat(), sub_id)
        )
        conn.commit()
        if infos_notif:
            _notifier_attribution(conn, value, infos_notif[0], infos_notif[1])
        return jsonify({'ok': True})
    finally:
        conn.close()


@subventions_bp.route('/api/subventions/<int:sub_id>/supprimer', methods=['POST'])
@login_required
def api_supprimer_subvention(sub_id):
    if not _peut_modifier():
        return jsonify({'ok': False, 'error': 'Non autorisé'}), 403

    conn = get_db()
    try:
        refus = _refus_acces_subvention(conn, sub_id)
        if refus:
            return refus

        conn.execute('DELETE FROM subventions_sous_elements WHERE subvention_id = ?', (sub_id,))
        sub = conn.execute('SELECT justificatif_path FROM subventions WHERE id = ?', (sub_id,)).fetchone()
        if sub and sub['justificatif_path']:
            chemin = os.path.join(DOCUMENTS_DIR, sub['justificatif_path'])
            chemin_reel = os.path.realpath(chemin)
            dossier_reel = os.path.realpath(DOCUMENTS_DIR)
            if chemin_reel.startswith(dossier_reel + os.sep) and os.path.exists(chemin):
                os.remove(chemin)
        conn.execute('DELETE FROM subventions WHERE id = ?', (sub_id,))
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()


# ── API : Types de subvention ──

@subventions_bp.route('/api/subventions/types/ajouter', methods=['POST'])
@login_required
def api_ajouter_type():
    if not _peut_gerer_types():
        return jsonify({'ok': False, 'error': 'Non autorisé'}), 403

    data = request.get_json(silent=True) or {}
    nom = (data.get('nom') or '').strip()
    if not nom:
        return jsonify({'ok': False, 'error': 'Nom requis'}), 400

    conn = get_db()
    try:
        existing = conn.execute(
            'SELECT id, nom, couleur FROM subventions_types WHERE nom = ? COLLATE NOCASE',
            (nom,)
        ).fetchone()
        if existing:
            return jsonify({'ok': True, 'id': existing['id'], 'nom': existing['nom'],
                            'couleur': existing['couleur'], 'existe': True})

        row = conn.execute(
            'SELECT COUNT(*) AS n, COALESCE(MAX(ordre), -1) AS m FROM subventions_types'
        ).fetchone()
        couleur = TYPE_COULEURS[row['n'] % len(TYPE_COULEURS)]
        try:
            cursor = conn.execute(
                'INSERT INTO subventions_types (nom, couleur, ordre) VALUES (?, ?, ?)',
                (nom, couleur, row['m'] + 1)
            )
        except sqlite3.IntegrityError:
            # Course entre deux creations simultanees du meme nom : renvoyer l'existant.
            existing = conn.execute(
                'SELECT id, nom, couleur FROM subventions_types WHERE nom = ? COLLATE NOCASE',
                (nom,)
            ).fetchone()
            if existing:
                return jsonify({'ok': True, 'id': existing['id'], 'nom': existing['nom'],
                                'couleur': existing['couleur'], 'existe': True})
            return jsonify({'ok': False, 'error': 'Ce type existe déjà'}), 400
        conn.commit()
        return jsonify({'ok': True, 'id': cursor.lastrowid, 'nom': nom, 'couleur': couleur})
    finally:
        conn.close()


@subventions_bp.route('/api/subventions/types/<int:type_id>/modifier', methods=['POST'])
@login_required
def api_modifier_type(type_id):
    if not _peut_gerer_types():
        return jsonify({'ok': False, 'error': 'Non autorisé'}), 403

    data = request.get_json(silent=True) or {}
    field = data.get('field', 'nom')
    value = (data.get('value') or '').strip()

    if field not in ('nom', 'couleur'):
        return jsonify({'ok': False, 'error': f'Champ non autorisé: {field}'}), 400
    if field == 'nom' and not value:
        return jsonify({'ok': False, 'error': 'Nom requis'}), 400
    # La couleur alimente des attributs de style et le JS inline de la page :
    # on impose un code hexadecimal strict (#rrggbb) pour eviter toute injection.
    if field == 'couleur' and not re.fullmatch(r'#[0-9A-Fa-f]{6}', value):
        return jsonify({'ok': False, 'error': 'Couleur invalide'}), 400

    conn = get_db()
    try:
        exists = conn.execute('SELECT 1 FROM subventions_types WHERE id = ?', (type_id,)).fetchone()
        if not exists:
            return jsonify({'ok': False, 'error': 'Type introuvable'}), 404
        if field == 'nom':
            doublon = conn.execute(
                'SELECT 1 FROM subventions_types WHERE nom = ? COLLATE NOCASE AND id != ?',
                (value, type_id)
            ).fetchone()
            if doublon:
                return jsonify({'ok': False, 'error': 'Ce type existe déjà'}), 400
        # field est valide ('nom' ou 'couleur') : pas d'injection possible.
        conn.execute(f'UPDATE subventions_types SET {field} = ? WHERE id = ?', (value, type_id))
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()


@subventions_bp.route('/api/subventions/types/<int:type_id>/supprimer', methods=['POST'])
@login_required
def api_supprimer_type(type_id):
    if not _peut_gerer_types():
        return jsonify({'ok': False, 'error': 'Non autorisé'}), 403

    conn = get_db()
    try:
        # Les subventions rattachees a ce type basculent en « Sans type ».
        conn.execute('UPDATE subventions SET type_id = NULL WHERE type_id = ?', (type_id,))
        conn.execute('DELETE FROM subventions_types WHERE id = ?', (type_id,))
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()


# ── API : Sous-éléments CRUD ──

@subventions_bp.route('/api/subventions/<int:sub_id>/sous-elements/ajouter', methods=['POST'])
@login_required
def api_ajouter_sous_element(sub_id):
    if not _peut_modifier():
        return jsonify({'ok': False, 'error': 'Non autorisé'}), 403

    data = request.get_json(silent=True) or {}
    nom = (data.get('nom') or '').strip()
    if not nom:
        return jsonify({'ok': False, 'error': 'Nom requis'}), 400

    conn = get_db()
    try:
        refus = _refus_acces_subvention(conn, sub_id)
        if refus:
            return refus

        max_ordre = conn.execute(
            'SELECT COALESCE(MAX(ordre), -1) as m FROM subventions_sous_elements WHERE subvention_id = ?',
            (sub_id,)
        ).fetchone()['m']

        cursor = conn.execute(
            'INSERT INTO subventions_sous_elements (subvention_id, nom, ordre) VALUES (?, ?, ?)',
            (sub_id, nom, max_ordre + 1)
        )
        conn.commit()
        return jsonify({'ok': True, 'id': cursor.lastrowid})
    finally:
        conn.close()


@subventions_bp.route('/api/subventions/sous-elements/<int:se_id>/modifier', methods=['POST'])
@login_required
def api_modifier_sous_element(se_id):
    if not _peut_modifier():
        return jsonify({'ok': False, 'error': 'Non autorisé'}), 403

    data = request.get_json(silent=True) or {}
    field = data.get('field')
    value = data.get('value')

    allowed_fields = {'nom', 'assignee_id', 'statut', 'date_echeance'}
    if field not in allowed_fields:
        return jsonify({'ok': False, 'error': f'Champ non autorisé: {field}'}), 400

    if field == 'assignee_id':
        value = int(value) if value else None
    elif field == 'statut':
        value = _normalize_sous_element_statut(value)

    conn = get_db()
    try:
        refus = _refus_acces_sous_element(conn, se_id)
        if refus:
            return refus

        infos_notif = None
        if field == 'assignee_id' and value:
            avant = conn.execute(
                'SELECT se.assignee_id AS ancien, se.nom AS se_nom, '
                '       s.nom AS sub_nom, s.annee_action AS annee '
                'FROM subventions_sous_elements se '
                'JOIN subventions s ON s.id = se.subvention_id '
                'WHERE se.id = ?',
                (se_id,)
            ).fetchone()
            if avant and value != avant['ancien']:
                infos_notif = (avant['sub_nom'], avant['annee'], avant['se_nom'])
        conn.execute(
            f'UPDATE subventions_sous_elements SET {field} = ? WHERE id = ?',
            (value, se_id)
        )
        conn.commit()
        if infos_notif:
            _notifier_attribution(conn, value, infos_notif[0], infos_notif[1], infos_notif[2])
        return jsonify({'ok': True})
    finally:
        conn.close()


@subventions_bp.route('/api/subventions/sous-elements/<int:se_id>/supprimer', methods=['POST'])
@login_required
def api_supprimer_sous_element(se_id):
    if not _peut_modifier():
        return jsonify({'ok': False, 'error': 'Non autorisé'}), 403

    conn = get_db()
    try:
        refus = _refus_acces_sous_element(conn, se_id)
        if refus:
            return refus

        se = conn.execute('SELECT document_path FROM subventions_sous_elements WHERE id = ?', (se_id,)).fetchone()
        if se and se['document_path']:
            chemin = os.path.join(DOCUMENTS_DIR, se['document_path'])
            chemin_reel = os.path.realpath(chemin)
            dossier_reel = os.path.realpath(DOCUMENTS_DIR)
            if chemin_reel.startswith(dossier_reel + os.sep) and os.path.exists(chemin):
                os.remove(chemin)
        conn.execute('DELETE FROM subventions_sous_elements WHERE id = ?', (se_id,))
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()


# ── API : Analytiques ──

@subventions_bp.route('/api/subventions/analytiques/ajouter', methods=['POST'])
@login_required
def api_ajouter_analytique():
    # Le plan analytique est un referentiel GLOBAL, partage par toutes les
    # subventions et tous les secteurs : sa creation suit la meme regle que la
    # gestion des types (direction / comptabilite). L'interface ne l'expose a
    # aucun responsable — la page subventions n'appelle pas cet endpoint —, la
    # restriction ne casse donc aucun parcours utilisateur.
    if not _peut_gerer_types():
        return jsonify({'ok': False, 'error': 'Non autorisé'}), 403

    data = request.get_json(silent=True) or {}
    nom = (data.get('nom') or '').strip()
    if not nom:
        return jsonify({'ok': False, 'error': 'Nom requis'}), 400

    conn = get_db()
    try:
        existing = conn.execute(
            'SELECT id FROM subventions_analytiques WHERE nom = ?', (nom,)
        ).fetchone()
        if existing:
            return jsonify({'ok': True, 'id': existing['id']})

        cursor = conn.execute(
            'INSERT INTO subventions_analytiques (nom) VALUES (?)', (nom,)
        )
        conn.commit()
        return jsonify({'ok': True, 'id': cursor.lastrowid})
    finally:
        conn.close()


def _normalize_filename(text):
    """Normalise un texte pour l'utiliser dans un nom de fichier."""
    text = unicodedata.normalize('NFD', text)
    text = text.encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[^a-zA-Z0-9]', '_', text)
    text = re.sub(r'_+', '_', text).strip('_')
    return text


def _sanitize_year_for_filename(year_value):
    """Retourne une année sûre (4 chiffres) pour un nom de fichier."""
    year_text = str(year_value or '').strip()
    if re.fullmatch(r'\d{4}', year_text):
        return year_text
    return datetime.now().strftime('%Y')


# ── Document sous-élément (upload / download) ──

@subventions_bp.route('/api/subventions/sous-elements/<int:se_id>/document', methods=['POST'])
@login_required
def api_upload_se_document(se_id):
    if not _peut_modifier():
        return jsonify({'ok': False, 'error': 'Non autorisé'}), 403

    fichier = request.files.get('fichier')
    if not fichier or not fichier.filename:
        return jsonify({'ok': False, 'error': 'Fichier requis'}), 400

    ext = os.path.splitext(fichier.filename)[1].lower()
    if ext != '.pdf':
        return jsonify({'ok': False, 'error': 'Seuls les fichiers PDF sont acceptés'}), 400

    os.makedirs(DOCUMENTS_DIR, exist_ok=True)

    conn = get_db()
    try:
        refus = _refus_acces_sous_element(conn, se_id)
        if refus:
            return refus

        se = conn.execute(
            'SELECT se.*, s.nom as sub_nom, s.annee_action '
            'FROM subventions_sous_elements se '
            'JOIN subventions s ON se.subvention_id = s.id '
            'WHERE se.id = ?', (se_id,)
        ).fetchone()
        if not se:
            return jsonify({'ok': False, 'error': 'Sous-élément introuvable'}), 404

        annee = _sanitize_year_for_filename(se['annee_action'])
        nom_sub = _normalize_filename(se['sub_nom'] or 'subvention')
        nom_se = _normalize_filename(se['nom'] or 'etape')
        nom_fichier = f"{annee}_{nom_sub}_{nom_se}_{se_id}{ext}"
        chemin_complet = os.path.join(DOCUMENTS_DIR, nom_fichier)
        chemin_reel = os.path.realpath(chemin_complet)
        dossier_reel = os.path.realpath(DOCUMENTS_DIR)
        try:
            est_dans_documents = os.path.commonpath([chemin_reel, dossier_reel]) == dossier_reel
        except ValueError:
            est_dans_documents = False
        if not est_dans_documents:
            return jsonify({'ok': False, 'error': 'Nom de fichier invalide'}), 400

        # Supprimer l'ancien document s'il existe
        if se['document_path']:
            old_path = os.path.join(DOCUMENTS_DIR, se['document_path'])
            old_path_reel = os.path.realpath(old_path)
            dossier_reel = os.path.realpath(DOCUMENTS_DIR)
            if old_path_reel.startswith(dossier_reel + os.sep) and os.path.exists(old_path):
                os.remove(old_path)

        fichier.save(chemin_complet)

        conn.execute(
            'UPDATE subventions_sous_elements SET document_path = ?, document_nom = ? WHERE id = ?',
            (nom_fichier, nom_fichier, se_id)
        )
        conn.commit()
        return jsonify({'ok': True, 'nom': nom_fichier})
    finally:
        conn.close()


@subventions_bp.route('/subventions/sous-element-document/<int:se_id>')
@login_required
def telecharger_se_document(se_id):
    if not _peut_voir():
        flash("Accès non autorisé.", "error")
        return redirect(url_for('subventions_bp.gestion_subventions'))

    conn = get_db()
    try:
        if not _peut_telecharger_piece_sous_element(conn, se_id):
            flash("Accès non autorisé.", "error")
            return redirect(url_for('subventions_bp.gestion_subventions'))
        se = conn.execute(
            'SELECT document_path, document_nom FROM subventions_sous_elements WHERE id = ?',
            (se_id,)
        ).fetchone()
    finally:
        conn.close()

    if not se or not se['document_path']:
        flash("Aucun document.", "error")
        return redirect(url_for('subventions_bp.gestion_subventions'))

    chemin = os.path.join(DOCUMENTS_DIR, se['document_path'])
    chemin_reel = os.path.realpath(chemin)
    dossier_reel = os.path.realpath(DOCUMENTS_DIR)
    if not chemin_reel.startswith(dossier_reel + os.sep):
        flash("Accès non autorisé.", "error")
        return redirect(url_for('subventions_bp.gestion_subventions'))

    if not os.path.exists(chemin):
        flash("Fichier introuvable.", "error")
        return redirect(url_for('subventions_bp.gestion_subventions'))

    return send_file(chemin, as_attachment=True, download_name=se['document_nom'] or 'document.pdf')


# ── Justificatif (upload / download) ──

@subventions_bp.route('/api/subventions/<int:sub_id>/justificatif', methods=['POST'])
@login_required
def api_upload_justificatif(sub_id):
    if not _peut_modifier():
        return jsonify({'ok': False, 'error': 'Non autorisé'}), 403

    fichier = request.files.get('fichier')
    if not fichier or not fichier.filename:
        return jsonify({'ok': False, 'error': 'Fichier requis'}), 400

    ext = os.path.splitext(fichier.filename)[1].lower()
    if ext != '.pdf':
        return jsonify({'ok': False, 'error': 'Seuls les fichiers PDF sont acceptés'}), 400

    os.makedirs(DOCUMENTS_DIR, exist_ok=True)

    conn = get_db()
    try:
        refus = _refus_acces_subvention(conn, sub_id)
        if refus:
            return refus

        sub = conn.execute(
            'SELECT nom, justificatif_path FROM subventions WHERE id = ?', (sub_id,)
        ).fetchone()
        if not sub:
            return jsonify({'ok': False, 'error': 'Subvention introuvable'}), 404

        # Nom normalisé : AAAA_NOTIFICATION_Nom-subvention.pdf
        annee = datetime.now().strftime('%Y')
        nom_sub = sub['nom'] or f'subvention-{sub_id}'
        # Retirer les accents
        nom_sub = unicodedata.normalize('NFD', nom_sub)
        nom_sub = nom_sub.encode('ascii', 'ignore').decode('ascii')
        # Remplacer espaces et caractères spéciaux par des tirets
        nom_sub = re.sub(r'[^a-zA-Z0-9-]', '-', nom_sub)
        nom_sub = re.sub(r'-+', '-', nom_sub).strip('-')
        nom_fichier = f"{annee}_NOTIFICATION_{nom_sub}{ext}"
        nom_affichage = nom_fichier
        chemin_complet = os.path.join(DOCUMENTS_DIR, nom_fichier)

        # Supprimer l'ancien fichier s'il existe
        if sub['justificatif_path']:
            old_path = os.path.join(DOCUMENTS_DIR, sub['justificatif_path'])
            old_path_reel = os.path.realpath(old_path)
            dossier_reel = os.path.realpath(DOCUMENTS_DIR)
            if old_path_reel.startswith(dossier_reel + os.sep) and os.path.exists(old_path):
                os.remove(old_path)

        fichier.save(chemin_complet)

        conn.execute(
            'UPDATE subventions SET justificatif_path = ?, justificatif_nom = ?, updated_at = ? WHERE id = ?',
            (nom_fichier, nom_affichage, datetime.now().isoformat(), sub_id)
        )
        conn.commit()
        return jsonify({'ok': True, 'nom': nom_affichage})
    finally:
        conn.close()


@subventions_bp.route('/subventions/justificatif/<int:sub_id>')
@login_required
def telecharger_justificatif(sub_id):
    if not _peut_voir():
        flash("Accès non autorisé.", "error")
        return redirect(url_for('subventions_bp.gestion_subventions'))

    conn = get_db()
    try:
        if not _peut_telecharger_piece_subvention(conn, sub_id):
            flash("Accès non autorisé.", "error")
            return redirect(url_for('subventions_bp.gestion_subventions'))
        sub = conn.execute(
            'SELECT justificatif_path, justificatif_nom FROM subventions WHERE id = ?',
            (sub_id,)
        ).fetchone()
    finally:
        conn.close()

    if not sub or not sub['justificatif_path']:
        flash("Aucun justificatif.", "error")
        return redirect(url_for('subventions_bp.gestion_subventions'))

    chemin = os.path.join(DOCUMENTS_DIR, sub['justificatif_path'])
    chemin_reel = os.path.realpath(chemin)
    dossier_reel = os.path.realpath(DOCUMENTS_DIR)
    if not chemin_reel.startswith(dossier_reel + os.sep):
        flash("Accès non autorisé.", "error")
        return redirect(url_for('subventions_bp.gestion_subventions'))

    if not os.path.exists(chemin):
        flash("Fichier introuvable.", "error")
        return redirect(url_for('subventions_bp.gestion_subventions'))

    return send_file(chemin, as_attachment=True, download_name=sub['justificatif_nom'] or 'justificatif.pdf')
