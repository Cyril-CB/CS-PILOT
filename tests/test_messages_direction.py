"""Communications direction : droits, cycle de vie, diffusion et isolation CSE."""
import importlib
import re
import sqlite3
from datetime import date
from unittest.mock import Mock

import pytest

from blueprints import messages_direction as module

URL = '/direction/messages'
DONNEES = {'titre': 'Note de service', 'contenu': 'Information au personnel',
           'date_validite': '2030-05-18'}


@pytest.fixture(autouse=True)
def date_fixe(monkeypatch):
    monkeypatch.setattr(module, 'aujourd_hui', lambda: date(2030, 5, 18))
    # Interdire tout envoi réel ; les notifications sont simulées dans les tests.
    monkeypatch.setattr('smtplib.SMTP', Mock(side_effect=AssertionError('SMTP réel interdit')))


def inserer(db, **valeurs):
    data = dict(DONNEES, **valeurs)
    message_id = db.execute('''
        INSERT INTO messages_direction (titre, contenu, date_validite)
        VALUES (?, ?, ?)
    ''', (data['titre'], data['contenu'], data['date_validite'])).lastrowid
    db.commit()
    return message_id


def connexion(client, login='salarie_test', password='sal123'):
    return client.post('/login', data={'login': login, 'password': password})


@pytest.mark.parametrize('fixture', ['admin_client', 'comptable_client'])
def test_gestion_autorisee_et_auteur_issu_de_session(request, fixture, db, sample_users):
    client = request.getfixturevalue(fixture)
    assert client.get(URL).status_code == 200
    response = client.post(URL + '/creer', data=dict(DONNEES, cree_par=999))
    assert response.status_code == 302
    message = db.execute('SELECT * FROM messages_direction').fetchone()
    cle = 'directeur_id' if fixture == 'admin_client' else 'comptable_id'
    assert message['cree_par'] == sample_users[cle]
    assert message['date_validite'] == '2030-05-18'  # borne incluse
    assert message['statut'] == 'actif'
    assert 'publié par' in client.get(URL).get_data(as_text=True)


@pytest.mark.parametrize('fixture', ['auth_client', 'resp_client', 'prestataire_client'])
def test_refus_gestion_meme_pour_un_membre_cse(request, fixture, db, sample_users):
    client = request.getfixturevalue(fixture)
    db.execute('INSERT INTO cse_membres (user_id) VALUES (?)', (sample_users['salarie_id'],))
    message_id = inserer(db)
    assert client.get(URL).status_code == 403
    assert client.post(URL + '/creer', data=DONNEES).status_code == 403
    assert client.post(f'{URL}/{message_id}/archiver').status_code == 403
    assert db.execute('SELECT statut FROM messages_direction').fetchone()[0] == 'actif'
    assert db.execute('SELECT COUNT(*) FROM messages_direction').fetchone()[0] == 1


def test_non_connecte_redirige(client):
    for url, method in [(URL, 'get'), (URL + '/creer', 'post'),
                        (URL + '/1/archiver', 'post'), (URL + '/1/lire', 'post')]:
        response = getattr(client, method)(url)
        assert response.status_code == 302
        assert '/login' in response.location


def test_remplacement_archive_et_conserve_auteur_sans_toucher_cse(admin_client, db, sample_users):
    db.execute("INSERT INTO cse_messages (contenu, date_validite) VALUES ('CSE indépendant', '2999-12-31')")
    db.commit()
    admin_client.post(URL + '/creer', data=DONNEES)
    ancien_id = db.execute('SELECT id FROM messages_direction').fetchone()[0]
    admin_client.post(URL + '/creer', data=dict(DONNEES, contenu='Deuxième note'))
    messages = db.execute('SELECT * FROM messages_direction ORDER BY id').fetchall()
    assert [m['statut'] for m in messages] == ['archive', 'actif']
    assert messages[0]['archive_le']
    assert messages[0]['cree_par'] == sample_users['directeur_id']
    assert db.execute('SELECT statut FROM cse_messages').fetchone()[0] == 'actif'
    page = admin_client.get(URL).get_data(as_text=True)
    assert 'Lire le message archivé' in page
    assert 'Auteur' in page and 'Système Admin' in page
    admin_client.post(f'{URL}/{messages[1]["id"]}/archiver')
    assert db.execute("SELECT COUNT(*) FROM messages_direction WHERE statut='actif'").fetchone()[0] == 0
    date_archive = db.execute('SELECT archive_le FROM messages_direction WHERE id=?', (ancien_id,)).fetchone()[0]
    admin_client.post(f'{URL}/{ancien_id}/archiver')
    assert db.execute('SELECT archive_le FROM messages_direction WHERE id=?', (ancien_id,)).fetchone()[0] == date_archive
    assert admin_client.post(URL + '/99999/archiver').status_code == 404


