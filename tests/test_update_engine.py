"""Mise à jour, retour arrière des données et reprise après interruption."""
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import sys
import threading
from unittest.mock import Mock
import zipfile

import pytest

from superviseur import Service
from update_engine import (UpdateEngine, UpdateError, extraire_sources, python_venv,
                           REPERTOIRES)
from update_protocol import demander_mise_a_jour, ecrire_json, etat_public, lire_json
from database import ALL_MIGRATION_VERSIONS

ROOT = Path(__file__).resolve().parents[1]
SHA = 'a' * 40
JOB = {'id': 'b' * 32, 'sha': SHA}
VERSION_TEST = f'{max(int(v) for v, _ in ALL_MIGRATION_VERSIONS) + 1:04d}'
VERSION_ECHEC = f'{int(VERSION_TEST) + 1:04d}'


def archive_sources(tmp_path, extra=None):
    archive = tmp_path / 'sources.zip'
    fichiers = {f'repo/{p}': 'pass' for p in ('app.py', 'resilience_cli.py', 'superviseur.py', 'requirements.txt')}
    fichiers['repo/update-protocol.json'] = json.dumps({'protocol': 1, 'data_paths': list(REPERTOIRES)})
    fichiers.update(extra or {})
    with zipfile.ZipFile(archive, 'w') as zf:
        for name, content in fichiers.items():
            zf.writestr(name, content)
    return archive


@pytest.mark.parametrize('chemin', ['repo/../../sortie.py', '/absolu.py', 'repo/a\\b',
    'repo/C:secret', 'autre/fichier.py'])
def test_archive_hostile(tmp_path, chemin):
    archive = archive_sources(tmp_path, {chemin: 'hostile'})
    with pytest.raises(UpdateError):
        extraire_sources(archive, tmp_path / 'app')
    assert not (tmp_path / 'sortie.py').exists()


def test_archive_liens_et_doublons(tmp_path):
    archive = archive_sources(tmp_path)
    with zipfile.ZipFile(archive, 'a') as zf:
        info = zipfile.ZipInfo('repo/lien')
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, '../../secret')
    with pytest.raises(UpdateError):
        extraire_sources(archive, tmp_path / 'app')


def test_archive_bornee_et_protegee(tmp_path, monkeypatch):
    archive = archive_sources(tmp_path, {'repo/.env': 'NE PAS INSTALLER',
        'repo/factures/secret.pdf': 'secret', 'repo/venv/bin/python': 'hostile'})
    extraire_sources(archive, tmp_path / 'app')
    assert not (tmp_path / 'app/.env').exists()
    assert not (tmp_path / 'app/factures').exists()
    assert not (tmp_path / 'app/venv').exists()
    monkeypatch.setattr('update_engine.MAX_EXTRACTED', 1)
    with pytest.raises(UpdateError):
        extraire_sources(archive, tmp_path / 'autre')


def test_contrat_incompatible(tmp_path):
    archive = archive_sources(tmp_path, {'repo/update-protocol.json': '{"protocol": 999}'})
    with pytest.raises(UpdateError, match='adaptation'):
        extraire_sources(archive, tmp_path / 'app')


def test_une_seule_demande_et_pas_de_chemin_arbitraire(tmp_path):
    reference = demander_mise_a_jour(tmp_path, SHA)
    with pytest.raises(FileExistsError):
        demander_mise_a_jour(tmp_path, 'c'*40)
    assert lire_json(tmp_path / 'demande.json') == {'id': reference, 'sha': SHA}
    with pytest.raises(ValueError):
        demander_mise_a_jour(tmp_path, '../main')
    assert len(list(tmp_path.iterdir())) == 1


def test_statut_public_sans_details_prives():
    state = {'active': {'sha': SHA}, 'job': {'id': JOB['id'], 'phase': 'migration',
        'raison': '/chemin/prive', 'secret': 'cle'}}
    public = etat_public(state, False)
    assert public['en_cours'] and not public['disponible']
    assert 'prive' not in json.dumps(public) and 'secret' not in json.dumps(public)


