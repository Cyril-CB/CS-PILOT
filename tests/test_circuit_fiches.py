"""Circuit ordonné, cumul explicite et confirmation historique : routes et SQLite."""
import pytest
from tests.test_fiches_versions import (fiche_complete, client_role, signer, validation,
                                       ANNEE, MOIS)


def test_t1_ordre_obligatoire(app, db, sample_users, fiche_complete):
    uid = fiche_complete
    sal, resp, direction = [client_role(app, sample_users, r) for r in ('salarie', 'responsable', 'directeur')]
    for c in (resp, direction):
        signer(c, uid)
        assert validation(uid) is None
        assert db.execute('SELECT COUNT(*) FROM fiches_evenements').fetchone()[0] == 0
    signer(sal, uid)
    v1 = validation(uid)['version_courante_id']
    signer(direction, uid)
    assert validation(uid)['version_directeur_id'] is None
    signer(resp, uid)
    signer(direction, uid)
    v = validation(uid)
    assert v['bloque'] and all(v[f'version_{r}_id'] == v1 for r in ('salarie', 'responsable', 'directeur'))


def _clients(app, users):
    return [client_role(app, users, r) for r in ('salarie', 'responsable', 'directeur')]


def _signatures(db, uid):
    return [tuple(r) for r in db.execute('SELECT evenement, role, version_id FROM fiches_evenements WHERE user_id=? ORDER BY id', (uid,))]


def _modifier(db, uid):
    db.execute("UPDATE heures_reelles SET commentaire=COALESCE(commentaire,'') || ' correction' WHERE user_id=?", (uid,))
    db.commit()


@pytest.mark.parametrize('avec_responsable', [False, True])
def test_t2_t3_recommencer_apres_modification(app, db, sample_users, fiche_complete, avec_responsable):
    uid = fiche_complete
    sal, resp, direction = _clients(app, sample_users)
    signer(sal, uid)
    if avec_responsable:
        signer(resp, uid)
    v1 = validation(uid)['version_courante_id']
    _modifier(db, uid)
    v2 = validation(uid)['version_courante_id']
    assert v1 != v2
    avant, events = validation(uid), _signatures(db, uid)
    signer(direction if avec_responsable else resp, uid)
    assert validation(uid) == avant and _signatures(db, uid) == events
    assert any(e[0] == 'approbations_obsoletes' for e in events)
    for c in (sal, resp, direction):
        signer(c, uid)
    v = validation(uid)
    assert v['bloque'] and all(v[f'version_{r}_id'] == v2 for r in ('salarie','responsable','directeur'))


@pytest.mark.parametrize('sans_secteur', [False, True])
def test_t4_responsable_personnel_deux_roles(app, db, sample_users, fiche_complete, sans_secteur):
    uid = fiche_complete
    db.execute("UPDATE users SET profil='responsable', responsable_id=id WHERE id=?", (uid,))
    if sans_secteur:
        db.execute('UPDATE users SET secteur_id=NULL WHERE id=?', (uid,))
    db.commit()
    sal, _, direction = _clients(app, sample_users)
    for modification in (False, True):
        if modification:
            _modifier(db, uid)
            avant = validation(uid)
            signer(direction, uid)
            assert validation(uid) == avant
        signer(sal, uid)
        v = validation(uid)
        assert v['version_salarie_id'] == v['version_responsable_id'] == v['version_courante_id']
        events = db.execute("SELECT * FROM fiches_evenements WHERE user_id=? AND evenement='signature' ORDER BY id DESC LIMIT 2", (uid,)).fetchall()
        assert {e['role'] for e in events} == {'salarie','responsable'}
        assert all(e['auteur_id'] == uid for e in events)
        assert events[0]['date_evenement'] == events[1]['date_evenement']
    signer(direction, uid)
    assert validation(uid)['bloque']


def test_direction_responsable_double_apres_salarie(app, db, sample_users, fiche_complete):
    uid = fiche_complete
    db.execute('UPDATE users SET responsable_id=?, secteur_id=NULL WHERE id=?', (sample_users['directeur_id'], uid))
    db.commit()
    sal, _, direction = _clients(app, sample_users)
    signer(direction, uid)
    assert validation(uid) is None
    signer(sal, uid)
    signer(direction, uid)
    v = validation(uid)
    assert v['bloque'] and v['version_responsable_id'] == v['version_directeur_id'] == v['version_salarie_id']
    assert [e[1] for e in _signatures(db, uid) if e[0] == 'signature'] == ['salarie','responsable','directeur']


