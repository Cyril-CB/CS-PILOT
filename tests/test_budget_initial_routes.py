"""Intégration Flask sur les fixtures synthétiques ; nécessite requirements.txt."""
import json
import importlib
import io

import pdfplumber
import pytest

from tests.test_budget_initial_moteur import depense, salaire
from tests.test_budget_regles import cadre, config, lire as lire_ancien, post, saisir

API = '/api/budget-initial-detaille'


@pytest.fixture(autouse=True)
def plan_general(db):
    db.executemany('INSERT OR IGNORE INTO plan_comptable_general (compte_num,libelle) VALUES (?,?)',
                   [(c, 'Compte synthétique ' + c) for c in ('606100','606200','641100','641200','645100','631100','706100','741100')])
    db.commit()


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


@pytest.mark.parametrize('path', ['enregistrer', 'reporter'])
def test_csrf_requis(app, admin_client, db, path):
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        # Le garde global invalide la session puis redirige vers la connexion.
        # Chaque endpoint est essayé avec une session authentifiée distincte.
        response = admin_client.post(API + '/' + path, json={'annee': 2026})
        assert response.status_code == 302
        assert response.headers['Location'].endswith('/login')
        with admin_client.session_transaction() as session:
            assert 'user_id' not in session
        assert db.execute('SELECT count(*) FROM budget_initial_hypotheses').fetchone()[0] == 0
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


def pdf_texte(client, sid):
    response = client.get('/api/budget-previsionnel/export-pdf', query_string={
        'type_budget': 'actualise', 'annee': 2026, 'secteur_id': sid})
    assert response.status_code == 200 and response.data.startswith(b'%PDF')
    with pdfplumber.open(io.BytesIO(response.data)) as pdf:
        return [page.extract_text() for page in pdf.pages]


def test_actualise_2026_recalcul_simulation_pdf_apres_migration_et_report(cadre, admin_client, db):
    sid, uid = cadre
    assert admin_client.post('/api/budget-previsionnel/ajouter-compte', json={
        'type_budget': 'actualise', 'annee': 2026, 'secteur_id': sid, 'compte_num': '606100'}).status_code == 200
    assert config(admin_client, sid).status_code == 200
    assert saisir(admin_client, sid, {'641100': 120000, '641200': 10000, '606100': 0}).status_code == 200
    assert post(admin_client, sid, 'paie-simulation', compte_num='641100', donnees={
        'salaire_socle': 120000, 'valeur_point': 0, 'temps_plein': 35,
        'employes': {str(uid): {'pesee': 0, 'competence': 0, 'anciennete': 0, 'maintien': 0}}
    }).status_code == 200
    db.execute("UPDATE budget_prev_saisies SET commentaire='Manuel zéro conservé' WHERE type_budget='actualise' AND compte_num='606100'")
    db.commit()
    # L'ancien actualisé affiche une colonne comparative « Initial ».
    # Établir son résultat de référence avec une écriture par l'ancien parcours.
    assert admin_client.post('/api/budget-previsionnel/ajouter-compte', json={
        'type_budget': 'initial', 'annee': 2026, 'secteur_id': sid, 'compte_num': '606100'}).status_code == 200
    assert saisir(admin_client, sid, {'606100': 1200}, typ='initial').status_code == 200
    attendu_apres_report = lire_ancien(admin_client, sid)
    pdf_attendu_apres_report = pdf_texte(admin_client, sid)
    db.execute("DELETE FROM budget_prev_saisies WHERE type_budget='initial'")
    # Reconstituer le schéma précédent sur cette seule base synthétique.
    for table in ('budget_initial_reports', 'budget_initial_lignes', 'budget_initial_hypotheses'):
        db.execute('DROP TABLE ' + table)
    db.execute("DELETE FROM schema_migrations WHERE version='0077'")
    db.commit()
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('schema_migrations','schema_migrations_tentatives','sqlite_sequence') ORDER BY name")]
    avant = {t: [tuple(r) for r in db.execute('SELECT * FROM "' + t + '"')] for t in tables}
    donnees_avant = lire_ancien(admin_client, sid)
    pdf_avant = pdf_texte(admin_client, sid)
    from migration_manager import appliquer_toutes_en_attente
    appliquer_toutes_en_attente(appliquee_par='pytest')
    importlib.import_module('migrations.0077_budget_initial_detaille').upgrade(db)
    db.commit()
    for table, valeurs in avant.items():
        assert [tuple(r) for r in db.execute('SELECT * FROM "' + table + '"')] == valeurs, table
    assert db.execute("SELECT statut FROM schema_migrations WHERE version='0077'").fetchone()[0] == 'ok'
    assert lire_ancien(admin_client, sid) == donnees_avant
    assert pdf_texte(admin_client, sid) == pdf_avant
    assert sauver(admin_client, depense(secteurs={str(sid): '100'})).status_code == 200
    state = etat(admin_client)
    response = admin_client.post(API + '/reporter', json={
        'annee': 2026, 'revision': state['revision'], 'reference_report': state['reference_report']})
    assert response.status_code == 200 and response.get_json()['reportes'] == 1
    apres = lire_ancien(admin_client, sid)
    assert apres['rows'] == attendu_apres_report['rows']
    assert apres['totaux'] == attendu_apres_report['totaux']
    assert pdf_texte(admin_client, sid) == pdf_attendu_apres_report
    assert post(admin_client, sid, 'recalculer').status_code == 200
    apres = lire_ancien(admin_client, sid)
    assert apres['rows'] == attendu_apres_report['rows']
    assert apres['totaux'] == donnees_avant['totaux']
    assert pdf_texte(admin_client, sid) == pdf_attendu_apres_report
    for table in ('budget_modes_comptes', 'budget_paie_simulations', 'users', 'contrats'):
        assert [tuple(r) for r in db.execute('SELECT * FROM ' + table)] == avant[table]
    assert saisir(admin_client, sid, {'606100': 1250}).status_code == 200
    assert next(r for r in lire_ancien(admin_client, sid)['rows'] if r['compte_num'] == '606100')['def'] == 1250


