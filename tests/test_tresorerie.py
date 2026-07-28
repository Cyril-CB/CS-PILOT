"""Tests ciblés pour le module trésorerie."""
import io


def test_import_fec_filtre_tout_journal_an(admin_client, db):
    """Les écritures du journal AN sont ignorées, y compris en janvier."""
    fec_content = (
        "JournalCode\tJournalLib\tEcritureNum\tEcritureDate\tCompteNum\tCompteLib\tCompAuxNum\t"
        "CompAuxLib\tPieceRef\tEcritureLib\tDebit\tCredit\n"
        "AN\tA nouveaux\t1\t20250101\t120000\tRésultat\t\t\tAN-1\tA nouveaux\t0\t1000\n"
        "AN\tA nouveaux\t2\t20250101\t280000\tAmortissements\t\t\tAN-2\tA nouveaux\t500\t0\n"
        "AN\tA nouveaux\t3\t20250101\t701000\tReport produits\t\t\tAN-3\tA nouveaux\t0\t200\n"
        "AC\tAchats\t4\t20250115\t601000\tAchats\t\t\tFAC-1\tFacture achat\t300\t0\n"
    )
    data = {'fichier': (io.BytesIO(fec_content.encode('utf-8')), 'fec.txt')}

    resp = admin_client.post('/api/tresorerie/import_fec',
                             data=data, content_type='multipart/form-data')
    result = resp.get_json()

    assert resp.status_code == 200
    assert result['success'] is True
    assert result['nb_ecritures'] == 1

    rows = db.execute("SELECT compte_num FROM tresorerie_donnees ORDER BY compte_num").fetchall()
    comptes = [r['compte_num'] for r in rows]
    assert comptes == ['601000']


def test_supprimer_tous_comptes_tresorerie_n_efface_pas_autres_modules(admin_client, db):
    """La purge des comptes trésorerie n'efface ni les données trésorerie ni les autres modules."""
    db.execute("""
        INSERT INTO tresorerie_comptes (compte_num, libelle_original, libelle_affiche, type_compte, actif)
        VALUES ('601000', 'Achats', 'Achats', 'charge', 1)
    """)
    db.execute("""
        INSERT INTO tresorerie_comptes (compte_num, libelle_original, libelle_affiche, type_compte, actif)
        VALUES ('701000', 'Ventes', 'Ventes', 'produit', 1)
    """)
    db.execute("""
        INSERT INTO tresorerie_donnees (compte_num, annee, mois, montant)
        VALUES ('601000', 2025, 1, 123.45)
    """)
    db.execute("""
        INSERT INTO plan_comptable_general (compte_num, libelle)
        VALUES ('411000', 'Clients')
    """)
    db.commit()

    resp = admin_client.post('/api/tresorerie/comptes/supprimer_tous')
    result = resp.get_json()

    assert resp.status_code == 200
    assert result['success'] is True
    assert result['nb_supprimes'] == 2

    nb_comptes_treso = db.execute(
        "SELECT COUNT(*) AS n FROM tresorerie_comptes"
    ).fetchone()['n']
    nb_donnees_treso = db.execute(
        "SELECT COUNT(*) AS n FROM tresorerie_donnees"
    ).fetchone()['n']
    nb_pcg = db.execute(
        "SELECT COUNT(*) AS n FROM plan_comptable_general"
    ).fetchone()['n']

    assert nb_comptes_treso == 0
    assert nb_donnees_treso == 1
    assert nb_pcg == 1


def test_page_tresorerie_charge_les_graphiques_depuis_un_script_local(admin_client):
    resp = admin_client.get('/tresorerie')
    html = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert '/static/js/vendor/chart-4.4.7.umd.js?v=4.4.7' in html
    assert 'simple-charts.js' not in html
    assert 'cdn.jsdelivr.net/npm/chart.js' not in html


# ============================================================
# Contrôle d'accès des routes mutantes (directeur / comptable)
# ============================================================

def _seed_tresorerie(db):
    """Insère un jeu de données trésorerie complet et renvoie les identifiants.

    Sert de référence aux tests négatifs : après un refus, ces données doivent
    être strictement inchangées (plusieurs routes sont des purges totales).
    """
    cur = db.execute("""
        INSERT INTO tresorerie_imports (type_import, fichier_nom, annee, nb_ecritures)
        VALUES ('historique', 'fec_2025.txt', 2025, 2)
    """)
    import_id = cur.lastrowid

    db.execute("""
        INSERT INTO tresorerie_comptes (compte_num, libelle_original, libelle_affiche,
                                        type_compte, actif, ordre_affichage)
        VALUES ('601000', 'Achats', 'Achats', 'charge', 1, 10)
    """)
    db.execute("""
        INSERT INTO tresorerie_comptes (compte_num, libelle_original, libelle_affiche,
                                        type_compte, actif, ordre_affichage)
        VALUES ('701000', 'Ventes', 'Ventes', 'produit', 1, 20)
    """)
    db.execute("""
        INSERT INTO tresorerie_donnees (compte_num, annee, mois, montant, import_id)
        VALUES ('601000', 2025, 1, -1500.0, ?)
    """, (import_id,))
    db.execute("""
        INSERT INTO tresorerie_donnees (compte_num, annee, mois, montant, import_id)
        VALUES ('701000', 2025, 1, 2500.0, ?)
    """, (import_id,))
    db.execute("""
        INSERT INTO tresorerie_solde_initial (annee, mois, montant, annee_ref, mois_ref)
        VALUES (2025, 1, 8000.0, 2025, 1)
    """)
    db.execute("""
        INSERT INTO tresorerie_budget_n (compte_num, annee, mois, montant)
        VALUES ('601000', 2025, 2, -1200.0)
    """)
    db.execute("""
        INSERT INTO tresorerie_epargne_solde (montant) VALUES (30000.0)
    """)
    cur = db.execute("""
        INSERT INTO tresorerie_epargne_mouvements (type_mouvement, annee, mois, montant, commentaire)
        VALUES ('placement', 2025, 3, 5000.0, 'Placement initial')
    """)
    mouvement_id = cur.lastrowid
    db.commit()

    return {'import_id': import_id, 'mouvement_id': mouvement_id}


