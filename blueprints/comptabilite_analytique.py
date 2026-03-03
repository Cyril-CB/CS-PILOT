"""
Blueprint comptabilite_analytique_bp - Plan comptable analytique.

Fonctionnalites :
- Saisie manuelle de comptes analytiques (numero, libelle)
- Import de comptes au format TXT tabule (numero + libelle)
- Affectation de chaque compte a un secteur (liste deroulante existante)
- Affectation de chaque compte a une action (liste deroulante, ajout possible)
- Accessible aux profils directeur et comptable
"""
import csv
import io
from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, jsonify)
from database import get_db
from utils import login_required

comptabilite_analytique_bp = Blueprint('comptabilite_analytique_bp', __name__)


def _peut_acceder():
    return session.get('profil') in ('directeur', 'comptable')


# ── Page principale ──────────────────────────────────────────────────────────

@comptabilite_analytique_bp.route('/plan-comptable-analytique')
@login_required
def plan_comptable_analytique():
    """Affiche le plan comptable analytique avec possibilite d'edition."""
    if not _peut_acceder():
        flash('Accès non autorisé.', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    try:
        comptes = conn.execute('''
            SELECT c.*, s.nom as secteur_nom, a.nom as action_nom
            FROM comptabilite_comptes c
            LEFT JOIN secteurs s ON c.secteur_id = s.id
            LEFT JOIN comptabilite_actions a ON c.action_id = a.id
            ORDER BY c.compte_num
        ''').fetchall()

        secteurs = conn.execute('SELECT id, nom FROM secteurs ORDER BY nom').fetchall()
        actions = conn.execute('SELECT id, nom FROM comptabilite_actions ORDER BY nom').fetchall()

        return render_template('plan_comptable_analytique.html',
                               comptes=comptes, secteurs=secteurs, actions=actions)
    finally:
        conn.close()


# ── Ajout d'un compte ────────────────────────────────────────────────────────

@comptabilite_analytique_bp.route('/api/comptabilite/comptes', methods=['POST'])
@login_required
def api_ajouter_compte():
    """Ajoute un compte analytique."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    data = request.get_json() or {}
    compte_num = (data.get('compte_num') or '').strip()
    libelle = (data.get('libelle') or '').strip()

    if not compte_num or not libelle:
        return jsonify({'error': 'Numéro de compte et libellé requis.'}), 400

    conn = get_db()
    try:
        existing = conn.execute(
            'SELECT id FROM comptabilite_comptes WHERE compte_num = ?', (compte_num,)
        ).fetchone()
        if existing:
            return jsonify({'error': f'Le compte {compte_num} existe déjà.'}), 409

        conn.execute(
            'INSERT INTO comptabilite_comptes (compte_num, libelle) VALUES (?, ?)',
            (compte_num, libelle)
        )
        conn.commit()
        return jsonify({'success': True, 'message': f'Compte {compte_num} ajouté.'})
    finally:
        conn.close()


# ── Suppression d'un compte ──────────────────────────────────────────────────

@comptabilite_analytique_bp.route('/api/comptabilite/comptes/<int:compte_id>', methods=['DELETE'])
@login_required
def api_supprimer_compte(compte_id):
    """Supprime un compte analytique."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    conn = get_db()
    try:
        conn.execute('DELETE FROM comptabilite_comptes WHERE id = ?', (compte_id,))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


# ── Import TXT ───────────────────────────────────────────────────────────────

@comptabilite_analytique_bp.route('/api/comptabilite/import-txt', methods=['POST'])
@login_required
def api_import_txt():
    """Importe un plan comptable analytique au format TXT tabule."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    fichier = request.files.get('fichier')
    if not fichier or not fichier.filename:
        return jsonify({'error': 'Aucun fichier fourni.'}), 400

    try:
        content = fichier.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        try:
            fichier.seek(0)
            content = fichier.read().decode('latin-1')
        except Exception:
            return jsonify({'error': 'Encodage du fichier non reconnu.'}), 400

    lines = content.strip().split('\n')
    if not lines:
        return jsonify({'error': 'Fichier vide.'}), 400

    conn = get_db()
    try:
        nb_importes = 0
        nb_doublons = 0

        for line in lines:
            parts = line.strip().split('\t')
            if len(parts) < 2:
                continue

            compte_num = parts[0].strip()
            libelle = parts[1].strip()
            if not compte_num or not libelle:
                continue

            existing = conn.execute(
                'SELECT id FROM comptabilite_comptes WHERE compte_num = ?', (compte_num,)
            ).fetchone()
            if existing:
                # Mettre a jour le libelle si different
                conn.execute(
                    'UPDATE comptabilite_comptes SET libelle = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                    (libelle, existing['id'])
                )
                nb_doublons += 1
            else:
                conn.execute(
                    'INSERT INTO comptabilite_comptes (compte_num, libelle) VALUES (?, ?)',
                    (compte_num, libelle)
                )
                nb_importes += 1

        conn.commit()
        msg = f'{nb_importes} compte(s) importé(s).'
        if nb_doublons:
            msg += f' {nb_doublons} mis à jour (existants).'
        return jsonify({'success': True, 'message': msg,
                        'nb_importes': nb_importes, 'nb_doublons': nb_doublons})
    finally:
        conn.close()


# ── Mise a jour secteur/action ───────────────────────────────────────────────

@comptabilite_analytique_bp.route('/api/comptabilite/comptes/<int:compte_id>/affectation', methods=['PUT'])
@login_required
def api_update_affectation(compte_id):
    """Met a jour le secteur et/ou l'action d'un compte analytique."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    data = request.get_json() or {}
    secteur_id = data.get('secteur_id')
    action_id = data.get('action_id')

    # Convertir en int ou None
    secteur_id = int(secteur_id) if secteur_id else None
    action_id = int(action_id) if action_id else None

    conn = get_db()
    try:
        conn.execute('''
            UPDATE comptabilite_comptes
            SET secteur_id = ?, action_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (secteur_id, action_id, compte_id))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


# ── Gestion des actions analytiques ──────────────────────────────────────────

@comptabilite_analytique_bp.route('/api/comptabilite/actions', methods=['POST'])
@login_required
def api_ajouter_action():
    """Ajoute une action analytique."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    data = request.get_json() or {}
    nom = (data.get('nom') or '').strip()
    if not nom:
        return jsonify({'error': 'Nom requis.'}), 400

    conn = get_db()
    try:
        existing = conn.execute(
            'SELECT id FROM comptabilite_actions WHERE nom = ?', (nom,)
        ).fetchone()
        if existing:
            return jsonify({'id': existing['id'], 'nom': nom, 'exists': True})

        conn.execute('INSERT INTO comptabilite_actions (nom) VALUES (?)', (nom,))
        conn.commit()
        new_id = conn.execute('SELECT last_insert_rowid() as id').fetchone()['id']
        return jsonify({'id': new_id, 'nom': nom, 'success': True})
    finally:
        conn.close()


@comptabilite_analytique_bp.route('/api/comptabilite/actions/<int:action_id>', methods=['DELETE'])
@login_required
def api_supprimer_action(action_id):
    """Supprime une action analytique (si non utilisee)."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    conn = get_db()
    try:
        used = conn.execute(
            'SELECT COUNT(*) as nb FROM comptabilite_comptes WHERE action_id = ?', (action_id,)
        ).fetchone()
        if used['nb'] > 0:
            return jsonify({'error': 'Action utilisée par des comptes.'}), 409

        conn.execute('DELETE FROM comptabilite_actions WHERE id = ?', (action_id,))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()
