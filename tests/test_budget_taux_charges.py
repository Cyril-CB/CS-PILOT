"""Taux individuels, brut global et reports atomiques sur des budgets fictifs."""
import json
import sqlite3

import pytest

from budget_calculs import donnees_reference
from tests.test_budget_regles import lire, post
from tests.test_budget import _texte_pdf_budget


@pytest.fixture
def simulation(db, admin_client):
    sid = db.execute("INSERT INTO secteurs (nom) VALUES ('Taux fictifs')").lastrowid
    db.execute("INSERT INTO budget_prev_config_codes (code_analytique, secteur_id) VALUES ('TAUX-TEST', ?)", (sid,))
    uid = db.execute('''INSERT INTO users (nom, prenom, login, password, profil, actif, secteur_id,
        pesee, competence, maintien) VALUES ('Fictif', 'Taux', 'taux-test', 'inutilise', 'salarie', 1, ?, 0, 0, 0)''', (sid,)).lastrowid
    db.execute("INSERT INTO contrats (user_id, type_contrat, date_debut, temps_hebdo) VALUES (?, 'CDI', '2020-01-01', 35)", (uid,))
    references = {'641100': 24000, '641200': 2400, '635100': 264,
                  '645100': 9600, '645200': 600, '646100': 400, '647100': 200, '648100': 200,
                  '644100': 50, '649100': -100}
    reels = {'641100': 12000, '641200': 1200, '635100': 132,
             '645100': 4800, '645200': 300, '646100': 200, '647100': 100, '648100': 100}
    for annee, montants in [(2025, references), (2026, reels)]:
        for compte, valeur in montants.items():
            db.execute('''INSERT INTO bilan_fec_donnees
                (compte_num, libelle, code_analytique, annee, mois, montant)
                VALUES (?, 'FICTIF', 'TAUX-TEST', ?, 6, ?)''', (compte, annee, valeur))
    # Une écriture hors périmètre sur le même compte ne doit jamais être reprise.
    db.execute("INSERT INTO bilan_fec_donnees (compte_num, code_analytique, annee, mois, montant) VALUES ('645100', 'AUTRE', 2026, 6, 999999)")
    h = donnees_reference(db, 2025, sid)['empreinte']
    for typ in ('initial', 'actualise'):
        db.execute('''INSERT INTO budget_parametres
            (type_budget, annee, secteur_id, mois_arrete, annee_reference, reference_empreinte)
            VALUES (?, 2026, ?, ?, 2025, ?)''', (typ, sid, 0 if typ == 'initial' else 6, h))
        db.execute("INSERT INTO budget_modes_comptes VALUES (?, 2026, ?, '635100', 'proportionnel')", (typ, sid))
        for compte, valeur in {**references, '641200': 3600}.items():
            db.execute('''INSERT INTO budget_prev_saisies
                (type_budget, annee, secteur_id, compte_num, valeur_temp, valeur_def, commentaire)
                VALUES (?, 2026, ?, ?, ?, ?, 'Commentaire conservé')''', (typ, sid, compte, valeur, valeur))
    db.commit()
    donnees = {'salaire_socle': 24000, 'valeur_point': 0, 'utiliser_taux_charges': True,
               'employes': {str(uid): {'taux_charges': 40}}, 'ajouts': []}
    return sid, uid, donnees


def enregistrer(client, simulation, typ='initial', donnees=None, **champs):
    sid, _, original = simulation
    return post(client, sid, 'paie-simulation', typ, compte_num='641100',
                donnees=original if donnees is None else donnees, **champs)


def etat(db, sid):
    return ([tuple(r) for r in db.execute('SELECT * FROM budget_prev_saisies WHERE secteur_id=? ORDER BY type_budget, compte_num', (sid,))],
            [tuple(r) for r in db.execute('SELECT * FROM budget_paie_simulations WHERE secteur_id=?', (sid,))])


