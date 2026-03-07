def test_dashboard_direction_ne_affiche_plus_cadre_anomalies_recentes(admin_client):
    response = admin_client.get('/dashboard_direction')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Demandes de recuperation' in html
    assert 'Top conges cumules' in html
    assert 'Anomalies recentes' not in html
