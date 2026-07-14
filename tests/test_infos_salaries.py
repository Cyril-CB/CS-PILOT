"""
Fiche salarié (infos_salaries) : édition de la pesée et des points de compétence.

Les points de compétence peuvent comporter des décimales (ex. 4,25) : la
saisie ne doit plus être bloquée à un entier ni tronquée à l'enregistrement.
"""


def test_competence_accepte_les_decimales(admin_client, db, sample_users):
    uid = sample_users['salarie_id']
    admin_client.post('/infos_salaries/pesee', data={
        'user_id': uid, 'pesee': '100', 'competence': '4.25', 'maintien': '0',
    }, follow_redirects=True)
    row = db.execute("SELECT competence FROM users WHERE id = ?", (uid,)).fetchone()
    assert row['competence'] == 4.25


def test_competence_entiere_reste_valide(admin_client, db, sample_users):
    uid = sample_users['salarie_id']
    admin_client.post('/infos_salaries/pesee', data={
        'user_id': uid, 'pesee': '100', 'competence': '6', 'maintien': '0',
    }, follow_redirects=True)
    row = db.execute("SELECT competence FROM users WHERE id = ?", (uid,)).fetchone()
    assert row['competence'] == 6


def test_competence_vide_remet_a_null(admin_client, db, sample_users):
    uid = sample_users['salarie_id']
    db.execute("UPDATE users SET competence = 5 WHERE id = ?", (uid,))
    db.commit()
    admin_client.post('/infos_salaries/pesee', data={
        'user_id': uid, 'pesee': '100', 'competence': '', 'maintien': '0',
    }, follow_redirects=True)
    row = db.execute("SELECT competence FROM users WHERE id = ?", (uid,)).fetchone()
    assert row['competence'] is None


# ── Modification de la date de fin d'un contrat (sans supprimer/re-saisir) ──
#
# Cas d'usage : CDD sans terme précis saisi avec sa durée minimale comme date
# de fin — à prolonger quand le remplacement se poursuit, sans perdre le PDF
# ni l'historique. Date vide = contrat remis « en cours ».

def _creer_cdd(db, user_id, date_debut='2026-01-01', date_fin='2026-06-30'):
    cur = db.execute(
        "INSERT INTO contrats (user_id, type_contrat, date_debut, date_fin) "
        "VALUES (?, 'CDD', ?, ?)", (user_id, date_debut, date_fin))
    db.commit()
    return cur.lastrowid


def test_modifier_date_fin_prolonge_le_cdd(admin_client, db, sample_users):
    uid = sample_users['salarie_id']
    cid = _creer_cdd(db, uid)
    r = admin_client.post(f'/infos_salaries/contrat/{cid}/date_fin',
                          data={'date_fin': '2026-09-15'}, follow_redirects=True)
    assert 'mise a jour' in r.get_data(as_text=True)
    row = db.execute("SELECT date_fin FROM contrats WHERE id = ?", (cid,)).fetchone()
    assert row['date_fin'] == '2026-09-15'


def test_date_fin_vide_remet_le_contrat_en_cours(admin_client, db, sample_users):
    uid = sample_users['salarie_id']
    cid = _creer_cdd(db, uid)
    r = admin_client.post(f'/infos_salaries/contrat/{cid}/date_fin',
                          data={'date_fin': ''}, follow_redirects=True)
    assert 'en cours' in r.get_data(as_text=True)
    row = db.execute("SELECT date_fin FROM contrats WHERE id = ?", (cid,)).fetchone()
    assert row['date_fin'] is None


def test_date_fin_avant_le_debut_refusee(admin_client, db, sample_users):
    uid = sample_users['salarie_id']
    cid = _creer_cdd(db, uid)
    r = admin_client.post(f'/infos_salaries/contrat/{cid}/date_fin',
                          data={'date_fin': '2025-12-01'}, follow_redirects=True)
    assert 'anterieure a la date de debut' in r.get_data(as_text=True)
    row = db.execute("SELECT date_fin FROM contrats WHERE id = ?", (cid,)).fetchone()
    assert row['date_fin'] == '2026-06-30'    # inchangée


def test_modification_date_fin_refusee_au_salarie(client, db, sample_users):
    from tests.conftest import _login
    uid = sample_users['salarie_id']
    cid = _creer_cdd(db, uid)
    _login(client, 'salarie_test', 'sal123')
    client.post(f'/infos_salaries/contrat/{cid}/date_fin',
                data={'date_fin': '2026-09-15'}, follow_redirects=True)
    row = db.execute("SELECT date_fin FROM contrats WHERE id = ?", (cid,)).fetchone()
    assert row['date_fin'] == '2026-06-30'    # inchangée


def test_modification_date_fin_journalisee(admin_client, db, sample_users):
    """La prolongation laisse une trace d'audit (ancienne -> nouvelle date)."""
    uid = sample_users['salarie_id']
    cid = _creer_cdd(db, uid)
    admin_client.post(f'/infos_salaries/contrat/{cid}/date_fin',
                      data={'date_fin': '2026-09-15'}, follow_redirects=True)
    log = db.execute(
        "SELECT details FROM journal_actions WHERE action = 'modif_date_fin_contrat' "
        "ORDER BY id DESC LIMIT 1").fetchone()
    assert log is not None
    assert '2026-06-30 -> 2026-09-15' in log['details']


def test_fiche_affiche_le_formulaire_date_fin(admin_client, db, sample_users):
    uid = sample_users['salarie_id']
    cid = _creer_cdd(db, uid)
    html = admin_client.get(f'/infos_salaries?user_id={uid}').get_data(as_text=True)
    assert f'df-form-{cid}' in html
    assert f'/infos_salaries/contrat/{cid}/date_fin' in html


def test_date_fin_mal_formee_refusee(admin_client, db, sample_users):
    """Une valeur non ISO (ex. « zzz », qui trie après toute date) est refusée
    avant enregistrement — les fenêtres de contrat comparent des chaînes
    (revue Codex)."""
    uid = sample_users['salarie_id']
    cid = _creer_cdd(db, uid)
    for mauvaise in ('zzz', '15/09/2026', '2026-13-45'):
        r = admin_client.post(f'/infos_salaries/contrat/{cid}/date_fin',
                              data={'date_fin': mauvaise}, follow_redirects=True)
        assert 'Date de fin invalide' in r.get_data(as_text=True), mauvaise
    row = db.execute("SELECT date_fin FROM contrats WHERE id = ?", (cid,)).fetchone()
    assert row['date_fin'] == '2026-06-30'    # inchangée


def test_ajout_contrat_dates_mal_formees_refusees(admin_client, db, sample_users):
    """Même garde sur l'ajout de contrat (dates début/fin)."""
    uid = sample_users['salarie_id']
    r = admin_client.post('/infos_salaries/contrat', data={
        'user_id': uid, 'type_contrat': 'CDD',
        'date_debut': 'zzz', 'date_fin': ''}, follow_redirects=True)
    assert 'Date invalide' in r.get_data(as_text=True)
    r = admin_client.post('/infos_salaries/contrat', data={
        'user_id': uid, 'type_contrat': 'CDD',
        'date_debut': '2026-01-01', 'date_fin': '31/12/2026'}, follow_redirects=True)
    assert 'Date invalide' in r.get_data(as_text=True)
    nb = db.execute("SELECT COUNT(*) AS nb FROM contrats WHERE user_id = ?", (uid,)).fetchone()
    assert nb['nb'] == 0    # rien enregistré
