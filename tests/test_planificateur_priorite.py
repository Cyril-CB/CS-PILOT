"""
Tests de la priorité relative du planificateur (comparaisons par paires).

La priorité n'est plus saisie sur une échelle haute/normale/basse : la
première tâche vaut 0, puis chaque nouvelle tâche est située (supérieur /
égal / inférieur) par rapport à la plus urgente et à la moins urgente des
tâches en cours d'ici J+3 (repli : toutes les tâches), présentées en
aveugle. Des réponses incohérentes réévaluent la tâche mal estimée.
"""
from datetime import date, timedelta

import planificateur_engine as moteur


def _inserer(db, uid, titre, prio_num=None, deadline=None, statut='a_faire'):
    cur = db.execute(
        "INSERT INTO planif_taches (user_id, type, titre, duree_min, deadline, priorite_num, statut) "
        "VALUES (?, 'tache', ?, 30, ?, ?, ?)",
        (uid, titre, deadline, prio_num, statut))
    db.commit()
    return cur.lastrowid


def _prio(db, tache_id):
    return db.execute('SELECT priorite_num FROM planif_taches WHERE id = ?',
                      (tache_id,)).fetchone()['priorite_num']


def _creer(client, titre, comparaisons=None):
    payload = {'type': 'tache', 'titre': titre, 'duree_min': 30}
    if comparaisons:
        payload['comparaisons'] = comparaisons
    r = client.post('/planificateur/api/tache', json=payload)
    assert r.status_code == 200
    assert r.get_json()['ok'] is True