def test_preparation_isole_python_et_dependances(tmp_path, monkeypatch):
    service = Mock()
    engine = UpdateEngine(ROOT, tmp_path, service)
    engine.state['job'] = dict(JOB, previous=None, phase='preparation')
    archive = archive_sources(tmp_path)
    def telecharger(sha, dest):
        assert sha == SHA
        shutil.copy2(archive, dest)
        return 'empreinte'
    monkeypatch.setattr('update_engine.telecharger_sources', telecharger)
    executer = Mock()
    monkeypatch.setattr(engine, 'executer', executer)
    engine.preparer(JOB)
    appels = [c.args[0] for c in executer.call_args_list]
    nouveau = engine.release_dir(JOB['id'])
    assert appels[0] == [sys.executable, '-m', 'venv', nouveau / 'venv']
    assert appels[1][0] == python_venv(nouveau / 'venv')
    assert appels[1][-1] == nouveau / 'app/requirements.txt'
    assert appels[2][1:] == ['-m', 'pip', 'check']
    service.fermer.assert_not_called()


@pytest.fixture
def installation(app, db, sample_users, tmp_path):
    source = tmp_path / 'donnees'
    source.mkdir()
    with app.app_context():
        from utils import save_setting
        save_setting('smtp_password', 'mot-de-passe-fictif')
    db.execute("INSERT INTO app_settings(key,value) VALUES ('digest_direction_2026-09-13', 'envoye')")
    db.commit()
    with closing(sqlite3.connect(source / 'cspilot.db')) as copie:
        db.backup(copie)
    for nom in REPERTOIRES:
        (source / nom).mkdir()
        (source / nom / 'fictif.txt').write_text('avant')
    (source / '.env').write_text("SECRET_KEY='test-secret-key-for-pytest'\nAPP_TIMEZONE='UTC'\n")
    return source


@pytest.fixture
def moteur(installation, monkeypatch):
    service = Service(installation, ROOT)
    engine = UpdateEngine(ROOT, installation, service)
    service.engine = engine
    runtime = engine.runtime
    # Pas de réseau/PyPI dans les tests : les CLI et processus Flask sont réels,
    # avec les dépendances du harnais. Le choix d'un venv séparé est testé ci-dessus.
    monkeypatch.setattr(engine, 'runtime', lambda active: (runtime(active)[0], sys.executable))
    def preparer(job):
        dossier = engine.release_dir(job['id'])
        dossier.mkdir()
        code = dossier / 'app'
        code.mkdir()
        for path in ROOT.glob('*.py'):
            shutil.copy2(path, code / path.name)
        for nom in ('blueprints', 'templates', 'static', 'migrations'):
            shutil.copytree(ROOT / nom, code / nom, ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy2(ROOT / 'requirements.txt', code / 'requirements.txt')
        shutil.copy2(ROOT / 'VERSION.txt', code / 'VERSION.txt')
        (code / f'migrations/{VERSION_TEST}_test_update.py').write_text('''
NOM = 'Test de mise à jour'
DESCRIPTION = 'Données fictives'
def upgrade(conn):
    conn.execute("UPDATE users SET prenom='Après mise à jour'")
    from pathlib import Path
    import os
    Path(os.environ['CSPILOT_DATA_DIR'], 'documents/fictif.txt').write_text('après')
def downgrade(conn): pass
''')
    monkeypatch.setattr(engine, 'preparer', preparer)
    service.demarrer(ROOT, sys.executable)
    service.ouvrir()
    yield engine, service
    service.arreter()


@pytest.mark.parametrize('defaut', [None, 'migration', 'demarrage'])
def test_mise_a_jour_reelle_et_retour_arriere(moteur, installation, defaut, monkeypatch):
    engine, service = moteur
    preparer = engine.preparer
    def avec_defaut(job):
        preparer(job)
        code = engine.runtime(job)[0]
        if defaut == 'migration':
            # La première migration fictive a écrit en base et sur disque avant cet échec.
            (code / f'migrations/{VERSION_ECHEC}_echec.py').write_text('''
NOM='Échec fictif'
DESCRIPTION='Test'
def upgrade(conn): raise RuntimeError('échec fictif')
def downgrade(conn): pass
''')
        elif defaut == 'demarrage':
            (code / 'app.py').write_text("raise RuntimeError('Démarrage impossible pour le test')")
    monkeypatch.setattr(engine, 'preparer', avec_defaut)
    engine.traiter(dict(JOB))
    assert service.disponible and service.process.poll() is None
    state = lire_json(engine.state_path)
    assert state['job']['phase'] == ('terminee' if defaut is None else 'retablie')
    assert state['active'] == (JOB if defaut is None else None)
    with closing(sqlite3.connect(installation / 'cspilot.db')) as conn:
        migration = conn.execute("SELECT COUNT(*) FROM schema_migrations WHERE version=?", (VERSION_TEST,)).fetchone()[0]
        valeur = conn.execute("SELECT value FROM app_settings WHERE key='smtp_password'").fetchone()[0]
    from cryptography.fernet import Fernet
    import hashlib, base64
    fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(b'test-secret-key-for-pytest').digest()))
    assert fernet.decrypt(valeur.encode()) == b'mot-de-passe-fictif'
    assert migration == (1 if defaut is None else 0)
    assert (installation / 'documents/fictif.txt').read_text() == ('après' if defaut is None else 'avant')
    for nom in REPERTOIRES:
        if nom != 'documents':
            assert (installation / nom / 'fictif.txt').read_text() == 'avant'
    dossier = engine.release_dir(JOB['id'])
    assert (dossier / 'avant.cspbackup').is_file()
    assert stat.S_IMODE((dossier / 'phrase-secrete').stat().st_mode) == 0o600
    if defaut:
        assert (dossier / 'donnees-echec/documents/fictif.txt').read_text() == 'après'


