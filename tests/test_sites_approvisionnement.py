"""Sites et entretien : bases synthétiques, périmètres réels et réceptions atomiques."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import importlib
import re
import sqlite3
from threading import Barrier

import pytest

from tests.conftest import _login


@pytest.fixture
def organisation(app, db, sample_users):
    from werkzeug.security import generate_password_hash
    from entretien import initialiser_catalogue

    def user(login):
        return db.execute('''INSERT INTO users (nom, prenom, login, password, profil)
            VALUES (?, 'Test', ?, ?, 'salarie')''',
            (login, login, generate_password_hash('test123'))).lastrowid

    s1 = db.execute("INSERT INTO sites (nom) VALUES ('Cyprian')").lastrowid
    s2 = db.execute("INSERT INTO sites (nom) VALUES ('Les Brosses')").lastrowid
    manager1, manager2, entretien1, entretien2, autre = [user(n) for n in ('four1', 'four2', 'ent1', 'ent2', 'autre')]
    demandeur = sample_users['responsable_id']
    salarie = sample_users['salarie_id']
    db.executemany('INSERT INTO sites_utilisateurs (site_id,user_id) VALUES (?, ?)', [(s1, salarie), (s2, demandeur)])
    db.executemany('INSERT INTO sites_responsables_modules (site_id,module,user_id) VALUES (?, ?, ?)',
        [(s1, 'fournitures', manager1), (s2, 'fournitures', manager2),
         (s1, 'entretien', entretien1), (s2, 'entretien', entretien2)])
    l1 = db.execute("INSERT INTO entretien_lieux (site_id,nom,demandeur_id) VALUES (?, 'Gribouille', ?)", (s1, demandeur)).lastrowid
    l2 = db.execute("INSERT INTO entretien_lieux (site_id,nom,demandeur_id) VALUES (?, 'Angle 9', ?)", (s1, salarie)).lastrowid
    l3 = db.execute("INSERT INTO entretien_lieux (site_id,nom,demandeur_id) VALUES (?, 'Lieu Brosses', ?)", (s2, autre)).lastrowid
    initialiser_catalogue(db, s1)
    initialiser_catalogue(db, s2)
    p1 = db.execute("SELECT id FROM entretien_produits WHERE site_id = ? AND nom = 'Lessive'", (s1,)).fetchone()[0]
    p2 = db.execute("SELECT id FROM entretien_produits WHERE site_id = ? AND nom = 'Lessive'", (s2,)).fetchone()[0]
    db.commit()
    return dict(s1=s1, s2=s2, l1=l1, l2=l2, l3=l3, p1=p1, p2=p2,
                manager1=manager1, manager2=manager2, entretien1=entretien1, entretien2=entretien2,
                autre=autre, demandeur=demandeur, salarie=salarie)


def acteur(app, login, password='test123'):
    client = app.test_client()
    _login(client, login, password)
    return client


def besoin(client, org, *, lieu='l1', produit='p1', cle='a' * 32, quantite='2', **extra):
    return client.post('/produits-entretien', data={
        'lieu_id': str(org[lieu]), 'cle_envoi': cle,
        'lieu_revision': '1', f"revision_produit_{org[produit]}": '1',
        f"quantite_{org[produit]}": quantite, **extra,
    })


def demande_id(db):
    return db.execute('SELECT id FROM entretien_demandes ORDER BY id DESC').fetchone()[0]


def passer_commande(client, did, revision=1):
    return client.post(f'/produits-entretien/{did}/statut', data={'statut': 'commandee', 'revision': revision})


def recevoir(client, did, revision=2, note=''):
    return client.post(f'/produits-entretien/{did}/statut', data={
        'statut': 'recue', 'revision': revision, 'reception_note': note})


def test_migration_ancienne_base_preserve_demandes_et_mission():
    migration = importlib.import_module('migrations.0079_sites_approvisionnement')
    with closing(sqlite3.connect(':memory:')) as conn:
        conn.execute('PRAGMA foreign_keys = ON')
        conn.execute('CREATE TABLE users(id INTEGER PRIMARY KEY)')
        conn.execute('CREATE TABLE commandes_salaries(id INTEGER PRIMARY KEY, groupe TEXT, description TEXT, quantite INTEGER)')
        conn.execute('CREATE TABLE delegations_missions(mission_key TEXT, delegated_user_id INTEGER)')
        conn.execute("INSERT INTO commandes_salaries VALUES(42, 'commandee', 'Papier historique', 7)")
        conn.execute("INSERT INTO delegations_missions VALUES('suivi_commandes_fournitures', 5)")
        migration.upgrade(conn)
        migration.upgrade(conn)
        assert conn.execute('SELECT * FROM commandes_salaries').fetchall() == [(42, 'commandee', 'Papier historique', 7, None)]
        assert conn.execute('SELECT * FROM delegations_missions').fetchall() == [('suivi_commandes_fournitures', 5)]
        assert conn.execute('SELECT COUNT(*) FROM sites').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM entretien_produits').fetchone()[0] == 0
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
        with pytest.raises(RuntimeError):
            migration.downgrade(conn)


def test_installation_neuve_et_resilience(db):
    from resilience import TABLES_REQUISES
    assert db.execute("SELECT statut FROM schema_migrations WHERE version = '0079'").fetchone()[0] == 'ok'
    for table in TABLES_REQUISES['0079']:
        assert db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table,)).fetchone()
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_schema_refuse_lignes_entre_deux_sites(db, organisation, resp_client):
    besoin(resp_client, organisation)
    did = demande_id(db)
    db.execute('PRAGMA foreign_keys = ON')
    with pytest.raises(sqlite3.IntegrityError):
        db.execute('''INSERT INTO entretien_lignes(demande_id,site_id,produit_id,produit_nom,unite,quantite)
            VALUES (?, ?, ?, 'Produit étranger', 'paquet', 1)''',
            (did, organisation['s1'], organisation['p2']))
    db.rollback()


def test_sites_configuration_et_controle_revision(admin_client, db, sample_users):
    assert admin_client.post('/sites', data={'action': 'creer', 'nom': 'Cyprian'}).status_code == 303
    site = db.execute('SELECT * FROM sites').fetchone()
    payload = {'action': 'modifier', 'site_id': site['id'], 'revision': 1,
               'nom': 'Cyprian', 'actif': 1, 'membres': [sample_users['salarie_id']],
               'responsable_fournitures': sample_users['responsable_id']}
    assert admin_client.post('/sites', data=payload).status_code == 303
    assert db.execute('SELECT revision FROM sites').fetchone()[0] == 2
    assert db.execute('SELECT user_id FROM sites_utilisateurs').fetchone()[0] == sample_users['salarie_id']
    assert db.execute('SELECT user_id FROM sites_responsables_modules').fetchone()[0] == sample_users['responsable_id']
    payload['nom'] = 'Modification périmée'
    assert admin_client.post('/sites', data=payload).status_code == 303
    assert db.execute('SELECT nom FROM sites').fetchone()[0] == 'Cyprian'


@pytest.mark.parametrize('nom', ['', 'x' * 101, '   '])
def test_site_nom_invalide(admin_client, db, nom):
    admin_client.post('/sites', data={'action': 'creer', 'nom': nom})
    assert db.execute('SELECT COUNT(*) FROM sites').fetchone()[0] == 0


def test_site_nom_duplique_et_compte_inactif_refuses(admin_client, db, organisation):
    admin_client.post('/sites', data={'action': 'creer', 'nom': 'cyprian'})
    assert db.execute('SELECT COUNT(*) FROM sites').fetchone()[0] == 2
    db.execute('UPDATE users SET actif = 0 WHERE id = ?', (organisation['autre'],))
    db.commit()
    admin_client.post('/sites', data={'action': 'modifier', 'site_id': organisation['s1'], 'revision': 1,
        'nom': 'Cyprian', 'actif': 1, 'responsable_entretien': organisation['autre']})
    assert db.execute('SELECT user_id FROM sites_responsables_modules WHERE site_id = ? AND module = ?',
        (organisation['s1'], 'entretien')).fetchone()[0] == organisation['entretien1']


@pytest.mark.parametrize('url', ['/sites', '/produits-entretien', '/produits-entretien/parametres'])
def test_non_connecte_refuse(client, url):
    response = client.get(url)
    assert response.status_code == 302
    assert '/login' in response.location


@pytest.mark.parametrize('url', ['/sites', '/produits-entretien', '/produits-entretien/parametres'])
def test_prestataire_refuse(prestataire_client, url):
    assert prestataire_client.get(url).status_code == 403


def test_sites_admin_uniquement(app, sample_users):
    auth_client = acteur(app, 'salarie_test', 'sal123')
    resp_client = acteur(app, 'resp_test', 'resp123')
    comptable_client = acteur(app, 'compta_test', 'compta123')
    assert auth_client.get('/sites').status_code == 403
    assert resp_client.post('/sites', data={'action': 'creer', 'nom': 'Non autorisé'}).status_code == 403
    assert comptable_client.get('/sites').status_code == 200


def test_fournitures_deux_files_et_aucun_pouvoir_croise(app, auth_client, resp_client, db, organisation):
    auth_client = acteur(app, 'salarie_test', 'sal123')
    resp_client = acteur(app, 'resp_test', 'resp123')
    org = organisation
    assert auth_client.post('/commandes-salaries', data={'description': 'Papier Cyprian', 'site_id': org['s1']}).status_code == 303
    assert resp_client.post('/commandes-salaries', data={'description': 'Papier Brosses', 'site_id': org['s2']}).status_code == 303
    c1, c2 = db.execute('SELECT id FROM commandes_salaries ORDER BY id').fetchall()
    four1, four2 = acteur(app, 'four1'), acteur(app, 'four2')
    assert 'Papier Cyprian' in four1.get('/commandes-salaries').get_data(as_text=True)
    assert 'Papier Brosses' not in four1.get('/commandes-salaries').get_data(as_text=True)
    assert 'Papier Brosses' in four2.get('/commandes-salaries').get_data(as_text=True)
    assert four1.post(f'/commandes-salaries/{c2[0]}/statut', data={'groupe': 'commandee'}).status_code == 403
    assert four1.post(f'/commandes-salaries/{c1[0]}/statut', data={'groupe': 'commandee'}).status_code == 302
    assert db.execute('SELECT groupe FROM commandes_salaries WHERE id = ?', (c2[0],)).fetchone()[0] == 'en_cours'
    assert four1.get('/commandes-salaries?site_id=' + str(org['s2'])).status_code == 403


def test_fourniture_site_forge_et_omission_refuses(auth_client, db, organisation):
    for site in (organisation['s2'], 99999, '', 'abc', '-1'):
        response = auth_client.post('/commandes-salaries', data={'description': 'Refus', 'site_id': site})
        assert response.status_code in (400, 403)
    assert db.execute('SELECT COUNT(*) FROM commandes_salaries').fetchone()[0] == 0


def test_salarie_multisite_ne_voit_que_ses_demandes(app, auth_client, db, organisation):
    org = organisation
    db.execute('INSERT INTO sites_utilisateurs (site_id,user_id) VALUES (?,?)', (org['s2'], org['salarie']))
    db.execute("INSERT INTO commandes_salaries(user_id,date_demande,description,site_id) VALUES (?, '2026-10-14', 'Demande privée collègue', ?)",
               (org['demandeur'], org['s2']))
    db.commit()
    auth_client.post('/commandes-salaries', data={'description': 'Mes Brosses', 'site_id': org['s2']})
    html = auth_client.get('/commandes-salaries').get_data(as_text=True)
    assert 'Mes Brosses' in html and 'Demande privée collègue' not in html


def test_ancienne_delegation_reste_globale(app, db, organisation, sample_users, auth_client):
    org = organisation
    db.execute('INSERT INTO delegations_missions(mission_key,delegated_user_id,delegated_by_user_id) VALUES (?, ?, ?)',
               ('suivi_commandes_fournitures', org['manager1'], sample_users['directeur_id']))
    did = db.execute("INSERT INTO commandes_salaries(user_id,date_demande,description) VALUES (?, '2026-10-14', 'Ancienne globale')", (org['salarie'],)).lastrowid
    db.commit()
    auth_client.post('/commandes-salaries', data={'description': 'Nouvelle Brosses', 'site_id': org['s2']})
    # La création sur le mauvais site est refusée, même à un ancien délégataire.
    four1 = acteur(app, 'four1')
    assert four1.post('/commandes-salaries', data={'description': 'Refus nouvelle', 'site_id': org['s2']}).status_code == 403
    html = four1.get('/commandes-salaries').get_data(as_text=True)
    assert 'Ancienne globale' in html
    assert four1.post(f'/commandes-salaries/{did}/statut', data={'groupe': 'commandee'}).status_code == 302


def test_retrait_responsable_et_archivage_effectifs_sans_reconnexion(app, auth_client, db, organisation):
    org = organisation
    auth_client.post('/commandes-salaries', data={'description': 'À protéger', 'site_id': org['s1']})
    did = db.execute('SELECT id FROM commandes_salaries').fetchone()[0]
    four1 = acteur(app, 'four1')
    db.execute("DELETE FROM sites_responsables_modules WHERE site_id = ? AND module = 'fournitures'", (org['s1'],))
    db.commit()
    assert four1.post(f'/commandes-salaries/{did}/statut', data={'groupe': 'commandee'}).status_code == 403
    assert 'À protéger' not in four1.get('/commandes-salaries').get_data(as_text=True)
    db.execute('UPDATE sites SET actif = 0')
    db.commit()
    assert auth_client.post('/commandes-salaries', data={'description': 'Fermé', 'site_id': org['s1']}).status_code == 403
    assert auth_client.post('/commandes-salaries', data={'description': 'Pas de retour global'}).status_code == 403
    assert 'À protéger' in auth_client.get('/commandes-salaries').get_data(as_text=True)


def test_entretien_catalogue_et_saisie_sans_validation(resp_client, db, organisation):
    html = resp_client.get('/produits-entretien').get_data(as_text=True)
    assert 'Nouvelle demande' in html and 'Lavettes roses' in html
    assert 'Sacs poubelle 100 litres' in html and 'Sacs poubelle 10 litres' in html
    assert db.execute('SELECT COUNT(*) FROM entretien_produits WHERE site_id = ?', (organisation['s1'],)).fetchone()[0] == 22
    assert besoin(resp_client, organisation).status_code == 303
    demande = db.execute('SELECT * FROM entretien_demandes').fetchone()
    assert demande['statut'] == 'en_cours' and demande['lieu_nom'] == 'Gribouille'
    assert demande['user_id'] == organisation['demandeur']
    ligne = db.execute('SELECT * FROM entretien_lignes').fetchone()
    assert (ligne['quantite'], ligne['produit_nom'], ligne['unite']) == (2, 'Lessive', 'bidon')


@pytest.mark.parametrize('qty', ['-1', '1.5', '10000', 'abc', 'NaN', '1e3', '0', ''])
def test_quantites_invalides_et_demande_vide_refusees(resp_client, db, organisation, qty):
    besoin(resp_client, organisation, quantite=qty)
    assert db.execute('SELECT COUNT(*) FROM entretien_demandes').fetchone()[0] == 0


def test_forgery_lieu_produit_et_separation_modules(app, auth_client, resp_client, db, organisation):
    auth_client = acteur(app, 'salarie_test', 'sal123')
    resp_client = acteur(app, 'resp_test', 'resp123')
    org = organisation
    assert besoin(resp_client, org, lieu='l2').status_code == 403
    assert besoin(auth_client, org, lieu='l1').status_code == 403
    besoin(resp_client, org, produit='p2')
    assert db.execute('SELECT COUNT(*) FROM entretien_demandes').fetchone()[0] == 0
    four1 = acteur(app, 'four1')
    assert four1.get('/produits-entretien').status_code == 403
    assert four1.get('/produits-entretien/parametres').status_code == 403
    ent1 = acteur(app, 'ent1')
    assert besoin(ent1, org).status_code == 403
    assert ent1.post('/commandes-salaries', data={'description': 'Pas de droit implicite', 'site_id': org['s1']}).status_code == 403


def test_demande_idempotente_et_contenu_different_refuse(resp_client, db, organisation):
    besoin(resp_client, organisation)
    besoin(resp_client, organisation)
    besoin(resp_client, organisation, quantite='3')
    assert db.execute('SELECT COUNT(*) FROM entretien_demandes').fetchone()[0] == 1
    assert db.execute('SELECT quantite FROM entretien_lignes').fetchone()[0] == 2


def test_demande_sans_cle_et_note_trop_longue_refusees(resp_client, db, organisation):
    besoin(resp_client, organisation, cle='invalide')
    besoin(resp_client, organisation, commentaire='x' * 1001)
    assert db.execute('SELECT COUNT(*) FROM entretien_demandes').fetchone()[0] == 0


def test_regroupement_commande_et_reception_notification(app, auth_client, resp_client, db, organisation):
    auth_client = acteur(app, 'salarie_test', 'sal123')
    resp_client = acteur(app, 'resp_test', 'resp123')
    org = organisation
    besoin(resp_client, org)
    premier = demande_id(db)
    besoin(auth_client, org, lieu='l2', cle='b' * 32, quantite='3')
    second = demande_id(db)
    ent1 = acteur(app, 'ent1')
    html = ent1.get('/produits-entretien').get_data(as_text=True)
    assert 'À commander — Cyprian' in html and '5 × bidon' in html
    assert ent1.post('/produits-entretien/commander', data={'site_id': org['s1'], 'demandes': [premier, second]}).status_code == 303
    assert db.execute("SELECT COUNT(*) FROM entretien_demandes WHERE statut='commandee'").fetchone()[0] == 2
    # Rejeu du regroupement : aucun changement de révision.
    ent1.post('/produits-entretien/commander', data={'site_id': org['s1'], 'demandes': [premier, second]})
    assert db.execute('SELECT MAX(revision) FROM entretien_demandes').fetchone()[0] == 2
    assert recevoir(ent1, premier, note='Un bidon manquant').status_code == 303
    avis = db.execute('SELECT * FROM entretien_notifications').fetchone()
    assert avis['user_id'] == org['demandeur'] and avis['lu_le'] is None
    assert 'Produits d’entretien disponibles — Gribouille' in resp_client.get('/produits-entretien').get_data(as_text=True)
    assert 'Un bidon manquant' in resp_client.get('/produits-entretien').get_data(as_text=True)
    assert 'Produits d’entretien disponibles — Gribouille' not in auth_client.get('/produits-entretien').get_data(as_text=True)
    resp_client.post(f'/produits-entretien/{premier}/lu')
    assert db.execute('SELECT lu_le FROM entretien_notifications').fetchone()[0] is not None
    recevoir(ent1, premier, note='Un bidon manquant')
    assert db.execute('SELECT COUNT(*) FROM entretien_notifications').fetchone()[0] == 1
    assert db.execute('SELECT lu_le FROM entretien_notifications').fetchone()[0] is not None


def test_refus_reception_avant_commande_et_revision_perimee(app, resp_client, db, organisation):
    besoin(resp_client, organisation)
    did = demande_id(db)
    ent1 = acteur(app, 'ent1')
    recevoir(ent1, did, revision=1)
    assert db.execute('SELECT statut FROM entretien_demandes').fetchone()[0] == 'en_cours'
    passer_commande(ent1, did)
    recevoir(ent1, did, revision=1)
    assert db.execute('SELECT statut FROM entretien_demandes').fetchone()[0] == 'commandee'
    assert db.execute('SELECT COUNT(*) FROM entretien_notifications').fetchone()[0] == 0


def test_entretien_lecture_et_actions_inter_sites_refusees(app, resp_client, db, organisation):
    besoin(resp_client, organisation, commentaire='Note privée Cyprian')
    did = demande_id(db)
    ent2 = acteur(app, 'ent2')
    assert 'Note privée Cyprian' not in ent2.get('/produits-entretien').get_data(as_text=True)
    assert passer_commande(ent2, did).status_code == 403
    assert recevoir(ent2, did).status_code == 403
    assert ent2.post(f'/produits-entretien/{did}/lu').status_code == 403
    assert ent2.get('/produits-entretien/parametres?site_id=' + str(organisation['s1'])).status_code == 403
    assert ent2.post('/produits-entretien/parametres', data={'site_id': organisation['s1'], 'action': 'catalogue_initial'}).status_code == 403


def test_regroupement_forge_atomique(app, resp_client, db, organisation):
    besoin(resp_client, organisation)
    did = demande_id(db)
    ent1 = acteur(app, 'ent1')
    assert ent1.post('/produits-entretien/commander', data={'site_id': organisation['s1'], 'demandes': [did, 999999]}).status_code == 403
    assert db.execute('SELECT statut FROM entretien_demandes').fetchone()[0] == 'en_cours'


def test_catalogue_modifiable_sans_modifier_historique(app, resp_client, db, organisation):
    org = organisation
    besoin(resp_client, org)
    ent1 = acteur(app, 'ent1')
    data = {'site_id': org['s1'], 'action': 'produit', 'id': org['p1'],
            'revision': 1, 'nom': 'Lessive nouvelle', 'unite': 'carton', 'actif': 1}
    assert ent1.post('/produits-entretien/parametres', data=data).status_code == 303
    assert db.execute('SELECT produit_nom,unite FROM entretien_lignes').fetchone()[:] == ('Lessive', 'bidon')
    data['nom'] = 'Ancien formulaire'
    ent1.post('/produits-entretien/parametres', data=data)
    assert db.execute('SELECT nom FROM entretien_produits WHERE id = ?', (org['p1'],)).fetchone()[0] == 'Lessive nouvelle'


def test_archiver_produit_et_rejouer_catalogue_ne_reactive_pas(app, db, organisation):
    org = organisation
    ent1 = acteur(app, 'ent1')
    ent1.post('/produits-entretien/parametres', data={'site_id': org['s1'], 'action': 'produit',
        'id': org['p1'], 'revision': 1, 'nom': 'Lessive', 'unite': 'bidon'})
    ent1.post('/produits-entretien/parametres', data={'site_id': org['s1'], 'action': 'catalogue_initial'})
    assert db.execute('SELECT actif FROM entretien_produits WHERE id = ?', (org['p1'],)).fetchone()[0] == 0
    assert db.execute('SELECT COUNT(*) FROM entretien_produits WHERE site_id = ?', (org['s1'],)).fetchone()[0] == 22


def test_parametres_id_produit_etranger_refuse(app, db, organisation):
    org = organisation
    ent1 = acteur(app, 'ent1')
    assert ent1.post('/produits-entretien/parametres', data={'site_id': org['s1'], 'action': 'produit',
        'id': org['p2'], 'revision': 1, 'nom': 'Pirate', 'unite': 'bidon'}).status_code == 403
    assert db.execute('SELECT nom FROM entretien_produits WHERE id = ?', (org['p2'],)).fetchone()[0] == 'Lessive'


def test_retrait_demandeur_et_responsable_effectif(app, resp_client, db, organisation):
    org = organisation
    besoin(resp_client, org, commentaire='Information retirée')
    did = demande_id(db)
    ent1 = acteur(app, 'ent1')
    db.execute('UPDATE entretien_lieux SET demandeur_id = ? WHERE id = ?', (org['autre'], org['l1']))
    db.execute("DELETE FROM sites_responsables_modules WHERE site_id = ? AND module = 'entretien'", (org['s1'],))
    db.commit()
    assert resp_client.get('/produits-entretien').status_code == 403
    assert besoin(resp_client, org, cle='c' * 32).status_code == 403
    assert passer_commande(ent1, did).status_code == 403


def test_reception_notifie_titulaire_courant(app, resp_client, db, organisation):
    org = organisation
    besoin(resp_client, org)
    did = demande_id(db)
    db.execute('UPDATE entretien_lieux SET demandeur_id = ? WHERE id = ?', (org['autre'], org['l1']))
    db.commit()
    ent1 = acteur(app, 'ent1')
    passer_commande(ent1, did)
    recevoir(ent1, did)
    assert db.execute('SELECT user_id FROM entretien_notifications').fetchone()[0] == org['autre']


def test_reception_rollback_si_notification_echoue(app, resp_client, db, organisation):
    besoin(resp_client, organisation)
    did = demande_id(db)
    ent1 = acteur(app, 'ent1')
    passer_commande(ent1, did)
    db.execute("CREATE TRIGGER echec_notification BEFORE INSERT ON entretien_notifications BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        recevoir(ent1, did)
    assert db.execute('SELECT statut FROM entretien_demandes').fetchone()[0] == 'commandee'
    assert db.execute('SELECT COUNT(*) FROM entretien_notifications').fetchone()[0] == 0


def test_reception_concurrente_une_seule_notification(app, resp_client, db, organisation):
    besoin(resp_client, organisation)
    did = demande_id(db)
    clients = [acteur(app, 'ent1'), acteur(app, 'ent1')]
    passer_commande(clients[0], did)
    barriere = Barrier(2)

    def go(client):
        barriere.wait(timeout=10)
        return recevoir(client, did).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(go, clients)) == [303, 303]
    assert db.execute('SELECT revision FROM entretien_demandes').fetchone()[0] == 3
    assert db.execute('SELECT COUNT(*) FROM entretien_notifications').fetchone()[0] == 1


def test_annulation_terminale_et_historique_conserve(app, resp_client, db, organisation):
    besoin(resp_client, organisation)
    did = demande_id(db)
    ent1 = acteur(app, 'ent1')
    ent1.post(f'/produits-entretien/{did}/statut', data={'statut': 'annulee', 'revision': 1})
    passer_commande(ent1, did, revision=2)
    assert db.execute('SELECT statut FROM entretien_demandes').fetchone()[0] == 'annulee'
    assert db.execute('SELECT COUNT(*) FROM entretien_lignes').fetchone()[0] == 1


def test_xss_echappe_et_csrf_reel(app, admin_client, resp_client, db, organisation):
    besoin(resp_client, organisation, commentaire='<script>alert("non")</script>')
    assert '<script>alert("non")</script>' not in resp_client.get('/produits-entretien').get_data(as_text=True)
    assert '&lt;script&gt;' in resp_client.get('/produits-entretien').get_data(as_text=True)
    admin_client = acteur(app, 'admin', 'Admin1234')
    valid_client = acteur(app, 'resp_test', 'resp123')
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        assert admin_client.post('/sites', data={'action': 'creer', 'nom': 'CSRF absent'}).status_code == 302
        assert besoin(resp_client, organisation, cle='b' * 32).status_code == 302
        assert db.execute("SELECT COUNT(*) FROM sites WHERE nom = 'CSRF absent'").fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM entretien_demandes').fetchone()[0] == 1
        # La fixture db garde un app_context : ne pas réutiliser le jeton g
        # généré lors du rendu d'un autre client dans ce même test.
        from flask import g
        g.pop('csrf_token', None)
        html = valid_client.get('/produits-entretien').get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]+)"', html)[1]
        assert besoin(valid_client, organisation, cle='c' * 32, csrf_token=token).status_code == 303
    finally:
        app.config['WTF_CSRF_ENABLED'] = False


def test_navigation_et_flux_par_site(app, db, organisation):
    from dashboard_actions import _fournitures_en_attente, _entretien_en_attente
    from interface_flux import carte_pour_utilisateur
    from search_palette import construire_suggestions
    from datetime import date
    org = organisation
    db.executemany("INSERT INTO commandes_salaries(user_id,date_demande,description,site_id) VALUES (?, '2026-10-14', ?, ?)",
        [(org['salarie'], 'Cyprian seulement', org['s1']), (org['demandeur'], 'Brosses seulement', org['s2'])])
    db.commit()
    with app.test_request_context():
        actions = _fournitures_en_attente(db, 'salarie', org['manager1'], date(2026, 10, 14))
        assert len(actions) == 1 and 'Cyprian seulement' in actions[0]['titre']
        assert 'site_id=' + str(org['s1']) in actions[0]['lien']
        carte = carte_pour_utilisateur('salarie', org['manager1'])
        suggestions = construire_suggestions(carte, 'commandes Cyprian')
        assert suggestions[0]['url'].endswith('site_id=' + str(org['s1']))
        assert not any('Brosses' in s['titre'] for s in suggestions)
        assert not _entretien_en_attente(db, 'salarie', org['manager1'], date(2026, 10, 14))


def test_direction_filtre_historique_site_archive(admin_client, db, organisation):
    org = organisation
    db.execute("INSERT INTO commandes_salaries(user_id,date_demande,description,site_id) VALUES (?, '2026-10-14', 'Historique du site archivé', ?)",
               (org['salarie'], org['s1']))
    db.execute('UPDATE sites SET actif = 0 WHERE id = ?', (org['s1'],))
    db.commit()
    response = admin_client.get('/commandes-salaries?site_id=' + str(org['s1']))
    assert response.status_code == 200
    assert 'Historique du site archivé' in response.get_data(as_text=True)


def test_en_tete_flux_identifie_un_seul_site(app, organisation):
    client = acteur(app, 'four1')
    html = client.get('/commandes-salaries?site_id=' + str(organisation['s1'])).get_data(as_text=True)
    assert '<h1>Commandes Cyprian</h1>' in html
    assert html.count('flx-chip-actif') == 1


def test_demande_apres_ouverture_regroupement_reste_a_commander(app, resp_client, auth_client, db, organisation):
    resp_client = acteur(app, 'resp_test', 'resp123')
    auth_client = acteur(app, 'salarie_test', 'sal123')
    besoin(resp_client, organisation)
    premier = demande_id(db)
    ent1 = acteur(app, 'ent1')
    ent1.get('/produits-entretien')
    besoin(auth_client, organisation, lieu='l2', cle='b' * 32)
    second = demande_id(db)
    ent1.post('/produits-entretien/commander', data={'site_id': organisation['s1'], 'demandes': [premier]})
    assert db.execute('SELECT statut FROM entretien_demandes WHERE id = ?', (second,)).fetchone()[0] == 'en_cours'


def test_compte_inactif_sans_fausse_confirmation_notification(app, resp_client, db, organisation):
    besoin(resp_client, organisation)
    did = demande_id(db)
    ent1 = acteur(app, 'ent1')
    passer_commande(ent1, did)
    db.execute('UPDATE users SET actif = 0 WHERE id = ?', (organisation['demandeur'],))
    db.commit()
    recevoir(ent1, did)
    assert db.execute('SELECT COUNT(*) FROM entretien_notifications').fetchone()[0] == 0
    assert db.execute('SELECT statut FROM entretien_demandes').fetchone()[0] == 'recue'
    html = ent1.get('/produits-entretien').get_data(as_text=True)
    assert 'Aucun avis envoyé' in html


def test_permissions_recontrolees_apres_garde_global(app, resp_client, db, organisation, monkeypatch):
    besoin(resp_client, organisation)
    did = demande_id(db)
    ent1 = acteur(app, 'ent1')
    import blueprints.entretien as module
    transaction = module._transaction

    def retirer_avant_verrou(conn):
        # Le garde global a déjà accepté le cookie ; le droit métier doit
        # néanmoins être lu dans la connexion qui va traiter la commande.
        db.execute("DELETE FROM sites_responsables_modules WHERE site_id = ? AND module = 'entretien'",
                   (organisation['s1'],))
        db.commit()
        return transaction(conn)

    monkeypatch.setattr(module, '_transaction', retirer_avant_verrou)
    assert passer_commande(ent1, did).status_code == 403
    assert db.execute('SELECT statut FROM entretien_demandes').fetchone()[0] == 'en_cours'


def test_lieu_archive_et_produit_archive_ferment_saisie(app, resp_client, db, organisation):
    org = organisation
    db.execute('UPDATE entretien_produits SET actif = 0 WHERE id = ?', (org['p1'],))
    db.commit()
    besoin(resp_client, org)
    assert db.execute('SELECT COUNT(*) FROM entretien_demandes').fetchone()[0] == 0
    db.execute('UPDATE entretien_lieux SET actif = 0 WHERE id = ?', (org['l1'],))
    db.commit()
    assert besoin(resp_client, org).status_code == 403


def test_notification_autrui_ne_peut_pas_etre_marquee_lue(app, resp_client, db, organisation):
    besoin(resp_client, organisation)
    did = demande_id(db)
    ent1 = acteur(app, 'ent1')
    passer_commande(ent1, did)
    recevoir(ent1, did)
    # Le gestionnaire peut lire la demande, mais son clic ne doit pas
    # acquitter l'avis adressé au demandeur.
    ent1.post(f'/produits-entretien/{did}/lu')
    assert db.execute('SELECT lu_le FROM entretien_notifications').fetchone()[0] is None


def test_nouvelle_attribution_lieu_inactive_mauvais_profil_refusee(app, db, organisation):
    org = organisation
    ent1 = acteur(app, 'ent1')
    db.execute("UPDATE users SET profil = 'prestataire' WHERE id = ?", (org['autre'],))
    db.commit()
    ent1.post('/produits-entretien/parametres', data={'site_id': org['s1'], 'action': 'lieu',
        'nom': 'Lieu interdit', 'demandeur_id': org['autre']})
    assert not db.execute("SELECT 1 FROM entretien_lieux WHERE nom = 'Lieu interdit'").fetchone()


def test_ancien_catalogue_ne_change_pas_silencieusement_les_conditionnements(app, resp_client, db, organisation):
    org = organisation
    resp_client.get('/produits-entretien')
    ent1 = acteur(app, 'ent1')
    ent1.post('/produits-entretien/parametres', data={'site_id': org['s1'], 'action': 'produit',
        'id': org['p1'], 'revision': 1, 'nom': 'Lessive', 'unite': 'carton de 12 bidons', 'actif': 1})
    besoin(resp_client, org)
    assert db.execute('SELECT COUNT(*) FROM entretien_demandes').fetchone()[0] == 0
    besoin(resp_client, org, **{f"revision_produit_{org['p1']}": '2'})
    assert db.execute('SELECT unite FROM entretien_lignes').fetchone()[0] == 'carton de 12 bidons'


def test_ancien_formulaire_lieu_refuse(app, resp_client, db, organisation):
    org = organisation
    ent1 = acteur(app, 'ent1')
    ent1.post('/produits-entretien/parametres', data={'site_id': org['s1'], 'action': 'lieu',
        'id': org['l1'], 'revision': 1, 'nom': 'Gribouille renommée', 'demandeur_id': org['demandeur'], 'actif': 1})
    besoin(resp_client, org)
    assert db.execute('SELECT COUNT(*) FROM entretien_demandes').fetchone()[0] == 0
    besoin(resp_client, org, lieu_revision='2')
    assert db.execute('SELECT lieu_nom FROM entretien_demandes').fetchone()[0] == 'Gribouille renommée'
