"""Lecture personnelle des annonces, permissions et persistance."""
from datetime import date
import importlib
import json
import re
from contextlib import closing

import pytest

from tests.test_stagiaires import _stagiaire, _creneau, _autre_secteur, _cartes_stagiaires

URL = '/stagiaires/annonces/lire'


@pytest.fixture(autouse=True)
def dates_fixes(monkeypatch):
    monkeypatch.setattr('blueprints.stagiaires.aujourd_hui', lambda: date(2026, 10, 5))
    monkeypatch.setattr('dashboard_actions.aujourd_hui', lambda: date(2026, 10, 5))


def annonce(db, sample_users, **kwargs):
    sid = _stagiaire(db, **kwargs)
    _creneau(db, sid, '2026-10-06', 'matin', sample_users['secteur_id'])
    return {'secteur_id': sample_users['secteur_id'],
            'annonces': [{'stagiaire_id': sid, 'date': '2026-10-06'}]}


def cartes(app, db, sample_users, monkeypatch, user_id=None):
    return _cartes_stagiaires(app, db, monkeypatch, 'responsable',
                            user_id or sample_users['responsable_id'],
                            sample_users['secteur_id'], date(2026, 10, 5))[1]


def test_lecture_personnelle_persistante_idempotente(resp_client, app, db, sample_users, monkeypatch):
    payload = annonce(db, sample_users)
    sid = payload['annonces'][0]['stagiaire_id']
    autre = db.execute("INSERT INTO users (nom, prenom, login, password, profil, secteur_id) "
                       "VALUES ('Autre', 'Responsable', 'autre', 'x', 'responsable', ?)",
                       (sample_users['secteur_id'],)).lastrowid
    db.commit()
    assert len(cartes(app, db, sample_users, monkeypatch)) == 1
    for _ in range(2):
        assert resp_client.post(URL, json=payload).get_json() == {'ok': True}
    assert db.execute('SELECT COUNT(*) FROM stagiaires_annonces_lectures').fetchone()[0] == 1
    assert cartes(app, db, sample_users, monkeypatch) == []
    assert len(cartes(app, db, sample_users, monkeypatch, autre)) == 1
    assert db.execute('SELECT nom FROM stagiaires WHERE id = ?', (sid,)).fetchone()[0] == 'Martin'
    assert db.execute('SELECT COUNT(*) FROM stagiaires_creneaux').fetchone()[0] == 1
    for page in ('/accueil', '/api/accueil/flux-fragment', '/dashboard_responsable'):
        assert 'Léa Martin' not in resp_client.get(page, follow_redirects=True).get_data(as_text=True)
    # Un autre jour d'accueil reste une autre annonce.
    _creneau(db, sid, '2026-10-05', 'matin', sample_users['secteur_id'])
    assert len(cartes(app, db, sample_users, monkeypatch)) == 1


def test_lecture_classique_et_csrf(resp_client, app, db, sample_users):
    payload = annonce(db, sample_users)
    app.config['WTF_CSRF_ENABLED'] = True
    assert resp_client.post(URL, json=payload).status_code == 302
    assert db.execute('SELECT COUNT(*) FROM stagiaires_annonces_lectures').fetchone()[0] == 0


def test_lecture_classique(resp_client, db, sample_users):
    payload = annonce(db, sample_users)
    r = resp_client.post(URL, data={'secteur_id': payload['secteur_id'],
                                    'annonces': json.dumps(payload['annonces'])})
    assert r.status_code == 302
    assert r.location.endswith('/dashboard_responsable')


@pytest.mark.parametrize('fixture', ['auth_client', 'admin_client', 'comptable_client', 'prestataire_client'])
def test_autres_profils_refuses(request, db, sample_users, fixture):
    payload = annonce(db, sample_users)
    assert request.getfixturevalue(fixture).post(URL, json=payload).status_code == 403
    assert db.execute('SELECT COUNT(*) FROM stagiaires_annonces_lectures').fetchone()[0] == 0


def test_non_connecte_refuse(client, db, sample_users):
    assert client.post(URL, json=annonce(db, sample_users)).status_code == 302
    assert db.execute('SELECT COUNT(*) FROM stagiaires_annonces_lectures').fetchone()[0] == 0


