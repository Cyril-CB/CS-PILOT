"""Exécution du script navigateur avec les primitives DOM utilisées par ce parcours."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(not shutil.which('node'), reason='Node requis pour exécuter le JavaScript livré')
def test_script_propositions_navigation_fichiers_et_retour():
    script = Path(__file__).with_name('propositions_frontend.cjs')
    resultat = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=10)
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr
