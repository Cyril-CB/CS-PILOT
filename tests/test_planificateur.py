"""
Tests du module Planificateur de taches (Time Blocking).

Couvre :
- le moteur d'optimisation pur (planificateur_engine) : horaires, evenements
  fixes, decoupage, equilibrage, echeances, recurrences, micro-pauses ;
- les routes du blueprint : controle d'acces (comptable uniquement),
  creation / replanification / suivi des taches, confidentialite.
"""
from datetime import date, timedelta

import pytest

import planificateur_engine as moteur


# ──────────────────────────────────────────────────────────────────────────
# Moteur d'optimisation (logique pure)
# ──────────────────────────────────────────────────────────────────────────

def _horaires_standard(intervalles=((540, 750), (810, 1050)), jours=(0, 1, 2, 3, 4)):
    """Horaires lun-ven 09:00-12:30 / 13:30-17:30, indexes par date.

    Le moteur attend desormais des horaires par date (le planning peut varier
    selon la periode / l'alternance). On couvre un large horizon : le moteur ne
    lit que les dates de [date_debut, date_fin], les dates en trop sont ignorees.
    """
    h = {}
    d = date.today() - timedelta(days=1)
    fin = date.today() + timedelta(days=120)
    while d <= fin:
        if d.weekday() in jours:
            h[d.isoformat()] = [tuple(iv) for iv in intervalles]
        d += timedelta(days=1)
    return h


def _lundi_prochain():
    """Retourne le prochain lundi (horizon deterministe, jours ouvres)."""
    d = date.today()
    while d.weekday() != 0:
        d += timedelta(days=1)
    return d


def test_to_min_et_hhmm():
    assert moteur._to_min('09:30') == 570
    assert moteur._to_min('') is None
    assert moteur._to_hhmm(570) == '09:30'


def test_soustraire_creneau():
    # Retirer 10h-11h de 9h-12h30 -> [9h-10h, 11h-12h30]
    res = moteur._soustraire([(540, 750)], [(600, 660)])
    assert res == [(540, 600), (660, 750)]


def test_engine_respecte_horaires():
    """Toutes les minutes placees tombent dans les horaires de travail."""
    lundi = _lundi_prochain()
    taches = [{'id': 1, 'titre': 'T', 'duree_min': 120, 'deadline': None,
               'priorite': 'normale', 'preference': 'aucune', 'secable': True,
               'duree_min_bloc': 30}]
    res = moteur.planifier(taches, {}, _horaires_standard(), lundi, lundi + timedelta(days=6))
    assert res['blocs']
    for b in res['blocs']:
        deb, fin = moteur._to_min(b['heure_debut']), moteur._to_min(b['heure_fin'])
        dans_matin = 540 <= deb and fin <= 750
        dans_aprem = 810 <= deb and fin <= 1050
        assert dans_matin or dans_aprem, f"bloc hors horaires : {b}"


def test_engine_evenement_fixe_non_chevauche():
    """Aucun bloc de tache ne chevauche un creneau occupe."""
    lundi = _lundi_prochain()
    occ = {lundi.isoformat(): [(600, 660)]}  # 10h-11h occupe
    taches = [{'id': 1, 'titre': 'T', 'duree_min': 300, 'deadline': None,
               'priorite': 'normale', 'preference': 'aucune', 'secable': True,
               'duree_min_bloc': 30}]
    res = moteur.planifier(taches, occ, _horaires_standard(), lundi, lundi + timedelta(days=6))
    for b in res['blocs']:
        if b['date'] != lundi.isoformat():
            continue
        deb, fin = moteur._to_min(b['heure_debut']), moteur._to_min(b['heure_fin'])
        assert fin <= 600 or deb >= 660, f"chevauche l'evenement fixe : {b}"


def test_engine_non_secable_bloc_unique():
    """Une tache non secable est placee en un seul bloc contigu."""
    lundi = _lundi_prochain()
    taches = [{'id': 7, 'titre': 'Appel', 'duree_min': 90, 'deadline': None,
               'priorite': 'normale', 'preference': 'aucune', 'secable': False,
               'duree_min_bloc': 30}]
    res = moteur.planifier(taches, {}, _horaires_standard(), lundi, lundi + timedelta(days=6))
    blocs = [b for b in res['blocs'] if b['tache_id'] == 7]
    assert len(blocs) == 1
    assert blocs[0]['duree_min'] == 90


def test_engine_decoupe_longue_mission_sur_plusieurs_jours():
    """Une longue mission secable est repartie sur plusieurs jours."""
    lundi = _lundi_prochain()
    taches = [{'id': 2, 'titre': 'Gros dossier', 'duree_min': 360, 'deadline': None,
               'priorite': 'normale', 'preference': 'aucune', 'secable': True,
               'duree_min_bloc': 60}]
    res = moteur.planifier(taches, {}, _horaires_standard(), lundi, lundi + timedelta(days=13))
    jours = {b['date'] for b in res['blocs']}
    assert len(jours) >= 2, "la mission de 6h devrait etre etalee sur plusieurs jours"
    assert sum(b['duree_min'] for b in res['blocs']) == 360
    # Pas de bloc minuscule (< duree_min_bloc) en dehors d'un eventuel reliquat.
    assert all(b['duree_min'] >= 5 for b in res['blocs'])


def test_engine_echeance_prioritaire():
    """La tache avec l'echeance la plus proche est planifiee en premier."""
    lundi = _lundi_prochain()
    taches = [
        {'id': 1, 'titre': 'Lointaine', 'duree_min': 120, 'deadline': (lundi + timedelta(days=12)).isoformat(),
         'priorite': 'normale', 'preference': 'aucune', 'secable': False, 'duree_min_bloc': 30},
        {'id': 2, 'titre': 'Urgente', 'duree_min': 120, 'deadline': (lundi + timedelta(days=1)).isoformat(),
         'priorite': 'normale', 'preference': 'aucune', 'secable': False, 'duree_min_bloc': 30},
    ]
    res = moteur.planifier(taches, {}, _horaires_standard(), lundi, lundi + timedelta(days=13))
    premier = {b['tache_id']: b['date'] for b in res['blocs']}
    assert premier[2] <= premier[1], "la tache urgente doit etre placee au plus tot"


def test_engine_recurrente_placee_en_dernier():
    """Les taches recurrentes remplissent l'espace restant (placees apres)."""
    lundi = _lundi_prochain()
    taches = [
        {'id': 1, 'titre': 'Normale', 'duree_min': 120, 'deadline': None,
         'priorite': 'haute', 'preference': 'aucune', 'secable': True, 'duree_min_bloc': 60},
        {'id': 2, 'titre': 'Recurrente', 'duree_min': 30, 'deadline': None,
         'priorite': 'haute', 'preference': 'aucune', 'secable': False, 'duree_min_bloc': 30,
         'est_recurrente': True},
    ]
    res = moteur.planifier(taches, {}, _horaires_standard(), lundi, lundi + timedelta(days=6))
    debut_normale = min(b['heure_debut'] for b in res['blocs'] if b['tache_id'] == 1
                        and b['date'] == lundi.isoformat())
    rec = [b for b in res['blocs'] if b['tache_id'] == 2 and b['date'] == lundi.isoformat()]
    # La recurrente du lundi ne prend pas le tout premier creneau (reserve a la normale).
    if rec:
        assert rec[0]['heure_debut'] >= debut_normale


def test_engine_micro_pauses_journee_chargee():
    """Sur une journee pleine, des respirations separent les blocs successifs."""
    lundi = _lundi_prochain()
    # 300 min secables, blocs de 60 -> doivent etre separes par des pauses.
    taches = [{'id': 1, 'titre': 'T', 'duree_min': 300, 'deadline': lundi.isoformat(),
               'priorite': 'haute', 'preference': 'aucune', 'secable': True, 'duree_min_bloc': 60}]
    res = moteur.planifier(taches, {}, _horaires_standard(), lundi, lundi)
    blocs = sorted((b for b in res['blocs']), key=lambda b: b['heure_debut'])
    # Au moins deux blocs consecutifs dans le meme segment avec un trou entre eux.
    trouve_pause = False
    for i in range(1, len(blocs)):
        fin_prec = moteur._to_min(blocs[i - 1]['heure_fin'])
        deb = moteur._to_min(blocs[i]['heure_debut'])
        if 0 < deb - fin_prec <= 20:  # un trou de respiration (pas la pause dejeuner)
            trouve_pause = True
    assert trouve_pause, "des micro-pauses devraient separer les blocs d'une journee chargee"


def test_engine_capacite_insuffisante():
    """Une tache trop grosse pour l'horizon est signalee non planifiee."""
    lundi = _lundi_prochain()
    taches = [{'id': 1, 'titre': 'Enorme', 'duree_min': 600, 'deadline': lundi.isoformat(),
               'priorite': 'normale', 'preference': 'aucune', 'secable': True, 'duree_min_bloc': 30}]
    # Horizon = un seul jour (capacite ~7h = 420 min < 600).
    res = moteur.planifier(taches, {}, _horaires_standard(), lundi, lundi)
    assert res['non_planifie'], "le reste non placé doit etre signale"


def test_engine_preference_matin():
    """Une tache avec preference matin est placee le matin si possible."""
    lundi = _lundi_prochain()
    taches = [{'id': 1, 'titre': 'Matinale', 'duree_min': 60, 'deadline': None,
               'priorite': 'normale', 'preference': 'matin', 'secable': False, 'duree_min_bloc': 30}]
    res = moteur.planifier(taches, {}, _horaires_standard(), lundi, lundi + timedelta(days=6))
    b = res['blocs'][0]
    assert moteur._to_min(b['heure_debut']) < 720, "devrait etre place le matin"


def test_niveau_urgence():
    ref = date(2026, 6, 30)
    assert moteur.niveau_urgence(None, ref) == 'sans_echeance'
    assert moteur.niveau_urgence('2026-06-29', ref) == 'retard'
    assert moteur.niveau_urgence('2026-06-30', ref) == 'urgent'
    assert moteur.niveau_urgence('2026-07-02', ref) == 'proche'
    assert moteur.niveau_urgence('2026-07-20', ref) == 'a_venir'
    assert moteur.niveau_urgence('2026-07-20', ref, statut='fait') == 'fait'


# ──────────────────────────────────────────────────────────────────────────
# Routes du blueprint
# ──────────────────────────────────────────────────────────────────────────

def test_acces_comptable_ok(comptable_client):
    resp = comptable_client.get('/planificateur')
    assert resp.status_code == 200
    assert 'Planificateur' in resp.get_data(as_text=True)


def test_acces_salarie_refuse(auth_client):
    resp = auth_client.get('/planificateur', follow_redirects=False)
    assert resp.status_code == 302  # redirige vers le dashboard


def test_acces_directeur_refuse(admin_client):
    resp = admin_client.get('/planificateur', follow_redirects=False)
    assert resp.status_code == 302


def test_api_refuse_non_comptable(auth_client):
    resp = auth_client.post('/planificateur/api/tache', json={'titre': 'X', 'duree_min': 30})
    assert resp.status_code == 403


def test_creer_tache_genere_des_blocs(comptable_client):
    demain = (date.today() + timedelta(days=3)).isoformat()
    resp = comptable_client.post('/planificateur/api/tache', json={
        'type': 'tache', 'titre': 'Cloture comptable', 'duree_min': 120,
        'deadline': demain, 'priorite': 'haute', 'preference': 'aucune',
        'secable': 1, 'duree_min_bloc': 30,
    })
    assert resp.status_code == 200
    assert resp.get_json()['ok'] is True

    # Les blocs doivent etre crees sur l'horizon.
    fin = (date.today() + timedelta(days=14)).isoformat()
    blocs = comptable_client.get(f'/planificateur/api/blocs?debut={date.today().isoformat()}&fin={fin}')
    data = blocs.get_json()
    assert data['ok'] is True
    total = sum(b['duree_min'] for b in data['blocs'])
    assert total == 120
    assert all(b['titre'] == 'Cloture comptable' for b in data['blocs'])


def test_creer_evenement_fixe_bloc_verrouille(comptable_client, db):
    jour = (date.today() + timedelta(days=2)).isoformat()
    resp = comptable_client.post('/planificateur/api/tache', json={
        'type': 'evenement', 'titre': 'Reunion equipe', 'date_fixe': jour,
        'heure_debut': '10:00', 'heure_fin': '11:00',
    })
    assert resp.status_code == 200
    row = db.execute(
        "SELECT b.verrouille, b.duree_min FROM planif_blocs b "
        "JOIN planif_taches t ON b.tache_id = t.id WHERE t.titre = 'Reunion equipe'"
    ).fetchone()
    assert row is not None
    assert row['verrouille'] == 1
    assert row['duree_min'] == 60


