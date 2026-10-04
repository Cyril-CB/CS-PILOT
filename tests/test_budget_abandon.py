"""Abandon volontaire de l'initial, sans effacement implicite des autres données."""
import pytest
from tests.test_budget_initial_routes import etat, sauver, plan_general
from tests.test_budget_initial_moteur import salaire
from tests.test_budget_regles import post, lire
from tests.test_budget_taux_charges import simulation, enregistrer

URL = '/api/budget-previsionnel/paie-simulation/abandonner'


def token(client, sid):
    return client.get('/api/budget-previsionnel/paie-simulation', query_string={
        'annee':2026, 'secteur_id':sid, 'type_budget':'initial'}).get_json()['reference_budget']


def payload(client, sid):
    return {'annee':2026,'secteur_id':sid,'type_budget':'initial',
            'confirmer':True,'reference_budget':token(client,sid)}


@pytest.fixture
def scenario(admin_client, db):
    sid=db.execute("INSERT INTO secteurs(nom) VALUES ('Pilotage fictif')").lastrowid
    db.commit()
    assert admin_client.post('/api/budget-previsionnel/ajouter-compte',json={
        'annee':2026,'type_budget':'initial','secteur_id':sid,'compte_num':'641100'}).status_code==200
    assert post(admin_client,sid,'paie-simulation','initial',compte_num='641100',
                donnees={'salaire_socle':24000,'ajouts':[{'type':'cdi','pesee':100}]}).status_code==200
    return sid


def test_effacer_puis_abandon_et_report(admin_client, db, scenario):
    sid=scenario
    before=[tuple(r) for r in db.execute('SELECT * FROM budget_paie_simulations')]
    row=lire(admin_client,sid,'initial')['rows'][0]
    assert post(admin_client,sid,'save-lines','initial',lignes=[{'compte_num':'641100',
        'valeur_def':None,'valeur_temp':row['temp'],'effacer_montant':True,'commentaire':'Conservé'}]).status_code==200
    assert tuple(db.execute("SELECT valeur_def,valeur_temp FROM budget_prev_saisies WHERE secteur_id=?",(sid,)).fetchone())==(None,None)
    assert [tuple(r) for r in db.execute('SELECT * FROM budget_paie_simulations')]==before
    assert sauver(admin_client,salaire(secteurs={str(sid):'100'})).status_code==200
    assert not etat(admin_client)['reports'][0]['possible']
    p=payload(admin_client,sid)
    assert admin_client.post(URL,json=p).status_code==200
    # Deuxième clic/rejeu : référence périmée, aucune deuxième mutation.
    assert admin_client.post(URL,json=p).status_code==409
    state=etat(admin_client)
    assert state['reports'][0]['possible']
    assert admin_client.post('/api/budget-initial-detaille/reporter',json={
        'annee':2026,'revision':state['revision'],'reference_report':state['reference_report']}).get_json()['reportes']==1
    assert db.execute('SELECT commentaire FROM budget_prev_saisies WHERE secteur_id=?',(sid,)).fetchone()[0]=='Conservé'


@pytest.mark.parametrize('value,flag,typ,expected',[(None,False,'initial',123),(0,True,'initial',0),(None,True,'actualise',123)])
def test_pas_effacement_implicite(admin_client, db, scenario,value,flag,typ,expected):
    sid=scenario
    if typ=='actualise':
        assert admin_client.post('/api/budget-previsionnel/ajouter-compte',json={
            'annee':2026,'type_budget':typ,'secteur_id':sid,'compte_num':'641100'}).status_code==200
    assert post(admin_client,sid,'save-lines',typ,lignes=[{'compte_num':'641100',
        'valeur_def':value,'valeur_temp':123,'effacer_montant':flag}]).status_code==200
    assert db.execute('SELECT valeur_temp FROM budget_prev_saisies WHERE secteur_id=? AND type_budget=?',(sid,typ)).fetchone()[0]==expected


