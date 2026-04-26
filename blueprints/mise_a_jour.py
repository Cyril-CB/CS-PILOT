"""
Blueprint mise_a_jour_bp - Mise a jour semi-automatique de l'application.
Permet de verifier et telecharger les nouvelles versions depuis GitHub.
Accessible uniquement aux directeurs et comptables.
"""
import os
import sys
import json
import shutil
import zipfile
import tempfile
import platform
import logging
from datetime import datetime

import requests
from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify
import app_version

from utils import login_required
from database import DATA_DIR

logger = logging.getLogger(__name__)

mise_a_jour_bp = Blueprint('mise_a_jour_bp', __name__)

GITHUB_OWNER = 'Cyril-CB'
GITHUB_REPO = 'CS-PILOT'
GITHUB_API_BASE = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}'
GITHUB_API_TIMEOUT = 15

# Fichiers et dossiers a ne jamais ecraser lors d'une mise a jour (chemins relatifs)
PROTECTED_PATHS = {
    '.env',
    '.git',
    'cspilot.db',
    'cspilot.db-wal',
    'cspilot.db-shm',
    'backups',
    'documents',
    'modeles_contrats',
    'contrats_generes',
}


def _check_admin():
    """Verifie que l'utilisateur est directeur ou comptable."""
    return session.get('profil') in ('directeur', 'comptable')


def _is_frozen():
    """Retourne True si l'application tourne en mode .exe (PyInstaller)."""
    return getattr(sys, 'frozen', False)


def _get_app_dir():
    """Retourne le repertoire racine de l'application (sources ou .exe)."""
    if _is_frozen():
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_current_version():
    """Retourne la version actuelle de l'application."""
    return app_version.APP_VERSION


def _fetch_latest_release():
    """Interroge l'API GitHub pour obtenir la derniere release.

    Returns:
        dict avec tag_name, name, body, published_at, assets, zipball_url
        ou None en cas d'erreur.
    """
    try:
        resp = requests.get(
            f'{GITHUB_API_BASE}/releases/latest',
            headers={'Accept': 'application/vnd.github+json'},
            timeout=GITHUB_API_TIMEOUT,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                'tag_name': data.get('tag_name', ''),
                'name': data.get('name', ''),
                'body': data.get('body', ''),
                'published_at': data.get('published_at', ''),
                'html_url': data.get('html_url', ''),
                'zipball_url': data.get('zipball_url', ''),
                'assets': [
                    {
                        'name': a['name'],
                        'size': a['size'],
                        'download_url': a['browser_download_url'],
                    }
                    for a in data.get('assets', [])
                ],
            }
        logger.warning("GitHub API returned status %s", resp.status_code)
        return None
    except requests.RequestException as e:
        logger.error("Error fetching latest release: %s", e)
        return None


def _find_exe_asset(assets):
    """Trouve l'asset .exe dans la liste des assets de la release."""
    for asset in assets:
        if asset['name'].lower().endswith('.exe'):
            return asset
    return None


