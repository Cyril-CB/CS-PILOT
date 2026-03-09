from blueprints.alsh import _build_tableau


def test_build_tableau_calcule_a_charge_enfant_en_excluant_7064xx(app, db):
    annee = 2025
    tranche = db.execute(
        'SELECT id FROM alsh_tranches_age WHERE active = 1 ORDER BY ordre, id LIMIT 1'
    ).fetchone()
    periode = db.execute(
        "SELECT id FROM alsh_periodes WHERE active = 1 AND type = 'mercredi' ORDER BY ordre, id LIMIT 1"
    ).fetchone()

    db.execute(
        '''
        INSERT INTO alsh_config_codes (annee, periode_id, tranche_age_id, code1, code2, code3)
        VALUES (?, ?, ?, ?, ?, ?)
        ''',
        (annee, periode['id'], tranche['id'], 'ALSH1', None, None)
    )
    db.execute(
        '''
        INSERT INTO alsh_saisie_noe (annee, periode_id, tranche_age_id, heures_presence, nb_enfants)
        VALUES (?, ?, ?, ?, ?)
        ''',
        (annee, periode['id'], tranche['id'], 100.0, 10)
    )

    # Charges
    db.execute(
        '''
        INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant)
        VALUES (?, ?, ?, ?, ?, ?)
        ''',
        ('601000', 'Charges ALSH', 'ALSH1', annee, 1, 1000.0)
    )
    # Subvention à déduire
    db.execute(
        '''
        INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant)
        VALUES (?, ?, ?, ?, ?, ?)
        ''',
        ('741100', 'Subvention CAF', 'ALSH1', annee, 1, 300.0)
    )
    # Participation familles à ne pas déduire (7064xx)
    db.execute(
        '''
        INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant)
        VALUES (?, ?, ?, ?, ?, ?)
        ''',
        ('706420', 'Participation familles', 'ALSH1', annee, 1, 200.0)
    )
    db.commit()

    data = _build_tableau(db, annee)
    ligne = next(
        l for l in data['lignes']
        if l['periode_id'] == periode['id'] and l['tranche_id'] == tranche['id']
    )

    assert ligne['charges'] == 1000.0
    assert ligne['produits'] == 500.0
    assert ligne['cout_enfant'] == 100.0
    assert ligne['a_charge_enfant'] == 70.0
    assert data['totaux']['a_charge_enfant'] == 70.0


def test_build_tableau_applique_taux_logistique_global(app, db):
    annee = 2025
    tranche = db.execute(
        'SELECT id FROM alsh_tranches_age WHERE active = 1 ORDER BY ordre, id LIMIT 1'
    ).fetchone()
    periode = db.execute(
        "SELECT id FROM alsh_periodes WHERE active = 1 AND type = 'mercredi' ORDER BY ordre, id LIMIT 1"
    ).fetchone()

    db.execute(
        '''
        INSERT INTO alsh_config_codes (annee, periode_id, tranche_age_id, code1, code2, code3)
        VALUES (?, ?, ?, ?, ?, ?)
        ''',
        (annee, periode['id'], tranche['id'], 'ALSH2', None, None)
    )
    db.execute(
        '''
        INSERT INTO alsh_saisie_noe (annee, periode_id, tranche_age_id, heures_presence, nb_enfants)
        VALUES (?, ?, ?, ?, ?)
        ''',
        (annee, periode['id'], tranche['id'], 100.0, 10)
    )
    db.execute(
        '''
        INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant)
        VALUES (?, ?, ?, ?, ?, ?)
        ''',
        ('601000', 'Charges ALSH', 'ALSH2', annee, 1, 1000.0)
    )
    db.execute(
        '''
        INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant)
        VALUES (?, ?, ?, ?, ?, ?)
        ''',
        ('741100', 'Subvention CAF', 'ALSH2', annee, 1, 300.0)
    )
    db.execute(
        '''
        INSERT INTO bilan_taux_logistique (annee, taux_site1, taux_site2, taux_global, taux_selectionne)
        VALUES (?, ?, ?, ?, ?)
        ''',
        (annee, 0.0, 0.0, 20.0, 'global')
    )
    db.commit()

    data = _build_tableau(db, annee)
    ligne = next(
        l for l in data['lignes']
        if l['periode_id'] == periode['id'] and l['tranche_id'] == tranche['id']
    )

    assert ligne['charges'] == 1200.0
    assert ligne['cout_enfant'] == 120.0
    assert ligne['a_charge_enfant'] == 90.0
    assert data['totaux']['charges'] == 1200.0
    assert data['totaux']['a_charge_enfant'] == 90.0
    assert data['taux_logistique_global'] == 20.0
    assert data['taux_logistique_manquant'] is False


def test_page_analyse_alsh_affiche_section_tarif_optimal(admin_client):
    response = admin_client.get('/analyse-alsh')
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Tarif optimal' in html
    assert 'Répartition type des quotients' in html
    assert 'A charge / enfant' in html
    assert 'Évolution pluriannuelle' not in html


def test_page_analyse_alsh_charge_les_graphiques_depuis_un_script_local(admin_client):
    response = admin_client.get('/analyse-alsh')
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '/static/js/simple-charts.js?v=1' in html
    assert 'cdn.jsdelivr.net/npm/chart.js' not in html


def test_api_tableau_alsh_indique_taux_logistique_manquant(admin_client):
    response = admin_client.get('/api/alsh/tableau?annee=2025')
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['taux_logistique_manquant'] is True


def test_api_tableau_alsh_indique_taux_logistique_manquant_si_taux_zero(admin_client, db):
    db.execute(
        '''
        INSERT INTO bilan_taux_logistique (annee, taux_site1, taux_site2, taux_global, taux_selectionne)
        VALUES (?, ?, ?, ?, ?)
        ''',
        (2024, 0.0, 0.0, 0.0, 'global')
    )
    db.commit()

    response = admin_client.get('/api/alsh/tableau?annee=2024')
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['taux_logistique_global'] == 0.0
    assert payload['taux_logistique_manquant'] is True


def test_api_alsh_config_retourne_repartition_quotients_par_defaut(admin_client):
    response = admin_client.get('/api/alsh/config')
    payload = response.get_json()

    assert response.status_code == 200
    assert 'tarif_repartition_quotients' in payload
    assert payload['tarif_repartition_quotients'][0]['id'] == 'qf_0_249'
    assert payload['tarif_repartition_quotients'][0]['pct'] == 22.0


def test_api_alsh_tarif_repartition_persiste_globalement(admin_client):
    nouvelle_repartition = [
        {'id': 'qf_0_249', 'pct': 35},
        {'id': 'qf_250_499', 'pct': 25},
        {'id': 'qf_500_749', 'pct': 15},
        {'id': 'qf_750_999', 'pct': 10},
        {'id': 'qf_1000_1249', 'pct': 6},
        {'id': 'qf_1250_1499', 'pct': 4},
        {'id': 'qf_1500_1749', 'pct': 3},
        {'id': 'qf_1750_plus', 'pct': 2},
    ]

    save_res = admin_client.post('/api/alsh/tarif-repartition', json={
        'tarif_repartition_quotients': nouvelle_repartition
    })
    assert save_res.status_code == 200
    assert save_res.get_json()['success'] is True

    config_1 = admin_client.get('/api/alsh/config').get_json()
    config_2 = admin_client.get('/api/alsh/config').get_json()

    assert config_1['tarif_repartition_quotients'] == nouvelle_repartition
    assert config_2['tarif_repartition_quotients'] == nouvelle_repartition
