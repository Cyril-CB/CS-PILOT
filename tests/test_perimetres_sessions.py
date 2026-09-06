"""Régressions B5/B6 : vrais formulaires de connexion et effets en base."""
import pytest
from tests.conftest import _login
from tests.test_equipe_responsable import _creer_agent_transverse, _creer_responsable_tiers


def _demande(db, uid, nature):
    table = 'demandes_conges' if nature == 'conge' else 'demandes_recup'
    extra = ", type_conge" if nature == 'conge' else ", nb_heures, type_demande"
    valeur = 'Congé payé' if nature == 'conge' else ('partielle' if nature == 'partielle' else 'journee')
    placeholder = "?" if nature == "conge" else "7, ?"
    cur = db.execute(f"INSERT INTO {table} (user_id, date_debut, date_fin, nb_jours, statut{extra}) "
                     f"VALUES (?, '2026-05-04', '2026-05-04', 1, 'en_attente_responsable', {placeholder})", (uid, valeur))
    db.commit()
    return table, cur.lastrowid


def _etat(db):
    tables = ('demandes_conges', 'demandes_recup', 'absences', 'heures_reelles',
              'users', 'historique_modifications', 'journal_actions', 'validations',
              'fiches_versions', 'fiches_evenements')
    return {t: [tuple(r) for r in db.execute(f'SELECT * FROM {t} ORDER BY rowid')] for t in tables}


@pytest.mark.parametrize('nature', ['conge', 'recup', 'partielle'])
@pytest.mark.parametrize('action', ['valider', 'refuser'])
def test_demande_hors_equipe_sans_effet(client, db, sample_users, monkeypatch, nature, action):
    uid, _ = _creer_agent_transverse(db, sample_users)
    _creer_responsable_tiers(db)
    table, did = _demande(db, uid, nature)
    _login(client, 'resp_tiers', 'tiers123')
    page = client.get('/validation_demandes_recup').get_data(as_text=True)
    assert 'Agent Paul' not in page
    notifications = []
    monkeypatch.setattr('blueprints.recup.is_email_configured', lambda: notifications.append(True) or True)
    avant = _etat(db)
    r = client.post('/validation_demandes_recup', data={
        'demande_id': did, 'demande_type': 'conge' if nature == 'conge' else 'recup',
        'action': action, 'motif_refus': 'Refus non autorisé',
    })
    assert r.status_code == 302
    assert _etat(db) == avant
    assert notifications == []


def _modifier(client, db, uid, **changements):
    user = dict(db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone())
    champs = ('nom', 'prenom', 'login', 'profil', 'secteur_id', 'responsable_id', 'solde_initial',
              'date_entree', 'cp_acquis', 'cp_a_prendre', 'cp_pris', 'cc_solde')
    data = {k: user[k] if user[k] is not None else '' for k in champs}
    data.update(changements)
    return client.post(f'/modifier_user/{uid}', data=data)


@pytest.mark.parametrize('premiere_methode', ['GET', 'POST'])
def test_desactivation_deux_sessions(app, db, sample_users, premiere_methode):
    a, b, gestion = [app.test_client() for _ in range(3)]
    for c in (a, b):
        _login(c, 'admin', 'Admin1234')
        assert c.get('/gestion_users').status_code == 200
    _login(gestion, 'compta_test', 'compta123')
    gestion.post(f"/toggle_user/{sample_users['directeur_id']}")
    assert db.execute('SELECT actif FROM users WHERE id=?', (sample_users['directeur_id'],)).fetchone()[0] == 0
    for c in (a, b):
        avant = _etat(db)
        if premiere_methode == 'GET':
            assert c.get('/gestion_users').status_code == 302
        c.post(f"/toggle_user/{sample_users['salarie_id']}")
        assert _etat(db) == avant
        with c.session_transaction() as sess:
            assert 'user_id' not in sess


def test_retrogradation_post(app, db, sample_users):
    directeur, gestion = app.test_client(), app.test_client()
    _login(directeur, 'admin', 'Admin1234')
    _login(gestion, 'compta_test', 'compta123')
    _modifier(gestion, db, sample_users['directeur_id'], profil='salarie')
    assert db.execute('SELECT profil FROM users WHERE id=?', (sample_users['directeur_id'],)).fetchone()[0] == 'salarie'
    avant = _etat(db)
    directeur.post(f"/toggle_user/{sample_users['salarie_id']}")
    assert _etat(db) == avant


@pytest.mark.parametrize('nature', ['conge', 'recup', 'partielle'])
@pytest.mark.parametrize('action', ['valider', 'refuser'])
@pytest.mark.parametrize('lien', ['direct_hors_secteur', 'secteur_seul'])
def test_decision_equipe_legitime(resp_client, db, sample_users, nature, action, lien):
    if lien == 'direct_hors_secteur':
        uid, _ = _creer_agent_transverse(db, sample_users)
    else:
        uid = sample_users['salarie_id']
        db.execute('UPDATE users SET responsable_id=NULL WHERE id=?', (uid,))
        db.commit()
    table, did = _demande(db, uid, nature)
    r = resp_client.post('/validation_demandes_recup', data={
        'demande_id': did, 'demande_type': 'conge' if nature == 'conge' else 'recup',
        'action': action, 'motif_refus': 'Indisponibilité',
    })
    assert r.status_code == 302
    demande = db.execute(f'SELECT * FROM {table} WHERE id=?', (did,)).fetchone()
    assert demande['statut'] == ('en_attente_direction' if action == 'valider' else 'refusee')
    if action == 'valider':
        assert demande['validation_responsable'] == 'Marie Dupont'
    else:
        assert demande['refuse_par'] == sample_users['responsable_id']
    # Décision intermédiaire : aucun report prématuré dans les compteurs/calendrier.
    assert db.execute('SELECT COUNT(*) FROM absences').fetchone()[0] == 0
    assert db.execute('SELECT COUNT(*) FROM heures_reelles').fetchone()[0] == 0


@pytest.mark.parametrize('nature', ['conge', 'recup'])
@pytest.mark.parametrize('statut', ['en_attente_direction', 'validee', 'refusee'])
@pytest.mark.parametrize('action', ['valider', 'refuser'])
def test_responsable_ne_retraite_pas_la_demande(resp_client, db, sample_users, nature, statut, action):
    table, did = _demande(db, sample_users['salarie_id'], nature)
    db.execute(f'UPDATE {table} SET statut=? WHERE id=?', (statut, did))
    db.commit()
    avant = _etat(db)
    resp_client.post('/validation_demandes_recup', data={
        'demande_id': did, 'demande_type': nature, 'action': action, 'motif_refus': 'Non',
    })
    assert _etat(db) == avant


@pytest.mark.parametrize('champ,valeur', [('action', 'autre'), ('demande_type', 'autre'),
                                        ('demande_id', 'texte'), ('motif_refus', '')])
def test_decision_parametres_invalides(resp_client, db, sample_users, champ, valeur):
    _, did = _demande(db, sample_users['salarie_id'], 'conge')
    data = dict(demande_id=did, demande_type='conge', action='refuser', motif_refus='Non')
    data[champ] = valeur
    avant = _etat(db)
    resp_client.post('/validation_demandes_recup', data=data)
    assert _etat(db) == avant


@pytest.mark.parametrize('route', ['/gestion_users', '/infos_salaries', '/prepa_paie',
                                   '/dashboard_direction', '/dashboard_comptable', '/exportation'])
@pytest.mark.parametrize('identifiants', [('admin', 'Admin1234', 'directeur_id'),
                                        ('compta_test', 'compta123', 'comptable_id')])
def test_anciens_roles_refuses_sur_get(app, db, sample_users, route, identifiants):
    c = app.test_client()
    _login(c, *identifiants[:2])
    # La réduction est déjà testée via le formulaire ; ici, couverture du garde central.
    db.execute("UPDATE users SET profil='salarie' WHERE id=?", (sample_users[identifiants[2]],))
    db.commit()
    r = c.get(route)
    assert r.status_code == 302
    assert r.headers['Location'].startswith('/dashboard')
    with c.session_transaction() as sess:
        assert sess['profil'] == 'salarie'


