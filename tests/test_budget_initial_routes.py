"""Intégration Flask sur les fixtures synthétiques ; nécessite requirements.txt."""
import json

import pytest

from tests.test_budget_initial_moteur import depense, salaire
from tests.test_budget_regles import lire as lire_ancien

API = '/api/budget-initial-detaille'


def etat(client, annee=2026):
    r = client.get(API, query_string={'annee': annee})
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def sauver(client, data, action='ligne', **options):
    d = {'annee': 2026, 'revision': etat(client)['revision'], 'action': action,
         action: {'donnees': data} if action == 'ligne' else data, **options}
    return client.post(API + '/enregistrer', json=d)


def ligne_secteur(sample_users, **champs):
    return depense(**{'secteurs': {str(sample_users['secteur_id']): '100'}, **champs})


@pytest.mark.parametrize('fixture', ['admin_client', 'comptable_client'])
def test_parcours_creation_reouverture_report_et_pdf(request, fixture, sample_users, db):
    client = request.getfixturevalue(fixture)
    sid = sample_users['secteur_id']
    page = client.get('/budget-initial-detaille?annee=2026')
    assert page.status_code == 200
    assert 'Initial annuel détaillé' in page.get_data(as_text=True)
    assert sauver(client, ligne_secteur(sample_users)).status_code == 200
    d = etat(client)
    assert d['calcul']['complet']
    ident = d['lignes'][0]['id']
    assert etat(client)['lignes'][0]['id'] == ident
    r = client.post(API + '/reporter', json={'annee': 2026, 'revision': d['revision'],
                                           'reference_report': d['reference_report']})
    assert r.status_code == 200 and r.get_json()['reportes'] == 1
    ancien = lire_ancien(client, sid, 'initial')
    assert next(r for r in ancien['rows'] if r['compte_num'] == '606100')['def'] == 1200
    pdf = client.get('/api/budget-previsionnel/export-pdf', query_string={
        'type_budget': 'initial', 'annee': 2026, 'secteur_id': sid})
    assert pdf.status_code == 200 and pdf.data.startswith(b'%PDF')
    row = db.execute('SELECT * FROM budget_initial_lignes WHERE id=?', (ident,)).fetchone()
    assert row['lien_type'] is None and row['lien_id'] is None


@pytest.mark.parametrize('fixture', ['auth_client', 'resp_client', 'prestataire_client'])
def test_details_individuels_refuses_aux_autres_profils(request, fixture):
    client = request.getfixturevalue(fixture)
    assert client.get('/budget-initial-detaille').status_code == 403
    assert client.get(API + '?annee=2026').status_code == 403
    for endpoint in ('enregistrer', 'reporter'):
        assert client.post(API + '/' + endpoint, json={'annee': 2026}).status_code == 403


def test_non_connecte(client):
    for path in ('/budget-initial-detaille', API + '?annee=2026'):
        assert client.get(path).status_code == 302
    assert client.post(API + '/enregistrer', json={}).status_code == 302


def test_csrf_requis(app, admin_client):
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        for path in ('enregistrer', 'reporter'):
            assert admin_client.post(API + '/' + path, json={'annee': 2026}).status_code == 400
    finally:
        app.config['WTF_CSRF_ENABLED'] = False


def test_session_revoquee_refusee(admin_client, sample_users, db):
    db.execute('UPDATE users SET session_version=session_version+1 WHERE id=?', (sample_users['directeur_id'],))
    db.commit()
    assert admin_client.post(API + '/enregistrer', json={'annee':2026}).status_code == 302


