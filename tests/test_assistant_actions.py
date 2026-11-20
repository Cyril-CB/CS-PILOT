"""Actions préparées : vrais circuits, acteurs isolés et fournisseurs simulés."""
from copy import deepcopy
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sqlite3
import uuid

import pytest

import assistant_actions as actions
import assistant_agent
import assistant_stockage as stockage
from tests.test_assistant import message, connexion_distincte

FIXE = datetime(2026, 11, 20, 9, 0)
TACHE = {'type':'tache', 'titre':'Préparer mon bilan', 'description':'Point de coordination',
         'duree_min':60, 'deadline':'2026-11-30', 'preference':'aucune', 'secable':False, 'duree_min_bloc':30}
RDV = {'type':'evenement', 'titre':'Point CAF', 'description':'Au centre',
       'date_fixe':'2026-11-23', 'heure_debut':'14:00', 'heure_fin':'15:00'}


@pytest.fixture(autouse=True)
def horloge_et_reseau(app, monkeypatch):
    import requests
    import utils
    import email_service
    import blueprints.planificateur as planif
    for module in (actions, assistant_agent, stockage, utils):
        monkeypatch.setattr(module, 'maintenant', lambda:FIXE)
    monkeypatch.setattr(planif, '_maintenant', lambda:FIXE)
    monkeypatch.setattr(planif, 'aujourd_hui', lambda:FIXE.date())
    def interdit(*a, **kw):
        raise AssertionError('Pas de service externe pendant les tests')
    monkeypatch.setattr(requests.sessions.Session, 'request', interdit)
    monkeypatch.setattr(email_service, 'envoyer_email', interdit)
    with app.app_context():
        utils.save_setting('openai_api_key', 'cle-factice-actions')


@pytest.fixture
def modele(monkeypatch):
    state = {'champs':deepcopy(TACHE), 'appels':[]}
    def fake(model, messages):
        state['appels'].append(messages)
        return {'consultations':[], 'reponse':'La tâche est déjà créée !', 'resume':'Création terminée.',
                'proposition':deepcopy(state['champs'])}
    monkeypatch.setattr(assistant_agent, 'appel_json', fake)
    return state


def preparer(client, modele, champs=None, rid=None):
    if champs is not None:
        modele['champs'] = deepcopy(champs)
    r = message(client, texte='Prépare un rendez-vous ou une tâche personnelle.', rid=rid)
    assert r.status_code == 200, r.json
    assert 'proposition' in r.json['messages'][-1]['texte']
    assert 'déjà créée' not in r.json['messages'][-1]['texte']
    return client.get('/api/assistant/actions').json['actions'][0]


def confirmer(client, a, reponses=None, doublon=False):
    return client.post('/api/assistant/actions/' + a['id'] + '/confirmer', json={
        'revision':a['revision'], 'comparaisons':reponses or [], 'accepter_doublon':doublon})


def reference(db, uid, nom='Référence', priorite=0, deadline='2026-11-22', statut='a_faire'):
    tid = db.execute('''INSERT INTO planif_taches(user_id,type,titre,duree_min,deadline,priorite_num,statut)
        VALUES (?,'tache',?,30,?,?,?)''', (uid,nom,deadline,priorite,statut)).lastrowid
    db.commit()
    return tid


def test_preparer_sans_creer_et_confirmation_unique(db, admin_client, modele):
    a = preparer(admin_client, modele)
    assert a['statut'] == 'attente' and not a['references']
    assert db.execute('SELECT COUNT(*) FROM planif_taches').fetchone()[0] == 0
    r = confirmer(admin_client, a)
    assert r.status_code == 200 and r.json['statut'] == 'executee', r.json
    tache = db.execute('SELECT * FROM planif_taches').fetchone()
    assert tache['priorite_num'] == 0 and tache['titre'] == TACHE['titre']
    assert db.execute('SELECT COUNT(*) FROM planif_blocs').fetchone()[0] > 0
    assert confirmer(admin_client, a).json['resultat']['id'] == tache['id']
    assert db.execute('SELECT COUNT(*) FROM planif_taches').fetchone()[0] == 1
    assert len(modele['appels']) == 1
    row = db.execute('SELECT contenu FROM assistant_actions').fetchone()
    assert TACHE['titre'] not in row['contenu']