def test_reactivation_ne_ressuscite_pas_cookie(app, db, sample_users):
    ancien, gestion = app.test_client(), app.test_client()
    _login(ancien, 'admin', 'Admin1234')
    _login(gestion, 'compta_test', 'compta123')
    uid = sample_users['directeur_id']
    gestion.post(f'/toggle_user/{uid}')
    gestion.post(f'/toggle_user/{uid}')
    assert ancien.get('/gestion_users').headers['Location'] == '/login'
    _login(ancien, 'admin', 'Admin1234')
    assert ancien.get('/gestion_users').status_code == 200


@pytest.mark.parametrize('nature', ['conge', 'recup'])
@pytest.mark.parametrize('lien', ['direct', 'secteur'])
def test_retrait_perimetre_session_ouverte(app, db, sample_users, nature, lien):
    resp, gestion = app.test_client(), app.test_client()
    uid, _ = _creer_agent_transverse(db, sample_users)
    if lien == 'secteur':
        uid = sample_users['salarie_id']
        db.execute('UPDATE users SET responsable_id=NULL WHERE id=?', (uid,))
        db.commit()
    table, did = _demande(db, uid, nature)
    _login(resp, 'resp_test', 'resp123')
    _login(gestion, 'admin', 'Admin1234')
    if lien == 'direct':
        _modifier(gestion, db, uid, responsable_id='')
    else:
        _modifier(gestion, db, sample_users['responsable_id'], secteur_id='')
    avant = _etat(db)
    resp.post('/validation_demandes_recup', data={'demande_id': did, 'demande_type': nature, 'action': 'valider'})
    assert _etat(db) == avant
    if lien == 'secteur':
        with resp.session_transaction() as sess:
            assert sess['secteur_id'] is None


def test_retrait_delegation_session_ouverte(app, db, sample_users):
    from tests.test_delegation_benevoles import _deleguer, _creer_benevole
    gestion, sal = app.test_client(), app.test_client()
    _login(gestion, 'admin', 'Admin1234')
    _login(sal, 'salarie_test', 'sal123')
    ben = _creer_benevole(app)
    _deleguer(gestion, [sample_users['salarie_id']])
    assert sal.get('/benevoles').status_code == 200
    assert sal.post(f'/api/benevoles/{ben}/modifier', json={'field': 'nom', 'value': 'Autorisé'}).status_code == 200
    _deleguer(gestion, [])
    assert sal.get('/benevoles').status_code == 302
    avant = [tuple(r) for r in db.execute('SELECT * FROM benevoles')]
    assert sal.post(f'/api/benevoles/{ben}/modifier', json={'field': 'nom', 'value': 'Refusé'}).status_code == 403
    assert [tuple(r) for r in db.execute('SELECT * FROM benevoles')] == avant


@pytest.mark.parametrize('methode', ['GET', 'POST'])
def test_changement_obligatoire_relu_en_base(app, db, sample_users, methode):
    c = app.test_client()
    _login(c, 'admin', 'Admin1234')
    db.execute('UPDATE users SET force_password_change=1 WHERE id=?', (sample_users['directeur_id'],))
    db.commit()
    avant = _etat(db)
    r = c.get('/gestion_users') if methode == 'GET' else c.post(f"/toggle_user/{sample_users['salarie_id']}")
    assert r.headers['Location'] == '/changer_mot_de_passe'
    assert _etat(db) == avant
    assert c.get('/changer_mot_de_passe').status_code == 200
    assert c.get('/login').headers['Location'] == '/changer_mot_de_passe'
    assert c.get('/logout', follow_redirects=True).status_code == 200


def test_reset_admin_revoque_deux_sessions(app, db, sample_users):
    a, b, gestion = [app.test_client() for _ in range(3)]
    for c in (a, b):
        _login(c, 'admin', 'Admin1234')
    _login(gestion, 'compta_test', 'compta123')
    _modifier(gestion, db, sample_users['directeur_id'], nouveau_password='Temporaire123!')
    for c in (a, b):
        avant = _etat(db)
        r = c.post(f"/toggle_user/{sample_users['salarie_id']}")
        assert r.headers['Location'] == '/login'
        assert _etat(db) == avant
    a.post('/login', data={'login': 'admin', 'password': 'Temporaire123!'})
    assert a.get('/gestion_users').headers['Location'] == '/changer_mot_de_passe'
    r = a.post('/changer_mot_de_passe', data={'current_password': 'Temporaire123!',
              'new_password': 'Personnel456!', 'password_confirm': 'Personnel456!'})
    assert r.status_code == 302
    assert a.get('/gestion_users').status_code == 200