def _etat_tresorerie(db):
    """Photographie l'ensemble des tables trésorerie pour détecter tout effet."""
    requetes = {
        'comptes': ("SELECT compte_num, libelle_affiche, type_compte, actif, ordre_affichage"
                    " FROM tresorerie_comptes ORDER BY compte_num"),
        'donnees': ("SELECT compte_num, annee, mois, montant FROM tresorerie_donnees"
                    " ORDER BY compte_num, annee, mois"),
        'imports': "SELECT id, fichier_nom FROM tresorerie_imports ORDER BY id",
        'solde_initial': ("SELECT annee, mois, montant FROM tresorerie_solde_initial"
                          " ORDER BY annee, mois"),
        'budget_n': ("SELECT compte_num, annee, mois, montant FROM tresorerie_budget_n"
                     " ORDER BY compte_num, annee, mois"),
        'epargne_solde': "SELECT montant FROM tresorerie_epargne_solde ORDER BY id",
        'epargne_mouvements': ("SELECT id, type_mouvement, annee, mois, montant"
                               " FROM tresorerie_epargne_mouvements ORDER BY id"),
    }
    return {cle: [tuple(r) for r in db.execute(sql).fetchall()]
            for cle, sql in requetes.items()}


def _routes_mutantes(ids):
    """Liste des routes POST protégées par _peut_acceder() : (chemin, corps JSON)."""
    return [
        ('/api/tresorerie/solde_initial', {'montant': 99999}),
        ('/api/tresorerie/budget_n',
         {'compte_num': '601000', 'annee': 2025, 'mois': 2, 'montant': -99999}),
        ('/api/tresorerie/comptes/601000/modifier',
         {'field': 'libelle_affiche', 'value': 'Libellé pirate'}),
        ('/api/tresorerie/comptes/reordonner',
         {'ordres': [{'compte_num': '601000', 'ordre': 999}]}),
        ('/api/tresorerie/comptes/supprimer_tous', None),
        (f"/api/tresorerie/imports/{ids['import_id']}/supprimer", None),
        ('/api/tresorerie/epargne/solde', {'montant': 1.0}),
        ('/api/tresorerie/epargne/mouvement',
         {'type_mouvement': 'retrait', 'annee': 2025, 'mois': 4, 'montant': 5000}),
        (f"/api/tresorerie/epargne/mouvement/{ids['mouvement_id']}/supprimer", None),
        ('/api/tresorerie/reinitialiser', {'confirmation': 'REINITIALISER_TRESORERIE'}),
    ]


def _poster(client, chemin, corps):
    """Envoie un POST, avec ou sans corps JSON selon la route."""
    if corps is None:
        return client.post(chemin)
    return client.post(chemin, json=corps)


def test_routes_mutantes_tresorerie_refusees_sans_effet_en_base(app, db, client, sample_users):
    """Trésorerie : toutes les routes mutantes (dont deux purges totales) sont
    refusées hors direction/comptabilité, et la base reste intacte.

    Les fixtures de clients authentifiés partagent le même client de test :
    on gère les connexions explicitement pour enchaîner plusieurs profils.
    """
    with app.app_context():
        ids = _seed_tresorerie(db)
        avant = _etat_tresorerie(db)

    routes = _routes_mutantes(ids)

    # Non connecté : redirection vers la page de connexion, aucune écriture.
    for chemin, corps in routes:
        resp = _poster(client, chemin, corps)
        assert resp.status_code in (301, 302), chemin
        assert '/login' in resp.headers.get('Location', ''), chemin

    # Salarié : accès refusé (403).
    client.post('/login', data={'login': 'salarie_test', 'password': 'sal123'},
                follow_redirects=True)
    for chemin, corps in routes:
        assert _poster(client, chemin, corps).status_code == 403, chemin
    client.get('/logout', follow_redirects=True)

    # Responsable : accès refusé également (aucun secteur ne donne la trésorerie).
    client.post('/login', data={'login': 'resp_test', 'password': 'resp123'},
                follow_redirects=True)
    for chemin, corps in routes:
        assert _poster(client, chemin, corps).status_code == 403, chemin
    client.get('/logout', follow_redirects=True)

    # Aucun refus n'a modifié quoi que ce soit.
    with app.app_context():
        assert _etat_tresorerie(db) == avant


