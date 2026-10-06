"""Lot 2 : bases exclusivement synthétiques, immutabilité et non-régression."""
import importlib
import io
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pdfplumber
import pytest

from budget_suivi import (SuiviRefuse, ajuster, changer_reference, figer,
                         suivi, verifier_initial)
from schema_budget_suivi import creer_schema


@pytest.fixture
def budget(db, sample_users, admin_client):
    sid = sample_users['secteur_id']
    db.executemany('INSERT INTO plan_comptable_general (compte_num,libelle) VALUES (?,?)',
                   [('606100','Énergie'), ('706100','Produits'), ('641100','Salaires')])
    for code, valeur in [('606100',1200), ('706100',2000), ('641100',0)]:
        db.execute("INSERT INTO budget_prev_saisies (type_budget,annee,secteur_id,compte_num,valeur_def) VALUES ('initial',2026,?,?,?)", (sid,code,valeur))
    db.commit()
    return sid


def geler(db, uid=1):
    db.execute('BEGIN IMMEDIATE')
    controle = verifier_initial(db, 2026)
    ident = figer(db, 2026, controle['empreinte'], uid, 'Validation synthétique', True)
    db.commit()
    return ident


def saisie(sid, **kwargs):
    return {'libelle':'Hausse énergie', 'nature':'charge', 'secteur_id':str(sid),
            'compte':'606100', 'montant':'1500', 'debut':'2026-01-01', 'fin':'2026-12-31',
            'etat':'estime', **kwargs}


def ajouter(db, sid, **kwargs):
    db.execute('BEGIN IMMEDIATE')
    ident = ajuster(db, 2026, suivi(db,2026)['revision'], 1, saisie(sid, **kwargs))
    db.commit()
    return ident


def test_gel_immuable_et_independant(budget, db):
    controle = verifier_initial(db,2026)
    assert not controle['blocages']
    gel = geler(db)
    original = db.execute('SELECT donnees FROM budget_gels WHERE id=?', (gel,)).fetchone()[0]
    db.execute("UPDATE budget_prev_saisies SET valeur_def=9000 WHERE compte_num='706100'")
    db.execute("UPDATE users SET pesee=999")
    db.commit()
    assert suivi(db,2026)['initial'] == '800.00'
    assert db.execute('SELECT donnees FROM budget_gels WHERE id=?',(gel,)).fetchone()[0] == original
    for sql in ('UPDATE budget_gels SET motif=?', 'DELETE FROM budget_gels WHERE id=?'):
        with pytest.raises(sqlite3.IntegrityError, match='immuable'):
            db.execute(sql, (gel,))
        db.rollback()


def test_vide_zero_et_double_gel(budget, db):
    db.execute("UPDATE budget_prev_saisies SET valeur_def=NULL WHERE compte_num='641100'")
    db.commit()
    c = verifier_initial(db,2026)
    assert c['blocages']
    with pytest.raises(SuiviRefuse, match='bloqué'):
        figer(db,2026,c['empreinte'],1,'Essai',True)
    db.rollback()
    db.execute("UPDATE budget_prev_saisies SET valeur_def=0 WHERE compte_num='641100'")
    db.commit()
    geler(db)
    with pytest.raises(SuiviRefuse, match='déjà figée'):
        figer(db,2026,verifier_initial(db,2026)['empreinte'],1,'Essai',True)
    assert db.execute('SELECT count(*) FROM budget_gels').fetchone()[0] == 1


def test_confirmation_et_page_perimee(budget, db):
    c = verifier_initial(db,2026)
    with pytest.raises(SuiviRefuse, match='Confirmez'):
        figer(db,2026,c['empreinte'],1,'Essai',False)
    db.execute("UPDATE budget_prev_saisies SET commentaire='modification' WHERE compte_num='641100'")
    with pytest.raises(SuiviRefuse, match='changé'):
        figer(db,2026,c['empreinte'],1,'Essai',True)
    db.rollback()
    assert db.execute('SELECT count(*) FROM budget_gels').fetchone()[0] == 0


