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


def test_engine_repartition_cap_taches_substantielles():
    """Cap souple de 3 taches >= 1h par jour, qui monte a 4 quand tout est plein."""
    from collections import Counter
    lundi = _lundi_prochain()
    # 10 taches d'1h a caser sur 3 jours ouvres (echeance serree).
    deadline = (lundi + timedelta(days=2)).isoformat()
    taches = [{'id': i, 'titre': f'T{i}', 'duree_min': 60, 'deadline': deadline,
               'priorite': 'normale', 'preference': 'aucune', 'secable': False,
               'duree_min_bloc': 60} for i in range(1, 11)]
    res = moteur.planifier(taches, {}, _horaires_standard(), lundi, lundi + timedelta(days=2))
    par_jour = Counter(b['date'] for b in res['blocs'])
    # 3 jours utilises, remplis a 3 puis un seul monte a 4 (10 = 4 + 3 + 3).
    assert len(par_jour) == 3
    assert sorted(par_jour.values()) == [3, 3, 4]


def test_engine_repartition_etale_sans_echeance():
    """Sans echeance, les taches substantielles s'etalent (pas de regroupement)."""
    from collections import Counter
    lundi = _lundi_prochain()
    taches = [{'id': i, 'titre': f'T{i}', 'duree_min': 60, 'deadline': None,
               'priorite': 'normale', 'preference': 'aucune', 'secable': False,
               'duree_min_bloc': 60} for i in range(1, 6)]
    res = moteur.planifier(taches, {}, _horaires_standard(), lundi, lundi + timedelta(days=13))
    par_jour = Counter(b['date'] for b in res['blocs'])
    # 5 taches -> 5 jours distincts (1 par jour), aucun regroupement.
    assert len(par_jour) == 5
    assert max(par_jour.values()) == 1


def test_engine_longue_mission_ne_se_concentre_pas():
    """Une longue mission secable s'etale meme quand d'autres jours sont deja pris
    (la tache en cours doit se compter elle-meme dans la repartition)."""
    lundi = _lundi_prochain()
    deadline = (lundi + timedelta(days=2)).isoformat()  # Lun-Mar-Mer
    taches = [
        {'id': 1, 'titre': 'A', 'duree_min': 60, 'deadline': deadline, 'priorite': 'haute',
         'preference': 'aucune', 'secable': False, 'duree_min_bloc': 60},
        {'id': 2, 'titre': 'B', 'duree_min': 60, 'deadline': deadline, 'priorite': 'haute',
         'preference': 'aucune', 'secable': False, 'duree_min_bloc': 60},
        {'id': 3, 'titre': 'Mission', 'duree_min': 360, 'deadline': deadline, 'priorite': 'normale',
         'preference': 'aucune', 'secable': True, 'duree_min_bloc': 60},
    ]
    res = moteur.planifier(taches, {}, _horaires_standard(), lundi, lundi + timedelta(days=2))
    jours_mission = {b['date'] for b in res['blocs'] if b['tache_id'] == 3}
    assert len(jours_mission) == 3, \
        "la mission de 6h doit s'etaler sur les 3 jours, pas se concentrer sur un seul"


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


def test_engine_reporte_le_debordement_au_lendemain():
    """Quand plusieurs taches ont une echeance le meme jour deja sature, le
    debordement est REPORTE sur les jours suivants au lieu d'etre empile sur la
    journee ou laisse non planifie."""
    lundi = _lundi_prochain()
    # 8 taches d'1h non secables, toutes dues lundi : elles ne tiennent pas
    # toutes le lundi (micro-pauses + cap), le reste doit partir mar/mer.
    taches = [{'id': i, 'titre': f'T{i}', 'duree_min': 60, 'deadline': lundi.isoformat(),
               'priorite': 'normale', 'preference': 'aucune', 'secable': False,
               'duree_min_bloc': 60} for i in range(1, 9)]
    res = moteur.planifier(taches, {}, _horaires_standard(), lundi, lundi + timedelta(days=6))

    assert not res['non_planifie'], "le debordement doit etre reporte, pas laisse non planifie"
    # Les 8 taches sont placees, et pas toutes le meme jour.
    assert len({b['tache_id'] for b in res['blocs']}) == 8
    jours = sorted({b['date'] for b in res['blocs']})
    assert jours[0] == lundi.isoformat(), "le lundi (echeance) doit etre rempli en priorite"
    assert len(jours) >= 2, "les taches en trop doivent etre reportees sur les jours suivants"


def test_engine_blocs_dune_journee_ne_se_chevauchent_pas():
    """Deux blocs places le meme jour n'occupent jamais la meme minute (une tache
    courte suivie d'une autre ne doit pas se superposer)."""
    lundi = _lundi_prochain()
    # Beaucoup de taches courtes (10 min) le meme jour.
    taches = [{'id': i, 'titre': f'R{i}', 'duree_min': 10, 'deadline': None,
               'priorite': 'normale', 'preference': 'matin', 'secable': False,
               'duree_min_bloc': 10} for i in range(1, 13)]
    res = moteur.planifier(taches, {}, _horaires_standard(), lundi, lundi)
    for jour in {b['date'] for b in res['blocs']}:
        blocs = sorted((b for b in res['blocs'] if b['date'] == jour),
                       key=lambda b: moteur._to_min(b['heure_debut']))
        for i in range(1, len(blocs)):
            fin_prec = moteur._to_min(blocs[i - 1]['heure_fin'])
            deb = moteur._to_min(blocs[i]['heure_debut'])
            assert deb >= fin_prec, f"blocs superposes : {blocs[i-1]} / {blocs[i]}"


def test_engine_repartit_matin_et_apres_midi():
    """Sans preference, plusieurs taches d'une meme journee n'entassent pas tout
    le matin : l'apres-midi est aussi occupe (il n'est plus reserve a la seule
    preference 'apres_midi')."""
    lundi = _lundi_prochain()
    # Deux taches d'1h qui tiendraient toutes deux le matin : elles doivent
    # malgre tout se repartir entre matin et apres-midi.
    taches = [{'id': i, 'titre': f'T{i}', 'duree_min': 60, 'deadline': lundi.isoformat(),
               'priorite': 'normale', 'preference': 'aucune', 'secable': False,
               'duree_min_bloc': 60} for i in range(1, 3)]
    res = moteur.planifier(taches, {}, _horaires_standard(), lundi, lundi)
    heures = sorted(moteur._to_min(b['heure_debut']) for b in res['blocs'])
    assert len(heures) == 2
    assert any(h < 720 for h in heures), "une tache doit etre le matin"
    assert any(h >= 720 for h in heures), "une tache doit occuper l'apres-midi"


def test_engine_utilise_apres_midi_meme_etale_sur_plusieurs_jours():
    """Des taches etalees sur plusieurs jours ne doivent pas atterrir toutes le
    matin : l'equilibrage matin/apres-midi est global a l'horizon, pas
    seulement interne a une journee. (Depuis le tri par priorite pure, les
    echeances ne forcent plus « une tache par jour » : on verifie l'etalement
    ET le respect des echeances.)"""
    lundi = _lundi_prochain()
    taches = [{'id': i, 'titre': f'T{i}', 'duree_min': 60,
               'deadline': (lundi + timedelta(days=i)).isoformat(),
               'priorite': 'normale', 'preference': 'aucune', 'secable': False,
               'duree_min_bloc': 60} for i in range(1, 5)]
    res = moteur.planifier(taches, {}, _horaires_standard(), lundi, lundi + timedelta(days=6))

    par_jour = {}
    for b in res['blocs']:
        par_jour.setdefault(b['date'], []).append(b)
    assert len(par_jour) >= 3, "les taches doivent s'etaler sur plusieurs jours"
    # Chaque tache reste dans les delais.
    deadlines = {t['id']: t['deadline'] for t in taches}
    for b in res['blocs']:
        assert b['date'] <= deadlines[b['tache_id']]
    heures = [moteur._to_min(b['heure_debut']) for b in res['blocs']]
    assert any(h < 720 for h in heures), "au moins une tache le matin"
    assert any(h >= 720 for h in heures), \
        "au moins une tache l'apres-midi (elles ne doivent pas etre toutes le matin)"


def test_engine_gros_bloc_non_secable_garde_sa_place():
    """Une grosse tache non secable (3h) reste planifiable meme quand de petites
    taches sans preference partagent sa journee : elle est placee en premier pour
    que l'equilibrage matin/apres-midi ne fragmente pas ses creneaux au point de
    la rendre improuvable (regression du correctif d'equilibrage)."""
    lundi = _lundi_prochain()
    dl = lundi.isoformat()
    taches = [
        {'id': 1, 'titre': '1h A', 'duree_min': 60, 'deadline': dl, 'priorite': 'haute',
         'preference': 'aucune', 'secable': False, 'duree_min_bloc': 60},
        {'id': 2, 'titre': '1h B', 'duree_min': 60, 'deadline': dl, 'priorite': 'haute',
         'preference': 'aucune', 'secable': False, 'duree_min_bloc': 60},
        {'id': 3, 'titre': 'Mission 3h', 'duree_min': 180, 'deadline': dl, 'priorite': 'normale',
         'preference': 'aucune', 'secable': False, 'duree_min_bloc': 180},
    ]
    # Horizon = le jour meme : aucune des trois ne doit rester non planifiee.
    res = moteur.planifier(taches, {}, _horaires_standard(), lundi, lundi)
    assert not res['non_planifie'], "les 3 taches doivent tenir dans la journee (pas de report force)"
    bloc3 = [b for b in res['blocs'] if b['tache_id'] == 3]
    assert len(bloc3) == 1 and bloc3[0]['duree_min'] == 180, \
        "la mission de 3h doit occuper un unique creneau contigu"