def _historique(db, uid, verrouille=True, versionnee=True):
    from fiches_contenu import calculer_contenu
    from fiches_versions import enregistrer_version
    vid = enregistrer_version(db, calculer_contenu(db, uid, MOIS, ANNEE), 'signature' if versionnee else 'reprise_historique')
    db.execute('''INSERT INTO validations (user_id, mois, annee, bloque, circuit_version,
                  validation_responsable, validation_directeur, date_responsable, date_directeur,
                  version_courante_id, version_responsable_id, version_directeur_id)
                  VALUES (?, ?, ?, ?, 1, 'Responsable historique', 'Direction historique',
                          '2026-09-01 08:00:00', '2026-09-02 10:00:00', ?, ?, ?)''',
               (uid, MOIS, ANNEE, int(verrouille), vid, vid if versionnee else None, vid if versionnee else None))
    db.commit()
    return vid


def _confirmer(client, uid, vid, db, **changes):
    digest = db.execute('SELECT empreinte FROM fiches_versions WHERE id=?', (vid,)).fetchone()[0]
    data = dict(user_id=uid, mois=MOIS, annee=ANNEE, version_id=vid, empreinte_fiche=digest)
    data.update(changes)
    return client.post('/confirmer_fiche_historique', data=data)


@pytest.mark.parametrize('versionnee', [True, False])
def test_t5_migration_verrou_historique_intact(app, db, sample_users, fiche_complete, versionnee):
    import importlib
    uid = fiche_complete
    vid = _historique(db, uid, versionnee=versionnee)
    db.execute('ALTER TABLE validations DROP COLUMN circuit_version')
    db.commit()
    avant = dict(db.execute('SELECT * FROM validations WHERE user_id=?', (uid,)).fetchone())
    contenu = db.execute('SELECT contenu FROM fiches_versions WHERE id=?', (vid,)).fetchone()[0]
    mig = importlib.import_module('migrations.0067_circuit_fiches_ordonne')
    mig.upgrade(db)
    db.commit()
    assert validation(uid) == {**avant, 'circuit_version': 1}
    assert db.execute('SELECT contenu FROM fiches_versions WHERE id=?', (vid,)).fetchone()[0] == contenu
    evenements = _signatures(db, uid)
    mig.upgrade(db)
    db.commit()
    assert _signatures(db, uid) == evenements
    sal = client_role(app, sample_users, 'salarie')
    page = sal.get(f'/vue_mensuelle?mois={MOIS}&annee={ANNEE}').get_data(as_text=True)
    assert 'Circuit historique' in page and 'validation salarié n’était pas obligatoire' in page.replace("n'était", 'n’était')
    assert validation(uid)['validation_salarie'] is None


def test_migration_ouverte_repart_salarie(app, db, sample_users, fiche_complete):
    import importlib
    uid = fiche_complete
    _historique(db, uid, verrouille=False)
    db.execute('ALTER TABLE validations DROP COLUMN circuit_version')
    db.commit()
    mig = importlib.import_module('migrations.0067_circuit_fiches_ordonne')
    mig.upgrade(db)
    db.commit()
    v = validation(uid)
    assert v['circuit_version'] == 2 and not v['bloque']
    assert all(v[f'version_{r}_id'] is None for r in ('salarie','responsable','directeur'))
    assert v['validation_responsable'] == 'Responsable historique'
    sal, resp, direction = _clients(app, sample_users)
    signer(direction, uid)
    assert not validation(uid)['bloque']
    for c in (sal, resp, direction):
        signer(c, uid)
    mig.upgrade(db)
    db.commit()
    assert validation(uid)['circuit_version'] == 2 and validation(uid)['bloque']


