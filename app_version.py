"""Version applicative de CS-PILOT."""

from pathlib import Path


MAJOR_VERSION = '1'
MINOR_VERSION = '1'
COMMIT_COUNT_FILE = Path(__file__).resolve().parent / 'COMMIT_COUNT.txt'


def get_commit_count():
    """Retourne le nombre de commits stocké dans le fichier racine."""
    try:
        commit_count = COMMIT_COUNT_FILE.read_text(encoding='utf-8').strip()
    except OSError:
        return '0'

    return commit_count if commit_count.isdigit() else '0'


def get_app_version():
    """Construit la version applicative au format majeur.mineur.commits."""
    return f'{MAJOR_VERSION}.{MINOR_VERSION}.{get_commit_count()}'


APP_VERSION = get_app_version()
