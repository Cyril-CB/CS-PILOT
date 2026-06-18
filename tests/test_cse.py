"""
Tests du module CSE (Comité Social et Économique).

Couvre :
- la désignation des membres (direction / comptable) ;
- l'espace réservé aux membres ;
- les messages aux salariés (un seul actif, archivage, bannière dashboard) ;
- le budget simplifié (soldes de départ, mouvements) ;
- le bilan annuel.
"""


def _faire_membre(db, user_id, par_id):
    """Insère directement un membre du CSE (raccourci de mise en place)."""
    db.execute(
        "INSERT INTO cse_membres (user_id, ajoute_par) VALUES (?, ?)",
        (user_id, par_id)
    )
    db.commit()


def _inserer_message(db, contenu, date_validite, statut='actif', cree_par=None):
    db.execute(
        "INSERT INTO cse_messages (contenu, date_validite, statut, cree_par) VALUES (?, ?, ?, ?)",
        (contenu, date_validite, statut, cree_par)
    )
    db.commit()


# ──────────────────────────────────────────────────────────────────────────
#  Accès
# ──────────────────────────────────────────────────────────────────────────

def test_salarie_non_membre_redirige(auth_client):
    resp = auth_client.get('/cse', follow_redirects=True)
    assert resp.status_code == 200
    assert 'Accès réservé au CSE' in resp.get_data(as_text=True)


def test_directeur_voit_gestion_membres(admin_client):
    resp = admin_client.get('/cse')
    assert resp.status_code == 200
    assert 'Membres du CSE' in resp.get_data(as_text=True)


def test_comptable_voit_gestion_membres(comptable_client):
    resp = comptable_client.get('/cse')
    assert resp.status_code == 200
    assert 'Membres du CSE' in resp.get_data(as_text=True)


def test_non_membre_bloque_sur_sous_pages(auth_client):
    for url in ('/cse/messages', '/cse/budget', '/cse/bilan'):
        resp = auth_client.get(url, follow_redirects=True)
        assert resp.status_code == 200
        assert 'réservé aux membres du CSE' in resp.get_data(as_text=True)


# ──────────────────────────────────────────────────────────────────────────
#  Gestion des membres
# ──────────────────────────────────────────────────────────────────────────