@pytest.mark.parametrize('champ,valeur', [
    ('contenu', ''), ('contenu', '   '), ('contenu', 'x' * 20001),
    ('titre', 'x' * 151), ('date_validite', ''), ('date_validite', 'invalide'),
    ('date_validite', '2030-02-30'), ('date_validite', '2030-05-17'),
    ('date_validite', '20300518'), ('date_validite', '2030-5-18'),
])
def test_saisie_invalide_ne_retire_pas_le_message_actif(admin_client, db, champ, valeur):
    message_id = inserer(db)
    response = admin_client.post(URL + '/creer', data=dict(DONNEES, **{champ: valeur}), follow_redirects=True)
    assert response.status_code == 200
    assert 'alert-error' in response.get_data(as_text=True)
    rows = db.execute('SELECT id, statut FROM messages_direction').fetchall()
    assert [tuple(row) for row in rows] == [(message_id, 'actif')]


def test_titre_facultatif_et_contenu_echappe(admin_client, auth_client, db):
    # Les fixtures de connexion partagent un client : rétablir le gestionnaire.
    connexion(admin_client, 'admin', 'Admin1234')
    admin_client.post(URL + '/creer', data=dict(DONNEES, titre='', contenu='<script>alert(1)</script>'))
    assert db.execute('SELECT titre FROM messages_direction').fetchone()[0] is None
    page = admin_client.get(URL).get_data(as_text=True)
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in page
    assert '<script>alert(1)</script>' not in page
    connexion(auth_client)
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in auth_client.get('/dashboard').get_data(as_text=True)


def test_expiration_masquee_avant_archivage_et_archivee_a_la_gestion(admin_client, db):
    message_id = inserer(db, date_validite='2030-05-17')
    assert module.get_message_actif(db) is None
    assert admin_client.post(f'{URL}/{message_id}/lire').status_code == 404
    admin_client.get(URL)
    message = db.execute('SELECT * FROM messages_direction').fetchone()
    assert message['statut'] == 'archive' and message['archive_le']


def test_rollback_si_echec_du_remplacement(admin_client, db):
    ancien_id = inserer(db)
    db.execute("CREATE TRIGGER refuser_note BEFORE INSERT ON messages_direction BEGIN SELECT RAISE(ABORT, 'échec fictif'); END")
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        admin_client.post(URL + '/creer', data=DONNEES)
    assert [tuple(r) for r in db.execute('SELECT id, statut FROM messages_direction')] == [(ancien_id, 'actif')]


def test_lecture_individuelle_explicite_persistante_et_independante_du_cse(app, db, sample_users):
    message_id = inserer(db)
    cse_id = db.execute("INSERT INTO cse_messages (contenu, date_validite) VALUES ('Du CSE', '2999-12-31')").lastrowid
    db.commit()
    salarie, autre = app.test_client(), app.test_client()
    connexion(salarie)
    connexion(autre, 'resp_test', 'resp123')
    for _ in range(2):
        page = salarie.get('/dashboard').get_data(as_text=True)
        assert 'Message de la direction à lire' in page and 'Message du CSE à lire' in page
    assert db.execute('SELECT COUNT(*) FROM messages_direction_lectures').fetchone()[0] == 0
    for _ in range(2):
        assert salarie.post(f'{URL}/{message_id}/lire', data={'user_id': sample_users['responsable_id']}).json == {'ok': True}
    assert [tuple(r) for r in db.execute('SELECT message_id, user_id FROM messages_direction_lectures')] == [(message_id, sample_users['salarie_id'])]
    assert db.execute('SELECT COUNT(*) FROM cse_messages_lectures').fetchone()[0] == 0
    page = salarie.get('/dashboard').get_data(as_text=True)
    assert 'Message de la direction à lire' not in page and 'Message du CSE à lire' in page
    assert 'Message de la direction à lire' in autre.get('/dashboard_responsable').get_data(as_text=True)
    salarie.get('/logout'); connexion(salarie)
    assert 'Message de la direction à lire' not in salarie.get('/dashboard').get_data(as_text=True)
    assert salarie.post(f'/cse/messages/{cse_id}/lire').json == {'ok': True}
    db.execute("UPDATE messages_direction SET statut='archive'")
    db.commit()
    nouveau_id = inserer(db, contenu='Nouvelle note')
    assert nouveau_id != message_id
    assert 'Message de la direction à lire' in salarie.get('/dashboard').get_data(as_text=True)