@pytest.mark.parametrize('versionnee', [True, False])
def test_t6_confirmation_figee_et_disparition_rappels(app, db, sample_users, fiche_complete, monkeypatch, versionnee):
    from fiches_circuit import fiches_historiques_a_confirmer
    from io import BytesIO
    import pdfplumber
    uid = fiche_complete
    vid = _historique(db, uid, versionnee=versionnee)
    avant = validation(uid)
    versions = [tuple(r) for r in db.execute('SELECT * FROM fiches_versions')]
    sal, _, direction = _clients(app, sample_users)
    assert fiches_historiques_a_confirmer(db, uid)
    page = sal.get(f'/vue_mensuelle?mois={MOIS}&annee={ANNEE}')
    assert b'/confirmer_fiche_historique' in page.data
    # Consulter/confirmer/exporter l'ancien contenu ne doit pas recalculer ses valeurs.
    monkeypatch.setattr('fiches_versions.calculer_contenu', lambda *a, **k: pytest.fail('Recalcul historique interdit'))
    monkeypatch.setattr('blueprints.validation.calculer_contenu', lambda *a, **k: pytest.fail('Recalcul historique interdit'))
    assert sal.get(f'/vue_mensuelle?mois={MOIS}&annee={ANNEE}').status_code == 200
    assert _confirmer(sal, uid, vid, db).status_code == 302
    assert validation(uid) == avant
    assert [tuple(r) for r in db.execute('SELECT * FROM fiches_versions')] == versions
    event = db.execute("SELECT * FROM fiches_evenements WHERE evenement='confirmation_historique'").fetchone()
    assert event['role'] == 'salarie' and event['auteur_id'] == uid and event['version_id'] == vid
    assert event['date_evenement'] > avant['date_directeur']
    assert not fiches_historiques_a_confirmer(db, uid) and not fiches_historiques_a_confirmer(db)
    for client in (sal, direction):
        assert 'Aucune confirmation historique en attente' in client.get('/fiches_historiques').get_data(as_text=True)
    with pdfplumber.open(BytesIO(sal.get(f'/export_pdf_mensuel?user_id={uid}&mois={MOIS}&annee={ANNEE}').data)) as pdf:
        texte = '\n'.join(p.extract_text() for p in pdf.pages)
    assert 'a posteriori' in texte and '2026-09-02 10:00:00' in texte
    assert 'Circuit historique' in texte


@pytest.mark.parametrize('cas', ['version', 'empreinte', 'mois', 'autrui', 'repete', 'contenu', 'nouveau_circuit', 'ouverte'])
def test_confirmation_ne_modifie_jamais_la_fiche(app, db, sample_users, fiche_complete, cas):
    uid = fiche_complete
    vid = _historique(db, uid)
    sal, _, direction = _clients(app, sample_users)
    changes = {}
    client = sal
    if cas == 'version': changes['version_id'] = vid + 999
    if cas == 'empreinte': changes['empreinte_fiche'] = 'fausse'
    if cas == 'mois': changes['mois'] = 1
    if cas == 'autrui': client = direction
    if cas == 'repete': _confirmer(sal, uid, vid, db)
    if cas == 'contenu': changes.update(commentaire='Injecté', bloque=0, heures=999)
    if cas == 'nouveau_circuit': db.execute('UPDATE validations SET circuit_version=2 WHERE user_id=?', (uid,))
    if cas == 'ouverte': db.execute('UPDATE validations SET bloque=0 WHERE user_id=?', (uid,))
    db.commit()
    avant = validation(uid)
    heures = [tuple(r) for r in db.execute('SELECT * FROM heures_reelles')]
    nb = db.execute("SELECT COUNT(*) FROM fiches_evenements WHERE evenement='confirmation_historique'").fetchone()[0]
    _confirmer(client, uid, vid, db, **changes)
    assert validation(uid) == avant
    assert [tuple(r) for r in db.execute('SELECT * FROM heures_reelles')] == heures
    assert db.execute("SELECT COUNT(*) FROM fiches_evenements WHERE evenement='confirmation_historique'").fetchone()[0] == nb + int(cas == 'contenu')


def test_reouverture_historique_nouveau_circuit_complet(app, db, sample_users, fiche_complete):
    uid = fiche_complete
    vid = _historique(db, uid)
    sal, resp, direction = _clients(app, sample_users)
    _confirmer(sal, uid, vid, db)
    direction.post('/deverrouiller_mois', data=dict(user_id=uid, mois=MOIS, annee=ANNEE, motif='Correction'))
    _modifier(db, uid)
    signer(direction, uid)
    signer(resp, uid)
    assert validation(uid) is None
    for c in (sal, resp, direction): signer(c, uid)
    v = validation(uid)
    assert v['circuit_version'] == 2 and v['bloque'] and v['version_courante_id'] != vid
    assert any(e[0] == 'confirmation_historique' for e in _signatures(db, uid))


def test_page_perimee_refusee_sans_signature(app, db, sample_users, fiche_complete):
    from fiches_contenu import calculer_contenu
    from fiches_versions import empreinte
    uid = fiche_complete
    sal, resp, _ = _clients(app, sample_users)
    signer(sal, uid)
    ancienne = empreinte(calculer_contenu(db, uid, MOIS, ANNEE))
    _modifier(db, uid)
    signer(sal, uid)
    avant = _signatures(db, uid)
    resp.post('/valider_mois', data=dict(user_id=uid, mois=MOIS, annee=ANNEE, empreinte_fiche=ancienne))
    assert _signatures(db, uid) == avant


def test_absence_responsable_aucune_suppleance(app, db, sample_users, fiche_complete):
    from fiches_circuit import destinataires_etape
    uid = fiche_complete
    db.execute('UPDATE users SET secteur_id=NULL, responsable_id=NULL WHERE id=?', (uid,))
    db.commit()
    sal, _, direction = _clients(app, sample_users)
    signer(sal, uid)
    assert destinataires_etape(db, uid, validation(uid)) == ('responsable', [])
    signer(direction, uid)
    assert validation(uid)['version_directeur_id'] is None


def test_relances_suivent_acteur_et_consentement(app, db, sample_users, fiche_complete, monkeypatch):
    import email_service
    from tests.test_dashboard_actions import _valider_tout_le_monde
    uid = fiche_complete
    _valider_tout_le_monde(db, MOIS, ANNEE, sauf=(uid,))
    db.execute("UPDATE users SET email=login || '@example.invalid'")
    db.commit()
    sal, resp, direction = _clients(app, sample_users)
    monkeypatch.setattr('blueprints.notifications.is_email_configured', lambda: True)
    envois = []
    monkeypatch.setattr(email_service, 'notifier_relance_fiche', lambda *a, **k: (envois.append((a, k)) or True, 'Test'))
    params = dict(mois=MOIS, annee=ANNEE)
    assert direction.post('/api/email/relance_validation', json=params).status_code == 200
    assert not envois  # Le consentement salarié reste nécessaire.
    db.execute('UPDATE users SET email_notifications_enabled=1 WHERE id=?', (uid,))
    db.commit()
    for acteur, client in [('salarie', sal), ('responsable', resp), ('directeur', direction)]:
        envois.clear()
        res = direction.post('/api/email/relance_validation', json=params)
        assert res.get_json()['nb_envoyes'] == 1
        args, _ = envois[0]
        assert args[5:] == (uid, acteur)
        login = {'salarie':'salarie_test','responsable':'resp_test','directeur':'admin'}[acteur]
        assert args[0] == login + '@example.invalid'
        envois.clear()
        direction.post('/api/email/relance_responsable', json={**params, 'responsable_id': sample_users['responsable_id']})
        assert len(envois) == int(acteur == 'responsable')
        signer(client, uid)
    envois.clear()
    assert direction.post('/api/email/relance_validation', json=params).get_json()['nb_envoyes'] == 0
    assert not envois
    assert direction.post('/api/email/relance_responsable', json=params).status_code == 400


def test_confirmation_historique_actions_et_relance_separees(app, db, sample_users, fiche_complete, monkeypatch):
    from dashboard_actions import construire_actions
    from tests.test_dashboard_actions import _valider_tout_le_monde
    from datetime import date
    uid = fiche_complete
    vid = _historique(db, uid)
    _valider_tout_le_monde(db, MOIS, ANNEE, sauf=(uid,))
    db.execute("UPDATE users SET email='sal@example.invalid', email_notifications_enabled=1 WHERE id=?", (uid,))
    db.commit()
    monkeypatch.setattr('dashboard_actions.aujourd_hui', lambda: date(2026,9,9))
    monkeypatch.setattr('blueprints.notifications.is_email_configured', lambda: True)
    envois = []
    monkeypatch.setattr('email_service.notifier_relance_fiche', lambda *a, **k: (envois.append((a,k)) or True, 'Test'))
    sal, resp, direction = _clients(app, sample_users)
    def actions(profil):
        with app.test_request_context():
            return construire_actions(db, profil, sample_users[profil + '_id'], etendu=True)
    for profil in ('salarie','directeur'):
        cartes = actions(profil)
        historique = next(a for a in cartes if a['id']=='confirmations-historiques')
        assert historique['categorie']=='historique' and historique['urgence']=='normal'
        assert not any(a['type']=='relance' or a['id'].startswith('fiche-') for a in cartes)
    assert 'Confirmer mes anciennes fiches' in sal.get('/dashboard', follow_redirects=True).get_data(as_text=True)
    params = dict(user_id=uid, mois=MOIS, annee=ANNEE)
    direction.post('/api/email/relance_validation', json=params)
    resp.post('/relancer_fiche_historique', data=params)
    assert not envois
    direction.post('/relancer_fiche_historique', data=params)
    assert len(envois)==1 and envois[0][1]=={'historique': True}
    _confirmer(sal, uid, vid, db)
    direction.post('/relancer_fiche_historique', data=params)
    assert len(envois)==1
    assert 'Confirmer mes anciennes fiches' not in sal.get('/dashboard', follow_redirects=True).get_data(as_text=True)
    for profil in ('salarie','directeur'):
        assert not any(a['id']=='confirmations-historiques' for a in actions(profil))


@pytest.mark.parametrize('double_role', [False, True])
@pytest.mark.parametrize('modification_avant', [False, True])
def test_concurrence_modification_et_approbation(app, db, sample_users, fiche_complete, monkeypatch, double_role, modification_avant):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from database import get_db
    from fiches_contenu import calculer_contenu
    from fiches_versions import empreinte
    import blueprints.validation as routes
    uid = fiche_complete
    if double_role:
        db.execute("UPDATE users SET profil='responsable' WHERE id=?", (uid,))
        db.commit()
    sal, resp, direction = _clients(app, sample_users)
    signer(sal, uid)
    v1 = validation(uid)['version_courante_id']
    if double_role:
        _modifier(db, uid)  # Les deux rôles doivent être approuvés à nouveau.
    cible = sal if double_role else resp
    reference = empreinte(calculer_contenu(db, uid, MOIS, ANNEE))
    def post():
        return cible.post('/valider_mois', data=dict(user_id=uid, mois=MOIS, annee=ANNEE, empreinte_fiche=reference))
    if modification_avant:
        conn = get_db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute("UPDATE heures_reelles SET commentaire='Concurrent avant' WHERE user_id=?", (uid,))
            demarree = Event()
            def envoyer():
                demarree.set()
                return post()
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(envoyer)
                assert demarree.wait(5)
                conn.commit()
                assert future.result(timeout=8).status_code == 302
        finally:
            conn.close()
        assert validation(uid)['version_responsable_id'] == (v1 if double_role else None)
    else:
        entree, continuer, modification = Event(), Event(), Event()
        original = routes.enregistrer_version
        def suspendre(*a, **k):
            entree.set()
            assert continuer.wait(5)
            return original(*a, **k)
        monkeypatch.setattr(routes, 'enregistrer_version', suspendre)
        def modifier():
            conn = get_db()
            try:
                modification.set()
                _modifier(conn, uid)
            finally:
                conn.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            signature = pool.submit(post)
            assert entree.wait(5)
            ecriture = pool.submit(modifier)
            assert modification.wait(5)
            continuer.set()
            assert signature.result(timeout=8).status_code == 302
            ecriture.result(timeout=8)
        v = validation(uid)
        assert v['version_responsable_id'] != v['version_courante_id']
        if double_role:
            assert v['version_salarie_id'] == v['version_responsable_id']
    avant = _signatures(db, uid)
    signer(direction, uid)
    assert _signatures(db, uid) == avant and not validation(uid)['bloque']


