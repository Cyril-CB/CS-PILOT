def test_dashboard_direction_ne_affiche_plus_cadre_anomalies_recentes(admin_client):
    response = admin_client.get('/dashboard_direction')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'cup &' in html  # "Demandes récup & congés"
    assert 'Top conges cumules' in html
    assert 'Anomalies recentes' not in html


def test_dashboard_direction_affiche_sections_financieres(admin_client):
    """Verifie que la refonte affiche les sections financieres."""
    response = admin_client.get('/dashboard_direction')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'ETP Total' in html
    assert 'Factures en attente' in html
    assert 'Factures a approuver' in html
    assert 'Subventions' in html
    assert 'Tresorerie' in html
    assert 'Budget' in html
    assert 'Effectifs par secteur' in html


def test_dashboard_direction_acces_rapides_complets(admin_client):
    """Verifie que les acces rapides incluent les nouveaux liens."""
    response = admin_client.get('/dashboard_direction')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Approbation factures' in html
    assert 'Statistiques RH' in html
    assert 'Bilan secteurs' in html
    assert 'Budgets' in html


def test_dashboard_direction_refuse_salarie(client, sample_users):
    """Verifie qu'un salarie ne peut pas acceder au dashboard direction."""
    from tests.conftest import _login
    _login(client, 'salarie_test', 'sal123')
    response = client.get('/dashboard_direction', follow_redirects=False)
    assert response.status_code == 302