def test_directeur_ajoute_membre(admin_client, db, sample_users):
    resp = admin_client.post(
        '/cse/membres/ajouter',
        data={'user_id': sample_users['salarie_id']},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    row = db.execute(
        "SELECT * FROM cse_membres WHERE user_id = ?", (sample_users['salarie_id'],)
    ).fetchone()
    assert row is not None


def test_ajout_membre_duplique_refuse(admin_client, db, sample_users):
    admin_client.post('/cse/membres/ajouter', data={'user_id': sample_users['salarie_id']})
    admin_client.post('/cse/membres/ajouter', data={'user_id': sample_users['salarie_id']})
    rows = db.execute(
        "SELECT COUNT(*) AS nb FROM cse_membres WHERE user_id = ?",
        (sample_users['salarie_id'],)
    ).fetchone()
    assert rows['nb'] == 1


def test_ajout_prestataire_refuse(admin_client, db):
    from werkzeug.security import generate_password_hash
    db.execute(
        "INSERT INTO users (nom, prenom, login, password, profil) VALUES (?,?,?,?,?)",
        ('Presta', 'Paul', 'presta_test', generate_password_hash('Presta1234'), 'prestataire')
    )
    db.commit()
    presta_id = db.execute("SELECT id FROM users WHERE login = 'presta_test'").fetchone()['id']

    admin_client.post('/cse/membres/ajouter', data={'user_id': presta_id}, follow_redirects=True)
    row = db.execute("SELECT * FROM cse_membres WHERE user_id = ?", (presta_id,)).fetchone()
    assert row is None


def test_salarie_ne_peut_ajouter_membre(auth_client, db, sample_users):
    auth_client.post(
        '/cse/membres/ajouter',
        data={'user_id': sample_users['salarie_id']},
        follow_redirects=True,
    )
    row = db.execute(
        "SELECT * FROM cse_membres WHERE user_id = ?", (sample_users['salarie_id'],)
    ).fetchone()
    assert row is None


def test_supprimer_membre(admin_client, db, sample_users):
    admin_client.post('/cse/membres/ajouter', data={'user_id': sample_users['salarie_id']})
    membre = db.execute(
        "SELECT id FROM cse_membres WHERE user_id = ?", (sample_users['salarie_id'],)
    ).fetchone()
    admin_client.post(f"/cse/membres/{membre['id']}/supprimer", follow_redirects=True)
    row = db.execute("SELECT * FROM cse_membres WHERE id = ?", (membre['id'],)).fetchone()
    assert row is None


def test_membre_accede_a_son_espace(auth_client, db, sample_users):
    _faire_membre(db, sample_users['salarie_id'], sample_users['directeur_id'])
    resp = auth_client.get('/cse')
    assert resp.status_code == 200
    assert 'Mon espace CSE' in resp.get_data(as_text=True)


# ──────────────────────────────────────────────────────────────────────────
#  Messages
# ──────────────────────────────────────────────────────────────────────────

def test_membre_publie_message(auth_client, db, sample_users):
    _faire_membre(db, sample_users['salarie_id'], sample_users['directeur_id'])
    resp = auth_client.post(
        '/cse/messages/creer',
        data={'titre': 'Réunion', 'contenu': 'Bonjour à tous', 'date_validite': '2999-12-31'},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    actif = db.execute("SELECT * FROM cse_messages WHERE statut = 'actif'").fetchall()
    assert len(actif) == 1
    assert actif[0]['contenu'] == 'Bonjour à tous'


def test_nouveau_message_archive_le_precedent(auth_client, db, sample_users):
    _faire_membre(db, sample_users['salarie_id'], sample_users['directeur_id'])
    auth_client.post('/cse/messages/creer',
                     data={'contenu': 'Premier', 'date_validite': '2999-12-31'})
    auth_client.post('/cse/messages/creer',
                     data={'contenu': 'Second', 'date_validite': '2999-12-31'})
    actifs = db.execute("SELECT * FROM cse_messages WHERE statut = 'actif'").fetchall()
    assert len(actifs) == 1
    assert actifs[0]['contenu'] == 'Second'
    archives = db.execute("SELECT * FROM cse_messages WHERE statut = 'archive'").fetchall()
    assert len(archives) == 1
    assert archives[0]['contenu'] == 'Premier'


def test_message_avec_date_passee_refuse(auth_client, db, sample_users):
    _faire_membre(db, sample_users['salarie_id'], sample_users['directeur_id'])
    auth_client.post('/cse/messages/creer',
                     data={'contenu': 'Trop tard', 'date_validite': '2000-01-01'},
                     follow_redirects=True)
    rows = db.execute("SELECT COUNT(*) AS nb FROM cse_messages").fetchone()
    assert rows['nb'] == 0


def test_message_expire_est_archive(auth_client, db, sample_users):
    _faire_membre(db, sample_users['salarie_id'], sample_users['directeur_id'])
    _inserer_message(db, 'Périmé', '2000-01-01', statut='actif',
                     cree_par=sample_users['salarie_id'])
    # La consultation déclenche l'archivage des messages expirés.
    auth_client.get('/cse/messages')
    row = db.execute("SELECT statut FROM cse_messages WHERE contenu = 'Périmé'").fetchone()
    assert row['statut'] == 'archive'


def test_archiver_message_manuellement(auth_client, db, sample_users):
    _faire_membre(db, sample_users['salarie_id'], sample_users['directeur_id'])
    _inserer_message(db, 'A retirer', '2999-12-31', statut='actif',
                     cree_par=sample_users['salarie_id'])
    msg = db.execute("SELECT id FROM cse_messages WHERE contenu = 'A retirer'").fetchone()
    auth_client.post(f"/cse/messages/{msg['id']}/archiver", follow_redirects=True)
    row = db.execute("SELECT statut FROM cse_messages WHERE id = ?", (msg['id'],)).fetchone()
    assert row['statut'] == 'archive'


def test_banniere_sur_dashboard(auth_client, db, sample_users):
    _inserer_message(db, 'Info importante', '2999-12-31', statut='actif',
                     cree_par=sample_users['directeur_id'])
    resp = auth_client.get('/dashboard')
    assert resp.status_code == 200
    assert 'Message du CSE à lire' in resp.get_data(as_text=True)


def test_pas_de_banniere_sans_message(auth_client):
    resp = auth_client.get('/dashboard')
    assert resp.status_code == 200
    assert 'Message du CSE à lire' not in resp.get_data(as_text=True)


def test_banniere_absente_si_message_expire(auth_client, db, sample_users):
    _inserer_message(db, 'Vieux', '2000-01-01', statut='actif',
                     cree_par=sample_users['directeur_id'])
    resp = auth_client.get('/dashboard')
    assert 'Message du CSE à lire' not in resp.get_data(as_text=True)


# ──────────────────────────────────────────────────────────────────────────
#  Budget
# ──────────────────────────────────────────────────────────────────────────

def test_definir_solde_initial(auth_client, db, sample_users):
    _faire_membre(db, sample_users['salarie_id'], sample_users['directeur_id'])
    auth_client.post('/cse/budget/solde',
                     data={'compte': 'banque', 'date_solde': '2026-01-01', 'montant': '1000,50'},
                     follow_redirects=True)
    row = db.execute("SELECT * FROM cse_soldes_initiaux WHERE compte = 'banque'").fetchone()
    assert row is not None
    assert abs(row['montant'] - 1000.50) < 0.001


def test_solde_initial_mis_a_jour(auth_client, db, sample_users):
    _faire_membre(db, sample_users['salarie_id'], sample_users['directeur_id'])
    auth_client.post('/cse/budget/solde',
                     data={'compte': 'caisse', 'date_solde': '2026-01-01', 'montant': '100'})
    auth_client.post('/cse/budget/solde',
                     data={'compte': 'caisse', 'date_solde': '2026-02-01', 'montant': '250'})
    rows = db.execute("SELECT * FROM cse_soldes_initiaux WHERE compte = 'caisse'").fetchall()
    assert len(rows) == 1
    assert abs(rows[0]['montant'] - 250.0) < 0.001


def test_ajouter_mouvement_et_solde_courant(auth_client, db, sample_users):
    _faire_membre(db, sample_users['salarie_id'], sample_users['directeur_id'])
    auth_client.post('/cse/budget/solde',
                     data={'compte': 'banque', 'date_solde': '2026-01-01', 'montant': '1000'})
    auth_client.post('/cse/budget/mouvement',
                     data={'compte': 'banque', 'type': 'entree',
                           'date_mouvement': '2026-03-01', 'montant': '200', 'commentaire': 'Cotisation'})
    auth_client.post('/cse/budget/mouvement',
                     data={'compte': 'banque', 'type': 'sortie',
                           'date_mouvement': '2026-03-05', 'montant': '50', 'commentaire': 'Achat'})

    from blueprints.cse import _calculer_soldes_courants
    import database
    conn = database.get_db()
    try:
        soldes = _calculer_soldes_courants(conn)
    finally:
        conn.close()
    assert abs(soldes['banque'] - 1150.0) < 0.001  # 1000 + 200 - 50


def test_mouvement_montant_invalide_refuse(auth_client, db, sample_users):
    _faire_membre(db, sample_users['salarie_id'], sample_users['directeur_id'])
    auth_client.post('/cse/budget/mouvement',
                     data={'compte': 'banque', 'type': 'entree',
                           'date_mouvement': '2026-03-01', 'montant': 'abc'},
                     follow_redirects=True)
    rows = db.execute("SELECT COUNT(*) AS nb FROM cse_mouvements").fetchone()
    assert rows['nb'] == 0


def test_supprimer_mouvement(auth_client, db, sample_users):
    _faire_membre(db, sample_users['salarie_id'], sample_users['directeur_id'])
    auth_client.post('/cse/budget/mouvement',
                     data={'compte': 'caisse', 'type': 'entree',
                           'date_mouvement': '2026-03-01', 'montant': '30'})
    mvt = db.execute("SELECT id FROM cse_mouvements").fetchone()
    auth_client.post(f"/cse/budget/mouvement/{mvt['id']}/supprimer", follow_redirects=True)
    rows = db.execute("SELECT COUNT(*) AS nb FROM cse_mouvements").fetchone()
    assert rows['nb'] == 0


def test_non_membre_ne_peut_ajouter_mouvement(auth_client, db, sample_users):
    auth_client.post('/cse/budget/mouvement',
                     data={'compte': 'banque', 'type': 'entree',
                           'date_mouvement': '2026-03-01', 'montant': '100'},
                     follow_redirects=True)
    rows = db.execute("SELECT COUNT(*) AS nb FROM cse_mouvements").fetchone()
    assert rows['nb'] == 0


# ──────────────────────────────────────────────────────────────────────────
#  Bilan annuel
# ──────────────────────────────────────────────────────────────────────────

def test_bilan_annuel_affiche_mouvements(auth_client, db, sample_users):
    _faire_membre(db, sample_users['salarie_id'], sample_users['directeur_id'])
    db.execute("INSERT INTO cse_soldes_initiaux (compte, date_solde, montant) VALUES ('banque','2025-01-01',500)")
    db.execute("INSERT INTO cse_mouvements (compte, type, date_mouvement, montant, commentaire) "
               "VALUES ('banque','entree','2025-06-10',300,'Don')")
    db.execute("INSERT INTO cse_mouvements (compte, type, date_mouvement, montant, commentaire) "
               "VALUES ('banque','sortie','2026-02-02',100,'Cadeau')")
    db.commit()

    resp = auth_client.get('/cse/bilan?annee=2025')
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert 'Bilan annuel du CSE' in html
    assert 'Année 2025' in html
    assert 'Don' in html
    # Le mouvement 2026 ne doit pas apparaître dans le bilan 2025.
    assert 'Cadeau' not in html


def test_bilan_annee_invalide_retombe_sur_defaut(auth_client, db, sample_users):
    _faire_membre(db, sample_users['salarie_id'], sample_users['directeur_id'])
    resp = auth_client.get('/cse/bilan?annee=abcd')
    assert resp.status_code == 200
    assert 'Bilan annuel du CSE' in resp.get_data(as_text=True)


def test_calcul_bilan_soldes(auth_client, db, sample_users):
    _faire_membre(db, sample_users['salarie_id'], sample_users['directeur_id'])
    db.execute("INSERT INTO cse_soldes_initiaux (compte, date_solde, montant) VALUES ('banque','2025-01-01',500)")
    db.execute("INSERT INTO cse_mouvements (compte, type, date_mouvement, montant) VALUES ('banque','entree','2025-06-10',300)")
    db.execute("INSERT INTO cse_mouvements (compte, type, date_mouvement, montant) VALUES ('banque','sortie','2025-07-10',100)")
    db.commit()

    from blueprints.cse import _calculer_bilan_annuel
    import database
    conn = database.get_db()
    try:
        bilan = _calculer_bilan_annuel(conn, '2025')
    finally:
        conn.close()
    banque = bilan['comptes']['banque']
    assert abs(banque['solde_debut'] - 500.0) < 0.001   # solde de départ avant mouvements
    assert abs(banque['entrees'] - 300.0) < 0.001
    assert abs(banque['sorties'] - 100.0) < 0.001
    assert abs(banque['solde_fin'] - 700.0) < 0.001     # 500 + 300 - 100


def test_bilan_ignore_solde_initial_date_apres_annee(auth_client, db, sample_users):
    """Un solde de départ daté après l'année du bilan ne doit pas la gonfler."""
    _faire_membre(db, sample_users['salarie_id'], sample_users['directeur_id'])
    db.execute("INSERT INTO cse_soldes_initiaux (compte, date_solde, montant) VALUES ('banque','2026-01-01',1000)")
    db.execute("INSERT INTO cse_mouvements (compte, type, date_mouvement, montant) VALUES ('banque','entree','2025-06-10',300)")
    db.commit()

    from blueprints.cse import _calculer_bilan_annuel
    import database
    conn = database.get_db()
    try:
        bilan_2025 = _calculer_bilan_annuel(conn, '2025')
        bilan_2026 = _calculer_bilan_annuel(conn, '2026')
    finally:
        conn.close()

    # 2025 : le solde de départ daté 2026 ne compte pas (300 de mouvement seul).
    assert abs(bilan_2025['comptes']['banque']['solde_fin'] - 300.0) < 0.001
    assert abs(bilan_2025['comptes']['banque']['solde_debut'] - 0.0) < 0.001
    # 2026 : le solde de départ est désormais pris en compte (1000 + 300).
    assert abs(bilan_2026['comptes']['banque']['solde_fin'] - 1300.0) < 0.001


def test_suppression_membre_nom_avec_apostrophe(admin_client, db):
    """Un nom avec apostrophe ne doit pas casser le JS ni permettre d'injection."""
    from werkzeug.security import generate_password_hash
    db.execute(
        "INSERT INTO users (nom, prenom, login, password, profil) VALUES (?,?,?,?,?)",
        ("D'Arc", "O'Neil", 'oneil', generate_password_hash('Oneil1234'), 'salarie')
    )
    db.commit()
    uid = db.execute("SELECT id FROM users WHERE login = 'oneil'").fetchone()['id']
    db.execute("INSERT INTO cse_membres (user_id, ajoute_par) VALUES (?, ?)", (uid, uid))
    db.commit()

    resp = admin_client.get('/cse')
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    # Le nom passe par un attribut data- (échappé) et plus par un confirm() inline.
    assert 'cse-remove-form' in html
    assert 'data-membre=' in html
    assert 'onsubmit="return confirm' not in html
    # Le nom n'apparaît jamais brut (non échappé) dans la page.
    assert "O'Neil D'Arc" not in html
    # L'apostrophe est échappée en entité HTML.
    assert 'D&#39;Arc' in html or 'D&#x27;Arc' in html
