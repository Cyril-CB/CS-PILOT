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


def test_budget_previsionnel_rendu_contient_classes_mise_en_page_table(admin_client):
    response = admin_client.get('/budget-previsionnel')
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'bp-col-input' in html
    assert 'bp-cat-total' in html
    assert 'data-bp-def-compte=' in html
    assert 'data-bp-comment-compte=' in html
    assert 'oninput="queueSave(' not in html
    assert 'onchange="updateBrutTemp(' not in html


def test_budget_previsionnel_entete_fige_sans_repetition(admin_client):
    """Étape 1 : en-têtes figés (thead sticky dans un conteneur défilant) et
    suppression de la répétition de l'en-tête par catégorie."""
    response = admin_client.get('/budget-previsionnel')
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'bp-table-scroll' in html
    assert 'bp-cat-header' not in html


def test_budget_previsionnel_sauvegarde_liee_au_contexte_edite(admin_client):
    response = admin_client.get('/budget-previsionnel')
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'function getCurrentBudgetContext()' in html
    assert 'const saveKey = getSaveKey(compte, context);' in html
    assert 'saveTimers[saveKey] = setTimeout(() => saveLine(row, context, saveKey), 300);' in html
    assert 'type_budget: context.type_budget' in html
    assert 'annee: context.annee' in html
    assert 'secteur_id: context.secteur_id' in html


def test_budget_previsionnel_responsable_sans_onglet_global(resp_client):
    response = resp_client.get('/budget-previsionnel')
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'Budget prévisionnel' in html
    assert 'Budget général' not in html


def test_jeton_csrf_sans_expiration(app):
    """Le jeton CSRF ne doit pas expirer (sinon enregistrements AJAX rejetés)."""
    assert app.config.get('WTF_CSRF_TIME_LIMIT') is None


def test_responsable_enregistre_budget_de_son_secteur(resp_client, db, sample_users):
    """Un responsable peut enregistrer les montants du budget de SON secteur."""
    sid = sample_users['secteur_id']
    db.execute("INSERT INTO budgets (secteur_id, annee, montant_global) VALUES (?, 2026, 5000)", (sid,))
    poste_id = db.execute("SELECT id FROM postes_depense ORDER BY id LIMIT 1").fetchone()['id']
    db.commit()

    resp = resp_client.post('/api/budget/save', json={
        'secteur_id': sid, 'annee': 2026, 'montant_global': None,
        'lignes': [{'poste_depense_id': poste_id, 'periode': 'annuel', 'montant': 1000}],
    })
    assert resp.status_code == 200
    assert resp.is_json
    assert resp.get_json().get('success') is True
    row = db.execute(
        "SELECT montant FROM budget_lignes WHERE poste_depense_id = ? AND periode = 'annuel'",
        (poste_id,)
    ).fetchone()
    assert row is not None and abs(row['montant'] - 1000) < 0.001


def test_responsable_ne_peut_pas_enregistrer_autre_secteur(resp_client, db):
    """Un responsable ne peut pas enregistrer le budget d'un autre secteur."""
    db.execute("INSERT INTO secteurs (nom, type_secteur) VALUES ('Autre secteur','administratif')")
    autre = db.execute("SELECT id FROM secteurs WHERE nom='Autre secteur'").fetchone()['id']
    db.execute("INSERT INTO budgets (secteur_id, annee, montant_global) VALUES (?, 2026, 5000)", (autre,))
    db.commit()

    resp = resp_client.post('/api/budget/save', json={
        'secteur_id': autre, 'annee': 2026, 'montant_global': None, 'lignes': [],
    })
    assert resp.status_code == 403


def test_budget_secteur_distingue_session_expiree_de_panne_reseau(resp_client, sample_users):
    """Le template doit afficher un message clair en cas de réponse non-JSON
    (session / jeton CSRF expiré) plutôt qu'une simple « Erreur réseau »."""
    sid = sample_users['secteur_id']
    resp = resp_client.get(f'/budget_secteur/{sid}?annee=2026')
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert 'readSaveResponse' in html
    assert 'Session expirée ou invalide' in html


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


