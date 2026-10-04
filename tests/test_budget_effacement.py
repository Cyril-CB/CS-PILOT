"""Effacement groupé : uniquement des budgets et données RH synthétiques."""
import sqlite3

import pytest

from tests.test_budget_initial_routes import etat, sauver, plan_general
from tests.test_budget_initial_moteur import depense
from tests.test_budget_regles import lire, post
from tests.test_budget_taux_charges import simulation, enregistrer

URL = '/api/budget-previsionnel/effacer-montants'


def payload(client, sid, typ='initial', annee=2026):
    return dict(type_budget=typ, annee=annee, secteur_id=sid, confirmer=True,
                reference_budget=lire(client, sid, typ, annee)['reference_budget'])


def saisies(db):
    return [dict(r) for r in db.execute('SELECT * FROM budget_prev_saisies ORDER BY id')]


@pytest.fixture
def perimetres(db, sample_users):
    sid = sample_users['secteur_id']
    other = db.execute("INSERT INTO secteurs(nom) VALUES ('Autre secteur synthétique')").lastrowid
    for typ, year, sector in [('initial', 2026, sid), ('actualise', 2026, sid),
                              ('initial', 2027, sid), ('initial', 2026, other)]:
        for code, val, temp in [('606100', 100, 120), ('706100', None, 150),
                                 ('641100', 0, 0), ('645100', None, None)]:
            db.execute('''INSERT INTO budget_prev_saisies
                (type_budget,annee,secteur_id,compte_num,valeur_def,valeur_temp,commentaire)
                VALUES (?,?,?,?,?,?,?)''', (typ, year, sector, code, val, temp, ' Note conservée '))
        for table in ('budget_paie_simulations', 'budget_fiches_travail'):
            db.execute(f'''INSERT INTO {table}(type_budget,annee,secteur_id,compte_num,donnees,total)
                VALUES (?,?,?,'641100','{{}}',123)''', (typ, year, sector))
        db.execute('''INSERT INTO budget_ps_simulations
            (type_budget,annee,secteur_id,compte_num,donnees,total,type_ps)
            VALUES (?,?,?,'706100','{}',123,'eaje')''', (typ, year, sector))
    db.commit()
    return sid


@pytest.mark.parametrize('typ', ['initial', 'actualise'])
@pytest.mark.parametrize('profil', ['admin_client', 'comptable_client'])
def test_effacement_portee_commentaires_simulations_rh(request, db, perimetres, typ, profil):
    client = request.getfixturevalue(profil)
    sid = perimetres
    before = saisies(db)
    tables = ['users', 'contrats', 'budget_paie_simulations', 'budget_ps_simulations',
              'budget_fiches_travail', 'budget_modes_comptes', 'budget_parametres',
              'budget_initial_lignes', 'budget_initial_hypotheses', 'budget_initial_reports',
              'bilan_fec_donnees']
    others = {t: [tuple(r) for r in db.execute('SELECT * FROM ' + t)] for t in tables}
    p = payload(client, sid, typ)
    response = client.post(URL, json=p)
    assert response.status_code == 200, response.get_json()
    assert response.get_json()['success'] is True
    for old, new in zip(before, saisies(db)):
        if (old['type_budget'], old['annee'], old['secteur_id']) == (typ, 2026, sid):
            assert new['valeur_def'] is None and new['valeur_temp'] is None
            assert new['commentaire'] == old['commentaire']
            assert new['id'] == old['id']
        else:
            assert new == old
    for table in tables:
        assert [tuple(r) for r in db.execute('SELECT * FROM ' + table)] == others[table]
    assert all(r['def'] is None for r in lire(client, sid, typ)['rows'])
    after = saisies(db)
    assert client.post(URL, json=p).status_code == 409  # Rejeu périmé.
    assert saisies(db) == after
    assert client.post(URL, json=payload(client, sid, typ)).status_code == 200  # Déjà vide.


@pytest.mark.parametrize('changes', [{'confirmer': False}, {'confirmer': 'true'},
    {'type_budget': 'global'}, {'secteur_id': None}, {'secteur_id': True},
    {'secteur_id': 999999}, {'annee': 2027}, {'type_budget': 'actualise'},
    {'reference_budget': 'invalide'}, {'reference_budget': None}])
def test_confirmation_contexte_et_reference(admin_client, db, perimetres, changes):
    p = payload(admin_client, perimetres)
    before = saisies(db)
    assert admin_client.post(URL, json={**p, **changes}).status_code in (400, 409)
    assert saisies(db) == before


def test_page_perimee(admin_client, db, perimetres):
    p = payload(admin_client, perimetres)
    db.execute("UPDATE budget_prev_saisies SET commentaire='Modification concurrente'")
    db.commit()
    before = saisies(db)
    assert admin_client.post(URL, json=p).status_code == 409
    assert saisies(db) == before


@pytest.mark.parametrize('profil', ['client', 'auth_client', 'resp_client', 'prestataire_client'])
def test_droits_refuses(request, db, perimetres, profil):
    before = saisies(db)
    client = request.getfixturevalue(profil)
    response = client.post(URL, json=dict(type_budget='initial', annee=2026,
                                         secteur_id=perimetres, confirmer=True))
    assert response.status_code == (302 if profil == 'client' else 403)
    assert saisies(db) == before


