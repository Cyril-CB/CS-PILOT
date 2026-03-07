TEST_SECTOR_TYPE_HIGH_ORDER = 999


def test_gestion_postes_depense_affiche_types_secteur_dynamiques(app, db, admin_client):
    """Les nouveaux types de secteur doivent être sélectionnables pour les postes de dépense."""
    with app.app_context():
        db.execute(
            'INSERT INTO types_secteur (code, libelle, ordre) VALUES (?, ?, ?)',
            ('transition_eco', 'Transition écologique', TEST_SECTOR_TYPE_HIGH_ORDER)
        )
        db.commit()

    response = admin_client.get('/gestion_postes_depense')
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Transition écologique' in html
    assert 'value="transition_eco"' in html


def test_gestion_budgets_affiche_libelle_type_secteur_dynamique(app, db, admin_client):
    """Les écrans budget doivent afficher les libellés issus de types_secteur."""
    with app.app_context():
        db.execute(
            'INSERT INTO types_secteur (code, libelle, ordre) VALUES (?, ?, ?)',
            ('mediation', 'Médiation numérique', TEST_SECTOR_TYPE_HIGH_ORDER)
        )
        db.execute(
            'INSERT INTO secteurs (nom, description, type_secteur) VALUES (?, ?, ?)',
            ('Secteur Médiation', 'Secteur test', 'mediation')
        )
        db.commit()

    response = admin_client.get('/gestion_budgets')
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Médiation numérique' in html
