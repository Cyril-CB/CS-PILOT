"""
Script de sauvegarde de la base de donnees SQLite.
Peut etre utilise en ligne de commande ou importe par le blueprint backup.

Usage CLI:
    python backup_db.py                 # Sauvegarde simple
    python backup_db.py --list          # Lister les sauvegardes
    python backup_db.py --restore <fichier>  # Restaurer une sauvegarde
    python backup_db.py --max-backups 10     # Garder max 10 sauvegardes
"""
import os
import re
import sys
import sqlite3
import shutil
import argparse
import zipfile
from datetime import datetime

from database import DATABASE, DATA_DIR

BACKUP_DIR = 'backups'
DOCUMENTS_DIR = 'documents'

# Regex stricte pour les noms de fichiers autorises dans le dossier backups
_SAFE_FILENAME_RE = re.compile(r'^[a-zA-Z0-9._-]+$')


def _validate_filename(filename):
    """Verifie qu'un nom de fichier respecte la whitelist stricte."""
    return bool(filename) and _SAFE_FILENAME_RE.match(filename) is not None


def _safe_backup_path(filename):
    """Retourne le chemin canonique dans le dossier backups, ou None si invalide."""
    if not _validate_filename(filename):
        return None
    backup_dir = os.path.realpath(get_backup_dir())
    filepath = os.path.realpath(os.path.join(backup_dir, filename))
    if not filepath.startswith(backup_dir + os.sep):
        return None
    return filepath


def get_backup_dir():
    """Retourne le chemin du repertoire de sauvegardes, le cree si necessaire.
    Utilise le meme repertoire inscriptible que la base de donnees (compatible .exe)."""
    base_dir = os.path.dirname(DATABASE)
    backup_path = os.path.join(base_dir, BACKUP_DIR)
    os.makedirs(backup_path, exist_ok=True)
    return backup_path


def get_db_path():
    """Retourne le chemin absolu de la base de donnees (source unique: database.DATABASE)."""
    return DATABASE


def get_documents_dir():
    """Retourne le chemin absolu du dossier documents."""
    documents_path = os.path.join(DATA_DIR, DOCUMENTS_DIR)
    os.makedirs(documents_path, exist_ok=True)
    return documents_path


def _sanitize_label(label):
    """Nettoie un label pour l'integrer dans un nom de fichier."""
    if not label:
        return ''
    return re.sub(r'[^a-zA-Z0-9_-]', '', label)


def _build_backup_filename(prefix, extension, label=None):
    """Construit un nom de fichier de sauvegarde standardise."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    clean_label = _sanitize_label(label)
    suffix = f"_{clean_label}" if clean_label else ""
    return f"{prefix}_{timestamp}{suffix}.{extension}"


def creer_sauvegarde(label=None):
    """
    Cree une sauvegarde de la base de donnees avec l'API sqlite3 backup.
    Retourne le chemin du fichier de sauvegarde ou None en cas d'erreur.
    """
    db_path = get_db_path()
    if not os.path.exists(db_path):
        return None, "Base de donnees introuvable"

    backup_dir = get_backup_dir()
    filename = _build_backup_filename('backup', 'db', label=label)
    backup_path = os.path.join(backup_dir, filename)

    try:
        # Utiliser l'API backup de SQLite pour une copie coherente
        source = sqlite3.connect(db_path)
        dest = sqlite3.connect(backup_path)
        source.backup(dest)
        dest.close()
        source.close()

        size = os.path.getsize(backup_path)
        return backup_path, None
    except Exception as e:
        # Nettoyer le fichier partiel en cas d'erreur
        if os.path.exists(backup_path):
            os.remove(backup_path)
        return None, str(e)


def creer_archive_documents(label=None):
    """Cree une archive ZIP de tous les documents uploades en conservant l'arborescence."""
    documents_dir = get_documents_dir()
    backup_dir = get_backup_dir()
    archive_name = _build_backup_filename('documents', 'zip', label=label)
    archive_path = os.path.join(backup_dir, archive_name)

    try:
        with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for root, dirs, files in os.walk(documents_dir):
                rel_root = os.path.relpath(root, documents_dir)
                rel_root_zip = rel_root.replace(os.sep, '/')

                if rel_root_zip != '.' and not dirs and not files:
                    archive.writestr(f'{rel_root_zip}/', '')

                for filename in files:
                    filepath = os.path.join(root, filename)
                    arcname = os.path.relpath(filepath, documents_dir).replace(os.sep, '/')
                    archive.write(filepath, arcname)

        return archive_path, None
    except Exception as e:
        if os.path.exists(archive_path):
            os.remove(archive_path)
        return None, str(e)


def _lister_fichiers_sauvegarde(prefix, extension):
    """Liste les fichiers de sauvegarde correspondant au prefixe et a l'extension demandes."""
    backup_dir = get_backup_dir()
    sauvegardes = []

    for f in os.listdir(backup_dir):
        if f.startswith(f'{prefix}_') and f.endswith(f'.{extension}'):
            filepath = os.path.join(backup_dir, f)
            stat = os.stat(filepath)
            sauvegardes.append({
                'filename': f,
                'path': filepath,
                'size': stat.st_size,
                'size_human': _format_size(stat.st_size),
                'date': datetime.fromtimestamp(stat.st_mtime),
                'date_str': datetime.fromtimestamp(stat.st_mtime).strftime('%d/%m/%Y %H:%M:%S'),
            })

    sauvegardes.sort(key=lambda x: x['date'], reverse=True)
    return sauvegardes