def test_ecarts_revision_annulation_et_incomplets(budget, db):
    geler(db)
    ident = ajouter(db,budget,initial_id=f'2026:{budget}:606100')
    assert suivi(db,2026)['impact'] == '-300.00'
    db.execute('BEGIN IMMEDIATE')
    ajuster(db,2026,1,1,saisie(budget,montant='1600',initial_id=f'2026:{budget}:606100'),ident)
    db.commit()
    assert suivi(db,2026)['impact'] == '-400.00'
    ajouter(db,budget,nature='recette',compte='706100',montant='250')
    assert suivi(db,2026)['courant'] == '650.00'
    ajouter(db,budget,montant='')
    d = suivi(db,2026)
    assert d['incomplets'] == 1 and d['details'][-1]['impact'] is None
    assert d['details'][-1]['etat'] == 'a_completer'
    db.execute('BEGIN IMMEDIATE')
    ajuster(db,2026,d['revision'],1,{},ident,annuler=True)
    db.commit()
    d = suivi(db,2026)
    assert d['impact'] == '250.00'
    assert len(d['details'][0]['historique']) == 3
    with pytest.raises(sqlite3.IntegrityError):
        db.execute('DELETE FROM budget_evenements')


@pytest.mark.parametrize('changes', [dict(montant='NaN'),dict(montant='1e999'),dict(montant='-1'),
    dict(compte='706100'),dict(secteur_id='99999'),dict(debut='2025-01-01'),dict(fin='2026-00-01'),
    dict(etat='incorrect'),dict(initial_id='absent'),dict(libelle=''),dict(compte='699999')])
def test_saisies_invalides_atomiques(budget, db, changes):
    geler(db)
    with pytest.raises(SuiviRefuse):
        ajouter(db,budget,**changes)
    db.rollback()
    assert suivi(db,2026)['revision'] == 0
    assert not suivi(db,2026)['details']


def test_prevu_unique_et_source_remplace_sans_cumul(budget, db):
    geler(db)
    lien = f'2026:{budget}:606100'
    ident = ajouter(db,budget,initial_id=lien)
    with pytest.raises(SuiviRefuse, match='double impact'):
        ajouter(db,budget,initial_id=lien)
    db.rollback()
    db.execute('BEGIN IMMEDIATE')
    ajuster(db,2026,1,1,saisie(budget,montant=1700,initial_id=lien),ident,source={'type':'facture','id':'future-1'})
    db.commit()
    d = suivi(db,2026)
    assert len(d['details']) == 1 and d['impact'] == '-500.00'
    assert d['details'][0]['remplace_revision'] == 1
    with pytest.raises(SuiviRefuse, match='piloté'):
        ajuster(db,2026,2,1,saisie(budget),ident)
    db.rollback()
    autre = ajouter(db,budget)
    with pytest.raises(SuiviRefuse, match='déjà rattachée'):
        ajuster(db,2026,3,1,saisie(budget),autre,source={'type':'facture','id':'future-1'})
    db.rollback()


def test_nouvelle_version_ne_deplace_pas_reference(budget, db):
    ancien = geler(db)
    ajouter(db,budget,initial_id=f'2026:{budget}:606100')
    db.execute("UPDATE budget_prev_saisies SET valeur_def=1400 WHERE compte_num='606100'")
    db.commit()
    nouveau = geler(db)
    d = suivi(db,2026)
    assert d['gel_id'] == ancien and d['impact'] == '-300.00'
    db.execute('BEGIN IMMEDIATE')
    changer_reference(db,2026,d['revision'],nouveau,1,'Correction votée')
    db.commit()
    d = suivi(db,2026)
    assert d['gel_id'] == nouveau and d['impact'] == '-100.00'
    assert d['courant'] == '500.00' and len(d['changements']) == 1
    assert db.execute('SELECT count(*) FROM budget_gels').fetchone()[0] == 2


