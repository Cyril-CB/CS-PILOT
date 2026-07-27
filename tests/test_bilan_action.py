"""
Tests du module Bilan action (blueprints/bilan_action.py).

Couvre : accès, contexte (salariés/bénévoles/taux/défauts), sauvegarde et
rechargement par action/année/onglet, calcul de la masse salariale et de la
logistique, partage du taux de logistique avec bilan_secteurs, message en
l'absence d'import BI, et export PDF.
"""
import json

import pytest

from database import get_db


def _make_action(app, nom='Action Test'):
    with app.app_context():
        conn = get_db()
        cur = conn.execute("INSERT INTO comptabilite_actions (nom) VALUES (?)", (nom,))
        conn.commit()
        aid = cur.lastrowid
        conn.close()
        return aid


def test_page_accessible_directeur(admin_client):
    r = admin_client.get('/bilan-action')
    assert r.status_code == 200
    # La page a été renommée « Budget action » (mais l'URL /bilan-action reste).
    assert 'Budget action' in r.get_data(as_text=True)


def test_page_refuse_salarie(auth_client):
    # Un salarié ne doit pas accéder à la page (redirection vers le dashboard).
    r = auth_client.get('/bilan-action', follow_redirects=False)
    assert r.status_code in (301, 302)


def test_contexte_defaults(admin_client):
    r = admin_client.get('/api/bilan-action/contexte?annee=2025')
    assert r.status_code == 200
    data = r.get_json()
    assert data['defaults']['socle'] == 23000
    assert data['defaults']['point'] == 55
    assert data['defaults']['temps_plein'] == 35
    assert data['defaults']['taux_charge'] == 27.0
    assert data['defaults']['taux_taxe'] == 4.25
    assert data['comptes_salaire'] == {'brut': '641100', 'taxe': '631100', 'charges': '645100'}
    assert data['import_existe'] is False


def test_contexte_employe_sous_contrat(admin_client, app, sample_users):
    # Un salarié avec un CDI en cours doit apparaître dans la liste.
    with app.app_context():
        conn = get_db()
        conn.execute(
            "INSERT INTO contrats (user_id, type_contrat, date_debut, date_fin, temps_hebdo) "
            "VALUES (?, 'CDI', '2015-01-01', NULL, 35)",
            (sample_users['salarie_id'],)
        )
        conn.commit()
        conn.close()

    r = admin_client.get('/api/bilan-action/contexte?annee=2025')
    data = r.get_json()
    ids = [e['user_id'] for e in data['employes']]
    assert sample_users['salarie_id'] in ids


def test_save_and_load_previsionnel(admin_client, app):
    action_id = _make_action(app)
    # Fixer un taux de logistique global de 10 % pour l'année.
    admin_client.post('/api/bilan-action/taux-logistique', json={
        'annee': 2025, 'taux_site1': 0, 'taux_site2': 0, 'taux_global': 10,
    })

    donnees = {
        'charges_60': [{'compte_num': '601000', 'libelle': 'Achats', 'montant': 1000, 'commentaire': ''}],
        'charges_61': [], 'charges_62': [],
        'produits': [{'compte_num': '706000', 'libelle': 'Prestations', 'montant': 5000, 'commentaire': ''}],
        'salaries': [{
            'user_id': None, 'nom': 'Salarié 1', 'prenom': '',
            'temps_hebdo': 35, 'pesee': 100, 'anciennete': 0, 'competence': 0, 'maintien': 0,
            'heures_action': 100, 'taux_charge': 27, 'taux_taxe': 4.25,
        }],
        'salaire_params': {'socle': 23000, 'point': 55, 'temps_plein': 35},
        'logistique': {'selection': 'global'},
        'benevoles': [{'benevole_id': None, 'nom': 'Paul', 'heures': 10, 'commentaire': 'aide'}],
    }
    r = admin_client.post('/api/bilan-action/save', json={
        'action_id': action_id, 'annee': 2025, 'onglet': 'previsionnel', 'donnees': donnees,
    })
    assert r.status_code == 200
    s = r.get_json()['summary']

    # Masse salariale : coût brut = 28500/1820*100 ≈ 1565.93
    assert s['total_brut'] == pytest.approx(1565.93, abs=0.02)
    assert s['total_charges_sociales'] == pytest.approx(422.80, abs=0.02)
    assert s['total_taxe'] == pytest.approx(66.55, abs=0.02)
    assert s['charges_comptes'] == pytest.approx(1000.0, abs=0.01)
    assert s['produits_total'] == pytest.approx(5000.0, abs=0.01)
    # Total charges = comptes + masse salariale chargée
    assert s['total_charges'] == pytest.approx(1000 + 1565.93 + 422.80 + 66.55, abs=0.05)
    assert s['taux_logistique'] == pytest.approx(10.0, abs=0.01)
    assert s['logistique'] == pytest.approx(s['total_charges'] * 0.10, abs=0.02)
    assert s['resultat_sans'] == pytest.approx(5000 - s['total_charges'], abs=0.02)
    assert s['resultat_avec'] == pytest.approx(s['resultat_sans'] - s['logistique'], abs=0.02)

    # Rechargement.
    r2 = admin_client.get(f'/api/bilan-action/donnees?action_id={action_id}&annee=2025&onglet=previsionnel')
    d2 = r2.get_json()
    assert d2['found'] is True
    assert d2['donnees']['charges_60'][0]['compte_num'] == '601000'
    assert d2['summary']['total_charges'] == pytest.approx(s['total_charges'], abs=0.01)


