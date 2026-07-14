"""
Équipe d'un responsable = son secteur + ses rattachés directs.

Un salarié peut être rangé dans un secteur pour l'analytique comptable (ex.
entretien en « logistique ») tout en étant encadré par le responsable d'un
autre secteur (la responsable de la crèche où il intervient). Le lien direct
users.responsable_id doit ouvrir les mêmes suivis que l'appartenance au
secteur : fiches d'heures (voir, saisir, valider, PDF), vue d'ensemble,
demandes, tableaux de bord, fiche salarié, planning, mon équipe.
"""
from tests.conftest import _login
from utils import est_dans_equipe_responsable


def _creer_agent_transverse(db, sample_users, avec_contrat=False):
    """Agent d'entretien en secteur Logistique, rattaché à la responsable
    (resp_test) du Secteur Test. Retourne (agent_id, logistique_id)."""
    from werkzeug.security import generate_password_hash
    cur = db.cursor()
    cur.execute("INSERT INTO secteurs (nom) VALUES ('Logistique')")
    logistique_id = cur.lastrowid
    cur.execute(
        "INSERT INTO users (nom, prenom, login, password, profil, secteur_id, responsable_id) "
        "VALUES ('Agent', 'Paul', 'agent_test', ?, 'salarie', ?, ?)",
        (generate_password_hash('agent123'), logistique_id, sample_users['responsable_id']))
    agent_id = cur.lastrowid
    if avec_contrat:
        cur.execute(
            "INSERT INTO contrats (user_id, type_contrat, date_debut, date_fin) "
            "VALUES (?, 'CDI', '2025-01-01', NULL)", (agent_id,))
    db.commit()
    return agent_id, logistique_id


def _creer_responsable_tiers(db):
    """Responsable d'un troisième secteur, sans aucun lien avec l'agent."""
    from werkzeug.security import generate_password_hash
    cur = db.cursor()
    cur.execute("INSERT INTO secteurs (nom) VALUES ('Animation')")
    cur.execute(
        "INSERT INTO users (nom, prenom, login, password, profil, secteur_id) "
        "VALUES ('Tiers', 'Anne', 'resp_tiers', ?, 'responsable', ?)",
        (generate_password_hash('tiers123'), cur.lastrowid))
    db.commit()


# ── Helper ──

def test_est_dans_equipe_meme_secteur(app, db, sample_users):
    with app.app_context():
        assert est_dans_equipe_responsable(
            db, sample_users['responsable_id'], sample_users['salarie_id'])


def test_est_dans_equipe_rattache_autre_secteur(app, db, sample_users):
    agent_id, _ = _creer_agent_transverse(db, sample_users)
    with app.app_context():
        assert est_dans_equipe_responsable(db, sample_users['responsable_id'], agent_id)


def test_pas_dans_equipe_sans_lien(app, db, sample_users):
    """Salarié d'un autre secteur SANS rattachement : hors équipe."""
    from werkzeug.security import generate_password_hash
    cur = db.cursor()
    cur.execute("INSERT INTO secteurs (nom) VALUES ('Autre')")
    cur.execute(
        "INSERT INTO users (nom, prenom, login, password, profil, secteur_id) "
        "VALUES ('Sans', 'Lien', 'sans_lien', ?, 'salarie', ?)",
        (generate_password_hash('x'), cur.lastrowid))
    etranger_id = cur.lastrowid
    db.commit()
    with app.app_context():
        assert not est_dans_equipe_responsable(db, sample_users['responsable_id'], etranger_id)


# ── Fiches d'heures ──

def test_vue_mensuelle_accessible_au_responsable(resp_client, db, sample_users):
    agent_id, _ = _creer_agent_transverse(db, sample_users)
    html = resp_client.get(f'/vue_mensuelle?user_id={agent_id}').get_data(as_text=True)
    assert 'Agent' in html                       # fiche affichée, pas de redirection
    assert f'value="{agent_id}"' in html         # présent dans le sélecteur


def test_vue_mensuelle_refusee_sans_lien(client, db, sample_users):
    agent_id, _ = _creer_agent_transverse(db, sample_users)
    _creer_responsable_tiers(db)
    _login(client, 'resp_tiers', 'tiers123')
    r = client.get(f'/vue_mensuelle?user_id={agent_id}', follow_redirects=True)
    assert 'Accès non autorisé' in r.get_data(as_text=True)


def test_valider_mois_du_rattache(resp_client, db, sample_users):
    """La responsable peut poser sa validation sur la fiche du rattaché."""
    agent_id, _ = _creer_agent_transverse(db, sample_users)
    resp_client.post('/valider_mois', data={
        'user_id': agent_id, 'mois': 5, 'annee': 2026}, follow_redirects=True)
    v = db.execute("SELECT validation_responsable FROM validations "
                   "WHERE user_id = ? AND mois = 5 AND annee = 2026", (agent_id,)).fetchone()
    assert v is not None and v['validation_responsable']


