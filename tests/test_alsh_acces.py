"""Accès ciblé du responsable enfance, avec saisie NOÉ sans gestion analytique."""
import re

import pytest


URL = '/analyse-alsh'
ANNEE = 2026
LECTURES = (
    '/api/alsh/config', '/api/alsh/noe?annee=2026',
    '/api/alsh/tableau?annee=2026', '/api/alsh/comparaison?annee=2026',
    '/api/alsh/charges-detail?annee=2026&codes=ALSH-TEST',
)
CONFIGURATION = (
    ('GET', '/api/alsh/codes?annee=2026'),
    ('GET', '/api/alsh/codes-disponibles?annee=2026'),
    ('POST', '/api/alsh/codes'), ('POST', '/api/alsh/tarif-repartition'),
    ('POST', '/api/alsh/tranches-age'), ('DELETE', '/api/alsh/tranches-age/999999'),
    ('POST', '/api/alsh/periodes'), ('DELETE', '/api/alsh/periodes/999999'),
)


@pytest.fixture
def responsable_enfance(resp_client, db, sample_users):
    db.execute("UPDATE secteurs SET nom='Enfance', type_secteur='accueil_loisirs' WHERE id=?",
               (sample_users['secteur_id'],))
    db.commit()
    return resp_client


@pytest.fixture
def cellule_alsh(db):
    tranche = db.execute('SELECT id FROM alsh_tranches_age WHERE active=1 ORDER BY ordre,id').fetchone()[0]
    periode = db.execute("SELECT id FROM alsh_periodes WHERE active=1 AND type='mercredi' ORDER BY ordre,id").fetchone()[0]
    db.execute('INSERT INTO alsh_config_codes(annee,periode_id,tranche_age_id,code1) VALUES(?,?,?,?)',
               (ANNEE, periode, tranche, 'ALSH-TEST'))
    db.executemany('INSERT INTO bilan_fec_donnees(compte_num,libelle,code_analytique,annee,mois,montant) VALUES(?,?,?,?,?,?)', [
        ('601000', 'Charges ALSH fictives', 'ALSH-TEST', ANNEE, 1, 120),
        ('601000', 'Charges hors ALSH fictives', 'AUTRE-SECTEUR', ANNEE, 1, 999),
    ])
    db.commit()
    return {'annee': ANNEE, 'periode_id': periode, 'tranche_age_id': tranche,
            'heures_presence': 25.5, 'nb_enfants': 6}


def _etat(db):
    tables = ('alsh_config_codes', 'alsh_saisie_noe', 'alsh_tranches_age',
              'alsh_periodes', 'bilan_fec_donnees', 'app_settings')
    return {t: [tuple(r) for r in db.execute(f'SELECT * FROM {t} ORDER BY rowid')] for t in tables}


@pytest.mark.parametrize('nom', ['Enfance', 'ENFANCE', ' enfance '])
def test_responsable_enfance_page_menu_et_recherche(responsable_enfance, db, sample_users, nom):
    db.execute('UPDATE secteurs SET nom=? WHERE id=?', (nom, sample_users['secteur_id']))
    db.commit()
    page = responsable_enfance.get(URL, headers={'User-Agent': 'Mozilla/5.0 Mobi'})
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert f'href="{URL}"' in html
    assert 'id="tab-noe"' in html and 'id="tab-config"' not in html
    assert 'id="pane-config"' not in html
    suggestions = responsable_enfance.post('/api/search/suggestions', json={'query': 'analyse alsh'}).json['suggestions']
    assert any(s.get('url') == URL for s in suggestions)
    verdict = responsable_enfance.post('/api/search', json={'query': 'analyse alsh'}).json
    assert verdict['type'] == 'redirect' and verdict['url'] == URL


@pytest.mark.parametrize('url', LECTURES)
def test_responsable_enfance_consulte_les_donnees_alsh(responsable_enfance, cellule_alsh, url):
    response = responsable_enfance.get(url)
    assert response.status_code == 200
    assert response.is_json


