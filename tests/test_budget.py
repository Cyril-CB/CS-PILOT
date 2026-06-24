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