# ============================================================
# Simulateur Prestation de Service (PS) CAF
# ============================================================

def test_budget_previsionnel_bouton_config_ps_directeur(admin_client):
    """Le directeur dispose du bouton de paramétrage et de la modale simulateur."""
    response = admin_client.get('/budget-previsionnel')
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'Paramétrer les comptes PS' in html
    assert 'Comptes concernés par une Prestation de Service' in html
    # La modale du simulateur est disponible pour tous ceux qui voient la page
    assert 'id="psSimulatorModal"' in html


def test_budget_previsionnel_config_ps_absente_responsable(resp_client):
    """Le responsable n'a pas accès au paramétrage des comptes PS (bouton + modale)."""
    response = resp_client.get('/budget-previsionnel')
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'Paramétrer les comptes PS' not in html
    assert 'Comptes concernés par une Prestation de Service' not in html


def test_api_ps_comptes_crud_directeur(app, db, admin_client):
    """Le directeur peut rattacher un compte 70 à une PS, le lister puis le retirer."""
    resp = admin_client.post('/api/budget-previsionnel/ps-comptes', json={
        'compte_num': '706000', 'type_ps': 'eaje'
    })
    assert resp.status_code == 200 and resp.get_json().get('success') is True

    resp = admin_client.get('/api/budget-previsionnel/ps-comptes')
    assert resp.get_json()['comptes'] == {'706000': 'eaje'}

    # Mise à jour du type
    admin_client.post('/api/budget-previsionnel/ps-comptes', json={
        'compte_num': '706000', 'type_ps': 'alsh'
    })
    assert admin_client.get('/api/budget-previsionnel/ps-comptes').get_json()['comptes'] == {'706000': 'alsh'}

    resp = admin_client.delete('/api/budget-previsionnel/ps-comptes/706000')
    assert resp.status_code == 200
    assert admin_client.get('/api/budget-previsionnel/ps-comptes').get_json()['comptes'] == {}


def test_api_ps_comptes_refuse_responsable(resp_client):
    """Le responsable ne peut pas paramétrer les comptes PS."""
    resp = resp_client.post('/api/budget-previsionnel/ps-comptes', json={
        'compte_num': '706000', 'type_ps': 'eaje'
    })
    assert resp.status_code == 403


def test_api_ps_comptes_type_invalide(admin_client):
    resp = admin_client.post('/api/budget-previsionnel/ps-comptes', json={
        'compte_num': '706000', 'type_ps': 'autre'
    })
    assert resp.status_code == 400


def test_api_ps_comptes_disponibles_liste_comptes_70(app, db, admin_client):
    """Les comptes 70 du plan comptable et du FEC sont proposés au paramétrage."""
    with app.app_context():
        db.execute(
            "INSERT INTO plan_comptable_general (compte_num, libelle) VALUES ('706100', 'PS EAJE')"
        )
        db.execute(
            "INSERT INTO plan_comptable_general (compte_num, libelle) VALUES ('601000', 'Achats')"
        )
        db.commit()
    resp = admin_client.get('/api/budget-previsionnel/ps-comptes-disponibles')
    comptes = {c['compte_num'] for c in resp.get_json()['comptes']}
    assert '706100' in comptes
    assert '601000' not in comptes