def test_engine_preference_matin():
    """Une tache avec preference matin est placee le matin si possible."""
    lundi = _lundi_prochain()
    taches = [{'id': 1, 'titre': 'Matinale', 'duree_min': 60, 'deadline': None,
               'priorite': 'normale', 'preference': 'matin', 'secable': False, 'duree_min_bloc': 30}]
    res = moteur.planifier(taches, {}, _horaires_standard(), lundi, lundi + timedelta(days=6))
    b = res['blocs'][0]
    assert moteur._to_min(b['heure_debut']) < 720, "devrait etre place le matin"


def test_engine_ne_planifie_pas_dans_le_passe():
    """A 23h, plus rien ne se planifie le jour courant : tout part au lendemain."""
    lundi = _lundi_prochain()
    taches = [{'id': 1, 'titre': 'T', 'duree_min': 60, 'deadline': None,
               'priorite': 'normale', 'preference': 'aucune', 'secable': 1, 'duree_min_bloc': 30}]
    res = moteur.planifier(taches, {}, _horaires_standard(), lundi,
                           lundi + timedelta(days=6), minute_courante=23 * 60)
    assert res['blocs'], "la tache doit etre planifiee (les jours suivants)"
    assert all(b['date'] != lundi.isoformat() for b in res['blocs']), \
        "rien ne doit etre place le jour deja ecoule"


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


def test_acces_salarie_ok(auth_client):
    resp = auth_client.get('/planificateur')
    assert resp.status_code == 200


def test_acces_directeur_ok(admin_client):
    resp = admin_client.get('/planificateur')
    assert resp.status_code == 200


def test_acces_responsable_ok(resp_client):
    resp = resp_client.get('/planificateur')
    assert resp.status_code == 200


def test_acces_prestataire_refuse(client, db):
    """Le prestataire de paie (externe) n'a pas acces au planificateur."""
    from werkzeug.security import generate_password_hash
    db.execute(
        "INSERT INTO users (nom, prenom, login, password, profil) "
        "VALUES ('Presta', 'Paie', 'presta_test', ?, 'prestataire')",
        (generate_password_hash('presta123'),)
    )
    db.commit()
    client.post('/login', data={'login': 'presta_test', 'password': 'presta123'},
                follow_redirects=True)
    assert client.get('/planificateur', follow_redirects=False).status_code == 302
    assert client.post('/planificateur/api/tache',
                       json={'titre': 'X', 'duree_min': 30}).status_code == 403


def test_confidentialite_directeur_ne_voit_pas_les_autres(admin_client, db, sample_users):
    """Meme la direction ne voit que son propre planning."""
    jour = (date.today() + timedelta(days=1)).isoformat()
    cur = db.execute(
        "INSERT INTO planif_taches (user_id, type, titre, duree_min, statut) "
        "VALUES (?, 'tache', 'Prive comptable', 60, 'a_faire')",
        (sample_users['comptable_id'],)
    )
    db.execute(
        "INSERT INTO planif_blocs (tache_id, user_id, date, heure_debut, heure_fin, duree_min) "
        "VALUES (?, ?, ?, '09:00', '10:00', 60)",
        (cur.lastrowid, sample_users['comptable_id'], jour)
    )
    db.commit()
    blocs = admin_client.get(f'/planificateur/api/blocs?debut={jour}&fin={jour}').get_json()['blocs']
    assert all(b['titre'] != 'Prive comptable' for b in blocs)


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