def test_csrf_requis(admin_client, app, db, perimetres):
    p = payload(admin_client, perimetres)
    before = saisies(db)
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        assert admin_client.post(URL, json=p).status_code == 302
        assert saisies(db) == before
    finally:
        app.config['WTF_CSRF_ENABLED'] = False


@pytest.mark.parametrize('failure', ['milieu', 'commit'])
def test_atomicite_erreur_ecriture_et_commit(admin_client, db, perimetres, monkeypatch, failure):
    p = payload(admin_client, perimetres)
    before = saisies(db)
    if failure == 'milieu':
        db.execute('''CREATE TRIGGER echec_synthetique BEFORE UPDATE ON budget_prev_saisies
            WHEN OLD.compte_num='706100' BEGIN SELECT RAISE(FAIL, 'Erreur synthétique'); END''')
        db.commit()
    else:
        import blueprints.budget as module
        get_db = module.get_db

        class CommitRefuse:
            def __init__(self):
                self.conn = get_db()

            def __getattr__(self, name):
                return getattr(self.conn, name)

            def commit(self):
                raise sqlite3.OperationalError('Erreur synthétique de commit')

        monkeypatch.setattr(module, 'get_db', CommitRefuse)
    response = admin_client.post(URL, json=p)
    assert response.status_code == 503
    assert not response.get_json().get('success')
    assert saisies(db) == before


def test_taux_actifs_conserves(admin_client, db, simulation):
    sid = simulation[0]
    assert enregistrer(admin_client, simulation).status_code == 200
    before = [tuple(r) for r in db.execute('SELECT * FROM budget_paie_simulations')]
    assert admin_client.post(URL, json=payload(admin_client, sid)).status_code == 200
    assert all(r['valeur_def'] is None and r['valeur_temp'] is None for r in saisies(db)
               if r['type_budget'] == 'initial')
    assert [tuple(r) for r in db.execute('SELECT * FROM budget_paie_simulations')] == before
    assert any(r['mode'] == 'taux_salaries' for r in lire(admin_client, sid, 'initial')['rows'])


@pytest.mark.parametrize('typ', ['initial', 'actualise'])
def test_commentaire_apres_effacement_sans_report_automatique(admin_client, db, perimetres, typ):
    sid = perimetres
    # À l'arrêté de décembre, ce mode produit un zéro même sans brut saisi.
    # En initial, une fiche mensuelle vide calcule également zéro.
    db.execute("INSERT INTO budget_modes_comptes VALUES (?,2026,?,'645100','mensuel')", (typ, sid))
    db.execute('''INSERT INTO budget_fiches_travail(type_budget,annee,secteur_id,compte_num,donnees)
        VALUES (?,2026,?,'645100','{}')''', (typ, sid))
    db.execute('''INSERT INTO budget_parametres(type_budget,annee,secteur_id,mois_arrete)
        VALUES (?,2026,?,12)''', (typ, sid))
    db.commit()
    assert admin_client.post(URL, json=payload(admin_client, sid, typ)).status_code == 200
    rows = lire(admin_client, sid, typ)['rows']
    assert next(r for r in rows if r['compte_num'] == '645100')['temp'] == 0
    for row in rows:
        assert post(admin_client, sid, 'save-lines', typ, lignes=[{
            'compte_num': row['compte_num'], 'valeur_def': row['def'],
            'valeur_temp': row['temp_saisie'], 'commentaire': 'Commentaire seul'}]).status_code == 200
    assert all(r['valeur_def'] is None and r['valeur_temp'] is None for r in saisies(db)
               if (r['type_budget'], r['annee'], r['secteur_id']) == (typ, 2026, sid))


def test_rechargement_commentaire_et_report_detaille(admin_client, db, perimetres):
    sid = perimetres
    assert sauver(admin_client, depense(secteurs={str(sid): '100'})).status_code == 200
    assert not etat(admin_client)['reports'][0]['possible']
    assert admin_client.post(URL, json=payload(admin_client, sid)).status_code == 200
    row = next(r for r in lire(admin_client, sid, 'initial')['rows'] if r['compte_num'] == '606100')
    assert post(admin_client, sid, 'save-lines', 'initial', lignes=[{
        'compte_num': '606100', 'valeur_def': row['def'], 'valeur_temp': row['temp_saisie'],
        'commentaire': 'Après rechargement'}]).status_code == 200
    state = etat(admin_client)
    assert state['reports'][0]['possible']
    assert admin_client.post('/api/budget-initial-detaille/reporter', json={
        'annee': 2026, 'revision': state['revision'], 'reference_report': state['reference_report']
    }).get_json()['reportes'] == 1
    assert db.execute("SELECT commentaire FROM budget_prev_saisies WHERE type_budget='initial' AND annee=2026 AND secteur_id=? AND compte_num='606100'", (sid,)).fetchone()[0] == 'Après rechargement'