def test_taux_logistique_partage_avec_bilan_secteurs(admin_client, app):
    admin_client.post('/api/bilan-action/taux-logistique', json={
        'annee': 2027, 'taux_site1': 5, 'taux_site2': 7.5, 'taux_global': 12,
    })
    with app.app_context():
        conn = get_db()
        row = conn.execute('SELECT * FROM bilan_taux_logistique WHERE annee = 2027').fetchone()
        conn.close()
    assert row is not None
    assert row['taux_site1'] == pytest.approx(5)
    assert row['taux_site2'] == pytest.approx(7.5)
    assert row['taux_global'] == pytest.approx(12)


def test_realise_compta_sans_import(admin_client, app):
    action_id = _make_action(app, 'Action Réalisé')
    r = admin_client.get(f'/api/bilan-action/realise-compta?action_id={action_id}&annee=2025')
    assert r.status_code == 200
    data = r.get_json()
    assert data['import_existe'] is False


def test_realise_reporte_previsionnel(admin_client, app):
    action_id = _make_action(app, 'Action Report')
    donnees = {
        'charges_60': [], 'charges_61': [], 'charges_62': [], 'produits': [],
        'salaries': [{'user_id': None, 'nom': 'Salarié 1', 'temps_hebdo': 35,
                      'pesee': 50, 'anciennete': 0, 'competence': 0, 'maintien': 0,
                      'heures_action': 50, 'taux_charge': 27, 'taux_taxe': 4.25}],
        'salaire_params': {'socle': 23000, 'point': 55, 'temps_plein': 35},
        'logistique': {'selection': 'global'},
        'benevoles': [],
    }
    admin_client.post('/api/bilan-action/save', json={
        'action_id': action_id, 'annee': 2025, 'onglet': 'previsionnel', 'donnees': donnees,
    })
    # Le réalisé (non encore enregistré) renvoie le prévisionnel pour report.
    r = admin_client.get(f'/api/bilan-action/donnees?action_id={action_id}&annee=2025&onglet=realise')
    d = r.get_json()
    assert d['found'] is False
    assert d['previsionnel'] is not None
    assert d['previsionnel']['salaries'][0]['nom'] == 'Salarié 1'


def test_export_pdf(admin_client, app):
    action_id = _make_action(app, 'Action PDF')
    donnees = {
        'charges_60': [{'compte_num': '601000', 'libelle': 'Achats', 'montant': 1000, 'commentaire': ''}],
        'charges_61': [], 'charges_62': [],
        'produits': [{'compte_num': '706000', 'libelle': 'Prestations', 'montant': 5000, 'commentaire': ''}],
        'salaries': [{'user_id': None, 'nom': 'Salarié 1', 'temps_hebdo': 35,
                      'pesee': 100, 'anciennete': 0, 'competence': 0, 'maintien': 0,
                      'heures_action': 100, 'taux_charge': 27, 'taux_taxe': 4.25}],
        'salaire_params': {'socle': 23000, 'point': 55, 'temps_plein': 35},
        'logistique': {'selection': 'global'},
        'benevoles': [{'benevole_id': None, 'nom': 'Paul', 'heures': 10, 'commentaire': ''}],
    }
    admin_client.post('/api/bilan-action/save', json={
        'action_id': action_id, 'annee': 2025, 'onglet': 'previsionnel', 'donnees': donnees,
    })
    r = admin_client.get(f'/api/bilan-action/export-pdf?action_id={action_id}&annee=2025&onglet=previsionnel')
    assert r.status_code == 200
    assert r.headers['Content-Type'] == 'application/pdf'
    assert r.get_data()[:4] == b'%PDF'


def test_calc_salarie_prorata_seulement_socle_et_pesee():
    """Mi-temps : le prorata s'applique au socle et à la pesée ; les points
    d'ancienneté et de compétences restent dus à temps plein (même règle que
    le simulateur de paie du budget prévisionnel)."""
    from blueprints.bilan_action import _calc_salarie
    res = _calc_salarie(
        {'temps_hebdo': 17.5, 'pesee': 100, 'anciennete': 10, 'competence': 20,
         'maintien': 0, 'heures_action': 0},
        {'socle': 23000, 'point': 55, 'temps_plein': 35})
    # [(23000 + 100×55) × 0,5 + (10 + 20) × 55] / 12 = 15 900 / 12 = 1 325 €/mois
    assert abs(res['brut_mensuel'] - 1325.0) < 0.01
