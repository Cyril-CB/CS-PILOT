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


# ── Barrière inter-secteurs en ÉCRITURE (_est_salarie_visible) ─────────────
#
# La fiche salarié porte les données les plus sensibles de l'application
# (n° de sécurité sociale, adresse, date de naissance, pesée, contrats).
# Le pendant en LECTURE est couvert par tests/test_responsable_rh_paie_access.py ;
# ces tests verrouillent le refus côté écriture : un responsable ne doit rien
# pouvoir modifier sur un salarié hors de son équipe, et un salarié simple
# n'a aucun droit d'écriture (même sur sa propre fiche).

def _creer_salarie_hors_equipe(db, login='hors_equipe'):
    """Crée un salarié dans un autre secteur, non rattaché au responsable de test.

    Ni le secteur, ni `responsable_id` ne le relient à `resp_test` : il est donc
    hors du périmètre rendu par `_est_salarie_visible`.
    """
    from werkzeug.security import generate_password_hash

    cur = db.execute("INSERT INTO secteurs (nom, description) VALUES (?, ?)",
                     ('Secteur Hors Equipe', 'Secteur distinct pour les tests'))
    secteur_id = cur.lastrowid
    cur = db.execute(
        "INSERT INTO users (nom, prenom, login, password, profil, secteur_id, actif) "
        "VALUES (?, ?, ?, ?, 'salarie', ?, 1)",
        ('Externe', 'Zoe', login, generate_password_hash('hors123'), secteur_id))
    db.commit()
    return cur.lastrowid


def _creer_document(db, user_id, saisi_par):
    """Crée une pièce jointe de fiche salarié (aucun fichier réel sur le disque)."""
    cur = db.execute(
        "INSERT INTO documents_salaries "
        "(user_id, type_document, description, fichier_path, fichier_nom, saisi_par) "
        "VALUES (?, 'CARTE-VITALE', ?, ?, ?, ?)",
        (user_id, 'Piece de test', 'CARTE-VITALE_Externe_Zoe.pdf',
         'carte_vitale.pdf', saisi_par))
    db.commit()
    return cur.lastrowid


def test_responsable_ne_peut_pas_modifier_email_hors_equipe(resp_client, db, sample_users):
    uid = _creer_salarie_hors_equipe(db)
    db.execute("UPDATE users SET email = ? WHERE id = ?", ('avant@test.fr', uid))
    db.commit()
    r = resp_client.post('/infos_salaries/email',
                         data={'user_id': uid, 'email': 'detourne@test.fr'},
                         follow_redirects=True)
    assert 'Acces non autorise.' in r.get_data(as_text=True)
    row = db.execute("SELECT email FROM users WHERE id = ?", (uid,)).fetchone()
    assert row['email'] == 'avant@test.fr'    # inchangé


def test_responsable_ne_peut_pas_modifier_infos_personnelles_hors_equipe(resp_client, db, sample_users):
    """Adresse, date de naissance et n° de sécurité sociale d'un salarié d'un
    autre secteur restent inaccessibles en écriture."""
    uid = _creer_salarie_hors_equipe(db)
    db.execute("UPDATE users SET adresse = ?, date_naissance = ?, numero_secu = ? WHERE id = ?",
               ('1 rue des Tests', '1990-05-04', '290054412345678', uid))
    db.commit()
    r = resp_client.post('/infos_salaries/infos_personnelles', data={
        'user_id': uid, 'adresse': '2 rue Detournee',
        'date_naissance': '1980-01-01', 'numero_secu': '199999999999999',
    }, follow_redirects=True)
    assert 'Acces non autorise.' in r.get_data(as_text=True)
    row = db.execute(
        "SELECT adresse, date_naissance, numero_secu FROM users WHERE id = ?", (uid,)).fetchone()
    assert row['adresse'] == '1 rue des Tests'
    assert row['date_naissance'] == '1990-05-04'
    assert row['numero_secu'] == '290054412345678'


def test_responsable_ne_peut_pas_modifier_pesee_hors_equipe(resp_client, db, sample_users):
    uid = _creer_salarie_hors_equipe(db)
    db.execute("UPDATE users SET pesee = 100, competence = 4, maintien = 0 WHERE id = ?", (uid,))
    db.commit()
    r = resp_client.post('/infos_salaries/pesee', data={
        'user_id': uid, 'pesee': '250', 'competence': '9', 'maintien': '12',
    }, follow_redirects=True)
    assert 'Acces non autorise.' in r.get_data(as_text=True)
    row = db.execute("SELECT pesee, competence, maintien FROM users WHERE id = ?", (uid,)).fetchone()
    assert row['pesee'] == 100
    assert row['competence'] == 4
    assert row['maintien'] == 0


