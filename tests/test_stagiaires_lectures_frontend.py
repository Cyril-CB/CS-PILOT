"""Contrat d'interaction de la lecture personnelle dans le fil."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(not shutil.which('node'), reason='Node requis pour exécuter le JavaScript livré')
def test_lecture_stagiaires_et_progression():
    script = Path(__file__).with_name('stagiaires_lectures_frontend_checks.cjs')
    resultat = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=10)
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr
