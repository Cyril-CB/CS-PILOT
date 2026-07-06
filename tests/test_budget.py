import importlib.util
import json
import os
from datetime import datetime

from blueprints.budget import (
    _compute_ps_eaje, _compute_ps_alsh_extrasco, _compute_ps_alsh_perisco
)

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


def test_api_budget_previsionnel_detail_liste_les_operations(app, db, admin_client, sample_users):
    # Le détail d'une somme compta liste les opérations FEC, filtrées par secteur.
    n = datetime.now().year
    secteur_id = sample_users['secteur_id']
    with app.app_context():
        db.execute('INSERT INTO budget_prev_config_codes (code_analytique, secteur_id) VALUES (?, ?)',
                   ('ANA-DET', secteur_id))
        db.execute("INSERT INTO bilan_fec_imports (fichier_nom, annee, nb_ecritures) VALUES ('bi.txt', ?, 3)", (n,))
        imp = db.execute('SELECT id FROM bilan_fec_imports ORDER BY id DESC LIMIT 1').fetchone()['id']
        for mois, montant in [(1, 100), (2, 250)]:
            db.execute('INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) '
                       'VALUES (?, ?, ?, ?, ?, ?, ?)', ('601000', 'Charge', 'ANA-DET', n, mois, montant, imp))
        # Opération d'un autre secteur (code non autorisé) : doit être exclue.
        db.execute('INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) '
                   'VALUES (?, ?, ?, ?, ?, ?, ?)', ('601000', 'Autre', 'ANA-AUTRE', n, 3, 999, imp))
        db.commit()

    r = admin_client.get(f'/api/budget-previsionnel/detail?compte=601000&annee={n}&secteur_id={secteur_id}')
    ops = r.get_json()['operations']
    assert sorted(o['montant'] for o in ops) == [100.0, 250.0]  # l'opération hors secteur est exclue
    assert all(o['mois_nom'] for o in ops)


def test_api_budget_previsionnel_detail_respecte_mois_max(app, db, admin_client, sample_users):
    # En « actualisé », la colonne N est partielle : le détail respecte mois_max.
    n = datetime.now().year
    secteur_id = sample_users['secteur_id']
    with app.app_context():
        db.execute('INSERT INTO budget_prev_config_codes (code_analytique, secteur_id) VALUES (?, ?)',
                   ('ANA-MM', secteur_id))
        db.execute("INSERT INTO bilan_fec_imports (fichier_nom, annee, nb_ecritures) VALUES ('bi.txt', ?, 3)", (n,))
        imp = db.execute('SELECT id FROM bilan_fec_imports ORDER BY id DESC LIMIT 1').fetchone()['id']
        for mois in (1, 2, 5):
            db.execute('INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) '
                       'VALUES (?, ?, ?, ?, ?, ?, ?)', ('601000', 'C', 'ANA-MM', n, mois, 100, imp))
        db.commit()

    r = admin_client.get(f'/api/budget-previsionnel/detail?compte=601000&annee={n}&secteur_id={secteur_id}&mois_max=2')
    ops = r.get_json()['operations']
    assert [o['mois'] for o in ops] == [1, 2]  # le mois 5 est exclu


def test_api_budget_previsionnel_detail_refuse_salarie(auth_client):
    r = auth_client.get('/api/budget-previsionnel/detail?compte=601000&annee=2026')
    assert r.status_code == 403


def test_api_budget_previsionnel_detail_responsable_sans_secteur_refuse(app, db, resp_client, sample_users):
    # Sécurité : un responsable autorisé mais SANS secteur ne doit pas récupérer
    # toutes les opérations du compte (fuite) — l'accès est refusé (403).
    from app_options import set_option_bool
    n = datetime.now().year
    with app.app_context():
        set_option_bool('budget_previsionnel_responsable_autorise', True)
        db.execute("UPDATE users SET secteur_id = NULL WHERE id = ?", (sample_users['responsable_id'],))
        # Une opération existe pour ce compte/année : elle ne doit PAS fuiter.
        db.execute("INSERT INTO bilan_fec_imports (fichier_nom, annee, nb_ecritures) VALUES ('bi.txt', ?, 1)", (n,))
        imp = db.execute('SELECT id FROM bilan_fec_imports ORDER BY id DESC LIMIT 1').fetchone()['id']
        db.execute('INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) '
                   'VALUES (?, ?, ?, ?, ?, ?, ?)', ('601000', 'X', 'ANA-X', n, 1, 500, imp))
        db.commit()
    r = resp_client.get(f'/api/budget-previsionnel/detail?compte=601000&annee={n}')
    assert r.status_code == 403


def test_budget_previsionnel_sommes_cliquables_et_modale(admin_client):
    # La page embarque l'indice, la fenêtre de détail, le handler et le style lien.
    html = admin_client.get('/budget-previsionnel').get_data(as_text=True)
    assert 'Cliquez les sommes pour afficher le détail' in html
    assert 'bpDetailModal' in html
    assert 'bpVoirDetail' in html
    assert 'bp-detail' in html


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


def test_budget_previsionnel_modales_rattachees_au_body(admin_client):
    """Les modales sont déplacées au <body> pour s'afficher par-dessus le menu."""
    html = admin_client.get('/budget-previsionnel').get_data(as_text=True)
    assert "'psSimulatorModal', 'psConfigModal'" in html
    assert 'document.body.appendChild(el)' in html


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
        'compte_num': '706000', 'type_ps': 'alsh_extrasco'
    })
    assert admin_client.get('/api/budget-previsionnel/ps-comptes').get_json()['comptes'] == {'706000': 'alsh_extrasco'}

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
        f'/api/budget-previsionnel/ps-simulation?compte_num=706000&annee={annee}&secteur_id={secteur_id}&type_budget=initial'
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
        f'/api/budget-previsionnel/ps-simulation?compte_num=706000&annee={annee}&secteur_id={secteur_id}&type_budget=initial'
    ).get_json()
    r_actu = admin_client.get(
        f'/api/budget-previsionnel/ps-simulation?compte_num=706000&annee={annee}&secteur_id={secteur_id}&type_budget=actualise'
    ).get_json()
    assert r_init['found'] is True and r_actu['found'] is True
    # Une année/type non saisi reste vide
    r_vide = admin_client.get(
        f'/api/budget-previsionnel/ps-simulation?compte_num=706000&annee={annee + 1}&secteur_id={secteur_id}&type_budget=initial'
    ).get_json()
    assert r_vide['found'] is False


def test_api_ps_simulation_attachee_au_secteur(app, db, admin_client, sample_users):
    """Deux secteurs (ex. deux crèches) partageant le même compte produit ont
    des simulations distinctes pour la même année et le même type de budget."""
    secteur1 = sample_users['secteur_id']
    with app.app_context():
        db.execute("INSERT INTO secteurs (nom, type_secteur) VALUES ('Crèche B', 'creche')")
        secteur2 = db.execute("SELECT id FROM secteurs WHERE nom='Crèche B'").fetchone()['id']
        db.commit()
    annee = datetime.now().year

    def payload(secteur_id, hfact, part):
        return {
            'compte_num': '706000', 'annee': annee, 'type_budget': 'initial',
            'type_ps': 'eaje', 'secteur_id': secteur_id,
            'donnees': {'mois': [{'heures_facturees': hfact, 'participation': part, 'places': 10,
                                  'jours_ouverture': 20, 'amplitude_horaire': 10}]}
        }
    admin_client.post('/api/budget-previsionnel/ps-simulation', json=payload(secteur1, 1000, 1500))
    admin_client.post('/api/budget-previsionnel/ps-simulation', json=payload(secteur2, 2000, 1000))

    # Deux lignes distinctes en base (pas d'écrasement)
    with app.app_context():
        rows = db.execute('''
            SELECT secteur_id FROM budget_ps_simulations
            WHERE compte_num='706000' AND annee=? AND type_budget='initial'
            ORDER BY secteur_id
        ''', (annee,)).fetchall()
    assert {r['secteur_id'] for r in rows} == {secteur1, secteur2}

    # La relecture par secteur renvoie les données propres à chaque secteur
    r1 = admin_client.get(
        f'/api/budget-previsionnel/ps-simulation?compte_num=706000&annee={annee}&secteur_id={secteur1}&type_budget=initial'
    ).get_json()
    r2 = admin_client.get(
        f'/api/budget-previsionnel/ps-simulation?compte_num=706000&annee={annee}&secteur_id={secteur2}&type_budget=initial'
    ).get_json()
    assert r1['donnees']['mois'][0]['heures_facturees'] == 1000
    assert r2['donnees']['mois'][0]['heures_facturees'] == 2000

    # Report sur le budget de chaque secteur séparément
    with app.app_context():
        defs = db.execute('''
            SELECT secteur_id FROM budget_prev_saisies
            WHERE compte_num='706000' AND annee=? AND type_budget='initial'
        ''', (annee,)).fetchall()
    assert {r['secteur_id'] for r in defs} == {secteur1, secteur2}


def test_api_ps_simulation_secteur_requis(admin_client):
    """Le secteur est obligatoire à l'enregistrement d'une simulation."""
    resp = admin_client.post('/api/budget-previsionnel/ps-simulation', json={
        'compte_num': '706000', 'annee': datetime.now().year, 'type_budget': 'initial',
        'type_ps': 'eaje', 'donnees': {}
    })
    assert resp.status_code == 400


def test_budget_previsionnel_simulateur_echappe_valeurs(admin_client):
    """Les valeurs persistées sont échappées avant injection HTML (P2 / anti-XSS)."""
    html = admin_client.get('/budget-previsionnel').get_data(as_text=True)
    assert 'function psAttr(' in html
    # Plus d'injection brute des valeurs persistées dans les attributs value
    assert "value=\"' + st.taux_ps + '\"" not in html
    assert 'psAttr(st.taux_ps)' in html
    assert 'psAttr(val)' in html


def test_api_ps_simulation_refuse_responsable(resp_client, sample_users):
    secteur_id = sample_users['secteur_id']
    resp = resp_client.post('/api/budget-previsionnel/ps-simulation', json={
        'compte_num': '706000', 'annee': datetime.now().year, 'type_budget': 'initial',
        'type_ps': 'eaje', 'secteur_id': secteur_id, 'donnees': {}
    })
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Simulateur PS EAJE : modes prévisionnel / réel par mois
# ---------------------------------------------------------------------------

_PS_BASE = {
    'taux_ps': 6.63, 'taux_regime': 100,
    'nb_enfants_inscrits': 50, 'financement_par_enfant': 8,
    'journees_peda': {'nb_journees': 3, 'nb_heures': 10},
    'bonus_attractivite_taux': 970,
}


def test_compute_ps_eaje_mode_reel_calcule_les_taux():
    """Réel : heures/participation saisies → taux d'occupation et horaire calculés."""
    d = dict(_PS_BASE, mois=[{
        'prev_reel': 'reel', 'jours_ouverture': 20, 'heures_facturees': 1000,
        'heures_realisees': 1100, 'participation': 1500, 'places': 20, 'amplitude_horaire': 10,
    }])
    c = _compute_ps_eaje(d)
    m = c['mois'][0]
    assert m['taux_occupation'] == 0.25      # 1000 / (10*20*20)
    assert m['taux_horaire'] == 1.5          # 1500 / 1000
    assert m['heures_realisees'] == 1100     # saisie indépendante en réel


def test_compute_ps_eaje_defaut_reel_retrocompat():
    """Un mois sans prev_reel garde le comportement historique (réel)."""
    d = dict(_PS_BASE, mois=[{
        'jours_ouverture': 20, 'heures_facturees': 1000, 'heures_realisees': 1000,
        'participation': 1500, 'places': 20, 'amplitude_horaire': 10,
    }])
    m = _compute_ps_eaje(d)['mois'][0]
    assert m['taux_occupation'] == 0.25
    assert m['taux_horaire'] == 1.5


def test_compute_ps_eaje_mode_previsionnel_calcule_les_heures():
    """Prévisionnel : taux occup (%) et taux horaire saisis → heures et participation calculées."""
    d = dict(_PS_BASE, mois=[{
        'prev_reel': 'prev', 'jours_ouverture': 20, 'places': 20, 'amplitude_horaire': 10,
        'taux_occupation': 25, 'taux_horaire': 1.5,
    }])
    m = _compute_ps_eaje(d)['mois'][0]
    assert m['heures_facturees'] == 1000.0   # 0.25 * (10*20*20)
    assert m['heures_realisees'] == 1000.0   # copie des heures facturées
    assert m['participation'] == 1500.0      # 1.5 * 1000


def test_compute_ps_eaje_previsionnel_equivaut_au_reel():
    """Un mois prévisionnel reproduit le total d'un mois réel équivalent."""
    reel = dict(_PS_BASE, mois=[{
        'prev_reel': 'reel', 'jours_ouverture': 20, 'heures_facturees': 1000,
        'heures_realisees': 1000, 'participation': 1500, 'places': 20, 'amplitude_horaire': 10,
    }])
    prev = dict(_PS_BASE, mois=[{
        'prev_reel': 'prev', 'jours_ouverture': 20, 'places': 20, 'amplitude_horaire': 10,
        'taux_occupation': 25, 'taux_horaire': 1.5,
    }])
    assert abs(_compute_ps_eaje(reel)['total'] - _compute_ps_eaje(prev)['total']) < 0.01


def test_api_ps_simulation_previsionnel_reporte_le_total(app, db, admin_client, sample_users):
    """La saisie prévisionnelle calcule heures/participation côté serveur et reporte le total."""
    secteur_id = sample_users['secteur_id']
    annee = datetime.now().year
    donnees = dict(_PS_BASE, mois=[{
        'prev_reel': 'prev', 'jours_ouverture': 20, 'places': 20, 'amplitude_horaire': 10,
        'taux_occupation': 25, 'taux_horaire': 1.5,
    }] + [{} for _ in range(11)])
    resp = admin_client.post('/api/budget-previsionnel/ps-simulation', json={
        'compte_num': '706000', 'annee': annee, 'type_budget': 'initial',
        'type_ps': 'eaje', 'secteur_id': secteur_id, 'donnees': donnees,
    })
    assert resp.status_code == 200
    # Même total que l'exemple réel équivalent (cf. test_api_ps_simulation_eaje_calcule_et_reporte)
    assert abs(resp.get_json()['total'] - 34908.0) < 0.01


def test_budget_previsionnel_simulateur_mode_par_mois_present(admin_client):
    """Le simulateur expose le basculement saisie/calcul selon le mode du mois."""
    html = admin_client.get('/budget-previsionnel').get_data(as_text=True)
    assert 'psToggleCell(' in html
    assert "prevReel === 'reel'" in html  # calcul inversé selon le mode
    # Nouvelle simulation : mois en prévisionnel par défaut…
    assert "prev_reel:'prev'" in html
    # …mais le repli quand le mode est absent reste « réel » (rétro-compat)
    assert "|| 'reel'" in html
    # Un mois enregistré sans mode est réaligné sur « réel » au chargement,
    # comme le serveur, pour ne pas rouvrir en prévisionnel et écraser les heures.
    assert "s.mois[i].prev_reel = 'reel'" in html


def _load_migration(version_prefix):
    fname = next(f for f in os.listdir(os.path.join(os.path.dirname(__file__), '..', 'migrations'))
                 if f.startswith(version_prefix))
    path = os.path.join(os.path.dirname(__file__), '..', 'migrations', fname)
    spec = importlib.util.spec_from_file_location('mig_' + version_prefix, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_0043_bascule_mois_eaje_en_reel(app, db, sample_users):
    """Les simulations EAJE existantes (mois 'prev' = données réelles) passent en 'reel'."""
    secteur_id = sample_users['secteur_id']
    donnees = {'mois': [
        {'prev_reel': 'prev', 'heures_facturees': 1000, 'participation': 1500},
        {'prev_reel': 'prev', 'heures_facturees': 500, 'participation': 700},
    ]}
    with app.app_context():
        db.execute(
            "INSERT INTO budget_ps_simulations (compte_num, annee, secteur_id, type_budget, "
            "type_ps, donnees, total) VALUES ('706000', 2025, ?, 'initial', 'eaje', ?, 0)",
            (secteur_id, json.dumps(donnees)),
        )
        db.commit()
        _load_migration('0043').upgrade(db)
        row = db.execute(
            "SELECT donnees FROM budget_ps_simulations WHERE compte_num='706000'"
        ).fetchone()
    mois = json.loads(row['donnees'])['mois']
    assert all(m['prev_reel'] == 'reel' for m in mois)


# ============================================================
# Simulateurs PS ALSH (PERISCO / EXTRASCO)
# ============================================================

def test_api_ps_comptes_accepte_types_alsh(admin_client):
    """Le paramétrage accepte les deux types ALSH et refuse l'ancien 'alsh'."""
    for t in ('alsh_perisco', 'alsh_extrasco'):
        r = admin_client.post('/api/budget-previsionnel/ps-comptes',
                              json={'compte_num': '7066' + t[-1], 'type_ps': t})
        assert r.status_code == 200 and r.get_json().get('success') is True
    r = admin_client.post('/api/budget-previsionnel/ps-comptes',
                          json={'compte_num': '706999', 'type_ps': 'alsh'})
    assert r.status_code == 400


def test_compute_ps_alsh_extrasco_unitaire():
    """heures = enfants×jours×heures/jour ; PS = heures×taux×régime ; + complément."""
    res = _compute_ps_alsh_extrasco({
        'taux_ps': 0.624, 'taux_compl_inclusif': 3.90, 'taux_regime': 100,
        'cellules': [{'periode_id': 1, 'tranche_id': 1, 'prev_reel': 'prev',
                      'enfants': 20, 'heures_jour': 8}],
        'heures_handicap': 100,
    }, {1: 10})
    assert abs(res['total_ps'] - 998.40) < 0.01
    assert abs(res['compl_inclusif'] - 390.0) < 0.01
    assert abs(res['total'] - 1388.40) < 0.01


def test_compute_ps_alsh_extrasco_mode_reel():
    """En mode réel, les heures sont saisies directement."""
    res = _compute_ps_alsh_extrasco({
        'taux_ps': 0.624, 'taux_regime': 100,
        'cellules': [{'periode_id': 1, 'tranche_id': 1, 'prev_reel': 'reel',
                      'enfants': 999, 'heures_jour': 999, 'heures_reel': 500}],
    }, {1: 10})
    assert abs(res['total_heures'] - 500) < 0.01
    assert abs(res['total_ps'] - 312.0) < 0.01


def test_compute_ps_alsh_perisco_initial_et_actualise():
    base = {'taux_ps': 0.59, 'taux_compl_inclusif': 3.90,
            'cellules': [{'tranche_id': 1, 'enfants': 15, 'heures_jour': 3, 'enfants_handicap': 1}]}
    ini = _compute_ps_alsh_perisco(base, 33, 0, 'initial')
    assert abs(ini['total'] - 1262.25) < 0.01
    actu = _compute_ps_alsh_perisco({
        **base, 'cellules': [{'tranche_id': 1, 'enfants': 15, 'heures_jour': 3,
                              'enfants_handicap': 1, 'heures_reel': 800, 'heures_handicap_reel': 50}]
    }, 33, 10, 'actualise')
    # 800 + 15*10*3=450 -> 1250h ; PS=737.50 ; handicap 50 + 1*10*3=30 -> 80h ; compl=312 ; total=1049.50
    assert abs(actu['total'] - 1049.50) < 0.01


def _setup_alsh_calendrier(db, annee):
    """Crée une période de vacances de 2 semaines (10 jours ouvrés) et l'année."""
    db.execute(
        "INSERT INTO periodes_vacances (nom, date_debut, date_fin) VALUES (?, ?, ?)",
        ('Vacances test', f'{annee}-02-09', f'{annee}-02-20')  # lun 9 -> ven 20
    )
    pid = db.execute("SELECT id FROM periodes_vacances ORDER BY id DESC LIMIT 1").fetchone()['id']
    db.execute("INSERT INTO alsh_tranches_age (libelle, ordre) VALUES ('6-8 ans', 1)")
    tid = db.execute("SELECT id FROM alsh_tranches_age ORDER BY id DESC LIMIT 1").fetchone()['id']
    db.commit()
    return pid, tid


def test_api_ps_alsh_context(app, db, admin_client):
    annee = 2026
    with app.app_context():
        pid, tid = _setup_alsh_calendrier(db, annee)
    data = admin_client.get(f'/api/budget-previsionnel/ps-alsh-context?annee={annee}').get_json()
    periode = next(p for p in data['periodes'] if p['id'] == pid)
    assert periode['jours_ouvres'] == 10  # 2 semaines pleines, sans férié
    assert any(t['id'] == tid for t in data['tranches'])
    assert data['mercredis_count'] > 0
    assert data['jours_initial'] == max(data['mercredis_count'] - data['mercredis_deduction'], 0)


def test_api_ps_simulation_alsh_extrasco_calcule_et_reporte(app, db, admin_client, sample_users):
    secteur_id = sample_users['secteur_id']
    annee = 2026
    with app.app_context():
        pid, tid = _setup_alsh_calendrier(db, annee)
    donnees = {
        'taux_ps': 0.624, 'taux_compl_inclusif': 3.90, 'taux_regime': 100,
        'heures_handicap': 100,
        'cellules': [{'periode_id': pid, 'tranche_id': tid, 'prev_reel': 'prev',
                      'enfants': 20, 'heures_jour': 8}],
    }
    r = admin_client.post('/api/budget-previsionnel/ps-simulation', json={
        'compte_num': '706600', 'annee': annee, 'type_budget': 'initial',
        'type_ps': 'alsh_extrasco', 'secteur_id': secteur_id, 'donnees': donnees
    })
    assert r.status_code == 200
    # heures=20*10*8=1600 ; PS=998.40 ; compl=390 ; total=1388.40
    assert abs(r.get_json()['total'] - 1388.40) < 0.01
    row = db.execute('''
        SELECT valeur_def FROM budget_prev_saisies
        WHERE type_budget='initial' AND annee=? AND secteur_id=? AND compte_num='706600'
    ''', (annee, secteur_id)).fetchone()
    assert row is not None and abs(row['valeur_def'] - 1388.40) < 0.01


def test_api_ps_simulation_alsh_perisco_initial(app, db, admin_client, sample_users):
    secteur_id = sample_users['secteur_id']
    annee = 2026
    with app.app_context():
        _setup_alsh_calendrier(db, annee)
        tid = db.execute("SELECT id FROM alsh_tranches_age ORDER BY id DESC LIMIT 1").fetchone()['id']
        # jours_initial dépend du calendrier réel ; on le récupère via le contexte
    ctx = admin_client.get(f'/api/budget-previsionnel/ps-alsh-context?annee={annee}').get_json()
    jours = ctx['jours_initial']
    donnees = {'taux_ps': 0.59, 'taux_compl_inclusif': 3.90,
               'cellules': [{'tranche_id': tid, 'enfants': 15, 'heures_jour': 3, 'enfants_handicap': 1}]}
    r = admin_client.post('/api/budget-previsionnel/ps-simulation', json={
        'compte_num': '706700', 'annee': annee, 'type_budget': 'initial',
        'type_ps': 'alsh_perisco', 'secteur_id': secteur_id, 'donnees': donnees
    })
    assert r.status_code == 200
    expected = (15 * jours * 3) * 0.59 + (1 * jours * 3) * 3.90
    assert abs(r.get_json()['total'] - round(expected, 2)) < 0.02


def test_perisco_deduction_restant_selon_date_arrete():
    """PERISCO actualisé : 5 jours déduits avant fin août, 1 jour fin août ou après."""
    from blueprints.budget import _perisco_deduction_restant
    assert _perisco_deduction_restant(2026, '2026-06-30') == 5
    assert _perisco_deduction_restant(2026, '2026-08-30') == 5
    assert _perisco_deduction_restant(2026, '2026-08-31') == 1
    assert _perisco_deduction_restant(2026, '2026-09-15') == 1


def test_suppression_tranche_bloquee_si_utilisee_par_simulation_ps(app, db, admin_client, sample_users):
    """Une tranche d'âge référencée par une simulation PS ALSH ne peut être supprimée
    (les tranches sont partagées avec Analyse ALSH)."""
    secteur_id = sample_users['secteur_id']
    with app.app_context():
        db.execute("INSERT INTO alsh_tranches_age (libelle, ordre) VALUES ('3-5 ans', 1)")
        tid = db.execute("SELECT id FROM alsh_tranches_age ORDER BY id DESC LIMIT 1").fetchone()['id']
        db.commit()
    admin_client.post('/api/budget-previsionnel/ps-simulation', json={
        'compte_num': '706750', 'annee': 2026, 'type_budget': 'initial',
        'type_ps': 'alsh_perisco', 'secteur_id': secteur_id,
        'donnees': {'cellules': [{'tranche_id': tid, 'enfants': 10, 'heures_jour': 3}]}
    })
    resp = admin_client.delete(f'/api/alsh/tranches-age/{tid}')
    assert resp.status_code == 400
    with app.app_context():
        still = db.execute("SELECT COUNT(*) FROM alsh_tranches_age WHERE id = ?", (tid,)).fetchone()[0]
    assert still == 1


# ============================================================
# Simulateur de paie (masse salariale)
# ============================================================

def _setup_paie_secteur(db, annee):
    """Secteur + 1 CDI actif + comptes 641/645 + FEC N-1 pour le prorata."""
    db.execute("INSERT INTO secteurs (nom, type_secteur) VALUES ('Paie test','administratif')")
    sid = db.execute("SELECT id FROM secteurs WHERE nom='Paie test'").fetchone()['id']
    db.execute("INSERT INTO users (nom,prenom,login,password,profil,actif,secteur_id,date_entree,pesee) "
               "VALUES ('Doe','Jane','jdoe_paie','x','salarie',1,?,?,0)", (sid, f'{annee-3}-01-01'))
    uid = db.execute("SELECT id FROM users WHERE login='jdoe_paie'").fetchone()['id']
    db.execute("INSERT INTO contrats (user_id,type_contrat,date_debut,date_fin) VALUES (?, 'CDI', ?, NULL)",
               (uid, f'{annee-3}-01-01'))
    db.execute("INSERT INTO comptabilite_comptes (compte_num,libelle,secteur_id) VALUES ('641000','Brut',?)", (sid,))
    db.execute("INSERT INTO comptabilite_comptes (compte_num,libelle,secteur_id) VALUES ('645000','Cotis',?)", (sid,))
    db.execute("INSERT INTO bilan_fec_imports (fichier_nom,annee,nb_ecritures) VALUES ('f',?,2)", (annee - 1,))
    imp = db.execute("SELECT id FROM bilan_fec_imports ORDER BY id DESC LIMIT 1").fetchone()['id']
    db.execute("INSERT INTO bilan_fec_donnees (compte_num,annee,mois,montant,import_id) VALUES ('641000',?,1,100000,?)", (annee - 1, imp))
    db.execute("INSERT INTO bilan_fec_donnees (compte_num,annee,mois,montant,import_id) VALUES ('645000',?,1,40000,?)", (annee - 1, imp))
    db.commit()
    return sid, uid


def test_paie_context_liste_employes(app, db, admin_client):
    annee = 2026
    with app.app_context():
        sid, uid = _setup_paie_secteur(db, annee)
    data = admin_client.get(
        f'/api/budget-previsionnel/paie-context?annee={annee}&secteur_id={sid}&compte_num=641000&type_budget=initial'
    ).get_json()
    emp = next(e for e in data['employes'] if e['id'] == uid)
    assert emp['type_contrat'] == 'CDI'
    assert emp['anciennete'] == 3
    assert emp['mois_debut'] == 1 and emp['mois_fin'] == 12


def test_paie_simulation_calcule_et_reporte(app, db, admin_client):
    annee = 2026
    with app.app_context():
        sid, uid = _setup_paie_secteur(db, annee)
    donnees = {'salaire_socle': 23000, 'valeur_point': 55,
               'employes': {str(uid): {'pesee': 0, 'nouvelle_pesee': '', 'anciennete': 0, 'competence': 0}},
               'ajouts': [], 'fermetures': []}
    r = admin_client.post('/api/budget-previsionnel/paie-simulation', json={
        'annee': annee, 'secteur_id': sid, 'type_budget': 'initial',
        'compte_num': '641000', 'donnees': donnees})
    assert r.status_code == 200
    data = r.get_json()
    assert abs(data['total'] - 23000.0) < 0.01  # brut annuel = 12 × 23000/12
    with app.app_context():
        d641 = db.execute("SELECT valeur_def FROM budget_prev_saisies WHERE compte_num='641000' "
                          "AND annee=? AND secteur_id=? AND type_budget='initial'", (annee, sid)).fetchone()
        d645 = db.execute("SELECT valeur_def FROM budget_prev_saisies WHERE compte_num='645000' "
                          "AND annee=? AND secteur_id=? AND type_budget='initial'", (annee, sid)).fetchone()
    assert d641 and abs(d641['valeur_def'] - 23000.0) < 0.01
    # prorata 645 = 23000 × 40000/100000 = 9200
    assert d645 and abs(d645['valeur_def'] - 9200.0) < 0.01


def test_paie_simulation_persiste_pesee_competence(app, db, admin_client):
    annee = 2026
    with app.app_context():
        sid, uid = _setup_paie_secteur(db, annee)
    donnees = {'employes': {str(uid): {'pesee': 120, 'competence': 5, 'anciennete': 3, 'nouvelle_pesee': ''}},
               'ajouts': [], 'fermetures': []}
    admin_client.post('/api/budget-previsionnel/paie-simulation', json={
        'annee': annee, 'secteur_id': sid, 'type_budget': 'initial', 'compte_num': '641000', 'donnees': donnees})
    with app.app_context():
        u = db.execute("SELECT pesee, competence FROM users WHERE id=?", (uid,)).fetchone()
    assert u['pesee'] == 120 and u['competence'] == 5


def test_paie_simulation_refuse_responsable(resp_client, sample_users):
    sid = sample_users['secteur_id']
    r = resp_client.post('/api/budget-previsionnel/paie-simulation', json={
        'annee': 2026, 'secteur_id': sid, 'type_budget': 'initial', 'compte_num': '641000', 'donnees': {}})
    assert r.status_code == 403


def test_budget_649_exclu_du_prorata_salaire(app, db, admin_client):
    """Un compte 649 n'est plus traité comme salaire (exclu du prorata du brut)."""
    from blueprints.budget import _compute_budget_previsionnel
    annee = 2026
    with app.app_context():
        db.execute("INSERT INTO secteurs (nom, type_secteur) VALUES ('S649','administratif')")
        sid = db.execute("SELECT id FROM secteurs WHERE nom='S649'").fetchone()['id']
        db.execute("INSERT INTO comptabilite_comptes (compte_num,libelle,secteur_id) VALUES ('641000','Brut',?)", (sid,))
        db.execute("INSERT INTO comptabilite_comptes (compte_num,libelle,secteur_id) VALUES ('649000','Divers',?)", (sid,))
        db.execute("INSERT INTO bilan_fec_imports (fichier_nom,annee,nb_ecritures) VALUES ('f',?,2)", (annee - 1,))
        imp = db.execute("SELECT id FROM bilan_fec_imports ORDER BY id DESC LIMIT 1").fetchone()['id']
        db.execute("INSERT INTO bilan_fec_donnees (compte_num,annee,mois,montant,import_id) VALUES ('641000',?,1,100000,?)", (annee - 1, imp))
        db.execute("INSERT INTO bilan_fec_donnees (compte_num,annee,mois,montant,import_id) VALUES ('649000',?,1,10000,?)", (annee - 1, imp))
        db.commit()
        data = _compute_budget_previsionnel(db, 'initial', annee, sid)
    rows = {r['compte_num']: r for r in data['rows']}
    assert rows['641000']['is_salary'] is True
    assert rows['649000']['is_salary'] is False
    assert '649000' not in data['salary_ratios']


def test_paie_reel_641_restreint_au_secteur(app, db):
    """Le réel du 641 (budget actualisé) est restreint au périmètre du secteur
    quand plusieurs secteurs partagent le même compte (P1)."""
    from blueprints.budget import _paie_reel_641
    annee = 2026
    with app.app_context():
        db.execute("INSERT INTO secteurs (nom, type_secteur) VALUES ('SA','administratif')")
        sa = db.execute("SELECT id FROM secteurs WHERE nom='SA'").fetchone()['id']
        db.execute("INSERT INTO secteurs (nom, type_secteur) VALUES ('SB','administratif')")
        sb = db.execute("SELECT id FROM secteurs WHERE nom='SB'").fetchone()['id']
        db.execute("INSERT INTO budget_prev_config_codes (code_analytique, secteur_id) VALUES ('ANA-A', ?)", (sa,))
        db.execute("INSERT INTO budget_prev_config_codes (code_analytique, secteur_id) VALUES ('ANA-B', ?)", (sb,))
        db.execute("INSERT INTO bilan_fec_imports (fichier_nom,annee,nb_ecritures) VALUES ('f',?,1)", (annee,))
        imp = db.execute("SELECT id FROM bilan_fec_imports ORDER BY id DESC LIMIT 1").fetchone()['id']
        for m in (1, 2, 3):
            db.execute("INSERT INTO bilan_fec_donnees (compte_num,code_analytique,annee,mois,montant,import_id) "
                       "VALUES ('641000','ANA-A',?,?,1000,?)", (annee, m, imp))
        for m in (1, 2, 3, 4, 5, 6):
            db.execute("INSERT INTO bilan_fec_donnees (compte_num,code_analytique,annee,mois,montant,import_id) "
                       "VALUES ('641000','ANA-B',?,?,2000,?)", (annee, m, imp))
        db.commit()
        la, ta = _paie_reel_641(db, sa, '641000', annee)
        lb, tb = _paie_reel_641(db, sb, '641000', annee)
    assert (la, ta) == (3, 3000.0)
    assert (lb, tb) == (6, 12000.0)


def test_paie_employes_ignore_contrat_annee_suivante(app, db):
    """Un salarié avec un contrat valide sur l'année ET un contrat futur déjà
    saisi reste pris dans la simulation (P2)."""
    from blueprints.budget import _paie_employes_secteur
    annee = 2026
    with app.app_context():
        db.execute("INSERT INTO secteurs (nom, type_secteur) VALUES ('SC','administratif')")
        sid = db.execute("SELECT id FROM secteurs WHERE nom='SC'").fetchone()['id']
        db.execute("INSERT INTO users (nom,prenom,login,password,profil,actif,secteur_id,date_entree) "
                   "VALUES ('X','Y','xy_paie','x','salarie',1,?,?)", (sid, f'{annee-1}-01-01'))
        uid = db.execute("SELECT id FROM users WHERE login='xy_paie'").fetchone()['id']
        db.execute("INSERT INTO contrats (user_id,type_contrat,date_debut,date_fin) VALUES (?, 'CDD', ?, ?)",
                   (uid, f'{annee}-01-01', f'{annee}-12-31'))
        db.execute("INSERT INTO contrats (user_id,type_contrat,date_debut,date_fin) VALUES (?, 'CDI', ?, NULL)",
                   (uid, f'{annee+1}-01-01'))
        db.commit()
        employes = _paie_employes_secteur(db, sid, annee)
    e = next((x for x in employes if x['id'] == uid), None)
    assert e is not None
    assert e['type_contrat'] == 'CDD'
    assert e['mois_debut'] == 1 and e['mois_fin'] == 12


def test_paie_direction_rattachee_au_secteur_administratif(app, db):
    """La direction (profil directeur) apparaît dans le secteur administratif
    principal, et pas dans un secteur opérationnel."""
    from blueprints.budget import _paie_employes_secteur
    annee = 2026
    with app.app_context():
        db.execute("INSERT INTO secteurs (nom, type_secteur) VALUES ('Admin','administratif')")
        admin_sid = db.execute("SELECT id FROM secteurs WHERE nom='Admin'").fetchone()['id']
        db.execute("INSERT INTO secteurs (nom, type_secteur) VALUES ('Creche','creche')")
        op_sid = db.execute("SELECT id FROM secteurs WHERE nom='Creche'").fetchone()['id']
        db.execute("INSERT INTO users (nom,prenom,login,password,profil,actif,secteur_id,date_entree) "
                   "VALUES ('Dir','Ecteur','dir_paie','x','directeur',1,NULL,?)", (f'{annee-5}-01-01',))
        did = db.execute("SELECT id FROM users WHERE login='dir_paie'").fetchone()['id']
        db.execute("INSERT INTO contrats (user_id,type_contrat,date_debut,date_fin) VALUES (?, 'CDI', ?, NULL)",
                   (did, f'{annee-5}-01-01'))
        db.commit()
        admin_emps = _paie_employes_secteur(db, admin_sid, annee)
        op_emps = _paie_employes_secteur(db, op_sid, annee)
    assert any(e['id'] == did for e in admin_emps)
    assert not any(e['id'] == did for e in op_emps)


def test_paie_direction_assignee_a_son_secteur(app, db):
    """Un directeur RATTACHÉ à un secteur (ex. « Pilotage ») est compté dans CE
    secteur pour le budget, et n'est plus rattaché d'office à l'administratif
    principal (pas de double comptage)."""
    from blueprints.budget import _paie_employes_secteur
    annee = 2026
    with app.app_context():
        # Deux secteurs administratifs : 'Admin' (id le plus petit = principal)
        # et 'Pilotage'. La direction est explicitement rattachée à Pilotage.
        db.execute("INSERT INTO secteurs (nom, type_secteur) VALUES ('Admin','administratif')")
        admin_sid = db.execute("SELECT id FROM secteurs WHERE nom='Admin'").fetchone()['id']
        db.execute("INSERT INTO secteurs (nom, type_secteur) VALUES ('Pilotage','administratif')")
        pil_sid = db.execute("SELECT id FROM secteurs WHERE nom='Pilotage'").fetchone()['id']
        db.execute("INSERT INTO users (nom,prenom,login,password,profil,actif,secteur_id,date_entree) "
                   "VALUES ('Dir','Pil','dir_pil','x','directeur',1,?,?)", (pil_sid, f'{annee-5}-01-01'))
        did = db.execute("SELECT id FROM users WHERE login='dir_pil'").fetchone()['id']
        db.execute("INSERT INTO contrats (user_id,type_contrat,date_debut,date_fin) VALUES (?, 'CDI', ?, NULL)",
                   (did, f'{annee-5}-01-01'))
        db.commit()
        admin_emps = _paie_employes_secteur(db, admin_sid, annee)
        pil_emps = _paie_employes_secteur(db, pil_sid, annee)
    # Compté dans son secteur (Pilotage)...
    assert any(e['id'] == did for e in pil_emps)
    # ... et plus dans l'administratif principal (pas de double comptage).
    assert not any(e['id'] == did for e in admin_emps)


def test_paie_maintien_ajoute_au_brut(app, db, admin_client):
    """Le maintien de salaire s'ajoute au brut mensuel et est persisté sur la fiche."""
    annee = 2026
    with app.app_context():
        sid, uid = _setup_paie_secteur(db, annee)
    donnees = {'salaire_socle': 23000, 'valeur_point': 55,
               'employes': {str(uid): {'pesee': 0, 'nouvelle_pesee': '', 'anciennete': 0,
                                       'competence': 0, 'maintien': 100}},
               'ajouts': [], 'fermetures': []}
    r = admin_client.post('/api/budget-previsionnel/paie-simulation', json={
        'annee': annee, 'secteur_id': sid, 'type_budget': 'initial', 'compte_num': '641000', 'donnees': donnees})
    assert r.status_code == 200
    assert abs(r.get_json()['total'] - 24200.0) < 0.01  # 23000 + 12 × 100
    with app.app_context():
        u = db.execute("SELECT maintien FROM users WHERE id=?", (uid,)).fetchone()
    assert abs(u['maintien'] - 100) < 0.01


def test_paie_maintien_vide_coherent(app, db, admin_client):
    """Maintien vidé dans le simulateur : report ET fiche utilisent 0 (et non
    l'ancienne valeur), de façon cohérente (revue P2)."""
    annee = 2026
    with app.app_context():
        sid, uid = _setup_paie_secteur(db, annee)
        db.execute("UPDATE users SET maintien = 200 WHERE id = ?", (uid,))
        db.commit()
    donnees = {'salaire_socle': 23000, 'valeur_point': 55,
               'employes': {str(uid): {'pesee': 0, 'nouvelle_pesee': '', 'anciennete': 0,
                                       'competence': 0, 'maintien': ''}},
               'ajouts': [], 'fermetures': []}
    r = admin_client.post('/api/budget-previsionnel/paie-simulation', json={
        'annee': annee, 'secteur_id': sid, 'type_budget': 'initial', 'compte_num': '641000', 'donnees': donnees})
    assert r.status_code == 200
    assert abs(r.get_json()['total'] - 23000.0) < 0.01  # maintien vidé -> 0
    with app.app_context():
        u = db.execute("SELECT maintien FROM users WHERE id=?", (uid,)).fetchone()
    assert abs((u['maintien'] or 0) - 0) < 0.01


def test_init_db_reajoute_colonnes_paie_si_absentes(app, db):
    """init_db ré-ajoute users.competence et users.maintien si elles manquent
    (auto-réparation au démarrage, sans migration manuelle). Sinon la requête
    des salariés du simulateur de paie échoue et aucun salarié n'apparaît."""
    import database
    with app.app_context():
        db.execute("ALTER TABLE users DROP COLUMN maintien")
        db.execute("ALTER TABLE users DROP COLUMN competence")
        db.commit()
        cols = [r[1] for r in db.execute("PRAGMA table_info(users)").fetchall()]
        assert 'maintien' not in cols and 'competence' not in cols
        database.init_db()
        cols = [r[1] for r in db.execute("PRAGMA table_info(users)").fetchall()]
    assert 'maintien' in cols
    assert 'competence' in cols


def test_paie_anciennete_depuis_contrat_directeur_sans_date_entree(app, db):
    """L'ancienneté vient de la date de début du contrat, pas de users.date_entree.
    Un directeur sans date_entree mais avec un contrat a une ancienneté correcte."""
    from blueprints.budget import _paie_employes_secteur
    annee = 2026
    with app.app_context():
        db.execute("INSERT INTO secteurs (nom, type_secteur) VALUES ('Admin','administratif')")
        sid = db.execute("SELECT id FROM secteurs WHERE nom='Admin'").fetchone()['id']
        db.execute("INSERT INTO users (nom,prenom,login,password,profil,actif,secteur_id,date_entree) "
                   "VALUES ('Dir','X','dir_anc','x','directeur',1,NULL,NULL)")
        did = db.execute("SELECT id FROM users WHERE login='dir_anc'").fetchone()['id']
        db.execute("INSERT INTO contrats (user_id,type_contrat,date_debut,date_fin) VALUES (?, 'CDI', ?, NULL)",
                   (did, f'{annee-4}-01-01'))
        db.commit()
        employes = _paie_employes_secteur(db, sid, annee)
    e = next(x for x in employes if x['id'] == did)
    assert e['anciennete'] == 4


def test_paie_anciennete_cdd_depuis_son_contrat(app, db):
    """Pour un CDD, l'ancienneté est calculée depuis le début de SON contrat,
    en ignorant une date_entree plus ancienne."""
    from blueprints.budget import _paie_employes_secteur
    annee = 2026
    with app.app_context():
        db.execute("INSERT INTO secteurs (nom, type_secteur) VALUES ('Op','creche')")
        sid = db.execute("SELECT id FROM secteurs WHERE nom='Op'").fetchone()['id']
        db.execute("INSERT INTO users (nom,prenom,login,password,profil,actif,secteur_id,date_entree) "
                   "VALUES ('C','D','cdd_anc','x','salarie',1,?,?)", (sid, f'{annee-6}-01-01'))
        uid = db.execute("SELECT id FROM users WHERE login='cdd_anc'").fetchone()['id']
        db.execute("INSERT INTO contrats (user_id,type_contrat,date_debut,date_fin) VALUES (?, 'CDD', ?, ?)",
                   (uid, f'{annee}-01-01', f'{annee}-08-31'))
        db.commit()
        employes = _paie_employes_secteur(db, sid, annee)
    e = next(x for x in employes if x['id'] == uid)
    assert e['anciennete'] == 0  # depuis le contrat (cette année), pas 6 (date_entree)


def test_paie_employes_recupere_temps_hebdo_du_contrat(app, db):
    """Le temps de travail hebdomadaire est repris du contrat."""
    from blueprints.budget import _paie_employes_secteur
    annee = 2026
    with app.app_context():
        sid, uid = _setup_paie_secteur(db, annee)
        db.execute("UPDATE contrats SET temps_hebdo = 28 WHERE user_id = ?", (uid,))
        db.commit()
        employes = _paie_employes_secteur(db, sid, annee)
    e = next(x for x in employes if x['id'] == uid)
    assert e['temps_hebdo'] == 28


def test_paie_simulation_proratise_temps_partiel(app, db, admin_client):
    """Le brut d'un salarié à temps partiel est proratisé (temps hebdo / temps plein)."""
    annee = 2026
    with app.app_context():
        sid, uid = _setup_paie_secteur(db, annee)
        db.execute("UPDATE contrats SET temps_hebdo = 28 WHERE user_id = ?", (uid,))
        db.commit()
    donnees = {'salaire_socle': 23000, 'valeur_point': 55, 'temps_plein': 35,
               'employes': {str(uid): {'pesee': 0, 'nouvelle_pesee': '', 'anciennete': 0,
                                       'competence': 0, 'maintien': 0, 'temps_hebdo': 28}},
               'ajouts': [], 'fermetures': []}
    r = admin_client.post('/api/budget-previsionnel/paie-simulation', json={
        'annee': annee, 'secteur_id': sid, 'type_budget': 'initial', 'compte_num': '641000', 'donnees': donnees})
    assert r.status_code == 200
    assert abs(r.get_json()['total'] - 18400.0) < 0.01  # 23000 × 28/35


def test_paie_temps_hebdo_absent_temps_plein(app, db, admin_client):
    """Sans temps hebdo renseigné, le salarié est considéré à temps plein."""
    annee = 2026
    with app.app_context():
        sid, uid = _setup_paie_secteur(db, annee)  # contrat sans temps_hebdo (NULL)
    donnees = {'salaire_socle': 23000, 'valeur_point': 55, 'temps_plein': 35,
               'employes': {str(uid): {'pesee': 0, 'nouvelle_pesee': '', 'anciennete': 0,
                                       'competence': 0, 'maintien': 0, 'temps_hebdo': ''}},
               'ajouts': [], 'fermetures': []}
    r = admin_client.post('/api/budget-previsionnel/paie-simulation', json={
        'annee': annee, 'secteur_id': sid, 'type_budget': 'initial', 'compte_num': '641000', 'donnees': donnees})
    assert r.status_code == 200
    assert abs(r.get_json()['total'] - 23000.0) < 0.01