def _download_file(url, dest_path):
    """Telecharge un fichier depuis une URL vers un chemin local.

    Returns:
        (True, None) en cas de succes, (False, message_erreur) sinon.
    """
    try:
        resp = requests.get(url, stream=True, timeout=120)
        resp.raise_for_status()
        with open(dest_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return True, None
    except requests.RequestException as e:
        return False, str(e)


def _is_protected(rel_path):
    """Verifie si un chemin relatif est protege (ne doit pas etre ecrase)."""
    parts = rel_path.replace('\\', '/').split('/')
    for part in parts:
        if part in PROTECTED_PATHS:
            return True
    return False


def _update_exe(release_info):
    """Met a jour l'executable .exe depuis la release GitHub.

    Returns:
        (True, message) ou (False, message_erreur)
    """
    exe_asset = _find_exe_asset(release_info.get('assets', []))
    if not exe_asset:
        return False, "Aucun fichier .exe trouve dans la release."

    current_exe = sys.executable
    app_dir = os.path.dirname(current_exe)

    # Telecharger dans un fichier temporaire
    with tempfile.NamedTemporaryFile(
        dir=app_dir, suffix='.exe.tmp', delete=False
    ) as tmp:
        tmp_path = tmp.name

    try:
        ok, err = _download_file(exe_asset['download_url'], tmp_path)
        if not ok:
            os.unlink(tmp_path)
            return False, f"Erreur de telechargement : {err}"

        # Renommer l'ancien exe et mettre le nouveau en place
        backup_path = current_exe + '.old'
        if os.path.exists(backup_path):
            os.unlink(backup_path)

        os.rename(current_exe, backup_path)
        os.rename(tmp_path, current_exe)

        return True, (
            f"Mise a jour .exe reussie (version {release_info['tag_name']}). "
            "Veuillez redemarrer l'application."
        )
    except Exception as e:
        # Tenter de restaurer l'ancien exe
        if os.path.exists(backup_path) and not os.path.exists(current_exe):
            try:
                os.rename(backup_path, current_exe)
            except Exception:
                pass
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
        return False, f"Erreur lors du remplacement : {e}"


def _update_sources(release_info):
    """Met a jour les fichiers sources depuis la branche main de GitHub.

    Telecharge le zipball de la branche main, extrait les fichiers et
    remplace ceux du projet en protegeant les donnees utilisateur.

    Returns:
        (True, message) ou (False, message_erreur)
    """
    app_dir = _get_app_dir()

    # Telecharger le zip de la branche main
    zip_url = f'{GITHUB_API_BASE}/zipball/main'

    with tempfile.TemporaryDirectory() as tmp_dir:
        zip_path = os.path.join(tmp_dir, 'main.zip')

        ok, err = _download_file(zip_url, zip_path)
        if not ok:
            return False, f"Erreur de telechargement : {err}"

        # Extraire le zip
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(tmp_dir)
        except zipfile.BadZipFile:
            return False, "Le fichier telecharge n'est pas un zip valide."

        # Le zip GitHub contient un dossier racine du type "Owner-Repo-SHA/"
        extracted_dirs = [
            d for d in os.listdir(tmp_dir)
            if os.path.isdir(os.path.join(tmp_dir, d))
        ]
        if not extracted_dirs:
            return False, "Aucun dossier trouve dans l'archive."

        source_dir = os.path.join(tmp_dir, extracted_dirs[0])

        # Copier les fichiers en protegeant les chemins proteges
        nb_updated = 0
        nb_skipped = 0
        errors = []

        for root, dirs, files in os.walk(source_dir):
            rel_root = os.path.relpath(root, source_dir)
            if rel_root == '.':
                rel_root = ''

            # Ignorer les dossiers proteges
            dirs[:] = [
                d for d in dirs
                if not _is_protected(os.path.join(rel_root, d) if rel_root else d)
            ]

            for fname in files:
                rel_path = os.path.join(rel_root, fname) if rel_root else fname

                if _is_protected(rel_path):
                    nb_skipped += 1
                    continue

                src = os.path.join(root, fname)
                dst = os.path.join(app_dir, rel_path)

                try:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
                    nb_updated += 1
                except Exception as e:
                    errors.append(f"{rel_path}: {e}")

        if errors:
            return False, (
                f"{nb_updated} fichier(s) mis a jour, "
                f"{len(errors)} erreur(s) : {'; '.join(errors[:5])}"
            )

        return True, (
            f"Mise a jour reussie (version {release_info['tag_name']}). "
            f"{nb_updated} fichier(s) mis a jour, {nb_skipped} protege(s). "
            "Veuillez redemarrer l'application."
        )


# ==================== Routes ====================

@mise_a_jour_bp.route('/mise-a-jour')
@login_required
def mise_a_jour():
    """Page de mise a jour de l'application."""
    if not _check_admin():
        flash('Acces non autorise', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    mode = 'exe' if _is_frozen() else 'script'
    current_version = _get_current_version()
    systeme = platform.system()

    return render_template(
        'mise_a_jour.html',
        mode=mode,
        current_version=current_version,
        systeme=systeme,
        github_url=f'https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}',
    )


@mise_a_jour_bp.route('/api/mise-a-jour/verifier', methods=['POST'])
@login_required
def verifier_mise_a_jour():
    """Verifie s'il existe une nouvelle version sur GitHub."""
    if not _check_admin():
        return jsonify({'error': 'Acces non autorise'}), 403

    release = _fetch_latest_release()
    if release is None:
        return jsonify({
            'error': 'Impossible de contacter GitHub. Verifiez votre connexion internet.'
        }), 502

    current_version = _get_current_version()
    mode = 'exe' if _is_frozen() else 'script'
    has_exe = _find_exe_asset(release.get('assets', [])) is not None

    return jsonify({
        'success': True,
        'current_version': current_version,
        'latest_version': release['tag_name'],
        'release_name': release['name'],
        'release_notes': release['body'],
        'published_at': release['published_at'],
        'html_url': release['html_url'],
        'mode': mode,
        'has_exe_asset': has_exe,
    })


@mise_a_jour_bp.route('/api/mise-a-jour/lancer', methods=['POST'])
@login_required
def lancer_mise_a_jour():
    """Lance la mise a jour de l'application."""
    if not _check_admin():
        return jsonify({'error': 'Acces non autorise'}), 403

    release = _fetch_latest_release()
    if release is None:
        return jsonify({
            'error': 'Impossible de contacter GitHub. Verifiez votre connexion internet.'
        }), 502

    user_name = f"{session.get('prenom', '')} {session.get('nom', '')}"
    logger.info(
        "Mise a jour lancee par %s (version cible: %s)",
        user_name, release['tag_name']
    )

    if _is_frozen():
        success, message = _update_exe(release)
    else:
        success, message = _update_sources(release)

    if success:
        logger.info("Mise a jour reussie: %s", message)

        # Redémarrage différé uniquement en mode script (VPS systemd)
        if not _is_frozen():
            import subprocess
            subprocess.Popen(
                ['bash', '-c', 'sleep 5 && sudo systemctl restart cspilot'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True
            )
            message = message.replace(
                "Veuillez redemarrer l'application.",
                "Redemarrage automatique dans 5 secondes..."
            )

        return jsonify({'success': True, 'message': message})
    else:
        logger.error("Mise a jour echouee: %s", message)
        return jsonify({'success': False, 'error': message}), 500