def test_evenement_fixe_repousse_les_taches(comptable_client):
    """Une tache ne doit pas etre planifiee sur un evenement fixe."""
    jour = (date.today() + timedelta(days=1)).isoformat()
    comptable_client.post('/planificateur/api/tache', json={
        'type': 'evenement', 'titre': 'RDV', 'date_fixe': jour,
        'heure_debut': '09:00', 'heure_fin': '17:00',  # journee entiere occupee
    })
    comptable_client.post('/planificateur/api/tache', json={
        'type': 'tache', 'titre': 'Tache jour', 'duree_min': 60,
        'deadline': None, 'secable': 1, 'duree_min_bloc': 30,
    })
    blocs = comptable_client.get(f'/planificateur/api/blocs?debut={jour}&fin={jour}').get_json()['blocs']
    taches_ce_jour = [b for b in blocs if b['type'] == 'tache']
    assert taches_ce_jour == [], "aucune tache ne doit etre placee sur la journee bloquee"


def test_marquer_bloc_fait(comptable_client, db):
    comptable_client.post('/planificateur/api/tache', json={
        'type': 'tache', 'titre': 'A faire', 'duree_min': 60, 'secable': 0, 'duree_min_bloc': 60,
    })
    bloc = db.execute("SELECT id FROM planif_blocs LIMIT 1").fetchone()
    resp = comptable_client.post(f'/planificateur/api/bloc/{bloc["id"]}/statut', json={'statut': 'fait'})
    assert resp.status_code == 200
    maj = db.execute("SELECT statut FROM planif_blocs WHERE id = ?", (bloc['id'],)).fetchone()
    assert maj['statut'] == 'fait'


def test_supprimer_tache(comptable_client, db):
    comptable_client.post('/planificateur/api/tache', json={
        'type': 'tache', 'titre': 'A supprimer', 'duree_min': 60, 'secable': 0, 'duree_min_bloc': 60,
    })
    tache = db.execute("SELECT id FROM planif_taches WHERE titre = 'A supprimer'").fetchone()
    resp = comptable_client.post(f'/planificateur/api/tache/{tache["id"]}/supprimer', json={})
    assert resp.status_code == 200
    assert db.execute("SELECT COUNT(*) AS n FROM planif_taches WHERE id = ?", (tache['id'],)).fetchone()['n'] == 0
    assert db.execute("SELECT COUNT(*) AS n FROM planif_blocs WHERE tache_id = ?", (tache['id'],)).fetchone()['n'] == 0


def _inserer_planning(db, user_id, matin=('08:00', '12:00'), aprem=(None, None)):
    """Cree un planning theorique simple (lun-ven) pour un utilisateur."""
    data = {'user_id': user_id, 'type_periode': 'periode_scolaire',
            'date_debut_validite': '2000-01-01', 'type_alternance': 'fixe'}
    for jour in ('lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi'):
        data[f'{jour}_matin_debut'] = matin[0]
        data[f'{jour}_matin_fin'] = matin[1]
        data[f'{jour}_aprem_debut'] = aprem[0]
        data[f'{jour}_aprem_fin'] = aprem[1]
    cols = ', '.join(data.keys())
    ph = ', '.join(['?'] * len(data))
    db.execute(f"INSERT INTO planning_theorique ({cols}) VALUES ({ph})", list(data.values()))
    db.commit()


def test_horaires_issus_du_planning(comptable_client, db, sample_users):
    """Le planificateur respecte le planning theorique (Mon planning), sans ressaisie."""
    # Planning : uniquement le matin 08:00-12:00 (pas d'apres-midi).
    _inserer_planning(db, sample_users['comptable_id'], matin=('08:00', '12:00'))

    comptable_client.post('/planificateur/api/tache', json={
        'type': 'tache', 'titre': 'Tache matin', 'duree_min': 180,
        'secable': 1, 'duree_min_bloc': 30,
    })
    fin = (date.today() + timedelta(days=20)).isoformat()
    blocs = comptable_client.get(
        f'/planificateur/api/blocs?debut={date.today().isoformat()}&fin={fin}'
    ).get_json()['blocs']
    assert blocs, "des blocs devraient etre planifies"
    for b in blocs:
        deb, f = moteur._to_min(b['heure_debut']), moteur._to_min(b['heure_fin'])
        assert 480 <= deb and f <= 720, f"hors planning (matin 08:00-12:00) : {b}"