@pytest.mark.parametrize('modification, code', [
    ({'secteur_id': 99999}, 403),
    ({'annonces': []}, 400),
    ({'annonces': 'invalide'}, 400),
    ({'annonces': [None]}, 400),
    ({'annonces': [{'stagiaire_id': 99999, 'date': '2026-10-06'}]}, 404),
    ({'annonces': [{'stagiaire_id': 1, 'date': '2026-10-07'}]}, 404),
    ({'annonces': [{'stagiaire_id': 1, 'date': '2026-10-04'}]}, 404),
    ({'annonces': [{'stagiaire_id': 1, 'date': '2026-02-31'}]}, 400),
])
def test_payload_invalide_refuse(resp_client, db, sample_users, modification, code):
    payload = annonce(db, sample_users)
    payload.update(modification)
    assert resp_client.post(URL, json=payload).status_code == code
    assert db.execute('SELECT COUNT(*) FROM stagiaires_annonces_lectures').fetchone()[0] == 0


def test_secteur_reverifie_et_lot_atomique(resp_client, db, sample_users):
    payload = annonce(db, sample_users)
    autre = _autre_secteur(db)
    autre_sid = _stagiaire(db, prenom='Autre')
    _creneau(db, autre_sid, '2026-10-06', 'matin', autre)
    payload['annonces'].append({'stagiaire_id': autre_sid, 'date': '2026-10-06'})
    assert resp_client.post(URL, json=payload).status_code == 404
    assert db.execute('SELECT COUNT(*) FROM stagiaires_annonces_lectures').fetchone()[0] == 0
    db.execute('UPDATE users SET secteur_id = ? WHERE id = ?',
               (autre, sample_users['responsable_id']))
    db.commit()
    assert resp_client.post(URL, json=payload).status_code == 403


def test_carte_groupee_complete_et_compteurs(resp_client, app, db, sample_users, monkeypatch):
    for prenom in ('Ana', 'Basile', 'Chloé', 'Diane'):
        annonce(db, sample_users, prenom=prenom)
    initiales = cartes(app, db, sample_users, monkeypatch)
    assert len(initiales) == 3
    assert initiales[-1]['detail'] == 'Demain : Chloé Martin ; Demain : Diane Martin'
    html = resp_client.get('/accueil').get_data(as_text=True)
    assert html.count('data-flx-act="stagiaire"') == 3
    assert 'J’ai lu' in html
    for carte in initiales:
        assert resp_client.post(URL, json={'annonces': carte['annonces'],
                                          'secteur_id': carte['secteur_id']}).status_code == 200
    assert cartes(app, db, sample_users, monkeypatch) == []
    assert db.execute('SELECT COUNT(*) FROM stagiaires_annonces_lectures').fetchone()[0] == 4
    assert 'data-flx-act="stagiaire"' not in resp_client.get('/accueil').get_data(as_text=True)


def test_migration_idempotente_et_suppression(resp_client, db, sample_users):
    payload = annonce(db, sample_users)
    migration = importlib.import_module('migrations.0076_lectures_annonces_stagiaires')
    migration.upgrade(db)
    migration.upgrade(db)
    db.commit()
    assert resp_client.post(URL, json=payload).status_code == 200
    sid = payload['annonces'][0]['stagiaire_id']
    assert resp_client.post(f'/stagiaires/{sid}/supprimer').status_code == 302
    assert db.execute('SELECT COUNT(*) FROM stagiaires_annonces_lectures').fetchone()[0] == 0


@pytest.mark.parametrize('format_envoi', ['json', 'formulaire'])
def test_lecture_avec_vrai_jeton_csrf(resp_client, app, db, sample_users, format_envoi):
    payload = annonce(db, sample_users)
    app.config['WTF_CSRF_ENABLED'] = True
    page = resp_client.get('/dashboard_responsable')
    assert page.status_code == 200
    token = re.search(r'<meta name="csrf-token" content="([^"]+)"',
                      page.get_data(as_text=True)).group(1)
    if format_envoi == 'json':
        response = resp_client.post(URL, json=payload, headers={'X-CSRFToken': token})
        assert response.status_code == 200
        assert response.get_json() == {'ok': True}
    else:
        response = resp_client.post(URL, data={
            'csrf_token': token,
            'secteur_id': payload['secteur_id'],
            'annonces': json.dumps(payload['annonces']),
        })
        assert response.status_code == 302
        assert response.location.endswith('/dashboard_responsable')
    assert db.execute('SELECT COUNT(*) FROM stagiaires_annonces_lectures').fetchone()[0] == 1