def test_rdv_bloc_fixe_et_chevauchement_signale(db, admin_client, modele):
    a = preparer(admin_client, modele, RDV)
    assert confirmer(admin_client, a).status_code == 200
    bloc = db.execute('SELECT * FROM planif_blocs').fetchone()
    assert bloc['date'] == RDV['date_fixe'] and bloc['verrouille'] == 1
    second = preparer(admin_client, modele, {**RDV, 'titre':'Autre point', 'heure_debut':'14:30'})
    assert second['conflits'][0]['debut'] == '14:00'
    assert db.execute('SELECT COUNT(*) FROM planif_taches').fetchone()[0] == 1
    assert confirmer(admin_client, second).status_code == 200
    assert dict(db.execute('SELECT * FROM planif_blocs WHERE id=?', (bloc['id'],)).fetchone()) == dict(bloc)


@pytest.mark.parametrize('nombre', [0,1,2,3])
def test_comparatif_zero_une_deux_references(db, admin_client, modele, sample_users, nombre):
    uid = sample_users['directeur_id']
    ids = [reference(db, uid, 'Référence ' + str(i), i*3) for i in range(nombre)]
    reference(db, sample_users['comptable_id'], 'Privé comptable', 99)
    reference(db, uid, 'Terminée', 99, statut='fait')
    a = preparer(admin_client, modele)
    assert len(a['references']) == min(nombre,2)
    assert all(r['id'] in ids and set(r) == {'id','titre'} for r in a['references'])
    if nombre:
        assert confirmer(admin_client, a).status_code == 400
    reps = [{'tache_id':r['id'], 'reponse':'superieur'} for r in a['references']]
    r = confirmer(admin_client, a, reps)
    assert r.status_code == 200, r.json
    attendu = 0 if not nombre else max(i*3 for i in range(nombre)) + (1 if nombre==1 else 2)
    assert db.execute('SELECT priorite_num FROM planif_taches WHERE id=?', (r.json['resultat']['id'],)).fetchone()[0] == attendu


def test_comparaisons_incoherentes_ne_modifient_pas_anciennes_taches(db, admin_client, modele, sample_users):
    uid = sample_users['directeur_id']
    h, b = reference(db,uid,'Haute',5), reference(db,uid,'Basse',2)
    a = preparer(admin_client, modele)
    avant = [dict(r) for r in db.execute('SELECT * FROM planif_taches')]
    r = confirmer(admin_client, a, [{'tache_id':h,'reponse':'superieur'},{'tache_id':b,'reponse':'inferieur'}])
    assert r.status_code == 400 and 'contradictoires' in r.json['error']
    assert [dict(r) for r in db.execute('SELECT * FROM planif_taches')] == avant
    r = confirmer(admin_client, a, [{'tache_id':h,'reponse':'inferieur'},{'tache_id':b,'reponse':'superieur'}])
    assert r.status_code == 200, r.json
    assert db.execute('SELECT priorite_num FROM planif_taches WHERE id=?', (r.json['resultat']['id'],)).fetchone()[0] == 3


def test_placement_nouveau_sans_deplacer_blocs_existants(db, admin_client, modele, sample_users):
    uid = sample_users['directeur_id']
    tid = reference(db, uid)
    bid = db.execute('''INSERT INTO planif_blocs(tache_id,user_id,date,heure_debut,heure_fin,duree_min)
        VALUES (?,?,'2026-11-20','09:00','12:30',210)''', (tid,uid)).lastrowid
    db.commit()
    avant = dict(db.execute('SELECT * FROM planif_blocs WHERE id=?',(bid,)).fetchone())
    a = preparer(admin_client, modele)
    r = confirmer(admin_client, a, [{'tache_id':tid,'reponse':'superieur'}])
    assert r.status_code == 200, r.json
    assert dict(db.execute('SELECT * FROM planif_blocs WHERE id=?',(bid,)).fetchone()) == avant
    nouveaux = db.execute('SELECT * FROM planif_blocs WHERE tache_id=?',(r.json['resultat']['id'],)).fetchall()
    assert nouveaux and all(b['date'] != avant['date'] or b['heure_debut'] >= '12:30' for b in nouveaux)


def test_modifications_imposent_nouvelle_revision(db, admin_client, modele):
    a = preparer(admin_client, modele, {**RDV,'heure_fin':None})
    assert a['precision'] and confirmer(admin_client,a).status_code == 400
    r = admin_client.put('/api/assistant/actions/'+a['id'],json={'revision':a['revision'], 'champs':RDV})
    assert r.status_code == 200 and not r.json['precision']
    assert confirmer(admin_client,a).status_code == 409
    assert confirmer(admin_client,r.json).status_code == 200
    assert db.execute('SELECT COUNT(*) FROM planif_taches').fetchone()[0] == 1


