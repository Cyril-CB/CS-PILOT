"""
Tests pour le module de mise a jour semi-automatique de l'application.
"""
import os
import sys
import json
import zipfile
import tempfile
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


FAKE_RELEASE = {
    'tag_name': '1.0.30',
    'name': 'Version 1.0.30',
    'body': 'Notes de version test',
    'published_at': '2026-03-15T00:00:00Z',
    'html_url': 'https://github.com/Cyril-CB/CS-PILOT/releases/tag/1.0.30',
    'zipball_url': 'https://api.github.com/repos/Cyril-CB/CS-PILOT/zipball/1.0.30',
    'assets': [
        {
            'name': 'CS-PILOT.exe',
            'size': 50000000,
            'browser_download_url': 'https://github.com/Cyril-CB/CS-PILOT/releases/download/1.0.30/CS-PILOT.exe',
        }
    ],
}


def _mock_github_response(status_code=200, json_data=None):
    """Cree un mock de reponse requests."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or FAKE_RELEASE
    return resp


# ---------------------------------------------------------------------------
# Tests d'acces
# ---------------------------------------------------------------------------


def test_page_mise_a_jour_requiert_login(client, sample_users):
    """La page de mise a jour doit rediriger si non connecte."""
    response = client.get('/mise-a-jour', follow_redirects=False)
    assert response.status_code in (302, 401)


def test_page_mise_a_jour_interdit_salarie(auth_client):
    """Un salarie ne doit pas pouvoir acceder a la page."""
    response = auth_client.get('/mise-a-jour', follow_redirects=True)
    assert b'Acces non autorise' in response.data


def test_page_mise_a_jour_accessible_directeur(admin_client):
    """Un directeur doit pouvoir acceder a la page."""
    response = admin_client.get('/mise-a-jour')
    assert response.status_code == 200
    assert 'Mise a jour' in response.data.decode('utf-8')


def test_api_verifier_requiert_login(client, sample_users):
    """L'API de verification doit refuser un utilisateur non connecte."""
    response = client.post('/api/mise-a-jour/verifier')
    assert response.status_code in (302, 401)


def test_api_verifier_interdit_salarie(auth_client):
    """L'API de verification doit refuser un salarie."""
    response = auth_client.post('/api/mise-a-jour/verifier')
    assert response.status_code == 403


def test_api_lancer_requiert_login(client, sample_users):
    """L'API de lancement doit refuser un utilisateur non connecte."""
    response = client.post('/api/mise-a-jour/lancer')
    assert response.status_code in (302, 401)


def test_api_lancer_interdit_salarie(auth_client):
    """L'API de lancement doit refuser un salarie."""
    response = auth_client.post('/api/mise-a-jour/lancer')
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Tests de verification
# ---------------------------------------------------------------------------


@patch('blueprints.mise_a_jour.requests.get')
def test_api_verifier_succes(mock_get, admin_client):
    """La verification doit retourner les informations de la release."""
    mock_get.return_value = _mock_github_response(200, FAKE_RELEASE)

    response = admin_client.post('/api/mise-a-jour/verifier')
    assert response.status_code == 200

    data = response.get_json()
    assert data['success'] is True
    assert data['latest_version'] == '1.0.30'
    assert data['release_name'] == 'Version 1.0.30'
    assert data['mode'] == 'script'  # En mode test, pas frozen
    assert data['has_exe_asset'] is True


@patch('blueprints.mise_a_jour.requests.get')
def test_api_verifier_github_erreur(mock_get, admin_client):
    """La verification doit gerer une erreur GitHub."""
    mock_get.return_value = _mock_github_response(500)

    response = admin_client.post('/api/mise-a-jour/verifier')
    assert response.status_code == 502

    data = response.get_json()
    assert 'error' in data


@patch('blueprints.mise_a_jour.requests.get')
def test_api_verifier_timeout(mock_get, admin_client):
    """La verification doit gerer un timeout reseau."""
    import requests as req
    mock_get.side_effect = req.ConnectionError("Timeout")

    response = admin_client.post('/api/mise-a-jour/verifier')
    assert response.status_code == 502

    data = response.get_json()
    assert 'error' in data


# ---------------------------------------------------------------------------
# Tests des fonctions utilitaires
# ---------------------------------------------------------------------------