def test_premiere_ligne_sans_hypotheses_reste_reouvrable(admin_client, sample_users):
    avant = etat(admin_client)['hypotheses']
    assert avant == {'note': '', 'taux_individuels': False}
    assert sauver(admin_client, ligne_secteur(sample_users)).status_code == 200
    assert etat(admin_client)['hypotheses'] == avant


def test_report_perime_et_incomplet_refuses_sans_ecriture(admin_client, sample_users, db):
    assert sauver(admin_client, ligne_secteur(sample_users, annuel=None)).status_code == 200
    state = etat(admin_client)
    payload = {'annee': 2026, 'revision': state['revision'], 'reference_report': state['reference_report']}
    assert admin_client.post(API + '/reporter', json=payload).status_code == 409
    assert db.execute('SELECT count(*) FROM budget_prev_saisies').fetchone()[0] == 0
    assert sauver(admin_client, ligne_secteur(sample_users), ligne={
        'id': state['lignes'][0]['id'], 'donnees': ligne_secteur(sample_users)}).status_code == 200
    state = etat(admin_client)
    assert admin_client.post(API + '/reporter', json=payload).status_code == 409
    db.execute("INSERT INTO budget_prev_saisies (type_budget,annee,secteur_id,compte_num,valeur_def) VALUES ('initial',2026,?,'606100',42)", (sample_users['secteur_id'],))
    db.commit()
    assert admin_client.post(API + '/reporter', json={
        'annee': 2026, 'revision': state['revision'], 'reference_report': state['reference_report']}).status_code == 409
    assert db.execute('SELECT valeur_def FROM budget_prev_saisies').fetchone()[0] == 42


@pytest.mark.parametrize('simulateur', ['paie', 'ps'])
def test_simulation_apres_report_meme_montant_reste_proprietaire(admin_client, db, simulateur):
    sid = db.execute("INSERT INTO secteurs (nom) VALUES ('Simulation sans RH')").lastrowid
    db.commit()
    code = '641100' if simulateur == 'paie' else '706100'
    ligne = (salaire(secteurs={str(sid): '100'}, brut_mensuel='0') if simulateur == 'paie'
             else depense(secteurs={str(sid): '100'}, nature='financement', compte=code, annuel='0'))
    assert sauver(admin_client, ligne).status_code == 200
    state = etat(admin_client)
    ident = state['lignes'][0]['id']
    payload = lambda s: {'annee': 2026, 'revision': s['revision'], 'reference_report': s['reference_report']}
    assert admin_client.post(API + '/reporter', json=payload(state)).get_json()['reportes'] == 1
    ancien_etat = etat(admin_client)
    response = post(admin_client, sid, simulateur + '-simulation', typ='initial', compte_num=code, donnees={})
    assert response.status_code == 200, response.get_json()
    assert response.get_json()['total'] == 0
    simulation_avant = [tuple(r) for r in db.execute('SELECT * FROM budget_' + simulateur + '_simulations')]
    # Même montant, mais le propriétaire a changé : une page déjà ouverte est périmée.
    assert admin_client.post(API + '/reporter', json=payload(ancien_etat)).status_code == 409
    ligne['brut_mensuel' if simulateur == 'paie' else 'annuel'] = '1200'
    assert sauver(admin_client, ligne, ligne={'id': ident, 'donnees': ligne}).status_code == 200
    # Un compte indépendant reste reportable dans le même secteur.
    assert sauver(admin_client, depense(secteurs={str(sid): '100'}, compte='606200', annuel='24')).status_code == 200
    state = etat(admin_client)
    proposition = next(r for r in state['reports'] if r['compte'] == code)
    assert not proposition['possible'] and 'Simulation' in proposition['motif']
    assert admin_client.post(API + '/reporter', json=payload(state)).get_json()['reportes'] == 1
    assert db.execute("SELECT valeur_def FROM budget_prev_saisies WHERE type_budget='initial' AND compte_num=?", (code,)).fetchone()[0] == 0
    assert [tuple(r) for r in db.execute('SELECT * FROM budget_' + simulateur + '_simulations')] == simulation_avant


@pytest.mark.parametrize('profil', ['admin_client', 'comptable_client'])
def test_secteur_avec_report_ne_peut_pas_etre_supprime(request, profil, db, tmp_path, app):
    client = request.getfixturevalue(profil)
    sid = db.execute("INSERT INTO secteurs (nom) VALUES ('Secteur avec historique initial')").lastrowid
    db.commit()
    assert sauver(client, depense(secteurs={str(sid): '100'})).status_code == 200
    state = etat(client)
    assert client.post(API + '/reporter', json={'annee': 2026, 'revision': state['revision'],
        'reference_report': state['reference_report']}).status_code == 200
    avant = {t: [tuple(r) for r in db.execute('SELECT * FROM ' + t)] for t in (
        'budget_initial_lignes', 'budget_initial_reports', 'budget_prev_saisies')}
    response = client.post('/gestion_secteurs', data={'action': 'supprimer', 'secteur_id': sid}, follow_redirects=True)
    assert response.status_code == 200
    assert 'report de budget initial' in response.get_data(as_text=True)
    assert db.execute('SELECT 1 FROM secteurs WHERE id=?', (sid,)).fetchone()
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    import database
    from resilience import diagnostiquer
    diagnostic = diagnostiquer(tmp_path, app.secret_key, db_path=database.DATABASE)
    assert diagnostic['integrite'] and not diagnostic['erreurs']
    for table, rows in avant.items():
        assert [tuple(r) for r in db.execute('SELECT * FROM ' + table)] == rows


@pytest.mark.parametrize('simulateur', ['paie', 'ps'])
@pytest.mark.parametrize('hors_perimetre', ['actualise', 'annee', 'secteur', 'compte'])
def test_simulation_autre_perimetre_ne_bloque_pas_report(admin_client, sample_users, db, simulateur, hors_perimetre):
    sid = sample_users['secteur_id']
    code = '641100' if simulateur == 'paie' else '706100'
    ligne = (salaire(secteurs={str(sid): '100'}) if simulateur == 'paie'
             else depense(secteurs={str(sid): '100'}, nature='financement', compte=code))
    assert sauver(admin_client, ligne).status_code == 200
    typ, annee, secteur, compte = 'initial', 2026, sid, code
    if hors_perimetre == 'actualise':
        typ = 'actualise'
    elif hors_perimetre == 'annee':
        annee = 2027
    elif hors_perimetre == 'secteur':
        secteur = db.execute("INSERT INTO secteurs (nom) VALUES ('Autre périmètre')").lastrowid
    else:
        compte = '641200' if simulateur == 'paie' else '706200'
    if simulateur == 'paie':
        db.execute('INSERT INTO budget_paie_simulations (type_budget,annee,secteur_id,compte_num,donnees) VALUES (?,?,?,?,?)',
                   (typ, annee, secteur, compte, '{}'))
    else:
        db.execute('INSERT INTO budget_ps_simulations (type_budget,annee,secteur_id,compte_num,donnees,type_ps) VALUES (?,?,?,?,?,?)',
                   (typ, annee, secteur, compte, '{}', 'eaje'))
    db.commit()
    state = etat(admin_client)
    assert state['reports'][0]['possible']
    response = admin_client.post(API + '/reporter', json={'annee': 2026, 'revision': state['revision'],
        'reference_report': state['reference_report']})
    assert response.status_code == 200 and response.get_json()['reportes'] == 1


@pytest.mark.parametrize('nature,code,ok', [
    ('salaire','641100',True), ('salaire','606100',False),
    ('depense','606100',True), ('depense','631100',False),
    ('depense','645100',False), ('depense','641100',False),
    ('financement','706100',True), ('financement','606100',False),
    ('depense','609999',False), ('financement','799999',False),
])
def test_comptes_plan_general_filtres_serveur(admin_client, sample_users, nature, code, ok):
    factory = salaire if nature == 'salaire' else depense
    data = factory(nature=nature, compte=code, secteurs={str(sample_users['secteur_id']): '100'})
    before = etat(admin_client)
    r = sauver(admin_client, data)
    assert r.status_code == (200 if ok else 409), r.get_json()
    if not ok:
        assert etat(admin_client)['revision'] == before['revision']
        assert etat(admin_client)['lignes'] == before['lignes']


def test_ancien_compte_preserve_sans_autoriser_nouveau(admin_client, sample_users, db):
    assert sauver(admin_client, ligne_secteur(sample_users)).status_code == 200
    line = etat(admin_client)['lignes'][0]
    line['donnees']['compte'] = '631100'
    db.execute('UPDATE budget_initial_lignes SET donnees=? WHERE id=?',
               (json.dumps(line['donnees']), line['id']))
    db.commit()
    line['donnees']['note'] = 'Reprise du budget existant'
    assert sauver(admin_client, None, ligne=line).status_code == 200
    assert sauver(admin_client, line['donnees']).status_code == 409
    line['donnees']['compte'] = '645100'
    assert sauver(admin_client, None, ligne=line).status_code == 409


def test_compte_retire_du_plan_et_complement(admin_client, sample_users, db):
    data = salaire(secteurs={str(sample_users['secteur_id']): '100'},
                   complements=[{'libelle':'Prime','compte':'641200','mois':['10'] * 12}])
    assert sauver(admin_client, data).status_code == 200
    line = etat(admin_client)['lignes'][0]
    db.execute("DELETE FROM plan_comptable_general WHERE compte_num LIKE '641%'")
    db.commit()
    assert sauver(admin_client, None, ligne=line).status_code == 200
    assert sauver(admin_client, data).status_code == 409
    line['donnees']['complements'][0]['compte'] = '641999'
    assert sauver(admin_client, None, ligne=line).status_code == 409


@pytest.mark.parametrize('fixture', ['admin_client','comptable_client'])
def test_alisfa_copie_modifiable_sans_ecriture_rh(request, fixture, sample_users, db):
    client = request.getfixturevalue(fixture)
    uid = sample_users['salarie_id']
    db.execute('UPDATE users SET pesee=20, competence=3, maintien=0 WHERE id=?', (uid,))
    db.execute("INSERT INTO contrats (user_id,type_contrat,date_debut,temps_hebdo) VALUES (?,'CDI','2020-01-01',28)", (uid,))
    db.execute("INSERT INTO contrats (user_id,type_contrat,date_debut,temps_hebdo) VALUES (?,'CEE','2025-01-01',5)", (uid,))
    db.commit()
    before = [tuple(r) for r in db.execute('SELECT * FROM users')], [tuple(r) for r in db.execute('SELECT * FROM contrats')]
    r = client.get(API + '/alisfa?annee=2026&salarie_id=' + str(uid))
    assert r.status_code == 200
    values = r.get_json()['valeurs']
    assert values == {'socle':23000, 'point':55, 'pesee':20, 'competence':3, 'maintien':0, 'anciennete':6, 'quotite':'80.0'}
    values['pesee'] = '99'
    data = salaire(base='alisfa', poste='occupe', salarie_id=str(uid), source='', note='',
                   secteurs={str(sample_users['secteur_id']):'100'}, **values)
    assert sauver(client, data).status_code == 200
    d = etat(client)
    assert d['calcul']['complet']
    assert d['lignes'][0]['donnees']['pesee'] == '99'
    assert client.post(API + '/reporter', json={'annee':2026, 'revision':d['revision'],
                                               'reference_report':d['reference_report']}).status_code == 200
    assert etat(client)['lignes'][0]['donnees']['pesee'] == '99'
    after = [tuple(r) for r in db.execute('SELECT * FROM users')], [tuple(r) for r in db.execute('SELECT * FROM contrats')]
    assert before == after


