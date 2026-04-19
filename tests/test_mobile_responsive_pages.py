def test_vue_mensuelle_utilise_table_cartes_mobile(auth_client, sample_users, sample_planning):
    response = auth_client.get('/vue_mensuelle')
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'data-table data-table-cards month-table' in html
    assert 'class="table-responsive"' in html
    assert 'data-label="Statut"' in html
    assert 'month-page-actions' in html


def test_planning_theorique_utilise_historique_responsive(auth_client, sample_planning):
    response = auth_client.get('/planning_theorique')
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'planning-history-table' in html
    assert 'data-label="Après-midi"' in html
    assert 'planning-day-card' in html


def test_mon_equipe_rend_les_versions_desktop_et_mobile(resp_client):
    response = resp_client.get('/mon_equipe')
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'equipe-grid-desktop' in html
    assert 'equipe-mobile-list' in html
    assert 'presences-mobile-list' in html
