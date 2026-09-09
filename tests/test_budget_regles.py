"""Règles annuelles : données fictives, vrais formulaires API et transactions."""
import importlib.util
import json
from pathlib import Path

import pytest


def lire(client, sid, typ='actualise', annee=2026):
    r = client.get(f'/api/budget-previsionnel/donnees?secteur_id={sid}&annee={annee}&type_budget={typ}')
    assert r.status_code == 200
    return r.get_json()


def post(client, sid, action, typ='actualise', annee=2026, **champs):
    data = {'secteur_id': sid, 'annee': annee, 'type_budget': typ,
            'reference_budget': lire(client, sid, typ, annee)['reference_budget'], **champs}
    return client.post('/api/budget-previsionnel/' + action, json=data)


def config(client, sid, mois=6, typ='actualise', choix=None, confirmer=True):
    return post(client, sid, 'parametres', typ, mois_arrete=mois, annee_reference=2025,
                confirmer_reference_complete=confirmer, modes=choix or {'645100': 'proportionnel'})


def saisir(client, sid, montants, typ='actualise'):
    return post(client, sid, 'save-lines', typ,
                lignes=[{'compte_num': c, 'valeur_def': v} for c, v in montants.items()])


@pytest.fixture
def cadre(db, admin_client):
    sid = db.execute("INSERT INTO secteurs (nom, type_secteur) VALUES ('Budget fictif', 'enfance')").lastrowid
    db.execute("INSERT INTO budget_prev_config_codes (code_analytique, secteur_id) VALUES ('BUDGET-TEST', ?)", (sid,))
    uid = db.execute("INSERT INTO users (nom, prenom, login, password, actif, profil, secteur_id, pesee, competence, maintien) VALUES ('Fictif', 'Test', 'budget-test', 'inutilise', 1, 'salarie', ?, 100, 5, 50)", (sid,)).lastrowid
    db.execute("INSERT INTO contrats (user_id, type_contrat, date_debut, temps_hebdo) VALUES (?, 'CDI', '2020-01-01', 35)", (uid,))
    for compte, total in [('641100', 100000), ('641200', 20000), ('645100', 48000), ('635120', 1200), ('649100', -1200)]:
        for m in range(1, 13):
            db.execute('''INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant)
                VALUES (?, 'FICTIF', 'BUDGET-TEST', 2025, ?, ?)''', (compte, m, round(total / 12, 2) if m < 12 else round(total - 11 * round(total / 12, 2), 2)))
    for compte, total in [('641100', 60000), ('641200', 4000), ('645100', 30000)]:
        for m in range(1, 7):
            db.execute('''INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant)
                VALUES (?, 'FICTIF', 'BUDGET-TEST', 2026, ?, ?)''', (compte, m, round(total / 6, 2) if m < 6 else round(total - 5 * round(total / 6, 2), 2)))
    db.commit()
    return sid, uid


def rows(client, sid, typ='actualise'):
    return {r['compte_num']: r for r in lire(client, sid, typ)['rows']}


def test_aucun_arrete_ni_reference_invente(cadre, admin_client):
    data = lire(admin_client, cadre[0])
    assert data['parametres']['mois_arrete'] is None
    assert not data['parametres']['reference_valide']
    assert data['salary_brut_account'] == '641100'
    assert all(r['mode'] == 'manuel' for r in data['rows'] if r['compte_num'] != '641100')
    assert all(r['def'] is None for r in data['rows'])


def test_brut_global_et_reference_annuelle_commune(cadre, admin_client):
    sid, _ = cadre
    assert config(admin_client, sid).status_code == 200
    assert saisir(admin_client, sid, {'641100': 120000, '641200': 10000}).status_code == 200
    data = lire(admin_client, sid)
    assert data['brut_global'] == 130000 and data['brut_reel'] == 64000
    cotis = rows(admin_client, sid)['645100']
    assert cotis['reference_brut'] == 120000
    assert cotis['taux'] == 0.4
    assert cotis['def'] == cotis['temp'] == 56400  # 30 000 + (130 000 - 64 000) × 40 %