@pytest.mark.parametrize('changement, code', [
    ('revocation', 302), ('salarie', 403), ('comptable', 403), ('secteur', 403),
])
def test_droits_reverifies_apres_le_garde_global(
        resp_client, db, sample_users, monkeypatch, changement, code):
    import blueprints.stagiaires as routes
    payload = annonce(db, sample_users)
    autre_secteur = _autre_secteur(db)
    ouvrir = routes._ouvrir_ecriture
    passages = []

    def changer_avant_verrou(conn):
        # Simule une modification validée après le garde global et avant
        # BEGIN IMMEDIATE ; le vérificateur réel doit la relire sous verrou.
        passages.append(True)
        if changement == 'revocation':
            db.execute('UPDATE users SET actif = 0 WHERE id = ?',
                       (sample_users['responsable_id'],))
        elif changement == 'secteur':
            db.execute('UPDATE users SET secteur_id = ? WHERE id = ?',
                       (autre_secteur, sample_users['responsable_id']))
        else:
            db.execute('UPDATE users SET profil = ? WHERE id = ?',
                       (changement, sample_users['responsable_id']))
        db.commit()
        return ouvrir(conn)

    monkeypatch.setattr(routes, '_ouvrir_ecriture', changer_avant_verrou)
    response = resp_client.post(URL, json=payload)
    assert passages == [True]
    assert response.status_code == code
    if changement == 'revocation':
        assert '/login' in response.location
    assert db.execute('SELECT COUNT(*) FROM stagiaires_annonces_lectures').fetchone()[0] == 0


def test_installation_neuve_sans_executer_les_migrations(app, tmp_path, monkeypatch):
    import database
    from resilience import TABLES_REQUISES
    chemin = tmp_path / 'installation_neuve.db'
    monkeypatch.setattr(database, 'DATABASE', str(chemin))
    with app.app_context():
        database.init_db()
        with closing(database.get_db()) as conn:
            assert conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name = 'stagiaires_annonces_lectures'").fetchone()
            version = conn.execute(
                "SELECT statut, appliquee_par FROM schema_migrations WHERE version = '0076'"
            ).fetchone()
            assert tuple(version) == ('ok', 'systeme')
            assert {r['name']: r['pk'] for r in conn.execute(
                'PRAGMA table_info(stagiaires_annonces_lectures)') if r['pk']} == {
                    'user_id': 1, 'secteur_id': 2, 'stagiaire_id': 3, 'date': 4}
    assert TABLES_REQUISES['0076'] == ('stagiaires_annonces_lectures',)


def test_migration_preserve_fiches_creneaux_et_lectures(db, sample_users):
    payload = annonce(db, sample_users)
    sid = payload['annonces'][0]['stagiaire_id']
    fiches = [tuple(r) for r in db.execute('SELECT * FROM stagiaires')]
    creneaux = [tuple(r) for r in db.execute('SELECT * FROM stagiaires_creneaux')]
    # État antérieur à 0076 : fiches et accueils déjà présents, aucune table de lectures.
    db.execute('DROP TABLE stagiaires_annonces_lectures')
    migration = importlib.import_module('migrations.0076_lectures_annonces_stagiaires')
    migration.upgrade(db)
    db.execute(
        'INSERT INTO stagiaires_annonces_lectures '
        '(stagiaire_id, date, secteur_id, user_id, lu_le) VALUES (?, ?, ?, ?, ?)',
        (sid, '2026-10-06', payload['secteur_id'], sample_users['responsable_id'],
         '2026-10-05 08:00:00'))
    lectures = [tuple(r) for r in db.execute('SELECT * FROM stagiaires_annonces_lectures')]
    migration.upgrade(db)
    db.commit()
    assert [tuple(r) for r in db.execute('SELECT * FROM stagiaires')] == fiches
    assert [tuple(r) for r in db.execute('SELECT * FROM stagiaires_creneaux')] == creneaux
    assert [tuple(r) for r in db.execute('SELECT * FROM stagiaires_annonces_lectures')] == lectures