def test_consolidation_et_pas_de_fuite(budget, db, resp_client):
    sid2 = db.execute("INSERT INTO secteurs (nom) VALUES ('Autre secteur secret')").lastrowid
    db.execute("INSERT INTO budget_prev_saisies (type_budget,annee,secteur_id,compte_num,valeur_def) VALUES ('initial',2026,?,'706100',500)", (sid2,))
    db.commit()
    geler(db)
    ajouter(db,budget,libelle='Nom RH secret',note='Dossier médical secret',montant=10)
    ajouter(db,sid2,montant=20)
    total = suivi(db,2026)
    a,b = suivi(db,2026,budget),suivi(db,2026,sid2)
    assert float(total['courant']) == float(a['courant']) + float(b['courant'])
    page = resp_client.get('/budget/suivi?annee=2026')
    assert page.status_code == 200
    text = page.get_data(as_text=True)
    for secret in ('Nom RH secret','Dossier médical secret','Autre secteur secret'):
        assert secret not in text
    assert resp_client.get(f'/budget/suivi?annee=2026&secteur_id={sid2}').status_code == 403
    assert resp_client.post('/budget/suivi',data={'annee':2026}).status_code == 403


@pytest.mark.parametrize('fixture', ['auth_client','prestataire_client','resp_client'])
def test_acces_gel_pdf_refuse(request,fixture):
    client = request.getfixturevalue(fixture)
    assert client.get('/budget/gel?annee=2026').status_code == 403
    assert client.post('/budget/gel',data={'annee':2026}).status_code == 403
    assert client.get('/budget/instantanes/inconnu/detail.pdf').status_code == 403


def test_non_connecte(client):
    for url in ('/budget/gel','/budget/suivi','/budget/instantanes/inconnu/detail.pdf'):
        assert client.get(url).status_code == 302


@pytest.mark.parametrize('path', ['/budget/gel','/budget/suivi'])
def test_csrf(app,admin_client,path):
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        assert admin_client.post(path,data={'annee':2026}).status_code == 302
    finally:
        app.config['WTF_CSRF_ENABLED'] = False


def test_routes_et_pdf_reproductible(budget,db,admin_client):
    assert admin_client.get('/budget/gel?annee=2026').status_code == 200
    controle = verifier_initial(db,2026)
    r = admin_client.post('/budget/gel',data={'annee':2026,'empreinte':controle['empreinte'],'motif':'Vote','confirme':'oui'})
    assert r.status_code == 302
    assert admin_client.get('/budget/suivi?annee=2026').status_code == 200
    r = admin_client.post('/budget/suivi', data={'annee':2026,'revision':0,'action':'ajuster',**saisie(budget,montant=20)})
    assert r.status_code == 302
    assert admin_client.post('/budget/suivi',data={'annee':2026,'revision':1,'action':'instantane'}).status_code == 302
    archive = db.execute('SELECT * FROM budget_instantanes').fetchone()
    pdfs = {}
    for mode in ('synthese','detail'):
        url = f'/budget/instantanes/{archive["id"]}/{mode}.pdf'
        pdfs[url] = admin_client.get(url).data
        with pdfplumber.open(io.BytesIO(pdfs[url])) as pdf:
            assert '780.00' in ' '.join(p.extract_text() for p in pdf.pages)
    ajouter(db,budget,montant=999)
    db.execute("UPDATE budget_prev_saisies SET valeur_def=8000")
    db.commit()
    for url,pdf in pdfs.items():
        assert admin_client.get(url).data == pdf
    with pytest.raises(sqlite3.IntegrityError):
        db.execute('DELETE FROM budget_instantanes')


def test_concurrence_deux_connexions(budget,db):
    geler(db)
    import database
    def tentative():
        conn = database.get_db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            ajuster(conn,2026,0,1,saisie(budget))
            conn.commit()
            return 'ok'
        except SuiviRefuse:
            conn.rollback()
            return 'perime'
        finally:
            conn.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: tentative(), range(2)))
    assert sorted(results) == ['ok','perime']
    assert len(suivi(db,2026)['details']) == 1