def test_complement_proportionnel_au_premier_641_uniquement(cadre, admin_client):
    sid, _ = cadre
    config(admin_client, sid, choix={'641200': 'proportionnel', '645100': 'proportionnel'})
    saisir(admin_client, sid, {'641100': 120000})
    r = rows(admin_client, sid)
    assert r['641200']['reference_brut'] == 100000
    assert r['641200']['def'] == 16000  # 4 000 réels + 60 000 × 20 %
    assert lire(admin_client, sid)['brut_global'] == 136000
    assert r['645100']['def'] == 58800


def test_initial_sur_douze_mois_sans_reel(cadre, admin_client):
    sid, _ = cadre
    config(admin_client, sid, typ='initial')
    saisir(admin_client, sid, {'641100': 120000, '641200': 10000}, 'initial')
    assert rows(admin_client, sid, 'initial')['645100']['def'] == 52000


def test_decembre_rejoint_reel_sans_recalcul_historique(cadre, db, admin_client):
    sid, _ = cadre
    for c, v in [('641100', 60000), ('641200', 6000), ('645100', 30000)]:
        db.execute("INSERT INTO bilan_fec_donnees (compte_num, code_analytique, annee, mois, montant) VALUES (?, 'BUDGET-TEST', 2026, 12, ?)", (c, v))
    db.commit()
    config(admin_client, sid, mois=12, confirmer=False)
    assert rows(admin_client, sid)['645100']['def'] == 60000


@pytest.mark.parametrize('mois', [0, 6, 9, 12])
def test_arrete_explicite_paie_tableau_fiche(cadre, db, admin_client, mois):
    sid, _ = cadre
    db.execute("INSERT INTO bilan_fec_donnees (compte_num, code_analytique, annee, mois, montant) VALUES ('606100', 'BUDGET-TEST', 2026, 12, 1000)")
    db.commit()
    config(admin_client, sid, mois=mois, choix={'641200': 'mensuel'})
    assert lire(admin_client, sid)['last_month'] == mois
    cx = admin_client.get(f'/api/budget-previsionnel/paie-context?type_budget=actualise&annee=2026&secteur_id={sid}&compte_num=641100').get_json()
    fiche = admin_client.get(f'/api/budget-previsionnel/fiche-travail?type_budget=actualise&annee=2026&secteur_id={sid}&compte_num=641200').get_json()
    assert cx['last_real_month'] == fiche['contexte']['last_month'] == mois


@pytest.mark.parametrize('mode', ['manuel', 'mensuel', 'proportionnel'])
def test_mode_configurable_pour_un_635(cadre, admin_client, mode):
    sid, _ = cadre
    assert config(admin_client, sid, choix={'635120': mode}).status_code == 200
    assert rows(admin_client, sid)['635120']['mode'] == mode


def test_manuel_preserve_zero_et_indemnite_exceptionnelle(cadre, admin_client):
    sid, _ = cadre
    config(admin_client, sid)
    saisir(admin_client, sid, {'641100': 120000, '641200': 60000, '635120': 0, '649100': -1500})
    saisir(admin_client, sid, {'641100': 130000})
    r = rows(admin_client, sid)
    assert r['641200']['def'] == 60000 and r['635120']['def'] == 0 and r['649100']['def'] == -1500
    assert lire(admin_client, sid)['brut_global'] == 190000