@pytest.mark.parametrize('envoi_ok', [True, False])
def test_reset_email_revoque_seulement_si_committe(app, db, sample_users, monkeypatch, envoi_ok):
    a, b, public = [app.test_client() for _ in range(3)]
    db.execute("UPDATE users SET email='fictif@example.invalid' WHERE id=?", (sample_users['directeur_id'],))
    db.commit()
    for c in (a, b):
        _login(c, 'admin', 'Admin1234')
    monkeypatch.setattr('blueprints.auth.is_email_configured', lambda: True)
    monkeypatch.setattr('blueprints.auth.envoyer_email', lambda *a: (envoi_ok, 'Test'))
    public.post('/mot-de-passe-oublie', data={'login': 'admin'})
    for c in (a, b):
        r = c.get('/gestion_users')
        assert r.status_code == (302 if envoi_ok else 200)
        if envoi_ok:
            assert r.headers['Location'] == '/login'


def test_changement_personnel_revoque_autres_sessions(app, sample_users):
    a, b = app.test_client(), app.test_client()
    for c in (a, b):
        _login(c, 'admin', 'Admin1234')
    r = a.post('/changer_mot_de_passe', data={'current_password': 'Admin1234',
              'new_password': 'Personnel456!', 'password_confirm': 'Personnel456!'})
    assert r.status_code == 302
    assert a.get('/gestion_users').status_code == 200
    assert b.get('/gestion_users').headers['Location'] == '/login'


@pytest.mark.parametrize('motif', ['ancien_cookie', 'compte_supprime'])
def test_session_invalide_sans_boucle(app, db, sample_users, motif):
    c = app.test_client()
    _login(c, 'admin', 'Admin1234')
    if motif == 'ancien_cookie':
        with c.session_transaction() as sess:
            sess.pop('session_version')
    else:
        db.execute('DELETE FROM users WHERE id=?', (sample_users['directeur_id'],))
        db.commit()
    r = c.get('/gestion_users?next=https://example.invalid', follow_redirects=True)
    assert r.status_code == 200 and r.request.path == '/login'
    assert 'Veuillez vous reconnecter' in r.get_data(as_text=True)
    with c.session_transaction() as sess:
        assert 'user_id' not in sess


def test_migration_sessions_ancienne_base_idempotente():
    import importlib
    import sqlite3
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, actif INTEGER, password TEXT)')
    conn.execute("INSERT INTO users VALUES (1, 1, 'hachage-factice')")
    migration = importlib.import_module('migrations.0066_revocation_sessions')
    migration.upgrade(conn)
    migration.upgrade(conn)
    assert conn.execute('SELECT session_version FROM users').fetchone()[0] == 1
    conn.execute("UPDATE users SET password='autre-hachage-factice' WHERE id=1")
    conn.commit()
    assert conn.execute('SELECT session_version FROM users').fetchone()[0] == 2
    conn.execute('UPDATE users SET actif=0 WHERE id=1')
    conn.rollback()
    assert conn.execute('SELECT session_version FROM users').fetchone()[0] == 2
    conn.close()