def test_purges_tresorerie_refusees_au_prestataire_paie(prestataire_client, app, db):
    """Le prestataire paie ne peut ni purger les comptes ni réinitialiser."""
    with app.app_context():
        _seed_tresorerie(db)
        avant = _etat_tresorerie(db)

    resp = prestataire_client.post('/api/tresorerie/comptes/supprimer_tous')
    assert resp.status_code == 403
    assert resp.get_json()['error'] == 'Accès non autorisé'

    resp = prestataire_client.post('/api/tresorerie/reinitialiser',
                                   json={'confirmation': 'REINITIALISER_TRESORERIE'})
    assert resp.status_code == 403

    with app.app_context():
        assert _etat_tresorerie(db) == avant


def test_saisie_montant_invalide_refusee_sans_effet(comptable_client, app, db):
    """Montants non numériques ou absents : erreur 400 propre, base inchangée."""
    with app.app_context():
        _seed_tresorerie(db)
        avant = _etat_tresorerie(db)

    cas_invalides = [
        # Solde initial global : montant non numérique, puis montant absent.
        ('/api/tresorerie/solde_initial', {'montant': 'douze euros'}),
        ('/api/tresorerie/solde_initial', {'annee': 2025}),
        # Budget N : montant non numérique, puis paramètres incomplets.
        ('/api/tresorerie/budget_n',
         {'compte_num': '601000', 'annee': 2025, 'mois': 2, 'montant': 'abc'}),
        ('/api/tresorerie/budget_n', {'annee': 2025, 'mois': 2, 'montant': 10}),
        # Solde d'épargne : montant non numérique, puis montant absent.
        ('/api/tresorerie/epargne/solde', {'montant': 'beaucoup'}),
        ('/api/tresorerie/epargne/solde', {'commentaire': 'sans montant'}),
        # Mouvement d'épargne : montant non numérique, négatif, mois hors bornes,
        # type inconnu.
        ('/api/tresorerie/epargne/mouvement',
         {'type_mouvement': 'placement', 'annee': 2025, 'mois': 5, 'montant': 'x'}),
        ('/api/tresorerie/epargne/mouvement',
         {'type_mouvement': 'placement', 'annee': 2025, 'mois': 5, 'montant': -100}),
        ('/api/tresorerie/epargne/mouvement',
         {'type_mouvement': 'retrait', 'annee': 2025, 'mois': 13, 'montant': 100}),
        ('/api/tresorerie/epargne/mouvement',
         {'type_mouvement': 'virement', 'annee': 2025, 'mois': 5, 'montant': 100}),
        # Modification de compte : champ hors liste blanche et type invalide.
        ('/api/tresorerie/comptes/601000/modifier',
         {'field': 'compte_num', 'value': '999999'}),
        ('/api/tresorerie/comptes/601000/modifier',
         {'field': 'type_compte', 'value': 'inconnu'}),
        ('/api/tresorerie/comptes/601000/modifier',
         {'field': 'ordre_affichage', 'value': 'premier'}),
    ]
    for chemin, corps in cas_invalides:
        resp = comptable_client.post(chemin, json=corps)
        assert resp.status_code == 400, (chemin, corps)
        assert 'error' in resp.get_json(), (chemin, corps)

    with app.app_context():
        assert _etat_tresorerie(db) == avant

    # Le cas légitime passe : un montant numérique remplace le solde initial.
    resp = comptable_client.post('/api/tresorerie/solde_initial', json={'montant': '1234.56'})
    assert resp.status_code == 200
    assert resp.get_json()['success'] is True

    with app.app_context():
        soldes = db.execute(
            "SELECT montant FROM tresorerie_solde_initial"
        ).fetchall()
    assert [r['montant'] for r in soldes] == [1234.56]


def test_reinitialisation_tresorerie_exige_la_confirmation_exacte(admin_client, app, db):
    """La réinitialisation n'efface rien sans la confirmation attendue."""
    with app.app_context():
        _seed_tresorerie(db)
        avant = _etat_tresorerie(db)

    for corps in ({}, {'confirmation': ''}, {'confirmation': 'oui'}):
        resp = admin_client.post('/api/tresorerie/reinitialiser', json=corps)
        assert resp.status_code == 400, corps
        assert resp.get_json()['error'] == 'Confirmation requise'

    with app.app_context():
        assert _etat_tresorerie(db) == avant

    # Avec la confirmation exacte, le directeur vide bien les tables trésorerie.
    resp = admin_client.post('/api/tresorerie/reinitialiser',
                             json={'confirmation': 'REINITIALISER_TRESORERIE'})
    assert resp.status_code == 200
    assert resp.get_json()['success'] is True

    with app.app_context():
        apres = _etat_tresorerie(db)
    assert all(lignes == [] for lignes in apres.values())