def test_responsable_enfance_saisit_noe_sans_modifier_analytique(responsable_enfance, cellule_alsh, db):
    avant = _etat(db)
    response = responsable_enfance.post('/api/alsh/noe', json=cellule_alsh)
    assert response.status_code == 200 and response.json['success'] is True
    row = db.execute('SELECT heures_presence,nb_enfants FROM alsh_saisie_noe').fetchone()
    assert tuple(row) == (25.5, 6)
    apres = _etat(db)
    assert {t: v for t, v in apres.items() if t != 'alsh_saisie_noe'} == {
        t: v for t, v in avant.items() if t != 'alsh_saisie_noe'}
    response = responsable_enfance.get('/api/alsh/noe?annee=2026')
    assert response.json['noe'][0]['heures_presence'] == 25.5


@pytest.mark.parametrize('method,url', CONFIGURATION)
def test_responsable_enfance_ne_modifie_pas_configuration(responsable_enfance, cellule_alsh, db, method, url):
    avant = _etat(db)
    payload = {**cellule_alsh, 'code1': 'INTERDIT', 'libelle': 'Interdit', 'nom': 'Interdit',
               'tarif_repartition_quotients': [{'id': 'qf_0_249', 'pct': 99}]}
    response = responsable_enfance.open(url, method=method, json=payload)
    assert response.status_code == 403
    assert _etat(db) == avant


@pytest.mark.parametrize('nom', ['Famille', 'Petite Enfance', 'Enfance jeunesse', 'Autre accueil de loisirs'])
def test_autres_secteurs_refuses_meme_type_alsh(resp_client, db, sample_users, nom):
    db.execute("UPDATE secteurs SET nom=?, type_secteur='accueil_loisirs' WHERE id=?",
               (nom, sample_users['secteur_id']))
    db.commit()
    assert resp_client.get(URL).status_code == 302
    for url in LECTURES:
        assert resp_client.get(url).status_code == 403
    assert resp_client.post('/api/alsh/noe', json={'profil': 'comptable', 'secteur_id': sample_users['secteur_id']}).status_code == 403
    html = resp_client.get('/dashboard_responsable', headers={'User-Agent': 'Mozilla/5.0 Mobi'}).get_data(as_text=True)
    assert f'href="{URL}"' not in html
    suggestions = resp_client.post('/api/search/suggestions', json={'query': 'analyse alsh'}).json['suggestions']
    assert all(s.get('url') != URL for s in suggestions)
    verdict = resp_client.post('/api/search', json={'query': 'analyse alsh'}).json
    assert verdict.get('url') != URL


@pytest.mark.parametrize('fixture', ['auth_client', 'prestataire_client', 'client'])
def test_autres_profils_et_non_connecte_refuses(request, fixture, db, sample_users):
    db.execute("UPDATE secteurs SET nom='Enfance' WHERE id=?", (sample_users['secteur_id'],))
    db.commit()
    client = request.getfixturevalue(fixture)
    assert client.get(URL).status_code == 302
    for url in LECTURES:
        assert client.get(url).status_code in (302, 403)
    assert client.post('/api/alsh/noe', json={}).status_code in (302, 403)


@pytest.mark.parametrize('changement', ['secteur', 'nom_secteur', 'profil', 'inactif'])
def test_droit_revoque_des_la_requete_suivante(responsable_enfance, db, sample_users, cellule_alsh, changement):
    assert responsable_enfance.get(URL).status_code == 200
    if changement == 'secteur':
        db.execute('UPDATE users SET secteur_id=NULL WHERE id=?', (sample_users['responsable_id'],))
    elif changement == 'nom_secteur':
        db.execute("UPDATE secteurs SET nom='Famille' WHERE id=?", (sample_users['secteur_id'],))
    elif changement == 'profil':
        db.execute("UPDATE users SET profil='salarie' WHERE id=?", (sample_users['responsable_id'],))
    else:
        db.execute('UPDATE users SET actif=0 WHERE id=?', (sample_users['responsable_id'],))
    db.commit()
    avant = _etat(db)
    assert responsable_enfance.post('/api/alsh/noe', json=cellule_alsh).status_code in (302, 403)
    assert _etat(db) == avant
    assert responsable_enfance.get(URL).status_code == 302