def test_tache_non_placee_exposee_et_supprimable(comptable_client):
    """Une tache que le moteur ne peut pas caser (non secable, plus longue que
    le plus grand creneau) n'a aucun bloc mais reste exposee dans `non_placees`,
    donc modifiable / reportable / supprimable — plus de « tache fantome »."""
    demain = (date.today() + timedelta(days=5)).isoformat()
    r = comptable_client.post('/planificateur/api/tache', json={
        'type': 'tache', 'titre': 'Gros dossier', 'duree_min': 300,
        'deadline': demain, 'priorite': 'normale', 'preference': 'aucune',
        'secable': 0, 'duree_min_bloc': 30,
    })
    assert r.status_code == 200
    # Signalee comme non planifiee des la creation.
    assert any('Gros dossier' in (x.get('titre') or '')
               for x in r.get_json().get('non_planifie', []))

    debut = date.today().isoformat()
    fin = (date.today() + timedelta(days=14)).isoformat()
    data = comptable_client.get(
        f'/planificateur/api/blocs?debut={debut}&fin={fin}').get_json()
    # Aucun bloc sur le calendrier, mais exposee dans non_placees (avec son id).
    assert all(b['titre'] != 'Gros dossier' for b in data['blocs'])
    cibles = [t for t in data['non_placees'] if t['titre'] == 'Gros dossier']
    assert len(cibles) == 1
    tid = cibles[0]['id']

    # Supprimable directement depuis le bandeau (l'action pointe sur cet id).
    d = comptable_client.post(f'/planificateur/api/tache/{tid}/supprimer', json={})
    assert d.status_code == 200
    data2 = comptable_client.get(
        f'/planificateur/api/blocs?debut={debut}&fin={fin}').get_json()
    assert all(t['titre'] != 'Gros dossier' for t in data2['non_placees'])


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
        'heure_debut': '08:00', 'heure_fin': '19:00',  # couvre toute la journee de travail
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


def test_bloc_fait_tache_sous_planifiee_reste_ouverte(comptable_client, db, sample_users):
    """Cocher tous les blocs visibles d'une tache sous-planifiee ne la cloture pas.

    Une tache de 120 min dont un seul bloc de 30 min a pu etre place (capacite
    insuffisante) doit rester 'a_faire' apres que ce bloc soit marque fait :
    son reliquat (90 min) ne doit pas etre perdu.
    """
    uid = sample_users['comptable_id']
    jour = (date.today() + timedelta(days=1)).isoformat()
    cur = db.execute(
        "INSERT INTO planif_taches (user_id, type, titre, duree_min, statut) "
        "VALUES (?, 'tache', 'Sous-planifiee', 120, 'a_faire')", (uid,)
    )
    tache_id = cur.lastrowid
    bloc = db.execute(
        "INSERT INTO planif_blocs (tache_id, user_id, date, heure_debut, heure_fin, duree_min) "
        "VALUES (?, ?, ?, '09:00', '09:30', 30)", (tache_id, uid, jour)
    )
    db.commit()

    resp = comptable_client.post(f'/planificateur/api/bloc/{bloc.lastrowid}/statut', json={'statut': 'fait'})
    assert resp.status_code == 200
    statut = db.execute("SELECT statut FROM planif_taches WHERE id = ?", (tache_id,)).fetchone()['statut']
    assert statut == 'a_faire', "la tache ne doit pas etre cloturee tant que sa duree n'est pas couverte"


def test_terminer_partiel_libere_les_blocs_futurs(comptable_client, db, sample_users):
    """« Planifier la fin » libere les creneaux futurs (pas de double comptage)."""
    uid = sample_users['comptable_id']
    comptable_client.post('/planificateur/api/tache', json={
        'type': 'tache', 'titre': 'Mission', 'duree_min': 240,
        'secable': 1, 'duree_min_bloc': 60,
    })
    tache = db.execute("SELECT id FROM planif_taches WHERE titre = 'Mission'").fetchone()

    resp = comptable_client.post(
        f'/planificateur/api/tache/{tache["id"]}/terminer_partiel', json={'minutes_faites': 60}
    )
    assert resp.status_code == 200

    # La tache d'origine est cloturee et n'a plus de bloc non realise.
    assert db.execute("SELECT statut FROM planif_taches WHERE id = ?", (tache['id'],)).fetchone()['statut'] == 'fait'
    assert db.execute(
        "SELECT COUNT(*) AS n FROM planif_blocs WHERE tache_id = ? AND statut != 'fait'", (tache['id'],)
    ).fetchone()['n'] == 0

    # Une tache « suite » de 180 min est creee et planifiee.
    suite = db.execute("SELECT id, duree_min FROM planif_taches WHERE titre LIKE '%suite%'").fetchone()
    assert suite is not None and suite['duree_min'] == 180

    # Pas de double comptage : le total planifie correspond au reste (180 min).
    total = db.execute(
        "SELECT COALESCE(SUM(duree_min), 0) AS s FROM planif_blocs WHERE user_id = ?", (uid,)
    ).fetchone()['s']
    assert total == 180


