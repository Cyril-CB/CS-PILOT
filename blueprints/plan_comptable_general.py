"""
Blueprint plan_comptable_general_bp - Plan comptable general.

Fonctionnalites :
- Saisie manuelle de comptes (numero, libelle)
- Import de comptes au format TXT tabule (numero + libelle)
- Accessible aux profils directeur et comptable
"""
import csv
import io
from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, jsonify)
from database import get_db
from utils import login_required

plan_comptable_general_bp = Blueprint('plan_comptable_general_bp', __name__)


def _peut_acceder():
    return session.get('profil') in ('directeur', 'comptable')


# ── Page principale ──────────────────────────────────────────────────────────

@plan_comptable_general_bp.route('/plan-comptable-general')
@login_required
def plan_comptable_general():
    """Affiche le plan comptable general avec possibilite d'edition."""
    if not _peut_acceder():
        flash('Accès non autorisé.', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    conn = get_db()
    try:
        comptes = conn.execute('''
            SELECT * FROM plan_comptable_general
            ORDER BY compte_num
        ''').fetchall()

        return render_template('plan_comptable_general.html', comptes=comptes)
    finally:
        conn.close()


# ── Ajout d'un compte ────────────────────────────────────────────────────────

@plan_comptable_general_bp.route('/api/plan-general/comptes', methods=['POST'])
@login_required
def api_ajouter_compte():
    """Ajoute un compte au plan comptable general."""
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
            'SELECT id FROM plan_comptable_general WHERE compte_num = %s', (compte_num,)
        ).fetchone()
        if existing:
            return jsonify({'error': f'Le compte {compte_num} existe déjà.'}), 409

        conn.execute(
            'INSERT INTO plan_comptable_general (compte_num, libelle) VALUES (%s, %s)',
            (compte_num, libelle)
        )
        conn.commit()
        return jsonify({'success': True, 'message': f'Compte {compte_num} ajouté.'})
    finally:
        conn.close()


# ── Suppression d'un compte ──────────────────────────────────────────────────

@plan_comptable_general_bp.route('/api/plan-general/comptes/<int:compte_id>', methods=['DELETE'])
@login_required
def api_supprimer_compte(compte_id):
    """Supprime un compte du plan comptable general."""
    if not _peut_acceder():
        return jsonify({'error': 'Accès non autorisé'}), 403

    conn = get_db()
    try:
        conn.execute('DELETE FROM plan_comptable_general WHERE id = %s', (compte_id,))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


# ── Import TXT ───────────────────────────────────────────────────────────────

@plan_comptable_general_bp.route('/api/plan-general/import-txt', methods=['POST'])
@login_required
def api_import_txt():
    """Importe un plan comptable general au format TXT tabule."""
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
                'SELECT id FROM plan_comptable_general WHERE compte_num = %s', (compte_num,)
            ).fetchone()
            if existing:
                # Mettre a jour le libelle si different
                conn.execute(
                    'UPDATE plan_comptable_general SET libelle = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s',
                    (libelle, existing['id'])
                )
                nb_doublons += 1
            else:
                conn.execute(
                    'INSERT INTO plan_comptable_general (compte_num, libelle) VALUES (%s, %s)',
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