def _derniere(db, uid):
    return db.execute("SELECT * FROM planif_taches WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                      (uid,)).fetchone()


class TestCalculPriorite:
    def test_premiere_tache_a_zero(self, comptable_client, db, sample_users):
        _creer(comptable_client, 'Première tâche')
        assert _derniere(db, sample_users['comptable_id'])['priorite_num'] == 0

    def test_deuxieme_tache_superieure(self, comptable_client, db, sample_users):
        uid = sample_users['comptable_id']
        ref = _inserer(db, uid, 'Référence', 0)
        _creer(comptable_client, 'Nouvelle', [{'tache_id': ref, 'reponse': 'superieur'}])
        assert _derniere(db, uid)['priorite_num'] == 1

    def test_deuxieme_tache_egale(self, comptable_client, db, sample_users):
        uid = sample_users['comptable_id']
        ref = _inserer(db, uid, 'Référence', 0)
        _creer(comptable_client, 'Nouvelle', [{'tache_id': ref, 'reponse': 'egal'}])
        assert _derniere(db, uid)['priorite_num'] == 0

    def test_deuxieme_tache_inferieure(self, comptable_client, db, sample_users):
        uid = sample_users['comptable_id']
        ref = _inserer(db, uid, 'Référence', 0)
        _creer(comptable_client, 'Nouvelle', [{'tache_id': ref, 'reponse': 'inferieur'}])
        assert _derniere(db, uid)['priorite_num'] == -1

    def test_entre_les_deux_moyenne_ponderee(self, comptable_client, db, sample_users):
        # Exemple validé avec l'utilisateur : haute à 5 (réponse inférieur),
        # basse à 2 (réponse supérieur) → (4×1 + 3×2) / 3 = 3,33 → 3.
        uid = sample_users['comptable_id']
        h = _inserer(db, uid, 'Haute', 5)
        b = _inserer(db, uid, 'Basse', 2)
        _creer(comptable_client, 'Nouvelle', [
            {'tache_id': h, 'reponse': 'inferieur'},
            {'tache_id': b, 'reponse': 'superieur'},
        ])
        assert _derniere(db, uid)['priorite_num'] == 3

    def test_superieure_aux_deux(self, comptable_client, db, sample_users):
        uid = sample_users['comptable_id']
        h = _inserer(db, uid, 'Haute', 5)
        b = _inserer(db, uid, 'Basse', 2)
        _creer(comptable_client, 'Nouvelle', [
            {'tache_id': h, 'reponse': 'superieur'},
            {'tache_id': b, 'reponse': 'superieur'},
        ])
        assert _derniere(db, uid)['priorite_num'] == 7   # la plus haute + 2

    def test_inferieure_aux_deux(self, comptable_client, db, sample_users):
        uid = sample_users['comptable_id']
        h = _inserer(db, uid, 'Haute', 5)
        b = _inserer(db, uid, 'Basse', 2)
        _creer(comptable_client, 'Nouvelle', [
            {'tache_id': h, 'reponse': 'inferieur'},
            {'tache_id': b, 'reponse': 'inferieur'},
        ])
        assert _derniere(db, uid)['priorite_num'] == 0   # la plus basse − 2

    def test_egale_a_une_reference(self, comptable_client, db, sample_users):
        uid = sample_users['comptable_id']
        h = _inserer(db, uid, 'Haute', 5)
        b = _inserer(db, uid, 'Basse', 2)
        _creer(comptable_client, 'Nouvelle', [
            {'tache_id': h, 'reponse': 'egal'},
            {'tache_id': b, 'reponse': 'superieur'},
        ])
        assert _derniere(db, uid)['priorite_num'] == 5

    def test_incoherence_reevalue_la_tache_mal_estimee(self, comptable_client, db, sample_users):
        # Exemple validé : supérieur à la tâche à 5, inférieur à celle à 2 →
        # la nouvelle passe à 6, la 5 ne bouge pas, la 2 remonte à 7.
        uid = sample_users['comptable_id']
        h = _inserer(db, uid, 'Haute', 5)
        b = _inserer(db, uid, 'Basse', 2)
        _creer(comptable_client, 'Nouvelle', [
            {'tache_id': h, 'reponse': 'superieur'},
            {'tache_id': b, 'reponse': 'inferieur'},
        ])
        assert _derniere(db, uid)['priorite_num'] == 6
        assert _prio(db, h) == 5
        assert _prio(db, b) == 7


class TestEndpointComparaison:
    URL = '/planificateur/api/priorite/comparaison'

    def test_sans_tache_liste_vide(self, comptable_client):
        assert comptable_client.get(self.URL).get_json()['comparaisons'] == []

    def test_une_tache_une_seule_reference(self, comptable_client, db, sample_users):
        _inserer(db, sample_users['comptable_id'], 'Seule', 0)
        comparaisons = comptable_client.get(self.URL).get_json()['comparaisons']
        assert len(comparaisons) == 1
        assert comparaisons[0]['titre'] == 'Seule'

    def test_references_plus_et_moins_urgentes(self, comptable_client, db, sample_users):
        uid = sample_users['comptable_id']
        a = _inserer(db, uid, 'P5', 5)
        _inserer(db, uid, 'P2', 2)
        c = _inserer(db, uid, 'P0', 0)
        comparaisons = comptable_client.get(self.URL).get_json()['comparaisons']
        assert {x['id'] for x in comparaisons} == {a, c}

    def test_fenetre_j3_prime_sur_les_taches_lointaines(self, comptable_client, db, sample_users):
        uid = sample_users['comptable_id']
        today = date.today()
        proche_haute = _inserer(db, uid, 'Proche haute', 4, deadline=today.isoformat())
        proche_basse = _inserer(db, uid, 'Proche basse', 1,
                                deadline=(today + timedelta(days=2)).isoformat())
        _inserer(db, uid, 'Lointaine', 9, deadline=(today + timedelta(days=30)).isoformat())
        comparaisons = comptable_client.get(self.URL).get_json()['comparaisons']
        assert {x['id'] for x in comparaisons} == {proche_haute, proche_basse}

    def test_repli_sur_toutes_les_taches(self, comptable_client, db, sample_users):
        # Une seule tâche d'ici J+3 : pas assez → on élargit à l'ensemble.
        uid = sample_users['comptable_id']
        today = date.today()
        proche = _inserer(db, uid, 'Proche', 1, deadline=today.isoformat())
        lointaine = _inserer(db, uid, 'Lointaine', 9,
                             deadline=(today + timedelta(days=30)).isoformat())
        comparaisons = comptable_client.get(self.URL).get_json()['comparaisons']
        assert {x['id'] for x in comparaisons} == {proche, lointaine}

    def test_exclusion_pour_reevaluation(self, comptable_client, db, sample_users):
        seule = _inserer(db, sample_users['comptable_id'], 'Seule', 0)
        data = comptable_client.get(f'{self.URL}?exclude_id={seule}').get_json()
        assert data['comparaisons'] == []

    def test_taches_faites_ignorees(self, comptable_client, db, sample_users):
        _inserer(db, sample_users['comptable_id'], 'Terminée', 5, statut='fait')
        assert comptable_client.get(self.URL).get_json()['comparaisons'] == []


class TestEditionPriorite:
    def test_edition_sans_comparaisons_conserve(self, comptable_client, db, sample_users):
        uid = sample_users['comptable_id']
        t = _inserer(db, uid, 'À modifier', 4)
        r = comptable_client.post(f'/planificateur/api/tache/{t}',
                                  json={'titre': 'Modifiée', 'duree_min': 45})
        assert r.status_code == 200
        assert _prio(db, t) == 4

    def test_edition_reevalue_avec_comparaisons(self, comptable_client, db, sample_users):
        uid = sample_users['comptable_id']
        ref = _inserer(db, uid, 'Référence', 2)
        t = _inserer(db, uid, 'À réévaluer', 0)
        r = comptable_client.post(f'/planificateur/api/tache/{t}', json={
            'titre': 'À réévaluer', 'duree_min': 30,
            'comparaisons': [{'tache_id': ref, 'reponse': 'superieur'}],
        })
        assert r.status_code == 200
        assert _prio(db, t) == 3


class TestMoteurPriorite:
    BASE = {'duree_min': 60, 'deadline': '2025-06-16', 'priorite': 'normale',
            'preference': 'aucune', 'secable': False, 'duree_min_bloc': 30}

    def _ordre(self, taches):
        horizon = date(2025, 6, 20)
        return [t['id'] for t in sorted(taches, key=lambda t: moteur._cle_tri_tache(t, horizon))]

    def test_priorite_numerique_avant_duree(self):
        t1 = dict(self.BASE, id=1, titre='A', priorite_num=5, duree_min=120)
        t2 = dict(self.BASE, id=2, titre='B', priorite_num=2, duree_min=30)
        assert self._ordre([t2, t1]) == [1, 2]

    def test_duree_croissante_puis_recence(self):
        t1 = dict(self.BASE, id=1, titre='Longue', priorite_num=0, duree_min=120)
        t2 = dict(self.BASE, id=2, titre='Rapide', priorite_num=0, duree_min=30)
        assert self._ordre([t1, t2]) == [2, 1]
        # Tout égal : la plus récente (id le plus grand) d'abord.
        t3 = dict(self.BASE, id=3, titre='Ancienne', priorite_num=0)
        t4 = dict(self.BASE, id=4, titre='Récente', priorite_num=0)
        assert self._ordre([t3, t4]) == [4, 3]

    def test_repli_sur_l_ancienne_echelle_texte(self):
        t1 = dict(self.BASE, id=1, titre='Haute', priorite='haute', priorite_num=None)
        t2 = dict(self.BASE, id=2, titre='Basse', priorite='basse', priorite_num=None)
        assert self._ordre([t2, t1]) == [1, 2]


def test_recurrence_creee_avec_priorite_neutre(comptable_client, db, sample_users):
    r = comptable_client.post('/planificateur/api/recurrence', json={
        'titre': 'Relevé hebdo', 'frequence': 'hebdomadaire', 'duree_min': 30,
        'jour_semaine': 1,
    })
    assert r.status_code == 200
    rec = db.execute("SELECT * FROM planif_recurrences ORDER BY id DESC LIMIT 1").fetchone()
    assert rec['priorite_num'] == 0


def test_fenetre_contient_l_espace_priorite(comptable_client):
    html = comptable_client.get('/planificateur').get_data(as_text=True)
    assert 'id="blocPriorite"' in html
    assert 'ajustement de priorité selon vos réponses' in html
    assert 'Réévaluer la priorité' in html
    assert 'id="t_priorite"' not in html   # l'ancien sélecteur a disparu
    assert 'id="r_priorite"' not in html


def test_migration_0060_reprend_l_ancienne_echelle(app, db, sample_users):
    uid = sample_users['salarie_id']
    for titre, prio in (('H', 'haute'), ('N', 'normale'), ('B', 'basse')):
        db.execute(
            "INSERT INTO planif_taches (user_id, type, titre, duree_min, priorite, priorite_num, statut) "
            "VALUES (?, 'tache', ?, 30, ?, NULL, 'a_faire')", (uid, titre, prio))
    db.commit()

    import importlib.util
    import os
    chemin = os.path.join(os.path.dirname(__file__), '..', 'migrations',
                          '0060_priorite_numerique_planificateur.py')
    spec = importlib.util.spec_from_file_location('migration_0060_test', chemin)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.upgrade(db)

    rows = {r['titre']: r['priorite_num'] for r in db.execute(
        "SELECT titre, priorite_num FROM planif_taches WHERE user_id = ?", (uid,))}
    assert rows == {'H': 1, 'N': 0, 'B': -1}