def test_reference_changee_actualisation_obligatoire(db, admin_client, modele, sample_users):
    a = preparer(admin_client, modele)
    tid = reference(db,sample_users['directeur_id'])
    assert confirmer(admin_client,a).status_code == 409
    b = admin_client.get('/api/assistant/actions/'+a['id']).json
    assert b['revision'] > a['revision'] and len(b['references']) == 1
    assert confirmer(admin_client,b,[{'tache_id':tid,'reponse':'egal'}]).status_code == 200


def test_doublon_semantique_demande_confirmation_distincte(db, admin_client, modele):
    a = preparer(admin_client, modele,RDV)
    assert confirmer(admin_client,a).status_code == 200
    b = preparer(admin_client,modele,RDV)
    assert len(b['similaires']) == 1
    assert confirmer(admin_client,b).status_code == 409
    assert db.execute('SELECT COUNT(*) FROM planif_taches').fetchone()[0] == 1
    b = admin_client.get('/api/assistant/actions/'+b['id']).json
    assert confirmer(admin_client,b,doublon=True).status_code == 200
    assert db.execute('SELECT COUNT(*) FROM planif_taches').fetchone()[0] == 2


def test_rejeu_message_apres_autre_tour_sans_nouvel_appel(db, admin_client, modele):
    rid = str(uuid.uuid4())
    preparer(admin_client,modele,RDV,rid)
    preparer(admin_client,modele,TACHE)
    avant = len(modele['appels'])
    r = message(admin_client,texte='Prépare un rendez-vous ou une tâche personnelle.',rid=rid)
    assert r.status_code == 200 and len(modele['appels']) == avant
    assert db.execute('SELECT COUNT(*) FROM assistant_actions').fetchone()[0] == 2
    assert message(admin_client,texte='Autre demande',rid=rid).status_code == 409
    assert db.execute('SELECT COUNT(*) FROM planif_taches').fetchone()[0] == 0


def test_abandon_et_expiration_sans_creation(db, admin_client, modele, monkeypatch):
    a = preparer(admin_client,modele)
    assert admin_client.post('/api/assistant/actions/'+a['id']+'/abandonner',json={'revision':a['revision']}).status_code == 200
    assert confirmer(admin_client,a).status_code == 409
    b = preparer(admin_client,modele)
    monkeypatch.setattr(actions,'instant',lambda:b['expire_le']+1)
    assert confirmer(admin_client,b).status_code == 409
    assert admin_client.get('/api/assistant/actions/'+b['id']).json['statut'] == 'expiree'
    assert db.execute('SELECT COUNT(*) FROM planif_taches').fetchone()[0] == 0


def test_isolation_autrui_et_changement_droits(app, db, admin_client, modele, sample_users):
    a = preparer(admin_client,modele,RDV)
    autre = connexion_distincte(app,'compta_test','compta123')
    assert autre.get('/api/assistant/actions').json['actions'] == []
    assert autre.get('/api/assistant/actions/'+a['id']).status_code == 404
    assert confirmer(autre,a).status_code == 404
    assert autre.put('/api/assistant/actions/'+a['id'],json={'revision':a['revision'],'champs':RDV}).status_code == 404
    db.execute("UPDATE users SET profil='salarie',secteur_id=? WHERE id=?",(sample_users['secteur_id'],sample_users['directeur_id']));db.commit()
    assert confirmer(admin_client,a).status_code == 403
    assert db.execute('SELECT COUNT(*) FROM planif_taches').fetchone()[0] == 0


def test_pilotage_cree_uniquement_dans_son_planificateur(db, auth_client, modele, sample_users):
    db.execute("UPDATE secteurs SET nom='Pilotage' WHERE id=?",(sample_users['secteur_id'],));db.commit()
    a = preparer(auth_client,modele,RDV)
    assert confirmer(auth_client,a).status_code == 200
    assert db.execute('SELECT user_id FROM planif_taches').fetchone()[0] == sample_users['salarie_id']


@pytest.mark.parametrize('champs', [{**TACHE,'user_id':1}, {**TACHE,'priorite_num':99},
    {'type':'supprimer','titre':'effacer'}, {**TACHE,'duree_min':True}, {**RDV,'date_fixe':'demain'},
    {**RDV,'heure_fin':'25:00'}, {**TACHE,'sql':'DELETE FROM users'}])
def test_modele_ne_fournit_ni_droits_ni_identifiants(db, admin_client, modele, champs):
    modele['champs'] = champs
    r = message(admin_client)
    assert r.status_code == 400, r.json
    assert db.execute('SELECT COUNT(*) FROM assistant_actions').fetchone()[0] == 0
    assert db.execute('SELECT COUNT(*) FROM planif_taches').fetchone()[0] == 0