@pytest.mark.parametrize('cause', ['non_confirmee', 'reimport', 'sans_brut', 'compte_absent'])
def test_reference_inexploitable_ne_met_pas_une_charge_a_zero(cadre, db, admin_client, cause):
    sid, _ = cadre
    saisir(admin_client, sid, {'641100': 120000, '641200': 10000, '645100': 45000})
    if cause == 'sans_brut':
        db.execute("DELETE FROM bilan_fec_donnees WHERE annee=2025 AND compte_num LIKE '641%'")
    if cause == 'compte_absent':
        db.execute("DELETE FROM bilan_fec_donnees WHERE annee=2025 AND compte_num='645100'")
    db.commit()
    config(admin_client, sid, confirmer=cause != 'non_confirmee')
    avant = rows(admin_client, sid)['645100']['def']
    if cause == 'reimport':
        db.execute("UPDATE bilan_fec_donnees SET montant=montant+1 WHERE annee=2025")
        db.commit()
    assert post(admin_client, sid, 'recalculer').status_code == 200
    r = rows(admin_client, sid)['645100']
    assert r['def'] == avant and r['temp'] is None and r['calcul_erreur']


def test_mensuel_complete_le_brut_et_recalcule_les_charges(cadre, admin_client):
    sid, _ = cadre
    config(admin_client, sid, choix={'641200': 'mensuel', '645100': 'proportionnel'})
    saisir(admin_client, sid, {'641100': 120000})
    response = post(admin_client, sid, 'fiche-travail', compte_num='641200', donnees={
        'methode': 'manuel', 'mois_prevus': {str(m): 1000 for m in range(7, 13)}})
    assert response.status_code == 200
    r = rows(admin_client, sid)
    assert r['641200']['def'] == 10000 and r['645100']['def'] == 56400
    assert config(admin_client, sid, choix={'641200': 'manuel', '645100': 'proportionnel'}).status_code == 200
    saisir(admin_client, sid, {'641200': 20000})
    assert post(admin_client, sid, 'recalculer').status_code == 200
    assert rows(admin_client, sid)['641200']['def'] == 20000


def test_simulateur_ne_modifie_jamais_fiche_rh(cadre, db, admin_client):
    sid, uid = cadre
    config(admin_client, sid)
    saisir(admin_client, sid, {'641200': 10000})
    avant = tuple(db.execute('SELECT pesee, competence, maintien FROM users WHERE id=?', (uid,)).fetchone())
    result = post(admin_client, sid, 'paie-simulation', compte_num='641100', donnees={
        'salaire_socle': 120000, 'valeur_point': 0, 'temps_plein': 35,
        'employes': {str(uid): {'pesee': 0, 'competence': 0, 'anciennete': 0, 'maintien': 0}}})
    assert result.status_code == 200
    assert result.get_json()['reports']['641100'] == 120000
    assert result.get_json()['reports']['645100'] == 56400
    assert tuple(db.execute('SELECT pesee, competence, maintien FROM users WHERE id=?', (uid,)).fetchone()) == avant


@pytest.mark.parametrize('cause', ['parametres', 'fec', 'saisie', 'rh', 'perimetre'])
def test_page_perimee_refusee_sans_ecriture(cadre, db, admin_client, cause):
    sid, uid = cadre
    token = lire(admin_client, sid)['reference_budget']
    if cause == 'parametres':
        config(admin_client, sid)
    elif cause == 'fec':
        db.execute('UPDATE bilan_fec_donnees SET montant=montant+1')
    elif cause == 'saisie':
        saisir(admin_client, sid, {'641200': 123})
    elif cause == 'rh':
        db.execute('UPDATE users SET pesee=101 WHERE id=?', (uid,))
    else:
        db.execute("INSERT INTO budget_prev_config_codes (code_analytique, secteur_id) VALUES ('NOUVEAU', ?)", (sid,))
    db.commit()
    avant = [tuple(r) for r in db.execute('SELECT * FROM budget_prev_saisies')]
    r = admin_client.post('/api/budget-previsionnel/save-line', json={
        'type_budget': 'actualise', 'annee': 2026, 'secteur_id': sid, 'compte_num': '641100',
        'valeur_def': 999999, 'reference_budget': token})
    assert r.status_code == 409
    assert [tuple(r) for r in db.execute('SELECT * FROM budget_prev_saisies')] == avant