@pytest.mark.parametrize('typ, attendu, charge63', [('initial', 11040, 276), ('actualise', 11260, 276)])
def test_taux_sur_tous_les_641_report_unique_et_reel_conserve(simulation, db, admin_client, typ, attendu, charge63):
    sid, uid, _ = simulation
    fec = [tuple(r) for r in db.execute('SELECT * FROM bilan_fec_donnees')]
    rh = tuple(db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone())
    response = enregistrer(admin_client, simulation, typ)
    assert response.status_code == 200, response.get_json()
    data = lire(admin_client, sid, typ)
    rows = {r['compte_num']: r for r in data['rows']}
    assert rows['645100']['def'] == rows['645100']['temp'] == attendu
    assert data['charges_salaries']['taux_moyen'] == pytest.approx(0.4)
    for compte in ('645200', '646100', '647100', '648100'):
        assert rows[compte]['def'] == rows[compte]['temp'] == 0
        assert rows[compte]['mode'] == 'taux_salaries'
    assert rows['635100']['def'] == charge63
    assert rows['644100']['def'] == 50 and rows['649100']['def'] == -100
    assert all(r['commentaire'] == 'Commentaire conservé' for r in rows.values())
    assert post(admin_client, sid, 'recalculer', typ).status_code == 200
    assert lire(admin_client, sid, typ)['charges_salaries']['total'] == attendu
    assert tuple(db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()) == rh
    assert [tuple(r) for r in db.execute('SELECT * FROM bilan_fec_donnees')] == fec


def test_taux_pondere_salarie_et_ajout(simulation, admin_client):
    sid, _, d = simulation
    d['ajouts'] = [{'type': 'cdi', 'temps_hebdo': 17.5, 'mois_embauche': 1, 'taux_charges': 20}]
    response = enregistrer(admin_client, simulation)
    assert response.status_code == 200
    data = lire(admin_client, sid, 'initial')
    # 24 000 × 40 % + 12 000 × 20 % = 12 000, puis 3 600 de compléments au même taux pondéré.
    assert data['brut_global'] == 39600
    assert data['charges_salaries']['taux_moyen'] == pytest.approx(1 / 3)
    assert data['charges_salaries']['total'] == 13200


def test_cee_taux_global_et_fermetures(simulation, admin_client):
    sid, _, d = simulation
    d.update(cee_mercredi=2, forfait_cee=100, taux_charges_cee=15,
             fermetures=[{'debut': '2026-01-01', 'fin': '2026-11-30'}])
    response = enregistrer(admin_client, simulation)
    assert response.status_code == 200
    computed = response.get_json()['computed']
    cee = sum(computed['cee_mois'].values())
    assert cee > 0 and all(v == 0 for m, v in computed['cee_mois'].items() if int(m) < 12)
    attendu = (9600 + cee * .15) / (24000 + cee)
    charges = lire(admin_client, sid, 'initial')['charges_salaries']
    assert charges['taux_moyen'] == pytest.approx(attendu)
    assert charges['total'] == pytest.approx(round((27600 + cee) * attendu, 2))


@pytest.mark.parametrize('valeur', [None, '', -1, 101, 'nan', 'inf', True, 'invalide'])
@pytest.mark.parametrize('emplacement', ['salarie', 'ajout', 'cee'])
def test_taux_absent_ou_invalide_refuse_sans_report(simulation, db, admin_client, valeur, emplacement):
    sid, uid, d = simulation
    if emplacement == 'salarie':
        d['employes'][str(uid)]['taux_charges'] = valeur
    elif emplacement == 'ajout':
        d['ajouts'] = [{'type': 'cdd', 'mois_debut': 7, 'mois_fin': 7, 'taux_charges': valeur}]
    else:
        d.update(cee_mercredi=1, taux_charges_cee=valeur)
    avant = etat(db, sid)
    assert enregistrer(admin_client, simulation).status_code == 409
    assert etat(db, sid) == avant


def test_zero_explicite_et_decembre(simulation, admin_client):
    sid, uid, d = simulation
    d['employes'][str(uid)]['taux_charges'] = 0
    assert enregistrer(admin_client, simulation).status_code == 200
    assert lire(admin_client, sid, 'initial')['charges_salaries']['total'] == 0
    assert post(admin_client, sid, 'parametres', mois_arrete=12, annee_reference=None, modes={}).status_code == 200
    d['employes'][str(uid)]['taux_charges'] = ''  # Aucun brut futur, donc aucun taux à exiger.
    assert enregistrer(admin_client, simulation, 'actualise').status_code == 200
    assert lire(admin_client, sid)['charges_salaries']['total'] == 5500