def test_api_ps_simulation_eaje_calcule_et_reporte(app, db, admin_client, sample_users):
    """La simulation EAJE calcule le total côté serveur et le reporte sur le
    compte (valeur définitive du budget prévisionnel)."""
    secteur_id = sample_users['secteur_id']
    annee = datetime.now().year
    donnees = {
        'taux_ps': 6.63,
        'taux_regime': 100,
        'mois': [
            {'jours_ouverture': 20, 'heures_facturees': 1000, 'heures_realisees': 1100,
             'participation': 1500, 'places': 20, 'amplitude_horaire': 10}
        ] + [{} for _ in range(11)],
        'nb_enfants_inscrits': 50,
        'financement_par_enfant': 8,
        'journees_peda': {'nb_journees': 3, 'nb_heures': 10},
        'bonus_attractivite_taux': 970,
    }
    resp = admin_client.post('/api/budget-previsionnel/ps-simulation', json={
        'compte_num': '706000', 'annee': annee, 'type_budget': 'initial',
        'type_ps': 'eaje', 'secteur_id': secteur_id, 'donnees': donnees
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True

    # Détail attendu :
    # PSU = 1000 * 6.63 * 1.0 = 6630 ; PSU - participation = 6630 - 1500 = 5130
    # taux horaire moyen = 1500 / 1000 = 1.5 -> bonus mixité bracket <=1.52 : 300/place
    # places moyen = 20 ; bonus mixité = 300 * 20 = 6000
    # PS prépa = 50 * 8 * 1.0 = 400
    # journées péda = 3 * 10 * 6.63 * 1.0 * 20 = 3978
    # bonus attractivité = 970 * 20 = 19400
    # total = 5130 + 400 + 6000 + 3978 + 19400 = 34908
    assert abs(data['total'] - 34908.0) < 0.01
    assert data['reported'] is True

    # Report sur la valeur définitive du compte
    row = db.execute('''
        SELECT valeur_def FROM budget_prev_saisies
        WHERE type_budget = 'initial' AND annee = ? AND secteur_id = ? AND compte_num = '706000'
    ''', (annee, secteur_id)).fetchone()
    assert row is not None and abs(row['valeur_def'] - 34908.0) < 0.01

    # La simulation est relue avec les mêmes données
    resp_get = admin_client.get(
        f'/api/budget-previsionnel/ps-simulation?compte_num=706000&annee={annee}&type_budget=initial'
    )
    got = resp_get.get_json()
    assert got['found'] is True
    assert abs(got['total'] - 34908.0) < 0.01
    assert got['donnees']['nb_enfants_inscrits'] == 50


def test_api_ps_simulation_attachee_au_type_et_annee(admin_client, sample_users):
    """Une simulation est attachée au couple (compte, année, type de budget)."""
    secteur_id = sample_users['secteur_id']
    annee = datetime.now().year
    base = {'compte_num': '706000', 'type_ps': 'eaje', 'secteur_id': secteur_id,
            'donnees': {'mois': [{'heures_facturees': 100, 'participation': 50, 'places': 10}]}}
    admin_client.post('/api/budget-previsionnel/ps-simulation',
                      json={**base, 'annee': annee, 'type_budget': 'initial'})
    admin_client.post('/api/budget-previsionnel/ps-simulation',
                      json={**base, 'annee': annee, 'type_budget': 'actualise'})

    r_init = admin_client.get(
        f'/api/budget-previsionnel/ps-simulation?compte_num=706000&annee={annee}&type_budget=initial'
    ).get_json()
    r_actu = admin_client.get(
        f'/api/budget-previsionnel/ps-simulation?compte_num=706000&annee={annee}&type_budget=actualise'
    ).get_json()
    assert r_init['found'] is True and r_actu['found'] is True
    # Une année/type non saisi reste vide
    r_vide = admin_client.get(
        f'/api/budget-previsionnel/ps-simulation?compte_num=706000&annee={annee + 1}&type_budget=initial'
    ).get_json()
    assert r_vide['found'] is False


def test_api_ps_simulation_refuse_responsable(resp_client, sample_users):
    secteur_id = sample_users['secteur_id']
    resp = resp_client.post('/api/budget-previsionnel/ps-simulation', json={
        'compte_num': '706000', 'annee': datetime.now().year, 'type_budget': 'initial',
        'type_ps': 'eaje', 'secteur_id': secteur_id, 'donnees': {}
    })
    assert resp.status_code == 403