def test_schema_neuf_et_trace_revocation(app, db, sample_users):
    assert db.execute("SELECT statut FROM schema_migrations WHERE version='0066'").fetchone()[0] == 'ok'
    a, gestion = app.test_client(), app.test_client()
    _login(a, 'admin', 'Admin1234')
    _login(gestion, 'compta_test', 'compta123')
    gestion.post(f"/toggle_user/{sample_users['directeur_id']}")
    a.get('/gestion_users')
    assert db.execute("SELECT COUNT(*) FROM journal_acces WHERE evenement='session_revoquee'").fetchone()[0] == 1
    details = db.execute("SELECT details FROM journal_actions ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert 'sessions_revoquees=oui' in details


@pytest.mark.parametrize('changement', ['profil', 'actif', 'force', 'proprietaire', 'statut'])
def test_decision_recontrole_apres_garde_global(app, db, sample_users, monkeypatch, changement):
    """Une modification validée après before_request est vue sous le verrou métier."""
    import blueprints.recup as module
    c = app.test_client()
    _login(c, 'resp_test', 'resp123')
    uid = sample_users['salarie_id']
    _, did = _demande(db, uid, 'conge')
    original = module.get_db
    attendu = {}

    def connexion_apres_changement():
        if changement == 'profil':
            db.execute("UPDATE users SET profil='salarie' WHERE id=?", (sample_users['responsable_id'],))
        elif changement == 'actif':
            db.execute('UPDATE users SET actif=0 WHERE id=?', (sample_users['responsable_id'],))
        elif changement == 'force':
            db.execute('UPDATE users SET force_password_change=1 WHERE id=?', (sample_users['responsable_id'],))
        elif changement == 'proprietaire':
            db.execute('UPDATE demandes_conges SET user_id=? WHERE id=?', (sample_users['comptable_id'], did))
        else:
            db.execute("UPDATE demandes_conges SET statut='refusee' WHERE id=?", (did,))
        db.commit()
        attendu.update(_etat(db))
        return original()

    monkeypatch.setattr(module, 'get_db', connexion_apres_changement)
    c.post('/validation_demandes_recup', data={'demande_id': did, 'demande_type': 'conge', 'action': 'valider'})
    assert _etat(db) == attendu


def test_verrou_empeche_changement_equipe_entre_controle_et_decision(
        app, db, sample_users, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import sqlite3
    import blueprints.recup as module
    import database
    c = app.test_client()
    _login(c, 'resp_test', 'resp123')
    _, did = _demande(db, sample_users['salarie_id'], 'conge')
    original = module.est_dans_equipe_responsable

    def mutation_concurrente():
        conn = database.get_db()
        try:
            conn.execute('PRAGMA busy_timeout=30')
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                conn.execute('UPDATE users SET secteur_id=NULL, responsable_id=NULL WHERE id=?',
                             (sample_users['salarie_id'],))
        finally:
            conn.close()

    def verifier_et_tenter_mutation(conn, responsable, salarie):
        ok = original(conn, responsable, salarie)
        assert ok
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(mutation_concurrente).result(timeout=5)
        return ok

    monkeypatch.setattr(module, 'est_dans_equipe_responsable', verifier_et_tenter_mutation)
    c.post('/validation_demandes_recup', data={'demande_id': did, 'demande_type': 'conge', 'action': 'valider'})
    assert db.execute('SELECT statut FROM demandes_conges WHERE id=?', (did,)).fetchone()[0] == 'en_attente_direction'


def test_deux_decisions_concurrentes_un_seul_report(app, db, sample_users):
    from concurrent.futures import ThreadPoolExecutor
    a, b = app.test_client(), app.test_client()
    for c in (a, b):
        _login(c, 'admin', 'Admin1234')
    _, did = _demande(db, sample_users['salarie_id'], 'conge')
    data = dict(demande_id=did, demande_type='conge', action='valider')
    with ThreadPoolExecutor(max_workers=2) as pool:
        requetes = [pool.submit(c.post, '/validation_demandes_recup', data=data) for c in (a, b)]
        assert [f.result(timeout=10).status_code for f in requetes] == [302, 302]
    assert db.execute('SELECT COUNT(*) FROM absences').fetchone()[0] == 1
    assert db.execute('SELECT cp_pris FROM users WHERE id=?', (sample_users['salarie_id'],)).fetchone()[0] == 1


def test_demande_absente_et_hors_equipe_meme_refus(client, db, sample_users):
    _, did = _demande(db, sample_users['salarie_id'], 'conge')
    _creer_responsable_tiers(db)
    _login(client, 'resp_tiers', 'tiers123')
    messages = []
    for identifiant in (did, 999999):
        r = client.post('/validation_demandes_recup', data={
            'demande_id': identifiant, 'demande_type': 'conge', 'action': 'valider'})
        assert r.headers['Location'] == '/validation_demandes_recup'
        with client.session_transaction() as sess:
            messages.append(sess.pop('_flashes'))
    assert messages[0][-1] == messages[1][-1]


@pytest.mark.parametrize('nature', ['planning', 'document', 'absence', 'fiche'])
def test_mutations_voisines_refusees_hors_equipe(app, db, sample_users, sample_planning, nature, monkeypatch):
    c = app.test_client()
    _creer_responsable_tiers(db)
    _login(c, 'resp_tiers', 'tiers123')
    uid = sample_users['salarie_id']
    if nature == 'planning':
        chemin = f"/planning_theorique/supprimer/{sample_planning['planning_id']}"
        data = {}
        table = 'planning_theorique'
    elif nature == 'document':
        cur = db.execute("INSERT INTO documents_salaries (user_id, type_document, fichier_path, fichier_nom) "
                         "VALUES (?, 'AUTRE-1', 'temoin.pdf', 'temoin.pdf')", (uid,))
        chemin, data, table = f'/infos_salaries/supprimer_document/{cur.lastrowid}', {}, 'documents_salaries'
        monkeypatch.setattr('blueprints.infos_salaries._supprimer_fichier', lambda *a: pytest.fail('Suppression interdite'))
    elif nature == 'absence':
        chemin, table = '/absences', 'absences'
        data = dict(user_id=uid, motif='Congé payé', date_debut='2026-05-04', date_fin='2026-05-04')
    else:
        chemin, table = '/valider_mois', 'validations'
        data = dict(user_id=uid, mois=5, annee=2026)
    db.commit()
    avant = _etat(db)
    lignes = [tuple(r) for r in db.execute(f'SELECT * FROM {table}')]
    assert c.post(chemin, data=data).status_code == 302
    assert [tuple(r) for r in db.execute(f'SELECT * FROM {table}')] == lignes
    assert _etat(db) == avant


def test_cout_garde_une_lecture_indexee_sans_ecriture(app, db, sample_users):
    from flask import session
    from sessions_securite import charger_compte, verifier_session
    from blueprints.auth import _populate_session
    with app.test_request_context('/gestion_users'):
        _populate_session(charger_compte(db, sample_users['directeur_id']))
        requetes = []
        db.set_trace_callback(requetes.append)
        try:
            assert verifier_session(db)
        finally:
            db.set_trace_callback(None)
        assert len(requetes) == 1 and requetes[0].startswith('SELECT ')
        plan = db.execute('EXPLAIN QUERY PLAN SELECT id FROM users WHERE id=?', (session['user_id'],)).fetchone()
        assert 'INTEGER PRIMARY KEY' in plan[3]


def test_retrait_mission_validation_sans_reconnexion(app, db, sample_users, monkeypatch):
    gestion, sal = app.test_client(), app.test_client()
    _login(gestion, 'admin', 'Admin1234')
    _login(sal, 'salarie_test', 'sal123')
    data = dict(mission_key='suivi_validations_relances', delegated_user_id=sample_users['salarie_id'])
    gestion.post('/delegations', data=data)
    assert sal.get('/vue_ensemble_validation').status_code == 200
    gestion.post('/delegations', data={**data, 'delegated_user_id': ''})
    assert sal.get('/vue_ensemble_validation').status_code == 302
    monkeypatch.setattr('blueprints.notifications.is_email_configured', lambda: pytest.fail('Envoi interdit'))
    for route in ('relance_validation', 'relance_responsable'):
        assert sal.post(f'/api/email/{route}', json={'mois': 5, 'annee': 2026}).status_code == 403


def test_retrait_cse_sans_reconnexion(app, db, sample_users):
    gestion, sal = app.test_client(), app.test_client()
    _login(gestion, 'admin', 'Admin1234')
    _login(sal, 'salarie_test', 'sal123')
    gestion.post('/cse/membres/ajouter', data={'user_id': sample_users['salarie_id']})
    assert sal.get('/cse/messages').status_code == 200
    membre = db.execute('SELECT id FROM cse_membres WHERE user_id=?', (sample_users['salarie_id'],)).fetchone()[0]
    gestion.post(f'/cse/membres/{membre}/supprimer')
    assert sal.get('/cse/messages').status_code == 302
    avant = [tuple(r) for r in db.execute('SELECT * FROM cse_messages')]
    sal.post('/cse/messages/creer', data={'titre': 'Interdit', 'contenu': 'Interdit', 'date_validite': '2026-12-31'})
    assert [tuple(r) for r in db.execute('SELECT * FROM cse_messages')] == avant
