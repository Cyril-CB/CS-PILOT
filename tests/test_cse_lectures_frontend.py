"""Exécution du script CSE avec les primitives DOM utilisées par le parcours."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_banniere_masquee_prioritaire_sur_display_flex():
    """Le display flex auteur ne doit pas annuler l'attribut HTML hidden."""
    css = (Path(__file__).parents[1] / 'static/css/style.css').read_text()
    assert '.cse-banner[hidden] {\n    display: none;\n}' in css


@pytest.mark.skipif(not shutil.which('node'), reason='Node requis pour exécuter le JavaScript livré')
def test_script_lecture_cse_masque_banniere_et_preserve_focus():
    script = Path(__file__).with_name('cse_lectures_frontend_checks.cjs')
    resultat = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=10)
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr
