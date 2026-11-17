"""Agent personnel : droits réels, outils bornés et effacement effectif."""
import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path
import sqlite3
import uuid
from unittest.mock import MagicMock

import pytest

import assistant_fournisseurs as fournisseur
from assistant_outils import consulter, valider_appels
from assistant_stockage import (AssistantErreur, MAX_MEMOIRES, decoder, encoder,
                               lire_etat, reserver, liberer, sauver_memoire)


@pytest.fixture(autouse=True)
def aucun_appel_reel(monkeypatch):
    def interdit(*args, **kwargs):
        raise AssertionError('Aucun appel réseau réel dans ces tests')
    monkeypatch.setattr(fournisseur.requests, 'post', interdit)


def modele(app):
    from utils import save_setting
    with app.app_context():
        save_setting('openai_api_key', 'cle-factice')


def connexion_distincte(app, login, password):
    client = app.test_client()
    client.post('/login', data={'login': login, 'password': password}, follow_redirects=True)
    return client


def message(client, texte='Quelles sont mes priorités ?', model='gpt-5.5', rid=None, **extra):
    return client.post('/api/assistant/message', json={
        'message': texte, 'model': model, 'request_id': rid or str(uuid.uuid4()), **extra})


def ajouter(client, texte='Je préfère des synthèses courtes.', categorie='preference'):
    return client.post('/api/assistant/memoires', json={'texte': texte, 'categorie': categorie})


@pytest.mark.parametrize('path,method', [('/assistant', 'get'), ('/api/assistant/etat', 'get'),
    ('/api/assistant/message', 'post'), ('/api/assistant/memoires', 'post'),
    ('/api/assistant/oublier', 'post')])
def test_anonyme_refuse(client, path, method):
    assert getattr(client, method)(path, json={}).status_code == 302


def test_page_separee_et_profils(app, sample_users, prestataire_client):
    for login, password in [('admin', 'Admin1234'), ('resp_test', 'resp123'), ('compta_test', 'compta123')]:
        client = connexion_distincte(app, login, password)
        response = client.get('/assistant')
        assert response.status_code == 200
        assert b'assistantPage' in response.data
        assert b'Aucune cl' in response.data
    for login, password in [('salarie_test', 'sal123'), ('presta_test', 'presta123')]:
        client = connexion_distincte(app, login, password)
        assert client.get('/assistant').status_code == 403
        assert client.get('/api/assistant/etat').status_code == 403
        assert ajouter(client).status_code == 403


def test_pilotage_salarie_accede_sans_droits_gestion(app, db, sample_users, auth_client):
    db.execute('UPDATE secteurs SET nom=? WHERE id=?', ('  PiLoTaGe  ', sample_users['secteur_id']))
    db.commit()
    assert auth_client.get('/assistant').status_code == 200
    assert auth_client.get('/api/assistant/etat').status_code == 200
    assert ajouter(auth_client).status_code == 200
    assert auth_client.get('/gestion_cles_api').status_code == 302
    assert auth_client.get('/api/api_keys/status').status_code == 403
    db.execute('UPDATE secteurs SET nom=? WHERE id=?', ('Accueil', sample_users['secteur_id']))
    db.commit()
    assert auth_client.get('/api/assistant/etat').status_code == 403


def test_prestataire_pilotage_reste_externe(db, sample_users, prestataire_client):
    uid = db.execute("SELECT id FROM users WHERE profil='prestataire'").fetchone()[0]
    db.execute('UPDATE secteurs SET nom=? WHERE id=?', ('Pilotage', sample_users['secteur_id']))
    db.execute('UPDATE users SET secteur_id=? WHERE id=?', (sample_users['secteur_id'], uid))
    db.commit()
    assert prestataire_client.get('/api/assistant/etat').status_code == 403


def test_memoire_privee_chiffree_et_crud(app, db, admin_client):
    resp_client = connexion_distincte(app, 'resp_test', 'resp123')
    response = ajouter(admin_client)
    assert response.status_code == 200
    note = response.json['memoires'][0]
    assert len(note['id']) == 36 and note['expire_le'] is None
    assert resp_client.get('/api/assistant/etat').json['memoires'] == []
    row = db.execute('SELECT contenu FROM assistant_memoires').fetchone()
    assert 'synthèses' not in row['contenu']
    assert resp_client.put('/api/assistant/memoires/' + note['id'], json={
        'texte': 'accès interdit', 'categorie': 'suivi'}).status_code == 404
    assert resp_client.delete('/api/assistant/memoires/' + note['id']).status_code == 404
    response = admin_client.put('/api/assistant/memoires/' + note['id'], json={
        'texte': 'Je prépare le bilan CAF.', 'categorie': 'suivi'})
    assert response.status_code == 200
    assert response.json['memoires'][0]['expire_le'] is not None
    assert admin_client.delete('/api/assistant/memoires/' + note['id']).json['memoires'] == []


@pytest.mark.parametrize('body', [None, [], {'texte': 12, 'categorie': 'suivi'},
    {'texte': 'x', 'categorie': 'secrets'}, {'texte': 'x' * 401, 'categorie': 'preference'},
    {'texte': '', 'categorie': 'preference'}, {'texte': 'x', 'categorie': 'suivi', 'user_id': 1}])
def test_memoire_invalide_refusee(admin_client, body):
    assert admin_client.post('/api/assistant/memoires', json=body).status_code == 400


def test_cap_et_expiration(app, db, admin_client):
    for i in range(MAX_MEMOIRES):
        assert ajouter(admin_client, f'Préférence personnelle {i}').status_code == 200
    assert ajouter(admin_client, 'une de trop').status_code == 409
    db.execute('UPDATE assistant_memoires SET expire_le=1')
    db.commit()
    assert admin_client.get('/api/assistant/etat').json['memoires'] == []


def test_droits_changes_vident_memoire(app, db, admin_client, sample_users):
    ajouter(admin_client)
    db.execute('UPDATE users SET profil=? WHERE id=?', ('responsable', sample_users['directeur_id']))
    db.commit()
    data = admin_client.get('/api/assistant/etat').json
    assert data['memoires'] == [] and data['messages'] == []
    assert 'droits ont changé' in data['notice']


def test_rattachement_retire_reinitialise_conversation(app, db, resp_client, sample_users):
    ajouter(resp_client)
    db.execute('UPDATE users SET responsable_id=NULL,secteur_id=NULL WHERE id=?', (sample_users['salarie_id'],))
    db.commit()
    assert resp_client.get('/api/assistant/etat').json['memoires'] == []


def test_message_sans_cle_ou_modele_exclu(app, admin_client):
    assert message(admin_client).status_code == 409
    modele(app)
    assert message(admin_client, model='gpt-6-astra').status_code == 400


@pytest.mark.parametrize('extra', [{'user_id': 1}, {'profil': 'directeur'}, {'history': []}])
def test_aucun_contexte_client_accepte(app, admin_client, extra):
    modele(app)
    assert message(admin_client, **extra).status_code == 400


@pytest.mark.parametrize('texte', [None, [], '', 'x' * 2001])
def test_message_invalide(admin_client, texte):
    assert message(admin_client, texte=texte).status_code == 400


def test_dialogue_lecture_reelle_et_sources(app, admin_client, monkeypatch):
    modele(app)
    appels = []
    def fake(model, messages):
        appels.append(messages)
        if len(appels) == 1:
            return {'consultations': [{'nom': 'rechercher', 'arguments': {'query': 'factures'}}]}
        ctx = json.loads(messages[1]['content'])
        assert ctx['resultats_de_consultation'][0]['outil'] == 'rechercher'
        assert ctx['resultats_de_consultation'][0]['elements']
        assert 'cle-factice' not in messages[1]['content']
        return {'reponse': 'Voici la page des factures [S1].', 'resume': 'Recherche de factures.'}
    monkeypatch.setattr('assistant_agent.appel_json', fake)
    rid = str(uuid.uuid4())
    result = message(admin_client, rid=rid)
    assert result.status_code == 200, result.json
    assert len(appels) == 2
    assert result.json['messages'][-1]['sources'][0]['url'].startswith('/')
    assert result.json['resume'] == 'Recherche de factures.'
    assert result.json['restant'] == 29
    assert message(admin_client, rid=rid).status_code == 200
    assert len(appels) == 2  # Replay sans nouvelle consommation.
    assert message(admin_client, texte='autre message', rid=rid).status_code == 409
    assert len(appels) == 2


def test_reprise_et_effacement_effectif(app, admin_client, monkeypatch):
    modele(app)
    contexts = []
    def fake(model, messages):
        contexts.append(json.loads(messages[1]['content']))
        return {'consultations': [], 'reponse': 'Je vous accompagne.', 'resume': 'Suivi du sujet personnel.'}
    monkeypatch.setattr('assistant_agent.appel_json', fake)
    ajouter(admin_client, 'Je préfère les réponses courtes.')
    assert message(admin_client).status_code == 200
    assert contexts[-1]['souvenirs_personnels'][0]['texte'] == 'Je préfère les réponses courtes.'
    assert message(admin_client, texte='Continuons.').status_code == 200
    assert contexts[-1]['echanges_recents']
    assert contexts[-1]['resume_precedent']
    note = admin_client.get('/api/assistant/etat').json['memoires'][0]
    result = admin_client.delete('/api/assistant/memoires/' + note['id'])
    assert result.json['messages'] == [] and result.json['resume'] == ''
    assert message(admin_client, texte='Repartons.').status_code == 200
    assert contexts[-1]['souvenirs_personnels'] == []
    assert contexts[-1]['resume_precedent'] == ''


def test_retiens_que_explicite_ne_consomme_pas_api(admin_client):
    result = message(admin_client, texte='Retiens que je prépare le bilan familles.')
    assert result.status_code == 200
    assert result.json['memoires'][0]['texte'] == 'je prépare le bilan familles.'
    assert result.json['restant'] == 30


def test_quota_et_concurrence(app, admin_client, monkeypatch, db):
    modele(app)
    admin_client.get('/api/assistant/etat')
    db.execute('UPDATE assistant_etats SET tours=30')
    db.commit()
    assert message(admin_client).status_code == 429
    db.execute('UPDATE assistant_etats SET tours=0')
    db.commit()
    def fake(model, messages):
        assert message(admin_client).status_code == 409
        return {'consultations': [], 'reponse': 'Une seule réponse.', 'resume': ''}
    monkeypatch.setattr('assistant_agent.appel_json', fake)
    assert message(admin_client).status_code == 200


def test_oubli_pendant_appel_annule_reponse_tardive(app, admin_client, monkeypatch):
    modele(app)
    def fake(model, messages):
        assert admin_client.post('/api/assistant/oublier', json={'tout': True}).status_code == 200
        return {'consultations': [], 'reponse': 'Ancien souvenir à ne pas réintroduire.', 'resume': 'ancien'}
    monkeypatch.setattr('assistant_agent.appel_json', fake)
    assert message(admin_client).status_code == 409
    assert admin_client.get('/api/assistant/etat').json['messages'] == []


def test_profil_change_pendant_appel_annule_reponse(app, db, admin_client, monkeypatch, sample_users):
    modele(app)
    def fake(model, messages):
        db.execute('UPDATE users SET profil=? WHERE id=?', ('salarie', sample_users['directeur_id']))
        db.commit()
        return {'consultations': [], 'reponse': 'Données privées.', 'resume': ''}
    monkeypatch.setattr('assistant_agent.appel_json', fake)
    assert message(admin_client).status_code == 403


@pytest.mark.parametrize('call', [[{'nom': 'sql', 'arguments': {'query': 'DELETE FROM users'}}],
    [{'nom': 'planificateur', 'arguments': {'user_id': 1}}],
    [{'nom': 'priorites', 'arguments': {}}] * 4, [{'nom': 'rechercher', 'arguments': {'query': 1}}]])
def test_outils_interdits(call):
    with pytest.raises(AssistantErreur):
        valider_appels(call)


def test_echec_fournisseur_n_expose_pas_secret_et_libere(app, admin_client, monkeypatch):
    modele(app)
    def error(*args):
        raise RuntimeError('cle-factice /etc/secret')
    monkeypatch.setattr('assistant_agent.appel_json', error)
    result = message(admin_client)
    assert result.status_code == 503
    assert 'cle-factice' not in result.get_data(as_text=True)
    assert admin_client.get('/api/assistant/etat').json['en_cours'] is False


@pytest.mark.parametrize('model,provider', [('gpt-6.1-sol','openai'), ('claude-sonnet-5-5','anthropic'),
    ('openai/gpt-oss-120b','groq'), ('qwen/qwen3.8-27b','groq')])
def test_transport_json_compatible(app, monkeypatch, model, provider):
    from utils import save_setting
    with app.app_context():
        save_setting(provider + '_api_key', 'factice')
        data = {'content': [{'type': 'thinking', 'thinking': '...'}, {'type': 'text', 'text': '{"ok":true}'}]} if provider == 'anthropic' else {
            'choices': [{'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}]}
        post = MagicMock(return_value=MagicMock(status_code=200, json=lambda: data))
        monkeypatch.setattr(fournisseur.requests, 'post', post)
        assert fournisseur.appel_json(model, [{'role': 'system', 'content': 'JSON'}, {'role':'user','content':'test'}]) == {'ok': True}
        payload = post.call_args.kwargs['json']
        assert 'temperature' not in payload
        if provider == 'openai':
            assert payload['reasoning_effort'] == 'medium'
        if model.startswith('openai/'):
            assert payload['include_reasoning'] is False and 'reasoning_format' not in payload
        if model.startswith('qwen/'):
            assert payload['reasoning_format'] == 'hidden'


def test_migration_idempotente_et_schema_neuf(app, db):
    path = Path(__file__).resolve().parents[1] / 'migrations/0084_assistant_personnel.py'
    spec = importlib.util.spec_from_file_location('mig0084', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with sqlite3.connect(':memory:') as conn:
        conn.execute('CREATE TABLE users(id INTEGER PRIMARY KEY)')
        migration.upgrade(conn)
        migration.upgrade(conn)
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='assistant_etats'").fetchone()
    assert db.execute("SELECT statut FROM schema_migrations WHERE version='0084'").fetchone()[0] == 'ok'


def test_rechiffrement_sauvegarde_assistant(app, admin_client, db):
    from resilience import verifier_parametres, rechiffrer_parametres, fernet_pour
    ajouter(admin_client, 'souvenir privé')
    with app.app_context():
        verifier_parametres(db, app.secret_key)
        rechiffrer_parametres(db, app.secret_key, 'nouvelle-cle-factice')
        row = db.execute('SELECT contenu FROM assistant_memoires').fetchone()
        assert json.loads(fernet_pour('nouvelle-cle-factice').decrypt(row[0].encode())) == 'souvenir privé'


def test_outils_agenda_prive_et_pilotage_sans_recherche_metier(app, db, auth_client, sample_users, monkeypatch):
    db.execute('UPDATE secteurs SET nom=? WHERE id=?', ('Pilotage', sample_users['secteur_id']))
    for uid, titre in [(sample_users['salarie_id'], 'Mon créneau personnel'),
                       (sample_users['directeur_id'], 'Réunion direction confidentielle')]:
        db.execute('INSERT INTO planif_taches(user_id,titre) VALUES (?,?)', (uid, titre))
    db.commit()
    def faux_metier(*args, **kwargs):
        pytest.fail('Un salarié Pilotage ne doit pas utiliser la recherche métier globale')
    monkeypatch.setattr('search_engine.analyser_recherche', faux_metier)
    with auth_client:
        auth_client.get('/api/assistant/etat')
        tour = reserver('Mon agenda', 'gpt-5.5', str(uuid.uuid4()))
        resultats, sources = consulter(tour, [
            {'nom': 'planificateur', 'arguments': {}},
            {'nom': 'rechercher', 'arguments': {'query': 'planificateur'}},
            {'nom': 'priorites', 'arguments': {}},
        ])
        assert 'Mon créneau personnel' in json.dumps(resultats, ensure_ascii=False)
        assert 'Réunion direction confidentielle' not in json.dumps(resultats, ensure_ascii=False)
        liberer(tour)


def test_planificateur_rdv_hors_fenetre_ne_masquent_pas_les_taches(db, admin_client, sample_users, monkeypatch):
    jour = date(2032, 6, 15)
    monkeypatch.setattr('assistant_outils.aujourd_hui', lambda: jour)
    # L'API crée aussi les blocs datés, mais laisse les rendez-vous à faire
    # sans deadline : ils ne doivent pas consommer les huit places des tâches.
    for decalage in [*range(-8, 0), *range(15, 23)]:
        response = admin_client.post('/planificateur/api/tache', json={
            'type': 'evenement', 'titre': f'Rendez-vous hors fenêtre {decalage}',
            'date_fixe': (jour + timedelta(days=decalage)).isoformat(),
            'heure_debut': '09:00', 'heure_fin': '10:00',
        })
        assert response.status_code == 200
    attendues = {'Tâche sans échéance', 'Tâche en retard', 'Tâche dans quatorze jours'}
    for titre, deadline, statut in [
        ('Tâche sans échéance', None, 'a_faire'),
        ('Tâche en retard', (jour - timedelta(days=1)).isoformat(), 'a_faire'),
        ('Tâche dans quatorze jours', (jour + timedelta(days=14)).isoformat(), 'a_faire'),
        ('Tâche plus lointaine', (jour + timedelta(days=15)).isoformat(), 'a_faire'),
        ('Tâche terminée', None, 'fait'),
    ]:
        db.execute('''INSERT INTO planif_taches(user_id,type,titre,deadline,statut)
            VALUES (?,'tache',?,?,?)''', (sample_users['directeur_id'], titre, deadline, statut))
    db.commit()
    with admin_client:
        admin_client.get('/api/assistant/etat')
        tour = reserver('Mon planificateur', 'gpt-5.5', str(uuid.uuid4()))
        resultats, _ = consulter(tour, [{'nom': 'planificateur', 'arguments': {}}])
        liberer(tour)
    assert {e['titre'] for e in resultats[0]['elements']} == attendues


@pytest.mark.parametrize('decalage', [0, 14])
def test_planificateur_rdv_dans_fenetre_reste_date_et_unique(admin_client, monkeypatch, decalage):
    jour = date(2032, 6, 15)
    monkeypatch.setattr('assistant_outils.aujourd_hui', lambda: jour)
    date_rdv = (jour + timedelta(days=decalage)).isoformat()
    response = admin_client.post('/planificateur/api/tache', json={
        'type': 'evenement', 'titre': 'Rendez-vous personnel', 'date_fixe': date_rdv,
        'heure_debut': '10:00', 'heure_fin': '11:00',
    })
    assert response.status_code == 200
    with admin_client:
        admin_client.get('/api/assistant/etat')
        tour = reserver('Mon planificateur', 'gpt-5.5', str(uuid.uuid4()))
        resultats, sources = consulter(tour, [{'nom': 'planificateur', 'arguments': {}}])
        liberer(tour)
    elements = resultats[0]['elements']
    assert len(elements) == 1
    assert elements[0]['titre'] == 'Rendez-vous personnel'
    assert elements[0]['detail'] == f'{date_rdv} · 10:00–11:00'
    assert len(sources) == 1


def test_priorites_reelles_ne_montrent_pas_une_autre_equipe(app, db, resp_client, sample_users):
    from utils import aujourd_hui
    from werkzeug.security import generate_password_hash
    sid = db.execute("INSERT INTO secteurs(nom) VALUES ('Autre secteur')").lastrowid
    uid = db.execute('''INSERT INTO users(nom,prenom,login,password,profil,secteur_id)
        VALUES (?,?,?,?,?,?)''', ('Secret', 'Hors équipe', 'hors', generate_password_hash('test'), 'salarie', sid)).lastrowid
    for user_id in (sample_users['salarie_id'], uid):
        db.execute('''INSERT INTO demandes_conges
            (user_id,date_debut,date_fin,nb_jours,type_conge,statut)
            VALUES (?,?,?,?,?,?)''', (user_id, aujourd_hui().isoformat(), aujourd_hui().isoformat(), 1, 'cp', 'en_attente_responsable'))
    db.commit()
    with resp_client:
        resp_client.get('/api/assistant/etat')
        tour = reserver('Mes priorités', 'gpt-5.5', str(uuid.uuid4()))
        resultats, sources = consulter(tour, [{'nom': 'priorites', 'arguments': {}}])
        assert 'Martin' in json.dumps(resultats, ensure_ascii=False)
        assert 'Hors équipe' not in json.dumps(resultats, ensure_ascii=False)
        assert 'circuit' in json.dumps(resultats, ensure_ascii=False)
        liberer(tour)


def test_tout_oublier_et_preference_sans_doublon(admin_client):
    assert ajouter(admin_client, 'Ma préférence').status_code == 200
    assert ajouter(admin_client, 'ma préférence').status_code == 409
    assert admin_client.post('/api/assistant/oublier', json={'tout': False}).json['memoires']
    assert admin_client.post('/api/assistant/oublier', json={'tout': True}).json['memoires'] == []
    assert admin_client.post('/api/assistant/oublier', json={'tout': 'true'}).status_code == 400


def test_csrf_conserve(app, db, admin_client):
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        # Le gestionnaire CSRF commun révoque la session et redirige vers login.
        assert ajouter(admin_client).status_code == 302
        assert db.execute('SELECT COUNT(*) FROM assistant_memoires').fetchone()[0] == 0
        assert admin_client.get('/assistant').status_code == 302
    finally:
        app.config['WTF_CSRF_ENABLED'] = False


@pytest.mark.parametrize('data', [
    {'choices': [{'message': {'content': 'pas du JSON'}, 'finish_reason': 'stop'}]},
    {'choices': [{'message': {'content': '{"ok":true}'}, 'finish_reason': 'length'}]},
    {'choices': [{'message': {'content': None}}]},
])
def test_reponses_fournisseur_inexploitables(app, monkeypatch, data):
    modele(app)
    with app.app_context():
        monkeypatch.setattr(fournisseur.requests, 'post', lambda *a, **kw: MagicMock(status_code=200, json=lambda: data))
        with pytest.raises(AssistantErreur) as exc:
            fournisseur.appel_json('gpt-5.5', [{'role': 'system', 'content': 'JSON'}, {'role': 'user', 'content': 'test'}])
        assert exc.value.statut == 502


def test_source_inventee_refusee(app, admin_client, monkeypatch):
    modele(app)
    monkeypatch.setattr('assistant_agent.appel_json', lambda *a: {
        'consultations': [], 'reponse': 'Selon S999, tout est validé.', 'resume': ''})
    result = message(admin_client)
    assert result.status_code == 502
    assert admin_client.get('/api/assistant/etat').json['messages'] == []