def test_echec_preparation_ne_coupe_pas_application(moteur, monkeypatch):
    engine, service = moteur
    pid = service.process.pid
    def echouer(job):
        raise UpdateError('Espace disque insuffisant.')
    monkeypatch.setattr(engine, 'preparer', echouer)
    engine.traiter(dict(JOB))
    assert service.disponible and service.process.pid == pid
    assert engine.state['job']['phase'] == 'annulee'
    assert engine.state['job']['raison'] == 'Espace disque insuffisant.'


def test_sauvegarde_refusee_aucune_migration(moteur, monkeypatch):
    engine, service = moteur
    def echouer(job):
        raise UpdateError('Sauvegarde refusée.')
    monkeypatch.setattr(engine, 'sauvegarder', echouer)
    migration = Mock()
    monkeypatch.setattr(engine, 'migrer', migration)
    engine.traiter(dict(JOB))
    assert engine.state['job']['phase'] == 'annulee' and service.disponible
    migration.assert_not_called()


def test_reprise_apres_coupure_pendant_restauration(moteur, installation, monkeypatch):
    engine, service = moteur
    job = dict(JOB, previous=None, phase='preparation')
    engine.state['job'] = job
    engine.preparer(job)
    service.fermer()
    service.arreter()
    engine.sauvegarder(job)
    engine.phase('migration')
    engine.migrer(job)
    engine.phase('restauration')
    rename = Path.rename
    def coupure(path, dest):
        resultat = rename(path, dest)
        if path == installation / 'documents':
            raise KeyboardInterrupt('Coupure fictive après déplacement du premier stockage')
        return resultat
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'rename', coupure)
        with pytest.raises(KeyboardInterrupt):
            engine.restaurer(job)
    assert not (installation / 'documents').exists()
    reprise = UpdateEngine(ROOT, installation, service)
    service.engine = reprise
    assert reprise.recuperer() is False
    assert reprise.state['job']['phase'] == 'retablie' and service.disponible
    assert (installation / 'documents/fictif.txt').read_text() == 'avant'
    with closing(sqlite3.connect(installation / 'cspilot.db')) as conn:
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations WHERE version=?", (VERSION_TEST,)).fetchone()[0] == 0


def test_pas_de_retour_arriere_apres_publication(tmp_path):
    service = Mock()
    engine = UpdateEngine(ROOT, tmp_path, service)
    engine.state = {'active': JOB, 'job': dict(JOB, phase='terminee', previous=None)}
    engine.sauver()
    assert engine.recuperer() is True
    service.demarrer.assert_not_called()


def test_restauration_impossible_reste_en_maintenance(moteur, monkeypatch):
    engine, service = moteur
    def echouer(job):
        raise UpdateError('échec fictif')
    monkeypatch.setattr(engine, 'migrer', echouer)
    monkeypatch.setattr(engine, 'restaurer', echouer)
    engine.traiter(dict(JOB))
    assert not service.disponible and service.process is None
    assert engine.state['job']['phase'] == 'intervention'


def test_demande_acceptee_survit_au_redemarrage(tmp_path):
    service = Mock()
    engine = UpdateEngine(ROOT, tmp_path, service)
    reference = demander_mise_a_jour(engine.base, SHA)
    assert engine.recuperer() is True
    assert lire_json(engine.base / 'demande.json')['id'] == reference