def test_supprimer_bloc_evenement_refuse(comptable_client, db):
    """On ne peut pas supprimer le seul creneau d'un evenement fixe."""
    jour = (date.today() + timedelta(days=2)).isoformat()
    comptable_client.post('/planificateur/api/tache', json={
        'type': 'evenement', 'titre': 'RDV important', 'date_fixe': jour,
        'heure_debut': '10:00', 'heure_fin': '11:00',
    })
    bloc = db.execute(
        "SELECT b.id FROM planif_blocs b JOIN planif_taches t ON b.tache_id = t.id "
        "WHERE t.titre = 'RDV important'"
    ).fetchone()
    resp = comptable_client.post(f'/planificateur/api/bloc/{bloc["id"]}/supprimer', json={})
    assert resp.status_code == 400
    # Le creneau existe toujours (l'evenement continue de bloquer son horaire).
    assert db.execute("SELECT COUNT(*) AS n FROM planif_blocs WHERE id = ?", (bloc['id'],)).fetchone()['n'] == 1


def test_journee_terminee_reporte_au_lendemain(app, db, sample_users):
    """Quand la journee est finie (23h), une nouvelle tache part au lendemain
    et l'occurrence recurrente manquee n'est pas signalee comme anomalie."""
    from datetime import datetime
    from blueprints.planificateur import _replanifier

    uid = sample_users['comptable_id']
    # Choisir un lundi a venir, a 23h00.
    d = date.today() + timedelta(days=1)
    while d.weekday() != 0:
        d += timedelta(days=1)
    maintenant = datetime(d.year, d.month, d.day, 23, 0)
    lendemain = (d + timedelta(days=1)).isoformat()

    db.execute(
        "INSERT INTO planif_taches (user_id, type, titre, duree_min, priorite, "
        "preference, secable, duree_min_bloc, statut) "
        "VALUES (?, 'tache', 'Tache jour', 60, 'normale', 'aucune', 1, 30, 'a_faire')",
        (uid,)
    )
    db.execute(
        "INSERT INTO planif_recurrences (user_id, titre, duree_min, priorite, "
        "preference, secable, duree_min_bloc, frequence, date_debut, active) "
        "VALUES (?, 'lecture mails', 10, 'haute', 'aucune', 0, 10, 'quotidien', ?, 1)",
        (uid, d.isoformat())
    )
    db.commit()

    with app.app_context():
        non_planifie = _replanifier(db, uid, maintenant=maintenant)

    # Rien n'est planifie le jour deja termine.
    nb_jour = db.execute(
        "SELECT COUNT(*) AS n FROM planif_blocs WHERE user_id = ? AND date = ?",
        (uid, d.isoformat())
    ).fetchone()['n']
    assert nb_jour == 0, "aucun bloc ne doit etre place sur la journee terminee"

    # La tache normale est bien planifiee (au lendemain ou apres).
    bloc_tache = db.execute(
        "SELECT b.date FROM planif_blocs b JOIN planif_taches t ON b.tache_id = t.id "
        "WHERE t.titre = 'Tache jour'"
    ).fetchone()
    assert bloc_tache is not None and bloc_tache['date'] >= lendemain

    # L'occurrence recurrente manquee n'est pas remontee comme non planifiee.
    assert all(x.get('titre') != 'lecture mails' for x in non_planifie)


def test_horaires_defaut_direction(admin_client):
    """Sans planning, la direction (forfait jours) a 09:00-12:30 / 14:00-18:00."""
    admin_client.post('/planificateur/api/tache', json={
        'type': 'tache', 'titre': 'Tache dir', 'duree_min': 120,
        'preference': 'apres_midi', 'secable': 1, 'duree_min_bloc': 60,
    })
    fin = (date.today() + timedelta(days=20)).isoformat()
    horaires = admin_client.get(
        f'/planificateur/api/blocs?debut={date.today().isoformat()}&fin={fin}'
    ).get_json()['horaires']
    aprem = [iv for jour in horaires.values() for iv in jour if iv[0] >= 720]
    assert aprem, "il doit y avoir un creneau d'apres-midi"
    assert all(iv[0] == 840 and iv[1] == 1080 for iv in aprem), \
        "l'apres-midi de la direction doit etre 14:00-18:00"