@pytest.mark.parametrize('valeur', ['nan', 'inf', '-inf', 'abc', '999999999999999999999'])
def test_montants_invalides_annulent_le_lot(cadre, db, admin_client, valeur):
    sid, _ = cadre
    r = saisir(admin_client, sid, {'641100': 120000, '641200': valeur})
    assert r.status_code == 409
    assert db.execute('SELECT COUNT(*) FROM budget_prev_saisies').fetchone()[0] == 0


def test_reference_absente_et_falsifiee_refusees(cadre, admin_client):
    sid, _ = cadre
    for token in (None, 'faux'):
        r = admin_client.post('/api/budget-previsionnel/parametres', json={
            'annee': 2026, 'secteur_id': sid, 'type_budget': 'actualise', 'reference_budget': token})
        assert r.status_code == 409


def test_mode_premier_641_et_compte_etranger_refuses(cadre, admin_client):
    sid, _ = cadre
    for choix in ({'641100': 'proportionnel'}, {'999999': 'manuel'}, {'645100': 'inconnu'}):
        assert config(admin_client, sid, choix=choix).status_code == 409


def test_migration_idempotente_preserve_saisies_et_null(cadre, db):
    from budget_calculs import creer_schema
    sid, _ = cadre
    db.execute("INSERT INTO budget_prev_saisies (type_budget, annee, secteur_id, compte_num, valeur_def) VALUES ('actualise', 2026, ?, '641100', 123456)", (sid,))
    db.commit()
    avant = [tuple(r) for r in db.execute('SELECT * FROM budget_prev_saisies')]
    path = Path(__file__).resolve().parents[1] / 'migrations/0070_budget_reference_annuelle.py'
    spec = importlib.util.spec_from_file_location('migration_budget_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for _ in range(2):
        module.upgrade(db)
        creer_schema(db)
    assert [tuple(r) for r in db.execute('SELECT * FROM budget_prev_saisies')] == avant
    assert db.execute('SELECT COUNT(*) FROM budget_parametres').fetchone()[0] == 0
    with pytest.raises(RuntimeError):
        module.downgrade(db)


@pytest.mark.parametrize('client_name', ['auth_client', 'resp_client', 'prestataire_client', 'client'])
@pytest.mark.parametrize('action', ['parametres', 'save-lines', 'recalculer'])
def test_roles_non_habilites_refuses(cadre, db, admin_client, app, request, client_name, action):
    sid, _ = cadre
    token = lire(admin_client, sid)['reference_budget']
    # Les fixtures authentifiées partagent un client : lire le jeton avant
    # de changer sa session ; le visiteur a son propre client vierge.
    client = app.test_client() if client_name == 'client' else request.getfixturevalue(client_name)
    r = client.post('/api/budget-previsionnel/' + action, json={
        'type_budget': 'actualise', 'annee': 2026, 'secteur_id': sid, 'reference_budget': token})
    assert r.status_code in (302, 403)
    assert db.execute('SELECT COUNT(*) FROM budget_parametres').fetchone()[0] == 0


def test_budget_d_un_autre_secteur_refuse_reference(cadre, db, admin_client):
    sid, _ = cadre
    other = db.execute("INSERT INTO secteurs (nom) VALUES ('Autre centre fictif')").lastrowid
    db.commit()
    token = lire(admin_client, sid)['reference_budget']
    r = admin_client.post('/api/budget-previsionnel/parametres', json={
        'type_budget': 'actualise', 'annee': 2026, 'secteur_id': other, 'reference_budget': token})
    assert r.status_code == 409
    assert db.execute('SELECT COUNT(*) FROM budget_parametres').fetchone()[0] == 0


@pytest.mark.parametrize('compte', ['641200', '645100'])
def test_post_direct_ne_contourne_pas_mode_automatique(cadre, admin_client, compte):
    sid, _ = cadre
    config(admin_client, sid, choix={'641200': 'proportionnel', '645100': 'proportionnel'})
    assert saisir(admin_client, sid, {compte: 123}).status_code == 409
    r = post(admin_client, sid, 'fiche-travail', compte_num=compte, donnees={'methode': 'manuel'})
    assert r.status_code == 409


def test_simulateur_refuse_un_autre_641_sans_effet(cadre, db, admin_client):
    sid, _ = cadre
    config(admin_client, sid)
    r = post(admin_client, sid, 'paie-simulation', compte_num='641200', donnees={})
    assert r.status_code == 409
    assert db.execute('SELECT COUNT(*) FROM budget_paie_simulations').fetchone()[0] == 0


def test_montant_non_saisi_distinct_du_zero(cadre, admin_client):
    sid, _ = cadre
    assert saisir(admin_client, sid, {'641200': 0}).status_code == 200
    assert rows(admin_client, sid)['641200']['def'] == 0
    assert saisir(admin_client, sid, {'641200': None}).status_code == 200
    assert rows(admin_client, sid)['641200']['def'] is None


def test_detail_aucun_reel_renvoie_zero_operation(cadre, admin_client):
    sid, _ = cadre
    config(admin_client, sid, mois=0)
    r = admin_client.get(f'/api/budget-previsionnel/detail?compte=641100&annee=2026&secteur_id={sid}&mois_max=0')
    assert r.status_code == 200 and r.get_json()['operations'] == []


def test_reference_autre_annee_complete_possible(cadre, db, admin_client):
    sid, _ = cadre
    db.execute('UPDATE bilan_fec_donnees SET annee=2024 WHERE annee=2025')
    db.commit()
    result = post(admin_client, sid, 'parametres', mois_arrete=6, annee_reference=2024,
                  confirmer_reference_complete=True, modes={'645100': 'proportionnel'})
    assert result.status_code == 200
    saisir(admin_client, sid, {'641100': 120000, '641200': 10000})
    assert rows(admin_client, sid)['645100']['def'] == 56400


def test_global_consolide_calculs_sectoriels(cadre, db, admin_client):
    sid, _ = cadre
    other = db.execute("INSERT INTO secteurs (nom) VALUES ('Autre budget fictif')").lastrowid
    db.execute("INSERT INTO budget_prev_config_codes (code_analytique, secteur_id) VALUES ('BUDGET-AUTRE', ?)", (other,))
    db.execute("INSERT INTO bilan_fec_donnees (compte_num, code_analytique, annee, mois, montant) SELECT compte_num, 'BUDGET-AUTRE', annee, mois, montant FROM bilan_fec_donnees WHERE code_analytique='BUDGET-TEST'")
    db.commit()
    for secteur, base in [(sid, 120000), (other, 130000)]:
        config(admin_client, secteur)
        saisir(admin_client, secteur, {'641100': base, '641200': 10000})
    r = admin_client.get('/api/budget-previsionnel/donnees?type_budget=actualise&annee=2026&global=1')
    assert r.status_code == 200
    charge = next(x for x in r.get_json()['rows'] if x['compte_num'] == '645100')
    assert charge['def'] == charge['temp'] == 116800
    assert charge['N'] == 60000


@pytest.mark.parametrize('valeur', ['nan', 'inf', 'abc'])
def test_simulation_refuse_nombres_invalides(cadre, db, admin_client, valeur):
    sid, _ = cadre
    config(admin_client, sid)
    r = post(admin_client, sid, 'paie-simulation', compte_num='641100', donnees={'salaire_socle': valeur})
    assert r.status_code == 409
    assert db.execute('SELECT COUNT(*) FROM budget_paie_simulations').fetchone()[0] == 0


def test_concurrence_refuse_ancienne_saisie_apres_verrou(cadre, db, admin_client, app, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from blueprints import budget as bp
    sid, _ = cadre
    token = lire(admin_client, sid)['reference_budget']
    with admin_client.session_transaction() as sess:
        cookie = dict(sess)
    get_db = bp.get_db
    attente = Event()

    class Connexion:
        def __init__(self):
            self.conn = get_db()
        def execute(self, sql, *args):
            if sql == 'BEGIN IMMEDIATE':
                attente.set()
            return self.conn.execute(sql, *args)
        def __getattr__(self, name):
            return getattr(self.conn, name)

    monkeypatch.setattr(bp, 'get_db', Connexion)

    def envoyer():
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess.update(cookie)
            return client.post('/api/budget-previsionnel/save-line', json={
                'type_budget': 'actualise', 'annee': 2026, 'secteur_id': sid,
                'compte_num': '641100', 'valeur_def': 99999, 'reference_budget': token}).status_code

    db.execute('BEGIN IMMEDIATE')
    db.execute("INSERT INTO budget_prev_saisies (type_budget, annee, secteur_id, compte_num, valeur_def) VALUES ('actualise', 2026, ?, '641100', 120000)", (sid,))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(envoyer)
        try:
            assert attente.wait(3)
        finally:
            db.commit()
        assert future.result(timeout=5) == 409
    assert db.execute('SELECT valeur_def FROM budget_prev_saisies WHERE secteur_id=?', (sid,)).fetchone()[0] == 120000


def test_global_detail_suit_arretes_sectoriels(cadre, db, admin_client):
    sid, _ = cadre
    other = db.execute("INSERT INTO secteurs (nom) VALUES ('Arrêté différent fictif')").lastrowid
    db.execute("INSERT INTO budget_prev_config_codes (code_analytique, secteur_id) VALUES ('BUDGET-AUTRE', ?)", (other,))
    db.execute("INSERT INTO bilan_fec_donnees (compte_num, code_analytique, annee, mois, montant) SELECT compte_num, 'BUDGET-AUTRE', annee, mois, montant FROM bilan_fec_donnees WHERE code_analytique='BUDGET-TEST'")
    db.commit()
    config(admin_client, sid, mois=6)
    config(admin_client, other, mois=3)
    data = admin_client.get('/api/budget-previsionnel/donnees?type_budget=actualise&annee=2026&global=1').get_json()
    charge = next(x for x in data['rows'] if x['compte_num'] == '645100')
    detail = admin_client.get('/api/budget-previsionnel/detail?compte=645100&annee=2026&global=1&arretes_budget=1&mois_max=0').get_json()
    assert charge['N'] == sum(x['montant'] for x in detail['operations']) == 45000
    assert any('arrêté différents' in a for a in data['alertes'])


def test_echec_sql_annule_toutes_les_saisies(cadre, db, admin_client, monkeypatch):
    import sqlite3
    from blueprints import budget
    sid, _ = cadre
    avant = [tuple(r) for r in db.execute('SELECT * FROM budget_prev_saisies')]
    def echouer(*args):
        raise sqlite3.OperationalError('échec fictif après les saisies')
    monkeypatch.setattr(budget, 'reporter_automatiques', echouer)
    r = saisir(admin_client, sid, {'641100': 120000, '641200': 10000})
    assert r.status_code == 503
    assert [tuple(r) for r in db.execute('SELECT * FROM budget_prev_saisies')] == avant


@pytest.mark.parametrize('compte', ['641100', '641200', '645100'])
def test_simulateur_ps_ne_contourne_pas_les_modes_63_64(cadre, db, admin_client, compte):
    sid, _ = cadre
    config(admin_client, sid)
    avant = [tuple(r) for r in db.execute('SELECT * FROM budget_prev_saisies')]
    for action in ('ps-comptes', 'ps-simulation'):
        r = admin_client.post('/api/budget-previsionnel/' + action, json={
            'compte_num': compte, 'annee': 2026, 'secteur_id': sid,
            'type_budget': 'actualise', 'type_ps': 'eaje', 'donnees': {}})
        assert r.status_code == 400
    assert [tuple(r) for r in db.execute('SELECT * FROM budget_prev_saisies')] == avant
    assert db.execute('SELECT COUNT(*) FROM budget_ps_simulations').fetchone()[0] == 0
