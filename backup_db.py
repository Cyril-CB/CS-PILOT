"""
Script de sauvegarde de la base de donnees PostgreSQL.
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
import glob
import subprocess
import shutil
import argparse
from datetime import datetime
from urllib.parse import urlparse

BACKUP_DIR = 'backups'

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
    """Retourne le chemin du repertoire de sauvegardes, le cree si necessaire."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    backup_path = os.path.join(base_dir, BACKUP_DIR)
    os.makedirs(backup_path, exist_ok=True)
    return backup_path


def get_db_path():
    """Pour PostgreSQL, retourne None (pas de fichier DB local)."""
    return None


def _find_pg_tool(tool_name):
    """
    Trouve l'executable PostgreSQL (pg_dump, psql...) sur le systeme.
    Cherche d'abord dans le PATH, puis dans les repertoires d'installation courants
    de PostgreSQL sous Windows.
    Retourne le chemin complet ou None si introuvable.
    """
    # Recherche standard via PATH
    found = shutil.which(tool_name)
    if found:
        return found

    # Chemins courants sous Windows
    if sys.platform == 'win32':
        pg_dirs = glob.glob(r'C:\Program Files\PostgreSQL\*\bin')
        pg_dirs += glob.glob(r'C:\Program Files (x86)\PostgreSQL\*\bin')

        def _pg_version_key(path):
            """Extrait le numero de version numerique depuis le chemin."""
            try:
                return float(os.path.basename(os.path.dirname(path)))
            except ValueError:
                return 0.0

        for pg_bin in sorted(pg_dirs, key=_pg_version_key, reverse=True):
            candidate = os.path.join(pg_bin, tool_name + '.exe')
            if os.path.isfile(candidate):
                return candidate

    return None


def _get_pg_env():
    """Retourne les variables d'environnement pour psql/pg_dump."""
    database_url = os.environ.get('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/cspilot')
    parsed = urlparse(database_url)
    env = os.environ.copy()
    if parsed.password:
        env['PGPASSWORD'] = parsed.password
    return env, parsed


def creer_sauvegarde(label=None):
    """
    Cree une sauvegarde de la base de donnees PostgreSQL avec pg_dump.
    Retourne le chemin du fichier de sauvegarde ou None en cas d'erreur.
    """
    pg_dump = _find_pg_tool('pg_dump')
    if not pg_dump:
        return None, (
            "pg_dump introuvable. Assurez-vous que les outils PostgreSQL sont installes "
            "et accessibles (PATH ou C:\\Program Files\\PostgreSQL\\<version>\\bin)."
        )

    env, parsed = _get_pg_env()
    backup_dir = get_backup_dir()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    if label:
        label = re.sub(r'[^a-zA-Z0-9_-]', '', label)
    suffix = f"_{label}" if label else ""
    filename = f"backup_{timestamp}{suffix}.sql"
    backup_path = os.path.join(backup_dir, filename)

    cmd = [pg_dump]
    if parsed.hostname:
        cmd += ['-h', parsed.hostname]
    if parsed.port:
        cmd += ['-p', str(parsed.port)]
    if parsed.username:
        cmd += ['-U', parsed.username]
    if parsed.path and parsed.path != '/':
        cmd += [parsed.path.lstrip('/')]

    try:
        with open(backup_path, 'w') as f:
            result = subprocess.run(cmd, env=env, stdout=f, stderr=subprocess.PIPE, timeout=120)
        if result.returncode != 0:
            if os.path.exists(backup_path):
                os.remove(backup_path)
            return None, result.stderr.decode('utf-8', errors='replace')
        return backup_path, None
    except Exception as e:
        if os.path.exists(backup_path):
            os.remove(backup_path)
        return None, str(e)


def lister_sauvegardes():
    """Liste toutes les sauvegardes disponibles, triees par date (plus recente en premier)."""
    backup_dir = get_backup_dir()
    sauvegardes = []

    for f in os.listdir(backup_dir):
        if f.startswith('backup_') and (f.endswith('.sql') or f.endswith('.db')):
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


def restaurer_sauvegarde(filename):
    """
    Restaure la base de donnees a partir d'un fichier de sauvegarde SQL.
    Cree automatiquement une sauvegarde de securite avant la restauration.
    """
    backup_path = _safe_backup_path(filename)
    if not backup_path:
        return False, "Nom de fichier invalide"

    if not os.path.exists(backup_path):
        return False, "Fichier de sauvegarde introuvable"

    if not filename.endswith('.sql'):
        return False, "Seules les sauvegardes SQL PostgreSQL peuvent etre restaurees"

    # Creer une sauvegarde de securite avant restauration
    securite_path, err = creer_sauvegarde(label="avant_restauration")
    if err:
        return False, f"Impossible de creer la sauvegarde de securite: {err}"

    env, parsed = _get_pg_env()

    psql = _find_pg_tool('psql')
    if not psql:
        return False, (
            "psql introuvable. Assurez-vous que les outils PostgreSQL sont installes "
            "et accessibles (PATH ou C:\\Program Files\\PostgreSQL\\<version>\\bin)."
        )

    cmd = [psql]
    if parsed.hostname:
        cmd += ['-h', parsed.hostname]
    if parsed.port:
        cmd += ['-p', str(parsed.port)]
    if parsed.username:
        cmd += ['-U', parsed.username]
    if parsed.path and parsed.path != '/':
        cmd += [parsed.path.lstrip('/')]

    try:
        with open(backup_path, 'r') as f:
            result = subprocess.run(cmd, env=env, stdin=f, stderr=subprocess.PIPE, timeout=300)
        if result.returncode != 0:
            return False, result.stderr.decode('utf-8', errors='replace')
        return True, f"Base restauree avec succes. Sauvegarde de securite: {os.path.basename(securite_path)}"
    except Exception as e:
        return False, str(e)


def supprimer_sauvegarde(filename):
    """Supprime un fichier de sauvegarde."""
    filepath = _safe_backup_path(filename)
    if not filepath or not (filename.endswith('.sql') or filename.endswith('.db')):
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
    parser = argparse.ArgumentParser(description='Sauvegarde de la base de donnees PostgreSQL')
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