@pytest.mark.parametrize('fixture', ['auth_client', 'resp_client', 'admin_client', 'comptable_client'])
def test_tous_les_profils_internes_peuvent_confirmer_lecture(request, fixture, db):
    client = request.getfixturevalue(fixture)
    message_id = inserer(db)
    assert client.post(f'{URL}/{message_id}/lire').status_code == 200


def test_prestataire_ne_voit_pas_et_ne_lit_pas(prestataire_client, db):
    message_id = inserer(db)
    assert prestataire_client.post(f'{URL}/{message_id}/lire').status_code == 403
    assert 'Message de la direction à lire' not in prestataire_client.get('/prepa_paie').get_data(as_text=True)
    assert db.execute('SELECT COUNT(*) FROM messages_direction_lectures').fetchone()[0] == 0


def test_message_archive_ou_inexistant_non_lisible(auth_client, db):
    message_id = inserer(db)
    db.execute("UPDATE messages_direction SET statut='archive'")
    db.commit()
    assert auth_client.post(f'{URL}/{message_id}/lire').status_code == 404
    assert auth_client.post(URL + '/99999/lire').status_code == 404


def test_compte_desactive_ne_peut_plus_lire(auth_client, db, sample_users):
    message_id = inserer(db)
    db.execute('UPDATE users SET actif = 0 WHERE id = ?', (sample_users['salarie_id'],))
    db.commit()
    response = auth_client.post(f'{URL}/{message_id}/lire')
    assert response.status_code in (302, 401, 403, 404)
    assert db.execute('SELECT COUNT(*) FROM messages_direction_lectures').fetchone()[0] == 0


def test_csrf_requis_sur_toutes_les_mutations(app, admin_client, db):
    message_id = inserer(db)
    try:
        for suffixe in ['/creer', f'/{message_id}/archiver', f'/{message_id}/lire']:
            connexion(admin_client, 'admin', 'Admin1234')
            app.config['WTF_CSRF_ENABLED'] = True
            response = admin_client.post(URL + suffixe, data=DONNEES)
            assert response.status_code == 302 and '/login' in response.location
            app.config['WTF_CSRF_ENABLED'] = False
        assert db.execute('SELECT statut FROM messages_direction').fetchone()[0] == 'actif'
        assert db.execute('SELECT COUNT(*) FROM messages_direction').fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM messages_direction_lectures').fetchone()[0] == 0
        connexion(admin_client, 'admin', 'Admin1234')
        app.config['WTF_CSRF_ENABLED'] = True
        from flask import g
        g.pop('csrf_token', None)  # contexte app maintenu par la fixture db
        page = admin_client.get(URL).get_data(as_text=True)
        token = re.search(r'name="csrf-token" content="([^"]+)"', page)[1]
        assert admin_client.post(f'{URL}/{message_id}/lire', headers={'X-CSRFToken': token}).json == {'ok': True}
    finally:
        app.config['WTF_CSRF_ENABLED'] = False


def test_notification_optionnelle_respecte_audience_et_consentement(admin_client, db, sample_users, monkeypatch):
    db.execute("UPDATE users SET email=login || '@example.test'")
    db.execute("INSERT INTO users (nom,prenom,login,password,profil,email) VALUES ('Paie','Externe','ext','fictif','prestataire','ext@example.test')")
    db.execute("INSERT INTO users (nom,prenom,login,password,profil,email,actif) VALUES ('Inactif','Test','off','fictif','salarie','off@example.test',0)")
    db.commit()
    monkeypatch.setattr(module, 'is_email_configured', lambda: True)
    consentement = Mock(side_effect=lambda uid: (uid == sample_users['salarie_id'], 'accord@example.test'))
    envoi = Mock(return_value=(1, 0, []))
    monkeypatch.setattr(module, 'peut_envoyer_email', consentement)
    monkeypatch.setattr(module, 'notifier_publication_direction', envoi)
    admin_client.post(URL + '/creer', data=DONNEES)
    envoi.assert_not_called()
    admin_client.post(URL + '/creer', data=dict(DONNEES, notifier_email='1'))
    assert {call.args[0] for call in consentement.call_args_list} == {
        sample_users[k] for k in ['salarie_id', 'responsable_id', 'directeur_id', 'comptable_id']}
    assert envoi.call_args.args[0] == [('accord@example.test', 'Jean')]
    assert envoi.call_args.args[-1] == 'Système Admin'
    envoi.side_effect = RuntimeError('échec SMTP fictif')
    response = admin_client.post(URL + '/creer', data=dict(DONNEES, notifier_email='1', contenu='Note conservée'))
    assert response.status_code == 302
    assert db.execute("SELECT contenu FROM messages_direction WHERE statut='actif'").fetchone()[0] == 'Note conservée'