def test_concurrence_responsable_direction_meme_version(app, db, sample_users, fiche_complete, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from fiches_contenu import calculer_contenu
    from fiches_versions import empreinte
    import blueprints.validation as routes
    uid = fiche_complete
    sal, resp, direction = _clients(app, sample_users)
    signer(sal, uid)
    reference = empreinte(calculer_contenu(db, uid, MOIS, ANNEE))
    entree, suite, direction_commencee = Event(), Event(), Event()
    original = routes.enregistrer_version
    def suspendre(*a, **k):
        entree.set()
        assert suite.wait(5)
        return original(*a, **k)
    monkeypatch.setattr(routes, 'enregistrer_version', suspendre)
    def post_direction():
        direction_commencee.set()
        return direction.post('/valider_mois', data=dict(user_id=uid, mois=MOIS, annee=ANNEE, empreinte_fiche=reference))
    with ThreadPoolExecutor(max_workers=2) as pool:
        r = pool.submit(signer, resp, uid)
        assert entree.wait(5)
        d = pool.submit(post_direction)
        assert direction_commencee.wait(5)
        suite.set()
        assert r.result(timeout=8).status_code == d.result(timeout=8).status_code == 302
    v = validation(uid)
    assert v['bloque'] and v['version_salarie_id']==v['version_responsable_id']==v['version_directeur_id']
    assert [e[1] for e in _signatures(db, uid) if e[0]=='signature']==['salarie','responsable','directeur']


def test_confirmation_reference_autre_fiche_et_session_revoquee(app, db, sample_users, fiche_complete):
    uid = fiche_complete
    vid = _historique(db, uid)
    autre = _historique(db, sample_users['comptable_id'])
    sal, _, _ = _clients(app, sample_users)
    avant = _signatures(db, uid)
    _confirmer(sal, uid, vid, db, version_id=autre)
    _confirmer(sal, sample_users['comptable_id'], autre, db)
    assert _signatures(db, uid)==avant
    assert not db.execute("SELECT 1 FROM fiches_evenements WHERE evenement='confirmation_historique'").fetchone()
    db.execute('UPDATE users SET actif=0 WHERE id=?', (uid,))
    db.commit()
    assert _confirmer(sal, uid, vid, db).headers['Location']=='/login'
    assert _signatures(db, uid)==avant


def test_confirmation_formulaire_csrf_et_anonyme(app, db, sample_users, fiche_complete):
    import re
    uid = fiche_complete
    vid = _historique(db, uid)
    sal = client_role(app, sample_users, 'salarie')
    assert _confirmer(app.test_client(), uid, vid, db).headers['Location']=='/login'
    sans_jeton = client_role(app, sample_users, 'salarie')
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        assert _confirmer(sans_jeton, uid, vid, db).status_code == 302  # Handler CSRF : redirection avec message.
        assert not db.execute("SELECT 1 FROM fiches_evenements WHERE evenement='confirmation_historique'").fetchone()
        page = sal.get(f'/vue_mensuelle?mois={MOIS}&annee={ANNEE}').get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]+)"', page)[1]
        assert _confirmer(sal, uid, vid, db, csrf_token=token).status_code==302
        assert db.execute("SELECT COUNT(*) FROM fiches_evenements WHERE evenement='confirmation_historique'").fetchone()[0]==1
    finally:
        app.config['WTF_CSRF_ENABLED'] = False


def test_migration_interrompue_rollback_puis_reprise(app, db, sample_users, fiche_complete, monkeypatch):
    import importlib
    import fiches_versions
    uid = fiche_complete
    _historique(db, uid)
    db.execute('ALTER TABLE validations DROP COLUMN circuit_version')
    db.commit()
    avant = [tuple(r) for r in db.execute('SELECT * FROM validations')]
    mig = importlib.import_module('migrations.0067_circuit_fiches_ordonne')
    with monkeypatch.context() as patch:
        def interrompre(*args, **kwargs):
            raise RuntimeError('Interruption simulée')
        patch.setattr(fiches_versions, 'evenement', interrompre)
        with pytest.raises(RuntimeError, match='Interruption'):
            mig.upgrade(db)
        db.rollback()
    assert 'circuit_version' not in {r[1] for r in db.execute('PRAGMA table_info(validations)')}
    assert [tuple(r) for r in db.execute('SELECT * FROM validations')]==avant
    mig.upgrade(db)
    db.commit()
    assert validation(uid)['circuit_version']==1