def test_actualise_formules_commentaires_et_simulation_inchanges(admin_client, sample_users, db):
    sid = sample_users['secteur_id']
    db.execute('''INSERT INTO budget_prev_saisies
        (type_budget,annee,secteur_id,compte_num,valeur_temp,valeur_def,commentaire)
        VALUES ('actualise',2026,?,'606100',55.55,55.55,'Commentaire fictif conservé')''', (sid,))
    db.execute("INSERT INTO budget_modes_comptes VALUES ('actualise',2026,?,'645100','proportionnel')", (sid,))
    db.execute('''INSERT INTO budget_paie_simulations (type_budget,annee,secteur_id,donnees)
        VALUES ('actualise',2026,?,?)''', (sid, json.dumps({'ajouts': [], 'salaire_socle': 24000})))
    db.commit()
    tables = ['budget_prev_saisies','budget_modes_comptes','budget_paie_simulations','users','contrats']
    avant = {t:[tuple(r) for r in db.execute('SELECT * FROM ' + t)] for t in tables}
    assert sauver(admin_client, ligne_secteur(sample_users)).status_code == 200
    d = etat(admin_client)
    assert admin_client.post(API + '/reporter',json={'annee':2026,'revision':d['revision'],'reference_report':d['reference_report']}).status_code == 200
    for t in tables:
        rows = db.execute('SELECT * FROM ' + t + (" WHERE type_budget='actualise'" if t=='budget_prev_saisies' else '')).fetchall()
        assert [tuple(r) for r in rows] == avant[t]
    assert lire_ancien(admin_client,sid)['rows']


def test_montant_manuel_zero_et_commentaire_preserves(admin_client, sample_users, db):
    sid=sample_users['secteur_id']
    db.execute("INSERT INTO budget_prev_saisies (type_budget,annee,secteur_id,compte_num,valeur_def,commentaire) VALUES ('initial',2026,?,'606100',0,'Manuel fictif')",(sid,));db.commit()
    assert sauver(admin_client,ligne_secteur(sample_users)).status_code==200
    d=etat(admin_client)
    assert not d['reports'][0]['possible']
    r=admin_client.post(API+'/reporter',json={'annee':2026,'revision':d['revision'],'reference_report':d['reference_report']})
    assert r.status_code==200 and r.get_json()['reportes']==0
    row=db.execute("SELECT valeur_def,commentaire FROM budget_prev_saisies WHERE type_budget='initial'").fetchone()
    assert tuple(row)==(0,'Manuel fictif')


def test_revision_obsolete_et_erreurs_atomiques(admin_client, sample_users, db):
    assert sauver(admin_client,ligne_secteur(sample_users)).status_code==200
    avant=etat(admin_client)
    for changes in ({'revision':0},{'ligne':{'donnees':ligne_secteur(sample_users,secteurs={'999999':'100'})}},
                    {'ligne':{'id':'inconnu','donnees':ligne_secteur(sample_users)}}, {'action':'actualise'}):
        payload={'annee':2026,'revision':avant['revision'],'action':'ligne','ligne':{'donnees':ligne_secteur(sample_users)},**changes}
        assert admin_client.post(API+'/enregistrer',json=payload).status_code==409
        assert etat(admin_client)['lignes']==avant['lignes']
        assert etat(admin_client)['revision']==avant['revision']


def test_nouvelle_installation_marquee_et_tables_creees(db):
    assert db.execute("SELECT statut FROM schema_migrations WHERE version='0077'").fetchone()['statut']=='ok'
    for table in ('budget_initial_hypotheses','budget_initial_lignes','budget_initial_reports'):
        assert db.execute('SELECT count(*) FROM '+table).fetchone()[0]==0


def test_report_salaire_pas_decriture_rh(admin_client,sample_users,db):
    sid=str(sample_users['secteur_id']);uid=str(sample_users['salarie_id'])
    avant=[tuple(r) for r in db.execute('SELECT * FROM users')]
    d=salaire(secteurs={sid:'100'},poste='occupe',salarie_id=uid)
    assert sauver(admin_client,d).status_code==200
    state=etat(admin_client)
    assert admin_client.post(API+'/reporter',json={'annee':2026,'revision':state['revision'],'reference_report':state['reference_report']}).status_code==200
    assert [tuple(r) for r in db.execute('SELECT * FROM users')]==avant


@pytest.mark.parametrize('annee',['actualise','NaN','1899','2201'])
def test_annees_invalides(admin_client,annee):
    assert admin_client.get(API,query_string={'annee':annee}).status_code==400
