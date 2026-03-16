def test_dashboard_responsable_accessible(resp_client):
    """Verifie que le responsable accede a son dashboard."""
    response = resp_client.get('/dashboard_responsable')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Mon equipe' in html
    assert 'Absences en cours' in html
    assert 'Validations mensuelles' in html


def test_dashboard_responsable_affiche_sections(resp_client):
    """Verifie que les sections specifiques responsable sont presentes."""
    response = resp_client.get('/dashboard_responsable')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'ETP Secteur' in html
    assert 'Factures en attente' in html
    assert 'Factures a approuver' in html
    assert 'Demandes de recuperation' in html
    assert 'Subventions' in html
    assert 'Budget' in html
    assert 'Conges de l&#39;equipe' in html or "Conges de l'equipe" in html


def test_dashboard_responsable_pas_tresorerie_anomalies(resp_client):
    """Verifie que Tresorerie et Anomalies ne sont PAS affiches."""
    response = resp_client.get('/dashboard_responsable')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Tresorerie' not in html
    assert 'Anomalies' not in html


def test_dashboard_responsable_acces_rapides(resp_client):
    """Verifie que les acces rapides sont presents et adaptes."""
    response = resp_client.get('/dashboard_responsable')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Vue ensemble validation' in html
    assert 'Approbation factures' in html
    assert 'Mon budget' in html
    assert 'Budget previsionnel' in html


def test_dashboard_responsable_refuse_salarie(client, sample_users):
    """Verifie qu'un salarie ne peut pas acceder au dashboard responsable."""
    from tests.conftest import _login
    _login(client, 'salarie_test', 'sal123')
    response = client.get('/dashboard_responsable', follow_redirects=False)
    assert response.status_code == 302


def test_dashboard_responsable_refuse_directeur(admin_client):
    """Verifie qu'un directeur ne peut pas acceder au dashboard responsable."""
    response = admin_client.get('/dashboard_responsable', follow_redirects=False)
    assert response.status_code == 302


def test_dashboard_redirect_responsable(resp_client):
    """Verifie que /dashboard redirige vers dashboard_responsable pour un responsable."""
    response = resp_client.get('/dashboard', follow_redirects=False)
    assert response.status_code == 302
    assert 'dashboard_responsable' in response.headers.get('Location', '')