def test_desactivation_restaure_manuels_et_recalcule_modes(simulation, db, admin_client):
    sid, _, d = simulation
    db.execute("INSERT INTO budget_modes_comptes VALUES ('initial', 2026, ?, '645200', 'proportionnel')", (sid,))
    db.commit()
    assert enregistrer(admin_client, simulation).status_code == 200
    d['utiliser_taux_charges'] = False
    # Le client ne peut pas choisir les montants à restaurer.
    d['_charges_avant_taux'] = {'645100': {'valeur_def': 999999}}
    assert enregistrer(admin_client, simulation).status_code == 200
    data = lire(admin_client, sid, 'initial')
    rows = {r['compte_num']: r for r in data['rows']}
    assert data['charges_salaries'] is None
    assert rows['645100']['def'] == 9600
    assert rows['646100']['def'] == 400 and rows['647100']['def'] == 200 and rows['648100']['def'] == 200
    assert rows['645200']['def'] == round(27600 * 600 / 26400, 2)
    assert rows['645200']['mode'] == 'proportionnel'


@pytest.mark.parametrize('initialement_actif', [False, True])
@pytest.mark.parametrize('emplacement', ['salarie', 'ajout', 'cee'])
def test_taux_invalide_ignore_option_desactivee(simulation, db, admin_client, initialement_actif, emplacement):
    sid, uid, d = simulation
    if emplacement == 'ajout':
        d['ajouts'] = [{'type': 'cdi', 'temps_hebdo': 35, 'taux_charges': 20}]
        ligne, champ = d['ajouts'][0], 'taux_charges'
    elif emplacement == 'cee':
        d.update(cee_mercredi=1, taux_charges_cee=15)
        ligne, champ = d, 'taux_charges_cee'
    else:
        ligne, champ = d['employes'][str(uid)], 'taux_charges'
    if initialement_actif:
        assert enregistrer(admin_client, simulation).status_code == 200
    # Même parcours que le navigateur : un taux invalide est saisi, puis décoché.
    ligne[champ] = 101
    d['utiliser_taux_charges'] = False
    response = enregistrer(admin_client, simulation)
    assert response.status_code == 200, response.get_json()
    assert response.get_json()['computed']['charges_salaries'] is None
    data = lire(admin_client, sid, 'initial')
    assert data['charges_salaries'] is None
    rows = {r['compte_num']: r for r in data['rows']}
    for compte, ancien in {'645100': 9600, '645200': 600, '646100': 400, '647100': 200, '648100': 200}.items():
        assert rows[compte]['def'] == ancien
        assert rows[compte]['mode'] == 'manuel'
    saved = json.loads(db.execute('SELECT donnees FROM budget_paie_simulations WHERE secteur_id=?', (sid,)).fetchone()[0])
    assert saved == d  # Les taux inutilisés restent dans le scénario.
    avant = etat(db, sid)
    saved['utiliser_taux_charges'] = True
    assert enregistrer(admin_client, simulation, donnees=saved).status_code == 409
    assert etat(db, sid) == avant  # Réactivation impossible tant que le taux reste invalide.


@pytest.mark.parametrize('action', ['save-line', 'fiche-travail', 'parametres', 'retirer-compte'])
def test_comptes_pilotes_proteges_sur_post_direct(simulation, db, admin_client, action):
    sid, _, _ = simulation
    assert enregistrer(admin_client, simulation).status_code == 200
    avant = etat(db, sid)
    response = post(admin_client, sid, action, 'initial', compte_num='645100', valeur_def=99,
                    donnees={'methode': 'n1'}, mois_arrete=0, annee_reference=None, modes={'645100': 'manuel'})
    assert response.status_code == 409
    assert etat(db, sid) == avant


@pytest.mark.parametrize('source', ['taux', 'fec', 'calendrier'])
def test_ancienne_page_refuse_changement_sources(simulation, db, admin_client, source):
    sid, uid, d = simulation
    assert enregistrer(admin_client, simulation).status_code == 200
    reference = lire(admin_client, sid, 'initial')['reference_budget']
    if source == 'taux':
        d['employes'][str(uid)]['taux_charges'] = 30
        assert enregistrer(admin_client, simulation).status_code == 200
    elif source == 'fec':
        db.execute("UPDATE bilan_fec_donnees SET montant=montant+1 WHERE code_analytique='TAUX-TEST' AND compte_num='641200'")
        db.commit()
    else:
        db.execute("INSERT INTO jours_feries (date, libelle, annee) VALUES ('2026-09-16', 'Fictif', 2026)")
        db.commit()
    avant = etat(db, sid)
    response = admin_client.post('/api/budget-previsionnel/paie-simulation', json={
        'secteur_id': sid, 'annee': 2026, 'type_budget': 'initial', 'compte_num': '641100',
        'reference_budget': reference, 'donnees': d})
    assert response.status_code == 409
    assert etat(db, sid) == avant