def test_retention_preserve_deux_versions_et_dossiers_inconnus(tmp_path):
    engine = UpdateEngine(ROOT, tmp_path, Mock())
    versions = [{'id': str(i) * 32, 'sha': SHA} for i in range(1, 5)]
    for i, version in enumerate(versions):
        dossier = engine.release_dir(version['id'])
        dossier.mkdir()
        ecrire_json(dossier / 'resultat.json', {'id': version['id'], 'termine_le': i})
    echec = engine.release_dir('e' * 32)
    echec.mkdir()
    engine.state = {'active': versions[-1], 'job': {'previous': versions[-2]}}
    engine.nettoyer_versions()
    assert not engine.release_dir(versions[0]['id']).exists()
    assert not engine.release_dir(versions[1]['id']).exists()
    assert engine.release_dir(versions[2]['id']).exists()
    assert engine.release_dir(versions[3]['id']).exists()
    assert echec.exists()


def test_processus_applicatif_meurt_avec_le_pipe_superviseur(moteur):
    engine, service = moteur
    process = service.process
    process.stdin.close()
    assert process.wait(timeout=5) != 0
    service.attendre_arret_precedent(timeout=2)


@pytest.mark.skipif(os.name != 'posix', reason='Contrôle de groupe de processus POSIX')
def test_commande_et_descendants_arretes_sur_perte_du_superviseur(tmp_path):
    import subprocess
    import time
    from update_protocol import verrou_exclusif
    programme = "from pathlib import Path; import sys, time; Path(sys.argv[1]).write_text('pret'); time.sleep(120)"
    marker = tmp_path / 'pret'
    env = dict(os.environ, CSPILOT_UPDATE_DIR=str(tmp_path))
    process = subprocess.Popen([sys.executable, ROOT / 'update_task.py', '--donnees',
        sys.executable, '-c', programme, marker], stdin=subprocess.PIPE, env=env, start_new_session=True)
    try:
        fin = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < fin:
            time.sleep(0.02)
        assert marker.exists()
        with pytest.raises(OSError):
            verrou_exclusif(tmp_path / 'worker.lock')
        process.stdin.close()  # Même EOF que si le superviseur était tué par SIGKILL.
        process.wait(timeout=5)
        with verrou_exclusif(tmp_path / 'worker.lock'):
            assert process.returncode != 0
    finally:
        if process.poll() is None:
            os.killpg(process.pid, 9)
            process.wait()


def test_echec_publication_ne_marque_pas_reussite(tmp_path, monkeypatch):
    service = Mock()
    engine = UpdateEngine(ROOT, tmp_path, service)
    engine.state = {'active': None, 'job': dict(JOB, phase='validation', previous=None)}
    def disque_indisponible(*args):
        raise OSError('Erreur disque fictive')
    monkeypatch.setattr('update_engine.ecrire_json', disque_indisponible)
    with pytest.raises(OSError):
        engine.terminer(JOB, 'terminee')
    assert engine.state['active'] is None and engine.state['job']['phase'] == 'validation'
    service.ouvrir.assert_not_called()


@pytest.mark.skipif(os.name != 'posix', reason='Environnement Python de recette Linux')
def test_redemarrage_du_service_reprend_la_version_active(moteur, installation):
    """Le lanceur d'origine doit reprendre le contrôleur/code isolés après redémarrage."""
    import http.client
    import socket
    import subprocess
    import time
    engine, service = moteur
    engine.traiter(dict(JOB))
    assert engine.state['job']['phase'] == 'terminee'
    service.arreter()
    # Les dépendances du harnais représentent le venv déjà installé. Aucune
    # connexion PyPI ; le choix du nouveau venv est couvert par le test dédié.
    (engine.release_dir(JOB['id']) / 'venv').symlink_to(sys.prefix, target_is_directory=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, CSPILOT_DATA_DIR=str(installation), PORT=str(port))
    for name in ('CSPILOT_WORKER_TOKEN', 'CSPILOT_SUPERVISED_STDIN', 'CSPILOT_UPDATE_DIR', 'CSPILOT_INSTALL_DIR'):
        env.pop(name, None)
    process = subprocess.Popen([sys.executable, ROOT / 'superviseur.py'], cwd=ROOT,
                               env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        fin = time.monotonic() + 15
        state = {}
        while time.monotonic() < fin:
            assert process.poll() is None
            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
            try:
                conn.request('GET', '/__cspilot__/mise-a-jour')
                response = conn.getresponse()
                state = json.loads(response.read())
                if state['disponible']:
                    break
            except OSError:
                pass
            finally:
                conn.close()
            time.sleep(0.05)
        assert state['disponible'] and state['phase'] == 'terminee'
        # Le code d'origine refuse la migration fictive supplémentaire : cette santé
        # prouve que le code isolé qui la connaît a bien été repris.
        assert lire_json(engine.state_path)['active'] == JOB
    finally:
        process.terminate()
        process.wait(timeout=10)