@pytest.mark.parametrize('raw',[None,'{invalide','null','[]','{}'])
def test_abandon_uniquement_explicite_et_perimetre(admin_client, db, scenario,raw):
    sid=scenario
    other=db.execute("INSERT INTO secteurs(nom) VALUES ('Autre fictif')").lastrowid
    db.execute("UPDATE budget_paie_simulations SET donnees=? WHERE secteur_id=?",(raw,sid))
    for typ,year,sector in [('actualise',2026,sid),('initial',2027,sid),('initial',2026,other)]:
        db.execute('INSERT INTO budget_paie_simulations(type_budget,annee,secteur_id,compte_num,donnees) VALUES (?,?,?,\'641100\',?)',(typ,year,sector,raw))
    db.commit()
    tables=['budget_prev_saisies','budget_modes_comptes','users','contrats','budget_initial_reports']
    before={t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in tables}
    simulations=[tuple(r) for r in db.execute('SELECT * FROM budget_paie_simulations WHERE NOT (type_budget=\'initial\' AND annee=2026 AND secteur_id=?)',(sid,))]
    p=payload(admin_client,sid)
    assert admin_client.post(URL,json={**p,'confirmer':False}).status_code==400
    assert db.execute('SELECT count(*) FROM budget_paie_simulations').fetchone()[0]==4
    assert admin_client.post(URL,json=p).status_code==200
    assert [tuple(r) for r in db.execute('SELECT * FROM budget_paie_simulations')]==simulations
    for t in tables:
        assert [tuple(r) for r in db.execute('SELECT * FROM '+t)]==before[t]


def test_abandon_taux_conserve_montants_et_modes(admin_client, db, simulation):
    sid,_,_=simulation
    assert enregistrer(admin_client,simulation).status_code==200
    tables=['budget_prev_saisies','budget_modes_comptes','users','contrats']
    before={t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in tables}
    assert admin_client.post(URL,json=payload(admin_client,sid)).status_code==200
    for t in tables:
        assert [tuple(r) for r in db.execute('SELECT * FROM '+t)]==before[t]
    assert all(r['mode']!='taux_salaries' for r in lire(admin_client,sid,'initial')['rows'])


@pytest.mark.parametrize('profil',['auth_client','resp_client','prestataire_client'])
def test_droits(request,profil,db,sample_users):
    client=request.getfixturevalue(profil)
    r=client.post(URL,json={'type_budget':'initial','annee':2026,'secteur_id':sample_users['secteur_id'],'confirmer':True})
    assert r.status_code==403


def test_csrf_et_actualise_refuses(admin_client,app,db,scenario):
    p=payload(admin_client,scenario)
    assert admin_client.post(URL,json={**p,'type_budget':'actualise'}).status_code==400
    assert admin_client.post(URL,json={**p,'reference_budget':'invalide'}).status_code==409
    app.config['WTF_CSRF_ENABLED']=True
    try:
        assert admin_client.post(URL,json=p).status_code==302
        assert db.execute('SELECT count(*) FROM budget_paie_simulations').fetchone()[0]==1
    finally:
        app.config['WTF_CSRF_ENABLED']=False


def test_reference_perimee_et_saisie_independante(admin_client, db, scenario):
    sid=scenario
    ancien=payload(admin_client,sid)
    db.execute("UPDATE budget_paie_simulations SET total=total+1 WHERE secteur_id=?",(sid,))
    db.commit()
    assert admin_client.post(URL,json=ancien).status_code==409
    assert admin_client.post(URL,json=payload(admin_client,sid)).status_code==200
    assert sauver(admin_client,salaire(secteurs={str(sid):'100'})).status_code==200
    assert not etat(admin_client)['reports'][0]['possible'] # Montant non effacé encore protégé.


def test_comptable_autorise_et_anonyme_refuse(request,db,scenario,admin_client):
    sid=scenario
    admin_client.get('/logout')
    assert admin_client.post(URL,json={'type_budget':'initial','confirmer':True}).status_code==302
    comptable=request.getfixturevalue('comptable_client')
    assert comptable.post(URL,json=payload(comptable,sid)).status_code==200
