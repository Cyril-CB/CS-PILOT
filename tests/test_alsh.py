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
    assert 'A charge / enfant' in html
    assert 'Évolution pluriannuelle' not in html


def test_api_tableau_alsh_indique_taux_logistique_manquant(admin_client):
    response = admin_client.get('/api/alsh/tableau?annee=2025')
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['taux_logistique_manquant'] is True