def test_api_blocs_retourne_horaires_du_planning(comptable_client, db, sample_users):
    """L'API expose les horaires de travail (pour les plages du calendrier)."""
    _inserer_planning(db, sample_users['comptable_id'],
                      matin=('09:00', '12:00'), aprem=('14:00', '17:00'))
    # Trouver un lundi a venir (jour ouvre garanti).
    d = date.today()
    while d.weekday() != 0:
        d += timedelta(days=1)
    data = comptable_client.get(
        f'/planificateur/api/blocs?debut={d.isoformat()}&fin={d.isoformat()}'
    ).get_json()
    assert 'horaires' in data
    assert data['horaires'].get(d.isoformat()) == [[540, 720], [840, 1020]]


def test_horaires_defaut_sans_planning(comptable_client, sample_users):
    """Sans planning, des horaires par defaut (9h-12h30 / 13h30-17h30) s'appliquent."""
    comptable_client.post('/planificateur/api/tache', json={
        'type': 'tache', 'titre': 'Tache defaut', 'duree_min': 60,
        'secable': 0, 'duree_min_bloc': 60,
    })
    fin = (date.today() + timedelta(days=20)).isoformat()
    blocs = comptable_client.get(
        f'/planificateur/api/blocs?debut={date.today().isoformat()}&fin={fin}'
    ).get_json()['blocs']
    assert blocs
    for b in blocs:
        deb, f = moteur._to_min(b['heure_debut']), moteur._to_min(b['heure_fin'])
        assert 540 <= deb and f <= 1050, f"hors horaires par defaut : {b}"


def test_recurrence_cree_occurrences(comptable_client, db, sample_users):
    debut = date.today().isoformat()
    resp = comptable_client.post('/planificateur/api/recurrence', json={
        'titre': 'Point quotidien', 'frequence': 'quotidien', 'duree_min': 30,
        'priorite': 'normale', 'preference': 'aucune', 'date_debut': debut,
    })
    assert resp.status_code == 200
    occ = db.execute(
        "SELECT COUNT(*) AS n FROM planif_taches WHERE user_id = ? AND recurrence_id IS NOT NULL",
        (sample_users['comptable_id'],)
    ).fetchone()
    assert occ['n'] > 0, "des occurrences quotidiennes doivent etre generees"


def test_replanifier_endpoint(comptable_client):
    comptable_client.post('/planificateur/api/tache', json={
        'type': 'tache', 'titre': 'T', 'duree_min': 60, 'secable': 0, 'duree_min_bloc': 60,
    })
    resp = comptable_client.post('/planificateur/api/replanifier', json={})
    assert resp.status_code == 200
    assert resp.get_json()['ok'] is True


def test_confidentialite_blocs_par_utilisateur(comptable_client, db, sample_users):
    """Un utilisateur ne voit jamais les blocs d'un autre (planning prive)."""
    # Inserer une tache + bloc pour le directeur directement en base.
    jour = (date.today() + timedelta(days=1)).isoformat()
    cur = db.execute(
        "INSERT INTO planif_taches (user_id, type, titre, duree_min, statut) "
        "VALUES (?, 'tache', 'Secret direction', 60, 'a_faire')",
        (sample_users['directeur_id'],)
    )
    db.execute(
        "INSERT INTO planif_blocs (tache_id, user_id, date, heure_debut, heure_fin, duree_min) "
        "VALUES (?, ?, ?, '09:00', '10:00', 60)",
        (cur.lastrowid, sample_users['directeur_id'], jour)
    )
    db.commit()

    blocs = comptable_client.get(f'/planificateur/api/blocs?debut={jour}&fin={jour}').get_json()['blocs']
    assert all(b['titre'] != 'Secret direction' for b in blocs)


def test_menu_lien_visible_comptable(comptable_client):
    resp = comptable_client.get('/dashboard_comptable')
    html = resp.get_data(as_text=True)
    assert '/planificateur' in html