def test_actions_normales_suivent_ordre_et_version(app, db, sample_users, fiche_complete, monkeypatch):
    from datetime import date
    from dashboard_actions import construire_actions
    from tests.test_dashboard_actions import _valider_tout_le_monde
    uid = fiche_complete
    _valider_tout_le_monde(db, MOIS, ANNEE, sauf=(uid,))
    monkeypatch.setattr('dashboard_actions.aujourd_hui', lambda: date(2026,9,9))
    sal, resp, direction = _clients(app, sample_users)
    def fiche(profil):
        with app.test_request_context():
            cartes = construire_actions(db, profil, sample_users[profil+'_id'], sample_users['secteur_id'])
        return next((a for a in cartes if a['id']==f'fiche-{uid}-{ANNEE}-{MOIS:02d}'), None)
    assert fiche('salarie') and fiche('responsable') is None
    assert 'salarié' in fiche('directeur')['titre']
    assert b'action="/valider_mois"' not in resp.get(f'/vue_mensuelle?user_id={uid}&mois={MOIS}&annee={ANNEE}').data
    signer(sal, uid)
    assert fiche('salarie') is None and fiche('responsable')['titre'].startswith('Fiche à valider')
    assert 'responsable' in fiche('directeur')['titre']
    signer(resp, uid)
    assert fiche('responsable') is None and fiche('directeur')['titre'].startswith('Fiche à valider')
    _modifier(db, uid)
    assert fiche('salarie') and fiche('responsable') is None
    assert 'salarié' in fiche('directeur')['titre']
    for c in (sal, resp, direction):
        signer(c, uid)
    assert all(fiche(r) is None for r in ('salarie','responsable','directeur'))


@pytest.mark.parametrize('historique', [False, True])
@pytest.mark.parametrize('base_url', ['', 'https://centre.example.invalid'])
@pytest.mark.parametrize('racine', ['', '/cspilot'])
def test_relances_liens_sans_adresse_publique_et_sous_repertoire(
        app, db, sample_users, fiche_complete, monkeypatch, historique, base_url, racine):
    """Exerce les routes et le constructeur réel ; seul l'envoi SMTP est simulé."""
    import re
    from html import unescape
    from urllib.parse import urlsplit, parse_qs
    import email_service
    from tests.test_email_notifications import _capturer
    from tests.test_dashboard_actions import _valider_tout_le_monde
    uid = fiche_complete
    if historique:
        _historique(db, uid)
    _valider_tout_le_monde(db, MOIS, ANNEE, sauf=(uid,))
    db.execute("UPDATE users SET email='sal@example.invalid', email_notifications_enabled=1 WHERE id=?", (uid,))
    db.commit()
    with app.app_context():
        email_service.save_email_config('smtp.example.invalid', '587', 'test@example.invalid', 'fictif-test', 'Test')
        email_service.save_base_url(base_url)
    envois = _capturer(monkeypatch)
    direction = client_role(app, sample_users, 'directeur')
    params = dict(user_id=uid, mois=MOIS, annee=ANNEE)
    if historique:
        response = direction.post('/relancer_fiche_historique', data=params, environ_overrides={'SCRIPT_NAME': racine})
        assert response.status_code == 302
    else:
        response = direction.post('/api/email/relance_validation', json=params, environ_overrides={'SCRIPT_NAME': racine})
        assert response.status_code == 200 and response.get_json()['nb_envoyes'] == 1
    assert len(envois) == 1
    sujet, contenu = envois[0]
    assert ('ancienne' in sujet) == historique
    lien = unescape(re.search(r'href="([^"]+)"', contenu)[1])
    url = urlsplit(lien)
    assert url.scheme == ('https' if base_url else 'http')
    assert url.netloc == ('centre.example.invalid' if base_url else 'localhost')
    assert url.path == racine + '/vue_mensuelle'
    assert parse_qs(url.query) == {'user_id': [str(uid)], 'mois': [str(MOIS)], 'annee': [str(ANNEE)]}