def test_alisfa_donnees_absentes_et_identifiants(admin_client, sample_users, db):
    uid = sample_users['salarie_id']
    db.execute('UPDATE users SET pesee=NULL, competence=NULL, maintien=NULL WHERE id=?', (uid,))
    db.commit()
    r = admin_client.get(API + '/alisfa?annee=2026&salarie_id=' + str(uid))
    assert r.status_code == 200
    assert all(r.get_json()['valeurs'][k] is None for k in ('pesee','competence','maintien','quotite','anciennete'))
    for ident in ('0','9999999','abc','1 OR 1=1','9'*30):
        assert admin_client.get(API + '/alisfa', query_string={'annee':2026,'salarie_id':ident}).status_code == 400
    assert admin_client.get(API + '/alisfa', query_string={'annee':'bad','salarie_id':uid}).status_code == 400


@pytest.mark.parametrize('fixture', ['client','auth_client','resp_client','prestataire_client'])
def test_alisfa_confidentialite(request, fixture, sample_users):
    r = request.getfixturevalue(fixture).get(API + '/alisfa?annee=2026&salarie_id=' + str(sample_users['salarie_id']))
    assert r.status_code == (302 if fixture == 'client' else 403)
    assert 'valeurs' not in (r.get_json(silent=True) or {})


def test_documents_facultatifs_calculs_obligatoires(admin_client, sample_users):
    assert sauver(admin_client, ligne_secteur(sample_users, source='', note='')).status_code == 200
    d = etat(admin_client)
    assert d['calcul']['complet']
    assert admin_client.post(API + '/reporter', json={'annee':2026,'revision':d['revision'],
                                                    'reference_report':d['reference_report']}).status_code == 200
    line = d['lignes'][0]
    line['donnees']['annuel'] = None
    assert sauver(admin_client, None, ligne=line).status_code == 200
    assert not etat(admin_client)['calcul']['complet']
    line['donnees']['annuel'] = '1200'
    line['donnees']['a_revoir'] = True
    assert sauver(admin_client, None, ligne=line).status_code == 200
    assert not etat(admin_client)['calcul']['complet']


def test_taux_individuels_sans_creation_manuelle_645(admin_client, sample_users, db):
    data = salaire(secteurs={str(sample_users['secteur_id']):'100'})
    data['reference_charges']['source'] = ''
    assert sauver(admin_client, data).status_code == 200
    assert sauver(admin_client, {'note':'', 'taux_individuels':True}, action='hypotheses').status_code == 200
    d = etat(admin_client)
    assert d['calcul']['complet']
    assert d['calcul']['general']['charges_annuel'] == '33600'
    assert set(d['calcul']['ventilation'][str(sample_users['secteur_id'])]) == {'641100','645100'}
    assert db.execute('SELECT COUNT(*) FROM budget_prev_saisies').fetchone()[0] == 0


@pytest.mark.parametrize('code', [[], {}, None, 641200])
def test_complement_compte_malforme_refuse(admin_client, sample_users, code):
    data = salaire(secteurs={str(sample_users['secteur_id']):'100'},
                   complements=[{'libelle':'Prime','compte':code,'mois':['0']*12}])
    assert sauver(admin_client, data).status_code == 409


def test_taux_individuels_preserve_645_ancienne_construction(admin_client, sample_users, db):
    from budget_initial import enregistrer
    sid = str(sample_users['secteur_id'])
    # Ancienne saisie autorisée avant le filtrage des nouveaux comptes.
    enregistrer(db, 2026, 0, sample_users['directeur_id'], {sid:'Pilote'},
                ligne={'donnees':depense(compte='645200', secteurs={sid:'100'})})
    db.commit()
    assert sauver(admin_client, salaire(secteurs={sid:'100'})).status_code == 200
    assert sauver(admin_client, {'note':'', 'taux_individuels':True}, action='hypotheses').status_code == 200
    d = etat(admin_client)
    assert d['calcul']['complet']
    assert set(d['calcul']['ventilation'][sid]) == {'641100','645200'}
    assert d['calcul']['general']['charges_annuel'] == '33600'


@pytest.mark.parametrize('payload', [None, '', '{invalide', 'null', '[]', '42'])
@pytest.mark.parametrize('proprietaire', [True, False])
def test_simulation_legacy_sans_objet_chargeable_et_protegee(admin_client, sample_users, db, payload, proprietaire):
    sid = sample_users['secteur_id']
    data = salaire(secteurs={str(sid):'100'}, source='', note='') if proprietaire else ligne_secteur(sample_users, source='', note='')
    assert sauver(admin_client, data).status_code == 200
    db.execute('''INSERT INTO budget_paie_simulations (type_budget,annee,secteur_id,compte_num,donnees,total)
                  VALUES ('initial',2026,?,'641100',?,24000)''', (sid,payload))
    db.commit()
    before = [tuple(r) for r in db.execute('SELECT * FROM budget_paie_simulations')]
    d = etat(admin_client)
    assert d['calcul']['complet']
    assert d['reports'][0]['possible'] is not proprietaire
    if proprietaire:
        assert 'Simulation' in d['reports'][0]['motif']
    response = admin_client.post(API + '/reporter', json={'annee':2026,'revision':d['revision'],
                                                         'reference_report':d['reference_report']})
    assert response.status_code == 200
    assert response.get_json()['reportes'] == (0 if proprietaire else 1)
    assert [tuple(r) for r in db.execute('SELECT * FROM budget_paie_simulations')] == before


@pytest.mark.parametrize('champ,valeur', [('denominateur','1e-999999'), ('numerateur','1e999999999'), ('denominateur','0e-999999')])
def test_exposant_extreme_refuse_sans_ecriture(admin_client, sample_users, champ, valeur):
    from tests.test_budget_initial_moteur import reference
    assert sauver(admin_client, salaire(secteurs={str(sample_users['secteur_id']):'100'})).status_code == 200
    before = etat(admin_client)
    data = ligne_secteur(sample_users, mode='proportionnel', reference=reference(**{champ:valeur}), source='', note='')
    response = sauver(admin_client, data)
    assert response.status_code == 409
    assert 'Nombre invalide' in response.get_json()['error']
    after = etat(admin_client)
    assert after['revision'] == before['revision']
    assert after['lignes'] == before['lignes']


@pytest.mark.parametrize('method,path,status', [
    ('get','/budget-initial-detaille',400),
    ('get',API,400),
    ('get',API + '/alisfa',400),
    ('post',API + '/enregistrer',409),
    ('post',API + '/reporter',409),
])
@pytest.mark.parametrize('code_connu', [False, True])
def test_erreur_interne_jamais_publiee(admin_client, monkeypatch, method, path, status, code_connu):
    import blueprints.budget_initial as routes
    from budget_initial import InitialRefuse
    secret = '<script>secret_synthetique</script> /srv/prive/base.sqlite Traceback SQL SELECT'
    def refuser(*args, **kwargs):
        exc = InitialRefuse('nombre_invalide' if code_connu else secret)
        exc.args = (secret,)
        raise exc from RuntimeError(secret)
    monkeypatch.setattr(routes, '_annee', refuser)
    response = getattr(admin_client, method)(path, **({'json':{'annee':2026}} if method == 'post' else {}))
    assert response.status_code == status
    text = response.get_json()['error'] if response.is_json else response.get_data(as_text=True)
    for fragment in ('secret_synthetique', 'Traceback', '/srv/prive', 'SELECT'):
        assert fragment not in text
    assert ('Nombre invalide ou hors limites.' if code_connu else 'Vérifiez la saisie') in text
