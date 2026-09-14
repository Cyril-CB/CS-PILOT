"""Lecture individuelle et persistante de la bannière des messages CSE."""
import importlib

from database import ALL_MIGRATION_VERSIONS


def _inserer_message(db, contenu='Information CSE'):
    curseur = db.execute(
        "INSERT INTO cse_messages (titre, contenu, date_validite, statut) "
        "VALUES ('À lire', ?, '2999-12-31', 'actif')",
        (contenu,),
    )
    db.commit()
    return curseur.lastrowid


def _connexion(client, login, password):
    return client.post(
        '/login', data={'login': login, 'password': password},
        follow_redirects=True,
    )


def test_ouverture_enregistre_la_lecture_et_la_masque_apres_reconnexion(
        auth_client, db, sample_users):
    message_id = _inserer_message(db)
    page = auth_client.get('/dashboard').get_data(as_text=True)
    assert 'Message du CSE à lire' in page
    assert f'/cse/messages/{message_id}/lire' in page

    reponse = auth_client.post(f'/cse/messages/{message_id}/lire')

    assert reponse.status_code == 200
    assert reponse.get_json() == {'ok': True}
    assert auth_client.post(f'/cse/messages/{message_id}/lire').status_code == 200
    lecture = db.execute(
        'SELECT message_id, user_id FROM cse_messages_lectures'
    ).fetchone()
    assert tuple(lecture) == (message_id, sample_users['salarie_id'])
    assert db.execute('SELECT COUNT(*) FROM cse_messages_lectures').fetchone()[0] == 1
    assert 'Message du CSE à lire' not in auth_client.get('/dashboard').get_data(as_text=True)

    auth_client.get('/logout')
    _connexion(auth_client, 'salarie_test', 'sal123')
    assert 'Message du CSE à lire' not in auth_client.get('/dashboard').get_data(as_text=True)


def test_lecture_est_individuelle_et_ignore_un_user_id_fourni_par_le_client(
        app, db, sample_users):
    message_id = _inserer_message(db)
    salarie = app.test_client()
    responsable = app.test_client()
    _connexion(salarie, 'salarie_test', 'sal123')
    _connexion(responsable, 'resp_test', 'resp123')

    reponse = salarie.post(
        f'/cse/messages/{message_id}/lire',
        data={'user_id': sample_users['responsable_id']},
    )

    assert reponse.status_code == 200
    lecteurs = [r['user_id'] for r in db.execute(
        'SELECT user_id FROM cse_messages_lectures WHERE message_id = ?',
        (message_id,),
    )]
    assert lecteurs == [sample_users['salarie_id']]
    assert 'Message du CSE à lire' not in salarie.get('/dashboard').get_data(as_text=True)
    assert 'Message du CSE à lire' in responsable.get(
        '/dashboard_responsable'
    ).get_data(as_text=True)


def test_nouveau_message_redevient_non_lu_pour_le_meme_utilisateur(auth_client, db):
    premier_id = _inserer_message(db, 'Premier')
    assert auth_client.post(f'/cse/messages/{premier_id}/lire').status_code == 200
    db.execute("UPDATE cse_messages SET statut = 'archive' WHERE id = ?", (premier_id,))
    second_id = _inserer_message(db, 'Second')

    page = auth_client.get('/dashboard').get_data(as_text=True)

    assert 'Message du CSE à lire' in page
    assert f'/cse/messages/{second_id}/lire' in page


def test_endpoint_lecture_refuse_un_anonyme(client, db):
    message_id = _inserer_message(db)
    assert client.post(f'/cse/messages/{message_id}/lire').status_code == 302


def test_endpoint_lecture_refuse_un_prestataire(prestataire_client, db):
    message_id = _inserer_message(db)
    assert prestataire_client.post(f'/cse/messages/{message_id}/lire').status_code == 403
    assert db.execute('SELECT COUNT(*) FROM cse_messages_lectures').fetchone()[0] == 0


def test_endpoint_lecture_refuse_un_message_inactif(auth_client, db):
    message_id = _inserer_message(db)
    db.execute("UPDATE cse_messages SET statut = 'archive' WHERE id = ?", (message_id,))
    db.commit()
    assert auth_client.post(f'/cse/messages/{message_id}/lire').status_code == 404
    assert db.execute('SELECT COUNT(*) FROM cse_messages_lectures').fetchone()[0] == 0


def test_banniere_et_modale_sont_accessibles_en_classique_et_en_flux(
        app, db, sample_users):
    _inserer_message(db)
    salarie = app.test_client()
    direction = app.test_client()
    _connexion(salarie, 'salarie_test', 'sal123')
    _connexion(direction, 'admin', 'Admin1234')

    classique = salarie.get('/dashboard').get_data(as_text=True)
    flux = direction.get('/accueil').get_data(as_text=True)
    for page in (classique, flux):
        assert 'class="cse-banner"' in page
        assert 'aria-haspopup="dialog"' in page
        assert 'role="dialog"' in page
        assert 'aria-modal="true"' in page
        assert "fetch(readUrl,{method:'POST'" in page
        assert "if(!response.ok)return" in page
        assert "trigger.hidden=true" in page
        assert "if(close)close.focus()" in page


def test_schema_neuf_et_migration_0074_idempotente(app, db):
    migration = importlib.import_module('migrations.0074_lectures_messages_cse')
    assert ('0074', migration.NOM) in ALL_MIGRATION_VERSIONS
    ddl_neuf = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='cse_messages_lectures'"
    ).fetchone()[0]

    db.execute('DROP TABLE cse_messages_lectures')
    migration.upgrade(db)
    message_id = _inserer_message(db)
    user_id = db.execute('SELECT id FROM users ORDER BY id LIMIT 1').fetchone()
    if user_id is None:
        db.execute(
            "INSERT INTO users (nom, prenom, login, password, profil) "
            "VALUES ('Test', 'Lecture', 'lecture_schema', 'x', 'salarie')"
        )
        user_id = db.execute('SELECT id FROM users WHERE login = ?', ('lecture_schema',)).fetchone()
    db.execute(
        'INSERT INTO cse_messages_lectures(message_id, user_id) VALUES (?, ?)',
        (message_id, user_id[0]),
    )
    migration.upgrade(db)

    assert db.execute('SELECT COUNT(*) FROM cse_messages_lectures').fetchone()[0] == 1
    ddl_migre = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='cse_messages_lectures'"
    ).fetchone()[0]
    assert ddl_migre == ddl_neuf