def test_deplacer_bloc_le_verrouille(comptable_client, db):
    """Glisser un bloc le deplace et le verrouille ; la replanif ne le bouge plus."""
    comptable_client.post('/planificateur/api/tache', json={
        'type': 'tache', 'titre': 'A deplacer', 'duree_min': 60, 'secable': 0, 'duree_min_bloc': 60,
    })
    bloc = db.execute("SELECT id FROM planif_blocs LIMIT 1").fetchone()
    cible = (date.today() + timedelta(days=3)).isoformat()
    resp = comptable_client.post(f'/planificateur/api/bloc/{bloc["id"]}/deplacer',
                                 json={'date': cible, 'heure_debut': '15:00'})
    assert resp.status_code == 200
    maj = db.execute("SELECT date, heure_debut, heure_fin, verrouille FROM planif_blocs WHERE id = ?",
                     (bloc['id'],)).fetchone()
    assert maj['date'] == cible and maj['heure_debut'] == '15:00' and maj['heure_fin'] == '16:00'
    assert maj['verrouille'] == 1

    comptable_client.post('/planificateur/api/replanifier', json={})
    apres = db.execute("SELECT date, heure_debut, verrouille FROM planif_blocs WHERE id = ?",
                       (bloc['id'],)).fetchone()
    assert apres is not None
    assert apres['date'] == cible and apres['heure_debut'] == '15:00' and apres['verrouille'] == 1


def test_verrou_bloc_pas_de_double_comptage(comptable_client, db, sample_users):
    """Verrouiller un morceau d'une tache n'augmente pas le total planifie."""
    uid = sample_users['comptable_id']
    comptable_client.post('/planificateur/api/tache', json={
        'type': 'tache', 'titre': 'Mission', 'duree_min': 240, 'secable': 1, 'duree_min_bloc': 60,
    })
    bloc = db.execute("SELECT id FROM planif_blocs WHERE user_id = ? LIMIT 1", (uid,)).fetchone()
    comptable_client.post(f'/planificateur/api/bloc/{bloc["id"]}/verrou', json={'verrouille': 1})
    comptable_client.post('/planificateur/api/replanifier', json={})
    total = db.execute("SELECT COALESCE(SUM(duree_min),0) AS s FROM planif_blocs WHERE user_id = ?",
                       (uid,)).fetchone()['s']
    assert total == 240, "le total planifie doit rester egal a la duree de la tache"


def test_deverrouiller_bloc(comptable_client, db):
    """Déverrouiller rend le bloc à l'optimiseur (la tâche reste planifiée, non verrouillée)."""
    comptable_client.post('/planificateur/api/tache', json={
        'type': 'tache', 'titre': 'T', 'duree_min': 60, 'secable': 0, 'duree_min_bloc': 60,
    })
    bloc = db.execute("SELECT id, tache_id FROM planif_blocs LIMIT 1").fetchone()
    tache_id = bloc['tache_id']
    comptable_client.post(f'/planificateur/api/bloc/{bloc["id"]}/verrou', json={'verrouille': 1})
    assert db.execute("SELECT verrouille FROM planif_blocs WHERE id = ?",
                      (bloc['id'],)).fetchone()['verrouille'] == 1
    # Verrouiller n'est pas « faire » : la tache reste a faire.
    assert db.execute("SELECT statut FROM planif_taches WHERE id = ?",
                      (tache_id,)).fetchone()['statut'] == 'a_faire'

    # Deverrouiller : le bloc est rendu a l'optimiseur (re-planifie librement).
    comptable_client.post(f'/planificateur/api/bloc/{bloc["id"]}/verrou', json={'verrouille': 0})
    restants = db.execute(
        "SELECT COUNT(*) AS n FROM planif_blocs WHERE tache_id = ? AND verrouille = 1",
        (tache_id,)
    ).fetchone()['n']
    total = db.execute("SELECT COUNT(*) AS n FROM planif_blocs WHERE tache_id = ?",
                       (tache_id,)).fetchone()['n']
    assert restants == 0, "plus aucun bloc verrouille apres deverrouillage"
    assert total >= 1, "la tache reste planifiee"


def test_supprimer_bloc_tache_verrouille_autorise(comptable_client, db):
    """Un bloc de tache verrouille reste supprimable (contrairement a un evenement)."""
    comptable_client.post('/planificateur/api/tache', json={
        'type': 'tache', 'titre': 'T', 'duree_min': 60, 'secable': 0, 'duree_min_bloc': 60,
    })
    bloc = db.execute("SELECT id FROM planif_blocs LIMIT 1").fetchone()
    comptable_client.post(f'/planificateur/api/bloc/{bloc["id"]}/verrou', json={'verrouille': 1})
    resp = comptable_client.post(f'/planificateur/api/bloc/{bloc["id"]}/supprimer', json={})
    assert resp.status_code == 200
    assert db.execute("SELECT COUNT(*) AS n FROM planif_blocs WHERE id = ?",
                      (bloc['id'],)).fetchone()['n'] == 0