def test_email_direction_echappe_et_ne_se_presente_pas_comme_cse(monkeypatch):
    import email_service
    envoi = Mock(return_value=(1, 0, []))
    monkeypatch.setattr(email_service, 'envoyer_email_multiple', envoi)
    email_service.notifier_publication_direction([('test@example.test', 'Test')], '<titre>', '<script>\ncorps', '2030-05-18', '<auteur>')
    _, sujet, html = envoi.call_args.args
    assert 'direction' in sujet and 'CSE' not in html
    assert '&lt;titre&gt;' in html and '&lt;script&gt;<br>corps' in html and '&lt;auteur&gt;' in html


def test_schema_neuf_migration_idempotente_et_preservation_cse(db):
    from database import ALL_MIGRATION_VERSIONS
    assert '0080' in dict(ALL_MIGRATION_VERSIONS)
    assert db.execute("SELECT name FROM sqlite_master WHERE name='messages_direction_lectures'").fetchone()
    migration = importlib.import_module('migrations.0080_messages_direction')
    conn = sqlite3.connect(':memory:')
    try:
        conn.executescript("CREATE TABLE users (id INTEGER PRIMARY KEY); INSERT INTO users VALUES(1); CREATE TABLE cse_messages (id INTEGER PRIMARY KEY, contenu TEXT); INSERT INTO cse_messages VALUES(1, 'historique CSE');")
        migration.upgrade(conn)
        conn.execute("INSERT INTO messages_direction (contenu,date_validite,cree_par) VALUES ('note','2030-05-18',1)")
        conn.execute('INSERT INTO messages_direction_lectures(message_id,user_id) VALUES(1,1)')
        migration.upgrade(conn)
        assert conn.execute('SELECT contenu FROM messages_direction').fetchone()[0] == 'note'
        assert conn.execute('SELECT COUNT(*) FROM messages_direction_lectures').fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO messages_direction (contenu,date_validite) VALUES ('doublon','2030-05-18')")
        migration.downgrade(conn)
        assert conn.execute('SELECT contenu FROM cse_messages').fetchone()[0] == 'historique CSE'
        assert conn.execute('SELECT id FROM users').fetchone()[0] == 1
    finally:
        conn.close()


@pytest.mark.parametrize('fixture', ['admin_client', 'comptable_client'])
@pytest.mark.parametrize('query', [
    'message', 'messages', 'info salarié', 'infos salariés', 'note de service',
    'notes de service', 'communication interne', 'message de la direction',
    'information au personnel', 'note interne',
])
def test_barre_intelligente_classique_et_palette(request, fixture, query):
    client = request.getfixturevalue(fixture)
    verdict = client.post('/api/search', json={'query': query}).json
    assert verdict['type'] == 'redirect' and verdict['url'] == URL
    suggestions = client.post('/api/search/suggestions', json={'query': query}).json['suggestions']
    assert suggestions[0]['url'] == URL


@pytest.mark.parametrize('fixture', ['auth_client', 'resp_client', 'prestataire_client'])
def test_menu_et_palette_naccordent_pas_la_gestion(request, fixture):
    client = request.getfixturevalue(fixture)
    page = client.get('/mon-espace').get_data(as_text=True)
    assert f'href="{URL}"' not in page
    response = client.post('/api/search/suggestions', json={'query': 'message'})
    assert all(s.get('url') != URL for s in response.json.get('suggestions', []))


@pytest.mark.parametrize('fixture', ['admin_client', 'comptable_client'])
def test_menu_classique_et_carte_flux_contiennent_le_module(request, fixture):
    client = request.getfixturevalue(fixture)
    # User-agent téléphone : le serveur sélectionne le menu classique.
    page = client.get(URL, headers={'User-Agent': 'Mozilla/5.0 Mobi'}).get_data(as_text=True)
    assert f'href="{URL}"' in page
    suggestions = client.post('/api/search/suggestions', json={'query': 'informer les salariés'}).json['suggestions']
    assert suggestions[0]['url'] == URL