def test_comparaisons_usurpees_refusees(db, admin_client, modele, sample_users):
    reference(db,sample_users['directeur_id'])
    autre = reference(db,sample_users['comptable_id'])
    a = preparer(admin_client,modele)
    assert confirmer(admin_client,a,[{'tache_id':autre,'reponse':'superieur'}]).status_code == 400
    assert db.execute('SELECT COUNT(*) FROM planif_taches').fetchone()[0] == 2


def test_erreur_creation_annule_tache_bloc_et_execution(db, admin_client, modele, monkeypatch):
    a = preparer(admin_client,modele)
    def echec(*args):
        raise RuntimeError('Erreur synthétique interne')
    monkeypatch.setattr(actions,'placer_nouvelle_tache',echec)
    r = confirmer(admin_client,a)
    assert r.status_code == 503 and 'synthétique' not in r.json['error']
    assert db.execute('SELECT COUNT(*) FROM planif_taches').fetchone()[0] == 0
    assert db.execute('SELECT statut FROM assistant_actions').fetchone()[0] == 'attente'


def test_effacement_conversation_en_cours_annule_proposition(db, admin_client, modele, monkeypatch):
    def fake(*args):
        assert admin_client.post('/api/assistant/oublier',json={'tout':False}).status_code == 200
        return {'consultations':[], 'proposition':RDV}
    monkeypatch.setattr(assistant_agent,'appel_json',fake)
    assert message(admin_client).status_code == 409
    assert db.execute('SELECT COUNT(*) FROM assistant_actions').fetchone()[0] == 0


def test_quotas_et_limite_propositions(db, admin_client, modele):
    for _ in range(10):
        preparer(admin_client,modele)
    assert message(admin_client).status_code == 409
    assert db.execute('SELECT COUNT(*) FROM assistant_actions').fetchone()[0] == 10
    db.execute('UPDATE assistant_etats SET tours=30');db.commit()
    avant = len(modele['appels'])
    assert message(admin_client).status_code == 429
    assert len(modele['appels']) == avant


def test_csrf_et_anonyme(app, admin_client, modele):
    a = preparer(admin_client,modele)
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        assert confirmer(admin_client,a).status_code == 302
    finally:
        app.config['WTF_CSRF_ENABLED'] = False
    admin_client.get('/logout')
    assert confirmer(admin_client,a).status_code == 302


def test_schema_migration_et_rechiffrement(app, db, admin_client, modele):
    a = preparer(admin_client,modele)
    p = Path(__file__).resolve().parents[1]/'migrations/0086_assistant_actions.py'
    spec=importlib.util.spec_from_file_location('migration86',p)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with sqlite3.connect(':memory:') as conn:
        conn.execute('CREATE TABLE users(id INTEGER PRIMARY KEY)')
        module.upgrade(conn);module.upgrade(conn)
        assert conn.execute('SELECT COUNT(*) FROM assistant_actions').fetchone()[0] == 0
    assert db.execute("SELECT statut FROM schema_migrations WHERE version='0086'").fetchone()[0] == 'ok'
    from resilience import rechiffrer_parametres, fernet_pour
    with app.app_context():
        rechiffrer_parametres(db,app.secret_key,'cle-test-nouvelle')
    contenu=db.execute('SELECT contenu FROM assistant_actions WHERE id=?',(a['id'],)).fetchone()[0]
    assert json.loads(fernet_pour('cle-test-nouvelle').decrypt(contenu.encode()))['champs']['titre'] == TACHE['titre']


def test_element_supprime_manuellement_non_recree(db, admin_client, modele):
    a = preparer(admin_client,modele,RDV)
    confirmer(admin_client,a)
    db.execute('DELETE FROM planif_blocs');db.execute('DELETE FROM planif_taches');db.commit()
    rejoue=confirmer(admin_client,a)
    assert rejoue.status_code == 200 and not rejoue.json['resultat']['existe']
    assert db.execute('SELECT COUNT(*) FROM planif_taches').fetchone()[0] == 0


def test_deux_confirmations_concurrentes_ne_creent_qu_un_rdv(app, db, admin_client, modele):
    from concurrent.futures import ThreadPoolExecutor
    a = preparer(admin_client,modele,RDV)
    c1=connexion_distincte(app,'admin','Admin1234')
    c2=connexion_distincte(app,'admin','Admin1234')
    with ThreadPoolExecutor(max_workers=2) as pool:
        resultats=list(pool.map(lambda c:confirmer(c,a),[c1,c2]))
    assert [r.status_code for r in resultats] == [200,200]
    assert resultats[0].json['resultat']['id'] == resultats[1].json['resultat']['id']
    assert db.execute('SELECT COUNT(*) FROM planif_taches').fetchone()[0] == 1
    assert db.execute('SELECT COUNT(*) FROM planif_blocs').fetchone()[0] == 1


