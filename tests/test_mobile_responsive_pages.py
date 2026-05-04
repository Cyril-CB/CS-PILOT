def test_vue_mensuelle_utilise_table_cartes_mobile(auth_client, sample_users, sample_planning):
    response = auth_client.get('/vue_mensuelle')
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'data-table data-table-cards month-table' in html
    assert 'class="table-responsive"' in html
    assert 'data-label="Statut"' in html
    assert 'month-page-actions' in html
    assert 'month-mobile-layout' in html
    assert 'month-mobile-day-card' in html
    assert 'window.matchMedia(' in html
    assert 'monthlyPage.dataset.layout' in html


def test_vue_calendrier_rend_versions_desktop_et_mobile(auth_client, sample_users, sample_planning):
    response = auth_client.get('/vue_calendrier')
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'calendar-mobile-layout' in html
    assert 'calendar-mobile-board' in html
    assert 'calendar-mobile-grid' in html
    assert 'calendar-mobile-cell' in html
    assert 'calendar-desktop-layout' in html
    assert 'cal-grid' in html


def test_planning_theorique_utilise_historique_responsive(auth_client, sample_planning):
    response = auth_client.get('/planning_theorique')
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'planning-history-table' in html
    assert 'data-label="Après-midi"' in html
    assert 'planning-day-card' in html
    assert 'vous pouvez ne saisir que le planning scolaire' in html
    assert 'use_specific_vacation_planning' in html
    assert 'Saisir un planning spécifique pour les vacances scolaires' in html
    assert 'vacancesOption.disabled = !useSpecificVacationPlanning' in html


def test_mon_equipe_rend_les_versions_desktop_et_mobile(resp_client, db, sample_users):
    cursor = db.cursor()
    for user_id in (sample_users['responsable_id'], sample_users['salarie_id']):
        cursor.execute(
            "INSERT INTO contrats (user_id, type_contrat, date_debut, temps_hebdo, saisi_par) VALUES (?,?,?,?,?)",
            (user_id, 'CDI', '2024-01-01', 35.0, sample_users['directeur_id'])
        )
    db.commit()

    response = resp_client.get('/mon_equipe')
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'equipe-grid-desktop' in html
    assert 'equipe-mobile-list' in html
    assert 'presences-mobile-list' in html
    assert '@media (max-width: 768px)' in html