def test_is_protected():
    """Les chemins proteges doivent etre detectes."""
    from blueprints.mise_a_jour import _is_protected

    assert _is_protected('.env') is True
    assert _is_protected('.git') is True
    assert _is_protected('cspilot.db') is True
    assert _is_protected('backups') is True
    assert _is_protected('backups/sauvegarde.zip') is True
    assert _is_protected('documents') is True
    assert _is_protected('documents/photo.jpg') is True
    assert _is_protected('modeles_contrats') is True
    assert _is_protected('contrats_generes') is True

    assert _is_protected('app.py') is False
    assert _is_protected('blueprints/auth.py') is False
    assert _is_protected('templates/base.html') is False
    assert _is_protected('static/css/style.css') is False
    assert _is_protected('requirements.txt') is False


def test_find_exe_asset():
    """Doit trouver l'asset .exe dans la liste."""
    from blueprints.mise_a_jour import _find_exe_asset

    assets = [
        {'name': 'CS-PILOT.exe', 'size': 50000000, 'download_url': 'http://example.com/CS-PILOT.exe'},
        {'name': 'checksums.txt', 'size': 256, 'download_url': 'http://example.com/checksums.txt'},
    ]
    result = _find_exe_asset(assets)
    assert result is not None
    assert result['name'] == 'CS-PILOT.exe'


def test_find_exe_asset_absent():
    """Doit retourner None si aucun .exe dans les assets."""
    from blueprints.mise_a_jour import _find_exe_asset

    assets = [
        {'name': 'checksums.txt', 'size': 256, 'download_url': 'http://example.com/checksums.txt'},
    ]
    result = _find_exe_asset(assets)
    assert result is None


# ---------------------------------------------------------------------------
# Tests de la mise a jour sources
# ---------------------------------------------------------------------------


@patch('blueprints.mise_a_jour.requests.get')
def test_update_sources_copie_fichiers(mock_get, app, tmp_path):
    """La mise a jour sources doit copier les fichiers et proteger les donnees."""
    from blueprints.mise_a_jour import _update_sources, _get_app_dir

    # Creer un faux zip contenant des fichiers source
    zip_path = str(tmp_path / 'fake.zip')
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.writestr('Cyril-CB-CS-PILOT-abc123/app.py', 'print("new app")')
        zf.writestr('Cyril-CB-CS-PILOT-abc123/blueprints/test.py', 'print("new bp")')
        zf.writestr('Cyril-CB-CS-PILOT-abc123/.env', 'SECRET=should_not_copy')
        zf.writestr('Cyril-CB-CS-PILOT-abc123/requirements.txt', 'flask==3.0')

    # Mock le telechargement pour ecrire notre zip
    def side_effect(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        with open(zip_path, 'rb') as f:
            content = f.read()
        resp.iter_content = MagicMock(return_value=[content])
        return resp

    mock_get.side_effect = side_effect

    release_info = {'tag_name': '1.0.30', 'assets': []}

    with app.app_context():
        with patch('blueprints.mise_a_jour._get_app_dir', return_value=str(tmp_path / 'app_dir')):
            target_dir = str(tmp_path / 'app_dir')
            os.makedirs(target_dir, exist_ok=True)
            os.makedirs(os.path.join(target_dir, 'blueprints'), exist_ok=True)

            # Creer un .env existant qui ne doit pas etre ecrase
            with open(os.path.join(target_dir, '.env'), 'w') as f:
                f.write('SECRET=original')

            success, message = _update_sources(release_info)

    assert success is True
    assert 'Mise a jour reussie' in message

    # Verifier que les fichiers sources ont ete copies
    assert os.path.exists(os.path.join(target_dir, 'app.py'))
    assert os.path.exists(os.path.join(target_dir, 'requirements.txt'))

    # Verifier que .env n'a pas ete ecrase
    with open(os.path.join(target_dir, '.env')) as f:
        assert f.read() == 'SECRET=original'


# ---------------------------------------------------------------------------
# Tests d'affichage de la page
# ---------------------------------------------------------------------------


def test_page_mise_a_jour_affiche_informations(admin_client):
    """La page doit afficher les informations systeme."""
    response = admin_client.get('/mise-a-jour')
    html = response.data.decode('utf-8')

    assert 'Version installee' in html
    assert 'Derniere version' in html
    assert 'Script' in html  # Mode script en test
    assert 'Verifier les mises a jour' in html
    assert 'github.com/Cyril-CB/CS-PILOT' in html


def test_page_mise_a_jour_liens_navigation(admin_client):
    """La page doit contenir les liens vers sauvegarde et administration."""
    response = admin_client.get('/mise-a-jour')
    html = response.data.decode('utf-8')

    assert 'Sauvegardes' in html
    assert 'Administration' in html