def test_bloc_verrouille_passe_non_compte(app, db, sample_users):
    """Un creneau verrouille dont le jour est passe (non realise) ne reduit pas
    le travail restant : il doit etre entierement replanifie, pas perdu."""
    from datetime import datetime
    from blueprints.planificateur import _replanifier

    uid = sample_users['comptable_id']
    # Aujourd'hui = un mardi a venir, 09:00 (journee en cours).
    d = date.today() + timedelta(days=1)
    while d.weekday() != 1:
        d += timedelta(days=1)
    maintenant = datetime(d.year, d.month, d.day, 9, 0)
    hier = (d - timedelta(days=1)).isoformat()

    cur = db.execute(
        "INSERT INTO planif_taches (user_id, type, titre, duree_min, secable, duree_min_bloc, statut) "
        "VALUES (?, 'tache', 'Mission', 120, 1, 60, 'a_faire')", (uid,)
    )
    tid = cur.lastrowid
    # Bloc verrouille de 60 min place HIER (rate, jamais marque fait).
    db.execute(
        "INSERT INTO planif_blocs (tache_id, user_id, date, heure_debut, heure_fin, duree_min, statut, verrouille) "
        "VALUES (?, ?, ?, '15:00', '16:00', 60, 'planifie', 1)", (tid, uid, hier)
    )
    db.commit()

    with app.app_context():
        _replanifier(db, uid, maintenant=maintenant)

    # Les 120 minutes doivent etre entierement planifiees dans le futur (le bloc
    # verrouille passe ne compte pas comme travail engage).
    futur = db.execute(
        "SELECT COALESCE(SUM(duree_min), 0) AS s FROM planif_blocs WHERE tache_id = ? AND date >= ?",
        (tid, d.isoformat())
    ).fetchone()['s']
    assert futur == 120, f"attendu 120 min planifiees dans le futur, obtenu {futur}"
    # La tache n'est pas marquee faite (rien n'a ete realise).
    assert db.execute("SELECT statut FROM planif_taches WHERE id = ?",
                      (tid,)).fetchone()['statut'] == 'a_faire'


def test_deplacer_bloc_dans_le_passe_refuse(comptable_client, db):
    """Le glisser-deposer refuse de deposer un creneau dans le passe."""
    comptable_client.post('/planificateur/api/tache', json={
        'type': 'tache', 'titre': 'T', 'duree_min': 60, 'secable': 0, 'duree_min_bloc': 60,
    })
    bloc = db.execute("SELECT id FROM planif_blocs LIMIT 1").fetchone()
    hier = (date.today() - timedelta(days=1)).isoformat()
    resp = comptable_client.post(f'/planificateur/api/bloc/{bloc["id"]}/deplacer',
                                 json={'date': hier, 'heure_debut': '10:00'})
    assert resp.status_code == 400


def test_menu_lien_visible_comptable(comptable_client):
    resp = comptable_client.get('/dashboard_comptable')
    html = resp.get_data(as_text=True)
    assert '/planificateur' in html


def test_menu_lien_visible_salarie(auth_client):
    html = auth_client.get('/dashboard').get_data(as_text=True)
    assert '/planificateur' in html


def test_engine_priorite_prime_sur_une_echeance_lointaine():
    """Une tache plus prioritaire SANS echeance passe avant une tache moins
    prioritaire dont l'echeance est lointaine (il reste le temps de la faire)."""
    lundi = _lundi_prochain()
    taches = [
        {'id': 1, 'titre': 'Echeance J+8', 'duree_min': 60,
         'deadline': (lundi + timedelta(days=8)).isoformat(), 'priorite_num': 0,
         'preference': 'aucune', 'secable': False, 'duree_min_bloc': 30},
        {'id': 2, 'titre': 'Prioritaire sans echeance', 'duree_min': 60,
         'deadline': None, 'priorite_num': 1,
         'preference': 'aucune', 'secable': False, 'duree_min_bloc': 30},
    ]
    res = moteur.planifier(taches, {}, _horaires_standard(), lundi, lundi + timedelta(days=8))

    premiers = {}
    for b in res['blocs']:
        cle = (b['date'], b['heure_debut'])
        if b['tache_id'] not in premiers or cle < premiers[b['tache_id']]:
            premiers[b['tache_id']] = cle
    assert premiers[2] < premiers[1], "la tache prioritaire doit etre placee avant"
    # Et l'echeance de la moins prioritaire reste respectee.
    deadline_1 = (lundi + timedelta(days=8)).isoformat()
    assert all(b['date'] <= deadline_1 for b in res['blocs'] if b['tache_id'] == 1)


