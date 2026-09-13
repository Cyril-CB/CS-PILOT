"""Choix du point d'entrée avec la configuration effective, sans serveur ouvert."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.parametrize('data_externe, debug_fichier, debug_env, mode', [
    (False, '1', None, 'debug'),
    (True, '1', None, 'debug'),
    (True, '1', '0', 'superviseur'),
    (True, '0', '1', 'debug'),
    (False, None, None, 'superviseur'),
])
def test_app_choisit_le_mode_apres_dotenv(tmp_path, data_externe,
                                        debug_fichier, debug_env, mode):
    root = Path(__file__).resolve().parents[1]
    projet = tmp_path / 'projet'
    projet.mkdir()
    # Copier ces deux points d'entrée garde aussi leur DATA_DIR par défaut isolé.
    for nom in ('app.py', 'database.py'):
        shutil.copy2(root / nom, projet / nom)
    data = tmp_path / 'donnees' if data_externe else projet
    data.mkdir(exist_ok=True)
    if debug_fichier is not None:
        (data / '.env').write_text(
            f'FLASK_DEBUG={debug_fichier}\nSECRET_KEY=cle-fictive-demarrage\n'
            f'CSPILOT_DATA_DIR={tmp_path / "autres-donnees"}\n', encoding='utf-8')
    ailleurs = tmp_path / 'ailleurs'
    ailleurs.mkdir()
    (ailleurs / '.env').write_text('FLASK_DEBUG=0\n', encoding='utf-8')
    env = os.environ.copy()
    for nom in ('CSPILOT_WORKER_TOKEN', 'CSPILOT_SUPERVISED_STDIN',
                'CSPILOT_DATA_DIR', 'CSPILOT_INSTALL_DIR', 'CSPILOT_UPDATE_DIR',
                'FLASK_DEBUG', 'PYTHON_DOTENV_DISABLED'):
        env.pop(nom, None)
    env['SECRET_KEY'] = 'cle-fictive-demarrage'
    if data_externe:
        env['CSPILOT_DATA_DIR'] = str(data)
    if debug_env is not None:
        env['FLASK_DEBUG'] = debug_env
    # Exécuter tout app.py ; intercepter uniquement l'ouverture des serveurs.
    probe = '''
import json, os, runpy, sys, types
sys.path[:0] = [sys.argv[1], sys.argv[2]]
from flask import Flask
def resultat(mode, **kwargs):
    database = sys.modules.get('database')
    print('RESULTAT_DEMARRAGE=' + json.dumps({
        'mode': mode, 'debug': kwargs.get('debug'),
        'data_env': os.environ.get('CSPILOT_DATA_DIR'),
        'data_db': database.DATA_DIR if database else None}))
superviseur = types.ModuleType('superviseur')
superviseur.main = lambda: resultat('superviseur')
sys.modules['superviseur'] = superviseur
Flask.run = lambda self, **kwargs: resultat('debug', **kwargs)
runpy.run_path(os.path.join(sys.argv[1], 'app.py'), run_name='__main__')
'''
    execution = subprocess.run([sys.executable, '-c', probe, str(projet), str(root)],
        cwd=ailleurs, env=env, capture_output=True, text=True, timeout=20)
    assert execution.returncode == 0, execution.stderr
    resultats = [json.loads(ligne.removeprefix('RESULTAT_DEMARRAGE='))
        for ligne in execution.stdout.splitlines() if ligne.startswith('RESULTAT_DEMARRAGE=')]
    assert resultats == [{'mode': mode, 'debug': True if mode == 'debug' else None,
        'data_env': str(data), 'data_db': str(data) if mode == 'debug' else None}]
    assert not (tmp_path / 'autres-donnees').exists()
