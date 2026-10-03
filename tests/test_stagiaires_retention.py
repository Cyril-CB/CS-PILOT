"""La conservation s'applique aussi aux écritures après le passage quotidien."""
from datetime import date
import sqlite3

import pytest

import blueprints.stagiaires as routes
import stagiaires as service


@pytest.fixture(autouse=True)
def jour_deja_traite(monkeypatch):
    today = date(2026, 10, 3)
    monkeypatch.setattr(routes, 'aujourd_hui', lambda: today)
    monkeypatch.setattr(routes, '_horodatage', lambda: '2026-10-03 12:00:00')
    monkeypatch.setattr(routes, '_anonymisation_traitee', today)


def _formulaire(fin='2026-04-03'):
    return {'nom': 'Martin', 'prenom': 'Léa', 'etudes': '3e',
            'etablissement': 'Collège de test', 'tuteur_id': '',
            'date_debut': fin, 'date_fin': fin}


def _creer(db, fin='2026-10-09'):
    row = db.execute(
        '''INSERT INTO stagiaires
           (nom, prenom, etudes, etablissement, date_debut, date_fin)
           VALUES ('Martin', 'Léa', '3e', 'Collège de test', ?, ?)''', (fin, fin))
    db.commit()
    return row.lastrowid


def _messages(client):
    with client.session_transaction() as session:
        return ' '.join(message for _, message in session.get('_flashes', []))


def _verifier_anonyme(row):
    assert row['nom'] == f"Stagiaire-{row['id']}"
    assert row['prenom'] == row['etablissement'] == ''
    assert row['etudes'] == '3e'
    assert row['anonymise_le'] == '2026-10-03 12:00:00'


@pytest.mark.parametrize('fin,anonyme', [
    ('2026-04-02', True), ('2026-04-03', True), ('2026-04-04', False),
    ('2026-10-09', False),
])
def test_creation_applique_la_limite_meme_apres_le_passage_quotidien(
        resp_client, db, fin, anonyme):
    response = resp_client.post('/stagiaires/nouveau', data=_formulaire(fin))
    assert response.status_code == 302
    row = db.execute('SELECT * FROM stagiaires').fetchone()
    if anonyme:
        _verifier_anonyme(row)
        assert response.headers['Location'].endswith(f"/stagiaires/{row['id']}")
        assert 'enregistrée et anonymisée' in _messages(resp_client)
        assert 'Indiquez maintenant' not in _messages(resp_client)
    else:
        assert row['nom'] == 'Martin'
        assert row['anonymise_le'] is None
        assert response.headers['Location'].endswith('#emploi-du-temps')
        assert 'Indiquez maintenant' in _messages(resp_client)


@pytest.mark.parametrize('fin,anonyme', [('2026-04-03', True), ('2026-04-04', False)])
def test_modifier_date_applique_la_limite_et_retire_les_creneaux(
        resp_client, db, sample_users, fin, anonyme):
    stagiaire_id = _creer(db)
    db.execute('''INSERT INTO stagiaires_creneaux
                  (stagiaire_id, date, demi_journee, secteur_id)
                  VALUES (?, '2026-10-09', 'matin', ?)''',
               (stagiaire_id, sample_users['secteur_id']))
    db.commit()
    response = resp_client.post(f'/stagiaires/{stagiaire_id}/informations',
                                data=_formulaire(fin))
    assert response.status_code == 302
    row = db.execute('SELECT * FROM stagiaires WHERE id = ?', (stagiaire_id,)).fetchone()
    assert row['date_fin'] == fin
    assert db.execute('SELECT COUNT(*) FROM stagiaires_creneaux').fetchone()[0] == 0
    assert '1 demi-journée' in _messages(resp_client)
    if anonyme:
        _verifier_anonyme(row)
        assert 'enregistrée et anonymisée' in _messages(resp_client)
        assert service.anonymiser_stages_termines(db, date(2026, 10, 3), 'autre') == 0
        db.commit()
        assert db.execute('SELECT anonymise_le FROM stagiaires').fetchone()[0] == row['anonymise_le']
        # La correction de date ne permet pas ensuite de réidentifier la fiche.
        response = resp_client.post(f'/stagiaires/{stagiaire_id}/informations',
                                    data=_formulaire('2026-10-09'))
        assert response.status_code == 302
        _verifier_anonyme(db.execute('SELECT * FROM stagiaires').fetchone())
    else:
        assert row['nom'] == 'Martin'
        assert row['anonymise_le'] is None
        assert 'enregistrée et anonymisée' not in _messages(resp_client)


@pytest.mark.parametrize('operation', ['creation', 'modification'])
def test_echec_anonymisation_annule_toute_lecriture(
        resp_client, db, sample_users, monkeypatch, operation):
    stagiaire_id = _creer(db)
    db.execute('''INSERT INTO stagiaires_creneaux
                  (stagiaire_id, date, demi_journee, secteur_id)
                  VALUES (?, '2026-10-09', 'matin', ?)''',
               (stagiaire_id, sample_users['secteur_id']))
    db.commit()
    avant = tuple(db.execute('SELECT * FROM stagiaires').fetchone())
    anonymiser = service.anonymiser_stages_termines

    def echouer_apres_effacement(conn, today, horodatage):
        anonymiser(conn, today, horodatage)
        raise sqlite3.OperationalError('échec simulé')

    monkeypatch.setattr(service, 'anonymiser_stages_termines', echouer_apres_effacement)
    url = ('/stagiaires/nouveau' if operation == 'creation'
           else f'/stagiaires/{stagiaire_id}/informations')
    response = resp_client.post(url, data=_formulaire())
    assert response.status_code == 503
    assert [tuple(row) for row in db.execute('SELECT * FROM stagiaires')] == [avant]
    assert db.execute('SELECT COUNT(*) FROM stagiaires_creneaux').fetchone()[0] == 1
    assert 'enregistrée' not in _messages(resp_client)


def test_creation_recente_ne_recoit_pas_le_message_dune_autre_fiche_expiree(resp_client, db):
    ancien_id = _creer(db, fin='2026-04-03')
    response = resp_client.post('/stagiaires/nouveau', data=_formulaire('2026-10-09'))
    assert response.status_code == 302
    _verifier_anonyme(db.execute('SELECT * FROM stagiaires WHERE id = ?', (ancien_id,)).fetchone())
    assert response.headers['Location'].endswith('#emploi-du-temps')
    assert 'enregistrée et anonymisée' not in _messages(resp_client)


@pytest.mark.parametrize('today,fin', [
    (date(2027, 2, 28), '2026-08-31'),
    (date(2028, 2, 29), '2027-08-31'),
])
def test_creation_efface_a_la_fin_du_sixieme_mois(resp_client, db, monkeypatch, today, fin):
    monkeypatch.setattr(routes, 'aujourd_hui', lambda: today)
    monkeypatch.setattr(routes, '_anonymisation_traitee', today)
    response = resp_client.post('/stagiaires/nouveau', data=_formulaire(fin))
    assert response.status_code == 302
    _verifier_anonyme(db.execute('SELECT * FROM stagiaires').fetchone())