def test_engine_echeance_rehausse_une_tache_hors_delai():
    """L'echeance sert d'ajustement : une tache moins prioritaire qui sortirait
    de son delai est rehaussee au-dessus de la moins urgente planifiee d'ici
    son echeance, puis replanifiee — et tient alors son echeance."""
    lundi = _lundi_prochain()
    # Horizon de 2 jours (450 min/jour, micro-pauses comprises). Le remplissage
    # prioritaire (720 min) sature lundi : sans rehaussement, la tache
    # d'echeance lundi partirait a mardi, hors delai.
    taches = [
        {'id': 1, 'titre': 'Remplissage prioritaire', 'duree_min': 720,
         'deadline': None, 'priorite_num': 5,
         'preference': 'aucune', 'secable': True, 'duree_min_bloc': 30},
        {'id': 2, 'titre': 'Echeance lundi', 'duree_min': 60,
         'deadline': lundi.isoformat(), 'priorite_num': 0,
         'preference': 'aucune', 'secable': False, 'duree_min_bloc': 30},
    ]
    res = moteur.planifier(taches, {}, _horaires_standard(), lundi, lundi + timedelta(days=1))

    blocs_2 = [b for b in res['blocs'] if b['tache_id'] == 2]
    assert blocs_2, "la tache a echeance doit etre placee"
    assert all(b['date'] == lundi.isoformat() for b in blocs_2), \
        "le rehaussement doit la ramener dans sa fenetre d'echeance"
    # Tout le reste tient aussi sur les deux jours.
    assert res['non_planifie'] == []
    # Le rehaussement est ephemere : les priorites stockees n'ont pas bouge.
    assert taches[0]['priorite_num'] == 5
    assert taches[1]['priorite_num'] == 0


def test_engine_surcapacite_reelle_reste_signalee():
    """Sans tache a deplacer dans la fenetre, le rehaussement n'insiste pas :
    la tache impossible reste signalee non planifiable (pas de boucle)."""
    lundi = _lundi_prochain()
    taches = [{'id': 1, 'titre': 'Impossible', 'duree_min': 600,
               'deadline': lundi.isoformat(), 'priorite_num': 0,
               'preference': 'aucune', 'secable': False, 'duree_min_bloc': 30}]
    res = moteur.planifier(taches, {}, _horaires_standard(), lundi, lundi + timedelta(days=1))
    assert res['blocs'] == []
    assert len(res['non_planifie']) == 1
    assert res['non_planifie'][0]['tache_id'] == 1


def test_engine_rehaussements_multiples_toutes_echeances_tenues():
    """Plusieurs taches en retard sur la MEME echeance : chacune peut devoir
    etre rehaussee plusieurs fois (elle depasse d'abord ses semblables avant
    ses vrais bloqueurs). Toutes les echeances tenables doivent etre tenues
    (revue Codex : la borne de passes ne doit pas s'epuiser avant)."""
    lundi = _lundi_prochain()
    taches = [
        # 6 taches tres prioritaires sans echeance : elles saturent lundi en
        # partie et peuvent glisser a mardi sans dommage.
        *[{'id': 10 + i, 'titre': f'Prioritaire {i}', 'duree_min': 60,
           'deadline': None, 'priorite_num': 5,
           'preference': 'aucune', 'secable': False, 'duree_min_bloc': 30}
          for i in range(1, 7)],
        # 4 taches modestes a echeance lundi : elles doivent toutes y tenir.
        *[{'id': i, 'titre': f'Echeance lundi {i}', 'duree_min': 60,
           'deadline': lundi.isoformat(), 'priorite_num': 0,
           'preference': 'aucune', 'secable': False, 'duree_min_bloc': 30}
          for i in range(1, 5)],
    ]
    res = moteur.planifier(taches, {}, _horaires_standard(), lundi, lundi + timedelta(days=1))

    assert res['non_planifie'] == []
    for b in res['blocs']:
        if b['tache_id'] <= 4:
            assert b['date'] == lundi.isoformat(), \
                f"echeance manquee pour la tache {b['tache_id']} : {b['date']}"
    # Les priorites stockees n'ont pas bouge (rehaussement ephemere).
    assert all(t['priorite_num'] in (0, 5) for t in taches)


def test_page_planificateur_bouton_rendez_vous(comptable_client):
    """Le bouton dédié « Rendez-vous » ouvre la modale directement sur
    l'onglet du même nom (créneau verrouillé automatiquement à la création,
    modifiable au clic ou à la souris comme les autres blocs)."""
    html = comptable_client.get('/planificateur').get_data(as_text=True)
    assert 'id="btnRdv"' in html
    assert 'ouvrirAjoutRdv' in html
    assert 'Ajouter un rendez-vous' in html
    assert '📌 Rendez-vous' in html