def test_aucune_place_disponible_tache_conservee(db, admin_client, modele, monkeypatch):
    monkeypatch.setattr('blueprints.planificateur._horaires_par_date',lambda *args:{})
    a=preparer(admin_client,modele)
    r=confirmer(admin_client,a)
    assert r.status_code == 200 and r.json['resultat']['non_placee'],r.json
    assert db.execute('SELECT COUNT(*) FROM planif_taches').fetchone()[0] == 1
    assert db.execute('SELECT COUNT(*) FROM planif_blocs').fetchone()[0] == 0


@pytest.mark.parametrize('modifs', [{'date_fixe':'2026-11-19'},{'heure_fin':'13:00'}])
def test_date_passee_ou_fin_avant_debut_sans_creation(db, admin_client, modele, modifs):
    a=preparer(admin_client,modele,{**RDV,**modifs})
    assert confirmer(admin_client,a).status_code == 400
    assert db.execute('SELECT COUNT(*) FROM planif_taches').fetchone()[0] == 0


def test_echec_enregistrement_resultat_annule_tous_les_elements(db, admin_client, modele):
    a=preparer(admin_client,modele)
    db.execute("""CREATE TRIGGER incident_execution BEFORE UPDATE ON assistant_actions
        WHEN NEW.statut='executee' BEGIN SELECT RAISE(ABORT,'Incident synthétique'); END""")
    db.commit()
    assert confirmer(admin_client,a).status_code == 503
    assert db.execute('SELECT COUNT(*) FROM planif_taches').fetchone()[0] == 0
    assert db.execute('SELECT COUNT(*) FROM planif_blocs').fetchone()[0] == 0
    assert db.execute('SELECT statut FROM assistant_actions').fetchone()[0] == 'attente'


def test_changement_perimetre_expire_proposition(db, admin_client, modele, sample_users):
    a=preparer(admin_client,modele)
    db.execute("UPDATE users SET profil='responsable' WHERE id=?",(sample_users['directeur_id'],));db.commit()
    assert confirmer(admin_client,a).status_code == 409
    assert admin_client.get('/api/assistant/actions/'+a['id']).json['statut'] == 'expiree'
    assert db.execute('SELECT COUNT(*) FROM planif_taches').fetchone()[0] == 0


def test_confirmation_sans_nouvel_appel_ni_cle_api(app, admin_client, modele):
    a=preparer(admin_client,modele,RDV)
    from utils import delete_setting
    with app.app_context():
        delete_setting('openai_api_key')
    assert confirmer(admin_client,a).status_code == 200
    assert len(modele['appels']) == 1


def test_preparation_apres_consultation_sans_execution(db, admin_client, modele, monkeypatch):
    appels=[]
    def fake(model,messages):
        appels.append(messages)
        if len(appels)==1:
            return {'consultations':[{'nom':'planificateur','arguments':{}}]}
        return {'proposition':TACHE}
    monkeypatch.setattr(assistant_agent,'appel_json',fake)
    a=preparer(admin_client,modele)
    assert a['champs']['titre'] == TACHE['titre'] and len(appels)==2
    assert db.execute('SELECT COUNT(*) FROM planif_taches').fetchone()[0] == 0


def test_priorites_egales_ordre_des_references_ne_permet_aucune_reevaluation(
        db, admin_client, modele, sample_users, monkeypatch):
    import blueprints.planificateur as planif
    uid=sample_users['directeur_id']
    a_id=reference(db,uid,'Référence A',0)
    b_id=reference(db,uid,'Référence B',0)
    lignes=[dict(db.execute('SELECT * FROM planif_taches WHERE id=?',(i,)).fetchone()) for i in (b_id,a_id)]
    monkeypatch.setattr(planif,'_candidats_comparaison',lambda *args,**kwargs:lignes)
    a=preparer(admin_client,modele)
    avant=[dict(r) for r in db.execute('SELECT * FROM planif_taches')]
    r=confirmer(admin_client,a,[{'tache_id':a_id,'reponse':'superieur'},{'tache_id':b_id,'reponse':'inferieur'}])
    assert r.status_code == 400,r.json
    assert [dict(r) for r in db.execute('SELECT * FROM planif_taches')] == avant
