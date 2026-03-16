def test_dashboard_comptable_accessible(comptable_client):
    """Verifie que le comptable accede a son dashboard."""
    response = comptable_client.get('/dashboard_comptable')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Tableau de bord Comptable' in html


def test_dashboard_comptable_sections_specifiques(comptable_client):
    """Verifie les sections specifiques au comptable."""
    response = comptable_client.get('/dashboard_comptable')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    # KPI cards
    assert "Ma fiche d&#39;heures" in html or "Ma fiche d'heures" in html
    assert 'Documents manquants' in html
    assert 'Cloture' in html
    assert 'Prepa paie' in html
    # Sections
    assert 'Documents obligatoires' in html
    assert 'Ecritures brouillon' in html
    assert 'Pretes a exporter' in html
    assert 'Factures en attente' in html
    assert 'Donnees importees disponibles' in html


def test_dashboard_comptable_acces_rapides(comptable_client):
    """Verifie les acces rapides du comptable."""
    response = comptable_client.get('/dashboard_comptable')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Vue Direction' in html
    assert 'Prepa paie' in html
    assert 'Fiches salaries' in html
    assert 'Ecritures comptables' in html
    assert 'Exportation' in html
    assert 'Bilan secteurs' in html
    assert 'Budget previsionnel' in html


def test_dashboard_comptable_refuse_salarie(client, sample_users):
    """Verifie qu'un salarie ne peut pas acceder au dashboard comptable."""
    from tests.conftest import _login
    _login(client, 'salarie_test', 'sal123')
    response = client.get('/dashboard_comptable', follow_redirects=False)
    assert response.status_code == 302


def test_dashboard_comptable_refuse_responsable(resp_client):
    """Verifie qu'un responsable ne peut pas acceder au dashboard comptable."""
    response = resp_client.get('/dashboard_comptable', follow_redirects=False)
    assert response.status_code == 302


def test_dashboard_redirect_comptable(comptable_client):
    """Verifie que /dashboard redirige vers dashboard_comptable pour un comptable."""
    response = comptable_client.get('/dashboard', follow_redirects=False)
    assert response.status_code == 302
    assert 'dashboard_comptable' in response.headers.get('Location', '')