def test_migration_idempotente_sans_conversion(budget,db):
    tables = ('budget_prev_saisies','budget_paie_simulations','budget_initial_lignes','users')
    before = {t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in tables}
    # Reproduire un état 0077, sans aucune archive du lot 2.
    for table in ('budget_instantanes','budget_evenements','budget_suivis','budget_gels'):
        db.execute('DROP TABLE '+table)
    migration = importlib.import_module('migrations.0078_budget_gel_suivi')
    migration.upgrade(db)
    migration.upgrade(db)
    assert {t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in tables} == before
    assert db.execute('SELECT count(*) FROM budget_gels').fetchone()[0] == 0
    with pytest.raises(RuntimeError):
        migration.downgrade(db)
    db.commit()
    geler(db)


def test_echec_evenement_rollback_total(budget,db):
    geler(db)
    db.execute("CREATE TRIGGER refuse_revision BEFORE UPDATE ON budget_suivis BEGIN SELECT RAISE(ABORT,'test'); END")
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        ajouter(db,budget)
    db.rollback()
    assert suivi(db,2026)['revision'] == 0 and not suivi(db,2026)['details']


def test_lignes_detaillees_et_double_imputation(budget,db):
    from budget_initial import enregistrer
    from tests.test_budget_initial_moteur import depense
    enregistrer(db,2026,0,1,{str(budget):'Secteur'},ligne={'donnees':depense(secteurs={str(budget):'100'},annuel='1200')})
    db.commit()
    gel = geler(db)
    data = suivi(db,2026)
    assert len(data['elements']) == 1
    lien = data['elements'][0]['id']
    ident = ajouter(db,budget,initial_id=lien,montant='1300')
    assert suivi(db,2026)['impact'] == '-100.00'
    with pytest.raises(SuiviRefuse,match='double impact'):
        ajouter(db,budget,initial_id=f'2026:{budget}:606100')
    db.rollback()
    # Le lien UUID et le détail restent disponibles dans la copie du gel.
    archived = json.loads(db.execute('SELECT donnees FROM budget_gels WHERE id=?',(gel,)).fetchone()[0])
    assert archived['elements'][0]['ligne_initiale_id'] == archived['construction']['lignes'][0]['id']
    db.execute("UPDATE budget_prev_saisies SET valeur_def=1400 WHERE compte_num='606100'")
    db.commit()
    nouveau = geler(db)
    with pytest.raises(SuiviRefuse,match='ne couvre pas'):
        changer_reference(db,2026,1,nouveau,1,'Nouvelle décision divergente')
    db.rollback()
    assert suivi(db,2026)['gel_id'] == gel


def test_actualise_2026_donnees_calculs_pdf_inchanges(budget,db,admin_client):
    from tests.test_budget_regles import lire
    db.execute("INSERT INTO budget_prev_saisies (type_budget,annee,secteur_id,compte_num,valeur_temp,valeur_def,commentaire) VALUES ('actualise',2026,?,'606100',777,777,'Conserver')",(budget,))
    db.commit()
    avant = lire(admin_client,budget)
    def contenu_pdf():
        response = admin_client.get(f'/api/budget-previsionnel/export-pdf?type_budget=actualise&annee=2026&secteur_id={budget}')
        assert response.status_code == 200
        with pdfplumber.open(io.BytesIO(response.data)) as pdf:
            return '\n'.join(p.extract_text() for p in pdf.pages)
    pdf_avant = contenu_pdf()
    row = tuple(db.execute("SELECT * FROM budget_prev_saisies WHERE type_budget='actualise'").fetchone())
    geler(db)
    ajouter(db,budget,montant=888)
    assert tuple(db.execute("SELECT * FROM budget_prev_saisies WHERE type_budget='actualise'").fetchone()) == row
    apres = lire(admin_client,budget)
    assert avant['rows'] == apres['rows'] and avant['totaux'] == apres['totaux']
    assert pdf_avant == contenu_pdf()