def lister_sauvegardes():
    """Liste toutes les sauvegardes disponibles, triees par date (plus recente en premier)."""
    return _lister_fichiers_sauvegarde('backup', 'db')


def lister_archives_documents():
    """Liste toutes les archives ZIP de documents disponibles."""
    return _lister_fichiers_sauvegarde('documents', 'zip')


def restaurer_sauvegarde(filename):
    """
    Restaure la base de donnees a partir d'un fichier de sauvegarde.
    Cree automatiquement une sauvegarde de securite avant la restauration.
    """
    backup_path = _safe_backup_path(filename)
    if not backup_path:
        return False, "Nom de fichier invalide"

    if not os.path.exists(backup_path):
        return False, "Fichier de sauvegarde introuvable"

    # Verifier que le fichier est une base SQLite valide
    try:
        conn = sqlite3.connect(backup_path)
        conn.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1")
        conn.close()
    except sqlite3.DatabaseError:
        return False, "Le fichier n'est pas une base de donnees SQLite valide"

    db_path = get_db_path()

    # Creer une sauvegarde de securite avant restauration
    securite_path, err = creer_sauvegarde(label="avant_restauration")
    if err:
        return False, f"Impossible de creer la sauvegarde de securite: {err}"

    try:
        # Restaurer via l'API backup de SQLite
        source = sqlite3.connect(backup_path)
        dest = sqlite3.connect(db_path)
        source.backup(dest)
        dest.close()
        source.close()
        return True, f"Base restauree avec succes. Sauvegarde de securite: {os.path.basename(securite_path)}"
    except Exception as e:
        return False, str(e)


def supprimer_sauvegarde(filename):
    """Supprime un fichier de sauvegarde."""
    filepath = _safe_backup_path(filename)
    is_backup_db = filename.startswith('backup_') and filename.endswith('.db')
    is_documents_zip = filename.startswith('documents_') and filename.endswith('.zip')
    if not filepath or not (is_backup_db or is_documents_zip):
        return False, "Operation non autorisee"

    if not os.path.exists(filepath):
        return False, "Fichier introuvable"

    try:
        os.remove(filepath)
        return True, "Sauvegarde supprimee"
    except Exception as e:
        return False, str(e)


def rotation_sauvegardes(max_backups=20):
    """Supprime les sauvegardes les plus anciennes pour ne garder que max_backups."""
    sauvegardes = lister_sauvegardes()
    return _appliquer_rotation(sauvegardes, max_backups)


def rotation_archives_documents(max_backups=20):
    """Supprime les archives de documents les plus anciennes."""
    sauvegardes = lister_archives_documents()
    return _appliquer_rotation(sauvegardes, max_backups)


def _appliquer_rotation(sauvegardes, max_backups):
    """Supprime les fichiers les plus anciens pour ne garder que max_backups."""
    supprimees = 0

    if len(sauvegardes) > max_backups:
        for s in sauvegardes[max_backups:]:
            ok, _ = supprimer_sauvegarde(s['filename'])
            if ok:
                supprimees += 1

    return supprimees


def _format_size(size_bytes):
    """Formate une taille en octets en format lisible."""
    if size_bytes < 1024:
        return f"{size_bytes} o"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} Ko"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} Mo"


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Sauvegarde de la base de donnees')
    parser.add_argument('--list', action='store_true', help='Lister les sauvegardes')
    parser.add_argument('--restore', type=str, help='Restaurer une sauvegarde (nom du fichier)')
    parser.add_argument('--max-backups', type=int, default=20, help='Nombre max de sauvegardes a conserver')
    parser.add_argument('--label', type=str, help='Label pour la sauvegarde')

    args = parser.parse_args()

    if args.list:
        sauvegardes = lister_sauvegardes()
        if not sauvegardes:
            print("Aucune sauvegarde trouvee.")
        else:
            print(f"{'Fichier':<45} {'Taille':<12} {'Date'}")
            print("-" * 80)
            for s in sauvegardes:
                print(f"{s['filename']:<45} {s['size_human']:<12} {s['date_str']}")
            print(f"\nTotal: {len(sauvegardes)} sauvegarde(s)")

    elif args.restore:
        print(f"Restauration de: {args.restore}")
        ok, msg = restaurer_sauvegarde(args.restore)
        if ok:
            print(f"OK - {msg}")
        else:
            print(f"ERREUR - {msg}")
            sys.exit(1)

    else:
        print("Creation d'une sauvegarde...")
        path, err = creer_sauvegarde(label=args.label)
        if err:
            print(f"ERREUR - {err}")
            sys.exit(1)
        else:
            print(f"OK - Sauvegarde creee: {os.path.basename(path)}")

            # Rotation
            supprimees = rotation_sauvegardes(args.max_backups)
            if supprimees > 0:
                print(f"Rotation: {supprimees} ancienne(s) sauvegarde(s) supprimee(s)")