def test_premier_645_choisi_serveur_et_nouveaux_comptes(simulation, admin_client):
    sid, _, _ = simulation
    assert enregistrer(admin_client, simulation).status_code == 200
    assert admin_client.post('/api/budget-previsionnel/ajouter-compte', json={
        'type_budget': 'initial', 'annee': 2026, 'secteur_id': sid, 'compte_num': '645000'}).status_code == 200
    assert post(admin_client, sid, 'recalculer', 'initial').status_code == 200
    rows = {r['compte_num']: r for r in lire(admin_client, sid, 'initial')['rows']}
    assert rows['645000']['def'] == 11040 and rows['645100']['def'] == 0


@pytest.mark.parametrize('cause', ['sans_645', '641_incomplet', 'sans_base_simulee', 'option_invalide'])
def test_activation_impossible_atomique(simulation, db, admin_client, cause):
    sid, _, d = simulation
    if cause == 'sans_645':
        db.execute("DELETE FROM bilan_fec_donnees WHERE compte_num LIKE '645%'")
        db.execute("DELETE FROM budget_prev_saisies WHERE compte_num LIKE '645%'")
    elif cause == '641_incomplet':
        db.execute("UPDATE budget_prev_saisies SET valeur_def=NULL WHERE compte_num='641200'")
    elif cause == 'sans_base_simulee':
        d['salaire_socle'] = 0
    else:
        d['utiliser_taux_charges'] = 'true'
    db.commit()
    avant = etat(db, sid)
    assert enregistrer(admin_client, simulation).status_code == 409
    assert etat(db, sid) == avant


def test_panne_au_report_annule_simulation_et_brut(simulation, db, admin_client, monkeypatch):
    import blueprints.budget as budget
    sid, _, _ = simulation
    avant = etat(db, sid)
    def panne(*args, **kwargs):
        raise sqlite3.OperationalError('FICTIF')
    monkeypatch.setattr(budget, 'reporter_automatiques', panne)
    assert enregistrer(admin_client, simulation).status_code == 503
    assert etat(db, sid) == avant


@pytest.mark.parametrize('profil', ['client', 'auth_client', 'resp_client', 'prestataire_client'])
def test_taux_reserves_direction_comptabilite(simulation, request, admin_client, profil):
    sid, _, d = simulation
    reference = lire(admin_client, sid, 'initial')['reference_budget']
    client = request.getfixturevalue('app').test_client() if profil == 'client' else request.getfixturevalue(profil)
    response = client.post('/api/budget-previsionnel/paie-simulation', json={
        'secteur_id': sid, 'annee': 2026, 'type_budget': 'initial', 'compte_num': '641100',
        'reference_budget': reference, 'donnees': d})
    assert response.status_code in (302, 403)


def test_persistence_pdf_et_consolidation(simulation, admin_client):
    sid, uid, _ = simulation
    assert enregistrer(admin_client, simulation).status_code == 200
    saved = admin_client.get(f'/api/budget-previsionnel/paie-simulation?annee=2026&secteur_id={sid}&type_budget=initial').get_json()
    assert saved['donnees']['utiliser_taux_charges'] is True
    assert saved['donnees']['employes'][str(uid)]['taux_charges'] == 40
    data = admin_client.get('/api/budget-previsionnel/donnees?type_budget=initial&annee=2026&global=1').get_json()
    assert data['secteurs_taux_charges'] == ['Taux fictifs']
    assert next(r for r in data['rows'] if r['compte_num'] == '645100')['def'] == 11040
    for scope in (f'secteur_id={sid}', 'global=1'):
        pdf = admin_client.get(f'/api/budget-previsionnel/export-pdf?type_budget=initial&annee=2026&{scope}')
        assert pdf.status_code == 200
        assert b'11040.00' in _texte_pdf_budget(pdf.data)
        assert b'645' in _texte_pdf_budget(pdf.data)


