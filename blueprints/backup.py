"""
Blueprint backup_bp - Gestion des sauvegardes de la base de donnees.
Accessible uniquement aux directeurs et comptables.
"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, send_file
from utils import login_required
from backup_db import (
    creer_sauvegarde,
    creer_archive_documents,
    lister_sauvegardes,
    lister_archives_documents,
    restaurer_sauvegarde,
    supprimer_sauvegarde,
    rotation_sauvegardes,
    rotation_archives_documents,
    get_db_path,
    _safe_backup_path,
)
import os

backup_bp = Blueprint('backup_bp', __name__)


def _check_admin():
    """Verifie que l'utilisateur est directeur ou comptable."""
    return session.get('profil') in ('directeur', 'comptable')


@backup_bp.route('/sauvegardes')
@login_required
def liste_sauvegardes():
    """Page principale de gestion des sauvegardes."""
    if not _check_admin():
        flash('Acces non autorise', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    sauvegardes = lister_sauvegardes()
    archives_documents = lister_archives_documents()

    # Info sur la base actuelle
    db_path = get_db_path()
    db_size = None
    if os.path.exists(db_path):
        db_size_bytes = os.path.getsize(db_path)
        if db_size_bytes < 1024:
            db_size = f"{db_size_bytes} o"
        elif db_size_bytes < 1024 * 1024:
            db_size = f"{db_size_bytes / 1024:.1f} Ko"
        else:
            db_size = f"{db_size_bytes / (1024 * 1024):.1f} Mo"

    return render_template(
        'backup.html',
        sauvegardes=sauvegardes,
        archives_documents=archives_documents,
        db_size=db_size,
    )


@backup_bp.route('/sauvegardes/creer', methods=['POST'])
@login_required
def creer():
    """Creer une nouvelle sauvegarde."""
    if not _check_admin():
        flash('Acces non autorise', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    label = request.form.get('label', '').strip() or None
    path, err = creer_sauvegarde(label=label)
    archive_path, archive_err = creer_archive_documents(label=label)

    if err:
        flash(f'Erreur lors de la sauvegarde : {err}', 'error')
    else:
        filename = os.path.basename(path)
        flash(f'Sauvegarde de la base creee avec succes : {filename}', 'success')
        rotation_sauvegardes(20)

    if archive_err:
        category = 'info' if archive_path is None and archive_err.startswith('Aucun document') else 'error'
        flash(f'Archive des documents : {archive_err}', category)
    else:
        archive_name = os.path.basename(archive_path)
        flash(f'Archive des documents creee avec succes : {archive_name}', 'success')
        rotation_archives_documents(20)

    return redirect(url_for('backup_bp.liste_sauvegardes'))


@backup_bp.route('/sauvegardes/telecharger/<filename>')
@login_required
def telecharger(filename):
    """Telecharger un fichier de sauvegarde."""
    if not _check_admin():
        flash('Acces non autorise', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    filepath = _safe_backup_path(filename)
    if not filepath or not os.path.exists(filepath):
        flash('Fichier introuvable ou nom invalide', 'error')
        return redirect(url_for('backup_bp.liste_sauvegardes'))

    return send_file(filepath, as_attachment=True, download_name=filename)


@backup_bp.route('/sauvegardes/restaurer', methods=['POST'])
@login_required
def restaurer():
    """Restaurer la base a partir d'une sauvegarde."""
    if not _check_admin():
        flash('Acces non autorise', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    filename = request.form.get('filename')
    if not filename:
        flash('Aucun fichier specifie', 'error')
        return redirect(url_for('backup_bp.liste_sauvegardes'))

    ok, msg = restaurer_sauvegarde(filename)
    if ok:
        flash(f'Restauration reussie. {msg}', 'success')
    else:
        flash(f'Erreur lors de la restauration : {msg}', 'error')

    return redirect(url_for('backup_bp.liste_sauvegardes'))


@backup_bp.route('/sauvegardes/supprimer', methods=['POST'])
@login_required
def supprimer():
    """Supprimer une sauvegarde."""
    if not _check_admin():
        flash('Acces non autorise', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    filename = request.form.get('filename')
    if not filename:
        flash('Aucun fichier specifie', 'error')
        return redirect(url_for('backup_bp.liste_sauvegardes'))

    ok, msg = supprimer_sauvegarde(filename)
    if ok:
        flash(msg, 'success')
    else:
        flash(f'Erreur : {msg}', 'error')

    return redirect(url_for('backup_bp.liste_sauvegardes'))
