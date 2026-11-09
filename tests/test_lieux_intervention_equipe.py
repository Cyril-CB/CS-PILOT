"""Tests du prototype des lieux habituels dans Mon équipe."""
from tests.conftest import _login


def test_schema_lieux_installation_neuve(db):
    noms = {r['name'] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {'equipe_lieux_options', 'equipe_lieux_affectations'} <= noms


def test_responsable_active_et_renseigne_un_lieu(resp_client, db, sample_users, sample_contrat):
    uid = sample_users['salarie_id']
    sid = sample_users['secteur_id']
    page = resp_client.get('/mon_equipe')
    assert page.status_code == 200
    assert 'Activer' in page.get_data(as_text=True)
    rep = resp_client.post('/mon_equipe/lieux',
                           data={'action': 'activation', 'actif': '1'})
    assert rep.status_code == 302
    active = db.execute(
        'SELECT actif FROM equipe_lieux_options WHERE secteur_id=?', (sid,)).fetchone()
    assert active['actif'] == 1
    rep = resp_client.post('/mon_equipe/lieux',
                           data={'action': 'affectation', 'user_id': uid,
                                 'jour': '0', 'demi_jour': 'matin', 'lieu': 'Angle 9'})
    assert rep.status_code == 302
    html = resp_client.get('/mon_equipe').get_data(as_text=True)
    assert 'Angle 9' in html


def test_salarie_voit_lieu_sans_pouvoir_modifier(app, resp_client, sample_users, sample_contrat):
    uid = sample_users['salarie_id']
    assert resp_client.post('/mon_equipe/lieux', data={'action': 'activation', 'actif': '1'}).status_code == 302
    assert resp_client.post('/mon_equipe/lieux',
                     data={'action': 'affectation', 'user_id': uid, 'jour': '1',
                           'demi_jour': 'aprem', 'lieu': 'MSCB'}).status_code == 302
    auth_client = app.test_client()
    _login(auth_client, 'salarie_test', 'sal123')
    html = auth_client.get('/mon_equipe').get_data(as_text=True)
    assert 'MSCB' in html
    assert 'Activer les lieux' not in html
    assert auth_client.post('/mon_equipe/lieux', data={'action': 'activation', 'actif': '0'}).status_code == 403


def test_non_membre_et_champ_invalide_refuses(resp_client, db, sample_users, sample_contrat):
    from werkzeug.security import generate_password_hash
    cur = db.execute("INSERT INTO secteurs(nom) VALUES('Autre secteur')")
    sid = cur.lastrowid
    cur = db.execute("""INSERT INTO users(nom,prenom,login,password,profil,secteur_id)
        VALUES('Test','Externe','externe',?,'salarie',?)""",
        (generate_password_hash('test'),sid))
    externe = cur.lastrowid
    db.commit()
    resp_client.post('/mon_equipe/lieux', data={'action': 'activation', 'actif': '1'})
    assert resp_client.post('/mon_equipe/lieux', data={'action': 'affectation',
        'user_id': externe, 'jour': '0', 'demi_jour': 'matin', 'lieu': 'Externe'}).status_code == 403
    assert resp_client.post('/mon_equipe/lieux', data={'action': 'affectation',
        'user_id': sample_users['salarie_id'], 'jour': '9',
        'demi_jour': 'matin', 'lieu': 'X'}).status_code == 400


def test_desactivation_masque_sans_effacer(app, resp_client, db, sample_users, sample_contrat):
    uid = sample_users['salarie_id']
    assert resp_client.post('/mon_equipe/lieux', data={'action': 'activation', 'actif': '1'}).status_code == 302
    assert resp_client.post('/mon_equipe/lieux', data={'action': 'affectation',
        'user_id': uid, 'jour': '0', 'demi_jour': 'matin', 'lieu': 'Angle 9'}).status_code == 302
    assert resp_client.post('/mon_equipe/lieux', data={'action': 'activation', 'actif': '0'}).status_code == 302
    auth_client = app.test_client()
    _login(auth_client, 'salarie_test', 'sal123')
    assert 'Angle 9' not in auth_client.get('/mon_equipe').get_data(as_text=True)
    assert db.execute('SELECT COUNT(*) AS n FROM equipe_lieux_affectations').fetchone()['n'] == 1