def test_contrat_partiel_socle_annuel_et_taux(simulation, db, admin_client):
    sid, uid, _ = simulation
    db.execute("UPDATE contrats SET type_contrat='CDD', date_debut='2026-07-06', date_fin='2026-07-12' WHERE user_id=?", (uid,))
    db.execute("UPDATE budget_prev_saisies SET valeur_def=0 WHERE compte_num='641200'")
    db.commit()
    response = enregistrer(admin_client, simulation)
    assert response.status_code == 200
    assert response.get_json()['total'] == 451.61  # 24 000 / 12 × 7 / 31.
    assert lire(admin_client, sid, 'initial')['charges_salaries']['total'] == 180.64


def test_restaure_inconnus_et_simulations_independantes(simulation, db, admin_client):
    sid, _, d = simulation
    db.execute("UPDATE budget_prev_saisies SET valeur_temp=NULL, valeur_def=NULL WHERE type_budget='initial' AND compte_num='647100'")
    db.commit()
    assert enregistrer(admin_client, simulation).status_code == 200
    assert enregistrer(admin_client, simulation, 'actualise').status_code == 200
    # Refaire un report actif ne remplace pas les valeurs d'avant activation.
    assert enregistrer(admin_client, simulation).status_code == 200
    d['utiliser_taux_charges'] = False
    assert enregistrer(admin_client, simulation).status_code == 200
    rows = {r['compte_num']: r for r in lire(admin_client, sid, 'initial')['rows']}
    assert rows['647100']['def'] is None and rows['647100']['temp'] is None
    assert rows['645100']['def'] == 9600
    assert lire(admin_client, sid, 'actualise')['charges_salaries']['total'] == 11260


def test_nouveau_salarie_sans_taux_ne_met_pas_les_charges_a_zero(simulation, db, admin_client):
    sid, _, _ = simulation
    assert enregistrer(admin_client, simulation).status_code == 200
    uid = db.execute("INSERT INTO users (nom, prenom, login, password, profil, actif, secteur_id) VALUES ('Nouveau', 'Fictif', 'taux-nouveau', 'inutilise', 'salarie', 1, ?)", (sid,)).lastrowid
    db.execute("INSERT INTO contrats (user_id, type_contrat, date_debut, temps_hebdo) VALUES (?, 'CDI', '2026-07-01', 35)", (uid,))
    db.commit()
    assert post(admin_client, sid, 'recalculer', 'initial').status_code == 200
    data = lire(admin_client, sid, 'initial')
    assert data['charges_salaries']['code_erreur'] == 'taux_charges_manquant'
    rows = {r['compte_num']: r for r in data['rows']}
    assert rows['645100']['def'] == 11040 and rows['645100']['temp'] is None
    assert data['incomplet']


def test_comptable_peut_enregistrer(simulation, comptable_client):
    assert enregistrer(comptable_client, simulation).status_code == 200


@pytest.mark.parametrize('changement, statut', [('taux', 409), ('droits', 403)])
def test_concurrence_recontrole_apres_verrou(simulation, db, admin_client, app, monkeypatch, changement, statut):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from blueprints import budget as bp
    sid, uid, d = simulation
    assert enregistrer(admin_client, simulation).status_code == 200
    token = lire(admin_client, sid, 'initial')['reference_budget']
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
            return client.post('/api/budget-previsionnel/paie-simulation', json={
                'type_budget': 'initial', 'annee': 2026, 'secteur_id': sid,
                'compte_num': '641100', 'donnees': d, 'reference_budget': token}).status_code

    db.execute('BEGIN IMMEDIATE')
    if changement == 'taux':
        saved = json.loads(db.execute('SELECT donnees FROM budget_paie_simulations WHERE secteur_id=?', (sid,)).fetchone()[0])
        saved['employes'][str(uid)]['taux_charges'] = 30
        db.execute('UPDATE budget_paie_simulations SET donnees=? WHERE secteur_id=?', (json.dumps(saved), sid))
    else:
        db.execute("UPDATE users SET profil='salarie' WHERE id=?", (cookie['user_id'],))
    attendu = etat(db, sid)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(envoyer)
        try:
            assert attente.wait(3)
        finally:
            db.commit()
        assert future.result(timeout=5) == statut
    assert etat(db, sid) == attendu
