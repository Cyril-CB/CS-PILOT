"""
Blueprint subventions_bp - Gestion des subventions (board style Monday.com).

Accessible aux profils : directeur, comptable, responsable.
Les responsables ne voient que les subventions auxquelles ils sont assignes.
"""
import os
import re
import json
import unicodedata
from datetime import datetime
from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, jsonify, send_file)
from database import get_db, DATA_DIR
from utils import login_required

subventions_bp = Blueprint('subventions_bp', __name__)

DOCUMENTS_DIR = os.path.join(DATA_DIR, 'documents', 'subventions')

GROUPES = [
    {'key': 'nouveau_projet', 'label': 'Nouveau projet', 'color': '#579bfc'},
    {'key': 'en_cours', 'label': 'Subvention en cours', 'color': '#fdab3d'},
    {'key': 'acceptee', 'label': 'Subventions acceptées', 'color': '#00c875'},
    {'key': 'refusee', 'label': 'Subventions refusées', 'color': '#e2445c'},
]

GROUPES_MAP = {g['key']: g for g in GROUPES}

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
    for value in values:
        try:
            ben_id = int(value)
        except (TypeError, ValueError):
            continue
        if ben_id not in ids:
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

        analytiques = conn.execute(
            'SELECT id, nom FROM subventions_analytiques ORDER BY nom'
        ).fetchall()

        comptes_comptables = conn.execute(
            'SELECT id, compte_num, libelle FROM comptabilite_comptes ORDER BY compte_num'
        ).fetchall()

        benevoles_list = conn.execute(
            'SELECT id, nom FROM benevoles ORDER BY nom'
        ).fetchall()

        is_responsable = session.get('profil') == 'responsable'
        user_id = session.get('user_id')

        if is_responsable:
            subventions = conn.execute(
                'SELECT * FROM subventions WHERE assignee_1_id = ? OR assignee_2_id = ? ORDER BY ordre, id',
                (user_id, user_id)
            ).fetchall()
        else:
            subventions = conn.execute(
                'SELECT * FROM subventions ORDER BY ordre, id'
            ).fetchall()

        subventions_data = []
        for s in subventions:
            s_dict = dict(s)
            parsed_benevoles_ids = _parse_benevoles_ids(s_dict.get('benevoles_ids'))
            s_dict['benevoles_ids'] = json.dumps(parsed_benevoles_ids)
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

        groupes_data = []
        for g in GROUPES:
            lignes = [s for s in subventions_data if s['groupe'] == g['key']]
            groupes_data.append({
                'key': g['key'],
                'label': g['label'],
                'color': g['color'],
                'lignes': lignes,
            })

    finally:
        conn.close()

    return render_template(
        'subventions.html',
        groupes=groupes_data,
        sous_elements=sous_elements,
        users=users,
        users_map=users_map,
        analytiques=analytiques,
        comptes_comptables=comptes_comptables,
        benevoles_list=benevoles_list,
        groupes_config=GROUPES,
        statuts_config=SOUS_ELEMENT_STATUTS,
        is_responsable=is_responsable,
    )


# ── API : Subventions CRUD ──

@subventions_bp.route('/api/subventions/ajouter', methods=['POST'])
@login_required
def api_ajouter_subvention():
    if not _peut_modifier():
        return jsonify({'ok': False, 'error': 'Non autorisé'}), 403

    data = request.get_json(silent=True) or {}
    nom = (data.get('nom') or '').strip()
    groupe = data.get('groupe', 'nouveau_projet')
    annee_action = (data.get('annee_action') or '').strip()

    if not nom:
        return jsonify({'ok': False, 'error': 'Nom requis'}), 400
    if groupe not in GROUPES_MAP:
        groupe = 'nouveau_projet'

    conn = get_db()
    try:
        cursor = conn.execute(
            'INSERT INTO subventions (nom, groupe, annee_action) VALUES (?, ?, ?)',
            (nom, groupe, annee_action or None)
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


@subventions_bp.route('/api/subventions/<int:sub_id>/modifier', methods=['POST'])
@login_required
def api_modifier_subvention(sub_id):
    if not _peut_modifier():
        return jsonify({'ok': False, 'error': 'Non autorisé'}), 403

    data = request.get_json(silent=True) or {}
    field = data.get('field')
    value = data.get('value')

    allowed_fields = {
        'nom', 'groupe', 'assignee_1_id', 'assignee_2_id',
        'date_echeance', 'montant_demande', 'montant_accorde',
        'date_notification', 'analytique_id', 'contact_email',
        'compte_comptable', 'annee_action',
        'compte_comptable_1_id', 'compte_comptable_2_id',
        'benevoles_ids',
    }

    if field not in allowed_fields:
        return jsonify({'ok': False, 'error': f'Champ non autorisé: {field}'}), 400

    if field in ('assignee_1_id', 'assignee_2_id', 'analytique_id',
                 'compte_comptable_1_id', 'compte_comptable_2_id'):
        value = int(value) if value else None
    elif field in ('montant_demande', 'montant_accorde'):
        try:
            value = float(value) if value else 0
        except (ValueError, TypeError):
            value = 0

    conn = get_db()
    try:
        conn.execute(
            f'UPDATE subventions SET {field} = ?, updated_at = ? WHERE id = ?',
            (value, datetime.now().isoformat(), sub_id)
        )
        conn.commit()
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
        conn.execute(
            f'UPDATE subventions_sous_elements SET {field} = ? WHERE id = ?',
            (value, se_id)
        )
        conn.commit()
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
    if not _peut_modifier():
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
