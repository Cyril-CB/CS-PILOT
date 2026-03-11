from datetime import datetime

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


def test_budget_previsionnel_page_accessible_directeur(admin_client):
    response = admin_client.get('/budget-previsionnel')
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'Budget prévisionnel' in html
    assert 'Budget général' in html


def test_budget_previsionnel_sans_onglet_configuration_analytique(admin_client):
    response = admin_client.get('/budget-previsionnel')
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "switchTab('config')" not in html
    assert 'Configuration des codes analytiques par secteur' not in html


def test_budget_previsionnel_responsable_sans_onglet_global(resp_client):
    response = resp_client.get('/budget-previsionnel')
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'Budget prévisionnel' in html
    assert 'Budget général' not in html


def test_api_budget_previsionnel_initial_calcule_temp(app, db, admin_client, sample_users):
    n = datetime.now().year
    secteur_id = sample_users['secteur_id']
    with app.app_context():
        db.execute(
            'INSERT INTO budget_prev_config_codes (code_analytique, secteur_id) VALUES (?, ?)',
            ('ANA-TEMP', secteur_id)
        )
        db.execute(
            "INSERT INTO bilan_fec_imports (fichier_nom, annee, nb_ecritures) VALUES ('bi.txt', ?, 3)",
            (n,)
        )
        imp = db.execute('SELECT id FROM bilan_fec_imports ORDER BY id DESC LIMIT 1').fetchone()['id']
        db.execute(
            'INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) VALUES (?, ?, ?, ?, ?, ?, ?)',
            ('601000', 'Charges test', 'ANA-TEMP', n - 1, 1, 1000, imp)
        )
        db.execute(
            'INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) VALUES (?, ?, ?, ?, ?, ?, ?)',
            ('601000', 'Charges test', 'ANA-TEMP', n, 1, 2000, imp)
        )
        db.execute(
            'INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) VALUES (?, ?, ?, ?, ?, ?, ?)',
            ('701000', 'Produit test', 'ANA-TEMP', n - 1, 1, 3000, imp)
        )
        db.commit()

    response = admin_client.get(
        f'/api/budget-previsionnel/donnees?type_budget=initial&annee={n}&secteur_id={secteur_id}&inflation=2'
    )
    data = response.get_json()
    row_charge = next(r for r in data['rows'] if r['compte_num'] == '601000')
    row_produit = next(r for r in data['rows'] if r['compte_num'] == '701000')
    assert row_charge['temp'] == 2040.0
    assert row_produit['temp'] == 3000.0


def test_api_budget_previsionnel_actualise_combine_n_partiel_et_n_1(app, db, admin_client, sample_users):
    n = datetime.now().year
    secteur_id = sample_users['secteur_id']
    with app.app_context():
        db.execute(
            'INSERT INTO budget_prev_config_codes (code_analytique, secteur_id) VALUES (?, ?)',
            ('ANA-ACTU', secteur_id)
        )
        db.execute(
            "INSERT INTO bilan_fec_imports (fichier_nom, annee, nb_ecritures) VALUES ('bi.txt', ?, 4)",
            (n,)
        )
        imp = db.execute('SELECT id FROM bilan_fec_imports ORDER BY id DESC LIMIT 1').fetchone()['id']
        db.execute(
            'INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) VALUES (?, ?, ?, ?, ?, ?, ?)',
            ('602000', 'Charge actua', 'ANA-ACTU', n, 1, 100, imp)
        )
        db.execute(
            'INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) VALUES (?, ?, ?, ?, ?, ?, ?)',
            ('602000', 'Charge actua', 'ANA-ACTU', n, 2, 100, imp)
        )
        db.execute(
            'INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) VALUES (?, ?, ?, ?, ?, ?, ?)',
            ('602000', 'Charge actua', 'ANA-ACTU', n - 1, 3, 1000, imp)
        )
        db.commit()

    response = admin_client.get(
        f'/api/budget-previsionnel/donnees?type_budget=actualise&annee={n}&secteur_id={secteur_id}'
    )
    data = response.get_json()
    row_charge = next(r for r in data['rows'] if r['compte_num'] == '602000')
    assert data['last_month'] == 2
    assert row_charge['N'] == 200.0
    assert row_charge['temp'] == 1200.0


def test_api_budget_previsionnel_save_line_refuse_responsable(resp_client, sample_users):
    secteur_id = sample_users['secteur_id']
    response = resp_client.post('/api/budget-previsionnel/save-line', json={
        'type_budget': 'initial',
        'annee': datetime.now().year,
        'secteur_id': secteur_id,
        'compte_num': '601000',
        'valeur_def': 123
    })
    assert response.status_code == 403


def test_api_budget_previsionnel_sauvegarde_separee_par_type_et_annee(app, db, admin_client, sample_users):
    secteur_id = sample_users['secteur_id']
    annee = datetime.now().year
    payload_base = {
        'secteur_id': secteur_id,
        'compte_num': '601000',
        'valeur_temp': 100,
        'valeur_def': 120
    }

    admin_client.post('/api/budget-previsionnel/save-line', json={
        **payload_base, 'type_budget': 'initial', 'annee': annee
    })
    admin_client.post('/api/budget-previsionnel/save-line', json={
        **payload_base, 'type_budget': 'actualise', 'annee': annee, 'valeur_temp': 200, 'valeur_def': 220
    })
    admin_client.post('/api/budget-previsionnel/save-line', json={
        **payload_base, 'type_budget': 'initial', 'annee': annee + 1, 'valeur_temp': 300, 'valeur_def': 320
    })

    with app.app_context():
        rows = db.execute('''
            SELECT type_budget, annee, valeur_temp, valeur_def
            FROM budget_prev_saisies
            WHERE secteur_id = ? AND compte_num = '601000'
            ORDER BY annee, type_budget
        ''', (secteur_id,)).fetchall()
    assert len(rows) == 3
    assert {(r['type_budget'], r['annee'], r['valeur_temp'], r['valeur_def']) for r in rows} == {
        ('initial', annee, 100, 120),
        ('actualise', annee, 200, 220),
        ('initial', annee + 1, 300, 320),
    }
