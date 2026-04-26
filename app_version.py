"""Version applicative de CS-PILOT."""

from pathlib import Path


DEFAULT_APP_VERSION = '1.1.0'
APP_VERSION_FILE = Path(__file__).resolve().parent / 'VERSION.txt'


def get_app_version():
    """Retourne la version applicative stockée dans le fichier racine."""
    try:
        version = APP_VERSION_FILE.read_text(encoding='utf-8').strip()
    except OSError:
        return DEFAULT_APP_VERSION

    return version or DEFAULT_APP_VERSION


APP_VERSION = get_app_version()