def test_responsable_ne_peut_pas_ajouter_contrat_hors_equipe(resp_client, db, sample_users):
    uid = _creer_salarie_hors_equipe(db)
    r = resp_client.post('/infos_salaries/contrat', data={
        'user_id': uid, 'type_contrat': 'CDI',
        'date_debut': '2026-01-01', 'date_fin': '',
    }, follow_redirects=True)
    assert 'Acces non autorise.' in r.get_data(as_text=True)
    nb = db.execute("SELECT COUNT(*) AS nb FROM contrats WHERE user_id = ?", (uid,)).fetchone()
    assert nb['nb'] == 0    # rien enregistré


def test_responsable_ne_peut_pas_modifier_date_fin_hors_equipe(resp_client, db, sample_users):
    uid = _creer_salarie_hors_equipe(db)
    cid = _creer_cdd(db, uid)
    r = resp_client.post(f'/infos_salaries/contrat/{cid}/date_fin',
                         data={'date_fin': '2027-12-31'}, follow_redirects=True)
    assert 'Acces non autorise.' in r.get_data(as_text=True)
    row = db.execute("SELECT date_fin FROM contrats WHERE id = ?", (cid,)).fetchone()
    assert row['date_fin'] == '2026-06-30'    # inchangée


def test_responsable_ne_peut_pas_supprimer_contrat_hors_equipe(resp_client, db, sample_users):
    uid = _creer_salarie_hors_equipe(db)
    cid = _creer_cdd(db, uid)
    r = resp_client.post(f'/infos_salaries/supprimer_contrat/{cid}', follow_redirects=True)
    assert 'Acces non autorise.' in r.get_data(as_text=True)
    assert db.execute("SELECT 1 FROM contrats WHERE id = ?", (cid,)).fetchone() is not None


def test_responsable_ne_peut_pas_supprimer_document_hors_equipe(resp_client, db, sample_users):
    uid = _creer_salarie_hors_equipe(db)
    did = _creer_document(db, uid, sample_users['directeur_id'])
    r = resp_client.post(f'/infos_salaries/supprimer_document/{did}', follow_redirects=True)
    assert 'Acces non autorise.' in r.get_data(as_text=True)
    assert db.execute("SELECT 1 FROM documents_salaries WHERE id = ?", (did,)).fetchone() is not None


def test_responsable_peut_modifier_un_salarie_de_son_equipe(resp_client, db, sample_users):
    """Contrôle positif : la barrière ne bloque pas l'équipe du responsable —
    sans quoi les refus ci-dessus seraient vrais pour une mauvaise raison."""
    uid = sample_users['salarie_id']
    resp_client.post('/infos_salaries/email',
                     data={'user_id': uid, 'email': 'jean.martin@test.fr'},
                     follow_redirects=True)
    row = db.execute("SELECT email FROM users WHERE id = ?", (uid,)).fetchone()
    assert row['email'] == 'jean.martin@test.fr'


def test_salarie_ne_peut_ecrire_sur_aucune_route_de_la_fiche(auth_client, db, sample_users):
    """Un salarié simple n'a aucun droit d'écriture sur la fiche salarié, même
    sur la sienne : `_peut_gerer()` ne couvre que comptable, directeur et
    responsable. Les 7 routes mutantes doivent toutes refuser sans effet."""
    uid = sample_users['salarie_id']
    cid = _creer_cdd(db, uid)
    did = _creer_document(db, uid, sample_users['directeur_id'])
    db.execute("UPDATE users SET email = ?, adresse = ?, pesee = 100 WHERE id = ?",
               ('avant@test.fr', '1 rue des Tests', uid))
    db.commit()

    routes = [
        ('/infos_salaries/email', {'user_id': uid, 'email': 'detourne@test.fr'}),
        ('/infos_salaries/infos_personnelles', {'user_id': uid, 'adresse': '2 rue Detournee'}),
        ('/infos_salaries/pesee', {'user_id': uid, 'pesee': '250', 'competence': '9', 'maintien': '0'}),
        ('/infos_salaries/contrat', {'user_id': uid, 'type_contrat': 'CDI', 'date_debut': '2026-02-01'}),
        (f'/infos_salaries/contrat/{cid}/date_fin', {'date_fin': '2027-12-31'}),
        (f'/infos_salaries/supprimer_contrat/{cid}', {}),
        (f'/infos_salaries/supprimer_document/{did}', {}),
    ]
    for url, data in routes:
        r = auth_client.post(url, data=data, follow_redirects=True)
        assert 'Acces non autorise.' in r.get_data(as_text=True), url

    user = db.execute("SELECT email, adresse, pesee FROM users WHERE id = ?", (uid,)).fetchone()
    assert user['email'] == 'avant@test.fr'
    assert user['adresse'] == '1 rue des Tests'
    assert user['pesee'] == 100
    nb = db.execute("SELECT COUNT(*) AS nb FROM contrats WHERE user_id = ?", (uid,)).fetchone()
    assert nb['nb'] == 1    # aucun contrat ajouté ni supprimé
    row = db.execute("SELECT date_fin FROM contrats WHERE id = ?", (cid,)).fetchone()
    assert row['date_fin'] == '2026-06-30'
    assert db.execute("SELECT 1 FROM documents_salaries WHERE id = ?", (did,)).fetchone() is not None
