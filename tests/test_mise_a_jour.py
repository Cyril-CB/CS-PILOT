"""Autorisation, cible vérifiée et prise en charge durable de l'installation."""
import json
import time
from unittest.mock import Mock

import pytest
import requests

from update_protocol import lire_json

SHA = 'a' * 40


@pytest.fixture
def supervise(monkeypatch, tmp_path):
    monkeypatch.setenv('CSPILOT_WORKER_TOKEN', 'secret-fictif')
    monkeypatch.setenv('CSPILOT_UPDATE_DIR', str(tmp_path))
    return tmp_path


@pytest.fixture
def github(monkeypatch):
    response = Mock()
    response.json.return_value = {'sha': SHA, 'commit': {
        'message': 'Une amélioration\nDétail', 'committer': {'date': '2026-09-13T10:00:00Z'}}}
    appel = Mock(return_value=response)
    monkeypatch.setattr('blueprints.mise_a_jour.requests.get', appel)
    return appel


@pytest.mark.parametrize('path,method', [('/mise-a-jour', 'get'),
    ('/api/mise-a-jour/verifier', 'post'), ('/api/mise-a-jour/lancer', 'post'),
    ('/api/mise-a-jour/etat', 'get')])
def test_non_connecte(client, path, method):
    assert getattr(client, method)(path).status_code in (302, 401)


@pytest.mark.parametrize('profil', ['salarie', 'responsable', 'prestataire'])
@pytest.mark.parametrize('path,method', [('/api/mise-a-jour/verifier', 'post'),
    ('/api/mise-a-jour/lancer', 'post'), ('/api/mise-a-jour/etat', 'get')])
def test_profils_refuses(admin_client, db, sample_users, profil, path, method, supervise, github):
    db.execute('UPDATE users SET profil=? WHERE id=?', (profil, sample_users['directeur_id']))
    db.commit()
    assert getattr(admin_client, method)(path).status_code == 403
    assert not (supervise / 'demande.json').exists()
    github.assert_not_called()


def test_page_salarie_refusee(auth_client):
    assert auth_client.get('/mise-a-jour').status_code == 302


@pytest.mark.parametrize('profil', ['directeur', 'comptable'])
def test_verification_et_lancement(admin_client, db, sample_users, profil, supervise, github):
    db.execute('UPDATE users SET profil=? WHERE id=?', (profil, sample_users['directeur_id']))
    db.commit()
    page = admin_client.get('/mise-a-jour')
    assert page.status_code == 200
    assert 'sauvegarde vos données et documents' in page.text
    r = admin_client.post('/api/mise-a-jour/verifier')
    assert r.status_code == 200 and r.json['disponible']
    assert r.json['revision'] == SHA[:12]
    assert github.call_args.args[0].endswith('/commits/main')
    # Le navigateur ne choisit ni SHA arbitraire, ni URL, ni commande.
    r = admin_client.post('/api/mise-a-jour/lancer', json={'sha': 'b'*40, 'url': 'http://evil.invalid'})
    assert r.status_code == 202
    assert lire_json(supervise / 'demande.json') == {'id': r.json['reference'], 'sha': SHA}
    assert admin_client.post('/api/mise-a-jour/lancer').status_code == 409


def test_github_en_echec(admin_client, github):
    github.side_effect = requests.ConnectionError('détail privé')
    r = admin_client.post('/api/mise-a-jour/verifier')
    assert r.status_code == 502
    assert 'privé' not in r.text


@pytest.mark.parametrize('sha', ['main', '../chemin', 'A'*40, None])
def test_revision_invalide(admin_client, github, sha):
    github.return_value.json.return_value['sha'] = sha
    assert admin_client.post('/api/mise-a-jour/verifier').status_code == 502


def test_mode_non_supervise(admin_client, github, monkeypatch):
    monkeypatch.delenv('CSPILOT_WORKER_TOKEN', raising=False)
    assert 'une seule fois' in admin_client.get('/mise-a-jour').text
    admin_client.post('/api/mise-a-jour/verifier')
    assert admin_client.post('/api/mise-a-jour/lancer').status_code == 503


def test_verification_requise_et_expiration(admin_client, supervise):
    assert admin_client.post('/api/mise-a-jour/lancer').status_code == 409
    with admin_client.session_transaction() as session:
        session['mise_a_jour_cible'] = {'sha': SHA, 'verifie_le': time.time() - 1801}
    assert admin_client.post('/api/mise-a-jour/lancer').status_code == 409
    assert not (supervise / 'demande.json').exists()


def test_revocation_apres_verification(admin_client, github, supervise, db, sample_users):
    admin_client.post('/api/mise-a-jour/verifier')
    db.execute('UPDATE users SET actif=0 WHERE id=?', (sample_users['directeur_id'],))
    db.commit()
    assert admin_client.post('/api/mise-a-jour/lancer').status_code == 302
    assert not (supervise / 'demande.json').exists()


def test_csrf_requis(admin_client, app, supervise, github):
    admin_client.post('/api/mise-a-jour/verifier')
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        r = admin_client.post('/api/mise-a-jour/lancer')
        assert r.status_code == 302
        assert not (supervise / 'demande.json').exists()
    finally:
        app.config['WTF_CSRF_ENABLED'] = False


def test_pas_de_reinstallation(admin_client, github, supervise):
    (supervise / 'etat.json').write_text(json.dumps({'active': {'sha': SHA}, 'job': None}))
    assert admin_client.post('/api/mise-a-jour/verifier').json['disponible'] is False
    assert admin_client.post('/api/mise-a-jour/lancer').status_code == 409