def test_vue_ensemble_liste_le_rattache(resp_client, db, sample_users):
    agent_id, _ = _creer_agent_transverse(db, sample_users)
    html = resp_client.get('/vue_ensemble_validation').get_data(as_text=True)
    assert 'Agent' in html          # rattaché listé
    assert 'Martin' in html         # salarié du secteur toujours là


def test_export_pdf_du_rattache(resp_client, db, sample_users):
    agent_id, _ = _creer_agent_transverse(db, sample_users)
    db.execute('''INSERT INTO validations (user_id, mois, annee, validation_salarie,
                  validation_responsable, validation_directeur, date_salarie,
                  date_responsable, date_directeur, bloque)
                  VALUES (?, 3, 2026, 'A', 'B', 'C', '2026-04-01', '2026-04-02',
                          '2026-04-03', 1)''', (agent_id,))
    db.commit()
    r = resp_client.get(f'/export_pdf_mensuel?user_id={agent_id}&mois=3&annee=2026')
    assert r.status_code == 200
    assert r.data[:4] == b'%PDF'


# ── Demandes ──

def test_demande_recup_du_rattache_visible(resp_client, db, sample_users):
    agent_id, _ = _creer_agent_transverse(db, sample_users)
    db.execute('''INSERT INTO demandes_recup (user_id, date_debut, date_fin, nb_jours,
                  nb_heures, statut) VALUES (?, '2026-08-03', '2026-08-03', 1, 7,
                  'en_attente_responsable')''', (agent_id,))
    db.commit()
    html = resp_client.get('/validation_demandes_recup').get_data(as_text=True)
    assert 'Agent' in html


def test_dashboard_actions_inclut_le_rattache(app, db, sample_users):
    from dashboard_actions import construire_actions
    agent_id, _ = _creer_agent_transverse(db, sample_users)
    db.execute('''INSERT INTO demandes_conges (user_id, type_conge, date_debut, date_fin,
                  nb_jours, statut) VALUES (?, 'Congé payé', '2026-08-10', '2026-08-14',
                  5, 'en_attente_responsable')''', (agent_id,))
    db.commit()
    with app.app_context():
        actions = construire_actions(db, 'responsable', sample_users['responsable_id'],
                                     secteur_id=sample_users['secteur_id'])
    assert any('Agent' in a['titre'] for a in actions)


# ── Dashboard, fiche salarié, planning, mon équipe ──

def test_dashboard_responsable_inclut_le_rattache(resp_client, db, sample_users):
    agent_id, _ = _creer_agent_transverse(db, sample_users, avec_contrat=True)
    html = resp_client.get('/dashboard_responsable').get_data(as_text=True)
    assert 'Agent' in html


def test_fiche_salarie_du_rattache_visible(resp_client, db, sample_users):
    agent_id, _ = _creer_agent_transverse(db, sample_users)
    html = resp_client.get(f'/infos_salaries?user_id={agent_id}').get_data(as_text=True)
    assert 'Agent' in html and 'Paul' in html


def test_planning_selecteur_inclut_le_rattache(resp_client, db, sample_users):
    agent_id, _ = _creer_agent_transverse(db, sample_users)
    html = resp_client.get('/planning_theorique').get_data(as_text=True)
    assert 'Agent' in html


def test_mon_equipe_inclut_le_rattache(resp_client, db, sample_users):
    agent_id, _ = _creer_agent_transverse(db, sample_users, avec_contrat=True)
    html = resp_client.get('/mon_equipe').get_data(as_text=True)
    assert 'Agent' in html


def test_selecteur_infos_salaries_liste_le_rattache(resp_client, db, sample_users):
    """Le rattaché apparaît dans le sélecteur de la page (pas seulement en
    accès direct par URL) — revue Codex."""
    agent_id, _ = _creer_agent_transverse(db, sample_users)
    html = resp_client.get('/infos_salaries').get_data(as_text=True)
    assert f'value="{agent_id}"' in html or 'Agent' in html


def test_entree_dashboard_redirige_responsable_sans_secteur(resp_client, app, db, sample_users):
    """/dashboard envoie vers le tableau responsable même sans secteur, dès
    lors qu'il y a des rattachés directs — revue Codex."""
    with app.app_context():
        db.execute("UPDATE users SET secteur_id = NULL WHERE id = ?",
                   (sample_users['responsable_id'],))
        db.commit()
    r = resp_client.get('/dashboard', follow_redirects=False)
    assert r.status_code == 302
    assert r.headers.get('Location', '').endswith('/dashboard_responsable')
