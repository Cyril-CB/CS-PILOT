"""Paramètres secrets et traces de digest historiques sur données fictives."""
import json
import sqlite3

from flask import Flask
import pytest

import resilience
from utils import encrypt_value


CLE = 'cle-fictive-parametres'
NOUVELLE_CLE = 'nouvelle-cle-fictive-parametres'
MARQUEUR = 'digest_direction_2026-09-11'


@pytest.fixture
def parametres():
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT)')
    app = Flask('parametres_fictifs')
    app.secret_key = CLE
    with app.app_context():
        conn.executemany('INSERT INTO app_settings VALUES (?, ?)', [
            ('smtp_password', encrypt_value('mot-de-passe-fictif')),
            ('email_enabled', encrypt_value('true')),
            (MARQUEUR, 'envoye'),
        ])
    yield conn
    conn.close()


def test_verification_accepte_secrets_et_marqueur_sans_modifier(parametres):
    avant = parametres.execute('SELECT * FROM app_settings ORDER BY key').fetchall()

    assert resilience.verifier_parametres(parametres, CLE) == 2

    assert parametres.execute('SELECT * FROM app_settings ORDER BY key').fetchall() == avant


def test_rechiffrement_preserve_marqueur_et_rechiffre_secrets(parametres):
    resilience.rechiffrer_parametres(parametres, CLE, NOUVELLE_CLE)

    valeurs = dict(parametres.execute('SELECT key, value FROM app_settings'))
    assert valeurs[MARQUEUR] == 'envoye'
    fernet = resilience.fernet_pour(NOUVELLE_CLE)
    assert fernet.decrypt(valeurs['smtp_password'].encode()) == b'mot-de-passe-fictif'
    assert fernet.decrypt(valeurs['email_enabled'].encode()) == b'true'
    assert resilience.verifier_parametres(parametres, NOUVELLE_CLE) == 2


@pytest.mark.parametrize('operation', ['verifier', 'rechiffrer'])
def test_marqueur_ne_masque_pas_mauvaise_cle(parametres, operation):
    avant = parametres.execute('SELECT * FROM app_settings ORDER BY key').fetchall()
    with pytest.raises(resilience.ErreurResilience, match='indéchiffrables'):
        if operation == 'verifier':
            resilience.verifier_parametres(parametres, 'mauvaise-cle-fictive')
        else:
            resilience.rechiffrer_parametres(parametres, 'mauvaise-cle-fictive', NOUVELLE_CLE)
    assert parametres.execute('SELECT * FROM app_settings ORDER BY key').fetchall() == avant


@pytest.mark.parametrize('key,value', [
    ('smtp_password', 'envoye'),
    ('digest_direction_api_key', 'envoye'),
    ('digest_direction_2026-02-30', 'envoye'),
    ('digest_direction_20260911', 'envoye'),
    ('digest_direction_2026-09-11', 'valeur-invalide'),
])
def test_valeur_non_chiffree_hors_marqueur_exact_reste_refusee(parametres, key, value):
    parametres.execute('INSERT OR REPLACE INTO app_settings VALUES (?, ?)', (key, value))
    avant = parametres.execute('SELECT * FROM app_settings ORDER BY key').fetchall()
    with pytest.raises(resilience.ErreurResilience, match='indéchiffrables'):
        resilience.verifier_parametres(parametres, CLE)
    with pytest.raises(resilience.ErreurResilience, match='indéchiffrables'):
        resilience.rechiffrer_parametres(parametres, CLE, NOUVELLE_CLE)
    assert parametres.execute('SELECT * FROM app_settings ORDER BY key').fetchall() == avant


def test_cli_migre_0071_et_autorise_demarrage_apres_digest(tmp_path, monkeypatch, capsys):
    import database
    import migration_manager
    from resilience_cli import main

    chemin = tmp_path / 'cspilot.db'
    monkeypatch.setattr(database, 'DATABASE', str(chemin))
    monkeypatch.setattr(database, 'DATA_DIR', str(tmp_path))
    monkeypatch.setenv('SECRET_KEY', CLE)
    for migration in migration_manager.lister_fichiers_migrations():
        if migration['version'] == '0071':
            break
        assert migration_manager.appliquer_migration(migration['version'])[0]
    chiffre = resilience.fernet_pour(CLE).encrypt(b'secret-fictif').decode()
    with sqlite3.connect(chemin) as conn:
        conn.executemany('INSERT INTO app_settings(key, value) VALUES (?, ?)', [
            ('smtp_password', chiffre), (MARQUEUR, 'envoye'),
        ])
    with pytest.raises(RuntimeError, match='Migrations en attente'):
        database.preparer_demarrage()

    retour = main(['migrer', '--data-dir', str(tmp_path), '--version', '0071',
                   '--application-arretee'])

    resultat = json.loads(capsys.readouterr().out)
    assert retour == 0 and resultat['ok'] and resultat['statut']['a_jour']
    database.preparer_demarrage()
    with sqlite3.connect(chemin) as conn:
        assert dict(conn.execute('SELECT key, value FROM app_settings')) == {
            'smtp_password': chiffre, MARQUEUR: 'envoye',
        }
        assert resilience.verifier_parametres(conn, CLE) == 1