def test_detail_charges_limite_aux_codes_alsh_de_l_annee(responsable_enfance, cellule_alsh):
    response = responsable_enfance.get('/api/alsh/charges-detail?annee=2026&codes=ALSH-TEST')
    assert response.status_code == 200
    assert response.json['lignes'][0]['montant_total'] == 120
    for query in ['annee=2026&codes=AUTRE-SECTEUR', 'annee=2026&codes=ALSH-TEST,AUTRE-SECTEUR',
                  'annee=2025&codes=ALSH-TEST']:
        assert responsable_enfance.get('/api/alsh/charges-detail?' + query).status_code == 403


@pytest.mark.parametrize('champ,valeur', [('heures_presence', -1), ('heures_presence', 'NaN'),
                                        ('nb_enfants', -1), ('nb_enfants', 'inf'),
                                        ('periode_id', 999999), ('tranche_age_id', 999999),
                                        ('annee', True), ('periode_id', [1])])
def test_saisie_noe_invalide_sans_ecriture(responsable_enfance, cellule_alsh, db, champ, valeur):
    avant = _etat(db)
    response = responsable_enfance.post('/api/alsh/noe', json={**cellule_alsh, champ: valeur})
    assert response.status_code == 400
    assert _etat(db) == avant


def test_saisie_noe_refuse_un_corps_non_objet(responsable_enfance, db):
    avant = _etat(db)
    assert responsable_enfance.post('/api/alsh/noe', json=['invalide']).status_code == 400
    assert _etat(db) == avant


def test_csrf_actif_pour_saisie_noe(responsable_enfance, cellule_alsh, app, db):
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        from flask import g
        g.pop('csrf_token', None)  # La fixture db conserve le contexte app.
        page = responsable_enfance.get(URL).get_data(as_text=True)
        token = re.search(r'name="csrf-token" content="([^"]+)"', page)[1]
        response = responsable_enfance.post('/api/alsh/noe', json=cellule_alsh, headers={'X-CSRFToken': token})
        assert response.status_code == 200 and response.json['success'] is True
        avant = _etat(db)
        # Un refus CSRF ferme la session : le cas négatif vient après le succès.
        assert responsable_enfance.post('/api/alsh/noe', json=cellule_alsh).status_code == 302
        assert _etat(db) == avant
    finally:
        app.config['WTF_CSRF_ENABLED'] = False


@pytest.mark.parametrize('fixture', ['admin_client', 'comptable_client'])
def test_acces_gestionnaires_existants_conserves(request, fixture):
    client = request.getfixturevalue(fixture)
    page = client.get(URL)
    assert page.status_code == 200 and 'id="tab-config"' in page.get_data(as_text=True)
    assert client.get('/api/alsh/codes?annee=2026').status_code == 200


def test_retrait_du_secteur_entre_controle_et_ecriture_refuse(responsable_enfance, cellule_alsh, db, sample_users, monkeypatch):
    from blueprints import alsh
    original = alsh.get_db
    ouvertures = 0

    def connexion_apres_reaffectation():
        nonlocal ouvertures
        ouvertures += 1
        if ouvertures == 2:
            db.execute('UPDATE users SET secteur_id=NULL WHERE id=?', (sample_users['responsable_id'],))
            db.commit()
        return original()

    monkeypatch.setattr(alsh, 'get_db', connexion_apres_reaffectation)
    avant = _etat(db)
    assert responsable_enfance.post('/api/alsh/noe', json=cellule_alsh).status_code == 403
    assert _etat(db) == avant