def test_gel_concurrent_une_seule_version(budget,db):
    import database
    reference = verifier_initial(db,2026)['empreinte']
    def tentative():
        conn = database.get_db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            figer(conn,2026,reference,1,'Vote',True)
            conn.commit()
            return 'ok'
        except SuiviRefuse:
            conn.rollback()
            return 'doublon'
        finally:
            conn.close()
    # Les anciens calculs accèdent au contexte Flask ; un contexte par thread.
    from app import app
    def contexte(_):
        with app.app_context():
            return tentative()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(contexte,range(2)))
    assert sorted(results) == ['doublon','ok']
    assert db.execute('SELECT count(*) FROM budget_gels').fetchone()[0] == 1


def test_comptable_et_session_revoquee(budget,db,comptable_client,sample_users):
    assert comptable_client.get('/budget/gel?annee=2026').status_code == 200
    c = verifier_initial(db,2026)
    db.execute('UPDATE users SET session_version=session_version+1 WHERE id=?',(sample_users['comptable_id'],))
    db.commit()
    response = comptable_client.post('/budget/gel',data={'annee':2026,'empreinte':c['empreinte'],'motif':'Vote','confirme':'oui'})
    assert response.status_code == 302
    assert db.execute('SELECT count(*) FROM budget_gels').fetchone()[0] == 0


def test_ecriture_gel_rollback_si_suivi_echoue(budget,db):
    db.execute("CREATE TRIGGER refuse_suivi BEFORE INSERT ON budget_suivis BEGIN SELECT RAISE(ABORT,'test'); END")
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        geler(db)
    db.rollback()
    assert db.execute('SELECT count(*) FROM budget_gels').fetchone()[0] == 0


def test_consultation_ancienne_version_independante(budget,db,admin_client):
    gel = geler(db)
    db.execute("UPDATE budget_prev_saisies SET valeur_def=88888")
    db.commit()
    page = admin_client.get(f'/budget/gel?annee=2026&version={gel}')
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'Archive immuable v1' in html and '1200.00' in html
    assert '88888' not in html and 'Figer une nouvelle version annuelle</button>' not in html
    assert admin_client.get(f'/budget/gel?annee=2025&version={gel}').status_code == 404


def test_calcul_automatique_incomplet_bloque_gel(budget,db):
    db.execute("INSERT INTO budget_prev_saisies (type_budget,annee,secteur_id,compte_num,valeur_def) VALUES ('initial',2026,?,'645100',100)",(budget,))
    db.execute("INSERT INTO budget_modes_comptes VALUES ('initial',2026,?,'645100','proportionnel')",(budget,))
    db.commit()
    c = verifier_initial(db,2026)
    assert any('calcul à actualiser' in b for b in c['blocages'])
    with pytest.raises(SuiviRefuse,match='bloqué'):
        figer(db,2026,c['empreinte'],1,'Vote',True)
    assert db.execute('SELECT count(*) FROM budget_gels').fetchone()[0] == 0


def test_total_signe_de_remplacement_et_source_http_non_activable(budget,db,admin_client):
    db.execute("INSERT INTO budget_prev_saisies (type_budget,annee,secteur_id,compte_num,valeur_def) VALUES ('initial',2026,?,'649100',-100)",(budget,))
    db.commit()
    geler(db)
    ajouter(db,budget,compte='649100',initial_id=f'2026:{budget}:649100',montant='-200')
    assert suivi(db,2026)['impact'] == '100.00'
    response = admin_client.post('/budget/suivi',data={'annee':2026,'revision':1,'action':'ajuster',
        'source_type':'facture','source_id':'interdit',**saisie(budget,montant='0')})
    assert response.status_code == 302
    assert suivi(db,2026)['details'][-1]['source_type'] == 'manuel'
    # Même formulaire rejoué : aucun second impact.
    response = admin_client.post('/budget/suivi',data={'annee':2026,'revision':1,'action':'ajuster',**saisie(budget)})
    assert response.status_code == 409
    assert len(suivi(db,2026)['details']) == 2
