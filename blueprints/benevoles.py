"""
Blueprint benevoles_bp - Liste des benevoles (board style Monday.com).

Accessible aux profils : directeur, comptable, responsable.
Les responsables ne voient que les benevoles auxquels ils sont assignes.
"""
from datetime import datetime
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


# ── Vue principale ──

@benevoles_bp.route('/benevoles')
@login_required
def gestion_benevoles():
    if not _peut_voir():
        flash("Acces non autorise.", "error")
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

        is_responsable = session.get('profil') == 'responsable'
        user_id = session.get('user_id')

        if is_responsable:
            benevoles = conn.execute(
                'SELECT * FROM benevoles WHERE responsable_id = %s ORDER BY ordre, id',
                (user_id,)
            ).fetchall()
        else:
            benevoles = conn.execute(
                'SELECT * FROM benevoles ORDER BY ordre, id'
            ).fetchall()

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
        is_responsable=is_responsable,
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
            'INSERT INTO benevoles (nom, groupe) VALUES (%s, %s) RETURNING id',
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
        'nom', 'groupe', 'responsable_id', 'date_debut',
        'email', 'telephone', 'adresse', 'competences',
        'heures_semaine',
    }

    if field not in allowed_fields:
        return jsonify({'ok': False, 'error': f'Champ non autorise: {field}'}), 400

    if field == 'responsable_id':
        value = int(value) if value else None

    conn = get_db()
    try:
        conn.execute(
            f'UPDATE benevoles SET {field} = %s, updated_at = %s WHERE id = %s',
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
        conn.execute('DELETE FROM benevoles WHERE id = %s', (ben_id,))
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()
