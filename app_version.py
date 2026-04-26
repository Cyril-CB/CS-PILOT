"""Version applicative de CS-PILOT."""

import re
from pathlib import Path


DEFAULT_APP_VERSION = '1.1.0'
APP_VERSION_FILE = Path(__file__).resolve().parent / 'VERSION.txt'
APP_VERSION_PATTERN = re.compile(r'^\d+\.\d+\.\d+$')


def get_app_version():
    """Retourne la version applicative stockée dans le fichier racine."""
    try:
        version = APP_VERSION_FILE.read_text(encoding='utf-8').strip()
    except OSError:
        return DEFAULT_APP_VERSION

    if not version or not APP_VERSION_PATTERN.fullmatch(version):
        return DEFAULT_APP_VERSION

    return version
