"""
Tests du blueprint regles_comptables_bp : contrôle d'accès et CRUD des règles
comptables utilisées par l'IA pour générer les écritures.
"""


def _count_regles(app, db):
    with app.app_context():
        return db.execute("SELECT COUNT(*) AS n FROM regles_comptables").fetchone()['n']


class TestAccesRegles:
    def test_salarie_refuse(self, auth_client):
        resp = auth_client.get('/regles-comptables', follow_redirects=False)
        assert resp.status_code == 302

    def test_comptable_autorise(self, comptable_client):
        resp = comptable_client.get('/regles-comptables')
        assert resp.status_code == 200


class TestCRUDRegles:
    def test_ajouter_regle_un_analytique(self, app, db, comptable_client):
        comptable_client.post('/regles-comptables/ajouter', data={
            'nom': 'Fournitures bureau',
            'type_regle': 'fournisseur',
            'cible': 'ACME',
            'compte_comptable': '606400',
            'code_analytique_1': 'ANA01',
            'pourcentage_analytique_1': '80',  # ignoré car un seul analytique
        }, follow_redirects=False)

        with app.app_context():
            r = db.execute(
                "SELECT * FROM regles_comptables WHERE nom = ?", ('Fournitures bureau',)
            ).fetchone()
        assert r is not None
        assert r['compte_comptable'] == '606400'
        # Un seul analytique → 100 % sur le premier
        assert r['pourcentage_analytique_1'] == 100.0
        assert r['pourcentage_analytique_2'] == 0.0
        assert r['statut'] == 'active'

    def test_ajouter_regle_deux_analytiques(self, app, db, comptable_client):
        comptable_client.post('/regles-comptables/ajouter', data={
            'nom': 'Répartition mixte',
            'type_regle': 'depense',
            'cible': 'energie',
            'compte_comptable': '606100',
            'code_analytique_1': 'ANA01',
            'code_analytique_2': 'ANA02',
            'pourcentage_analytique_1': '70',
            'pourcentage_analytique_2': '30',
        }, follow_redirects=False)

        with app.app_context():
            r = db.execute(
                "SELECT * FROM regles_comptables WHERE nom = ?", ('Répartition mixte',)
            ).fetchone()
        assert r['pourcentage_analytique_1'] == 70.0
        assert r['pourcentage_analytique_2'] == 30.0

    def test_ajouter_regle_champs_obligatoires_manquants(self, app, db, comptable_client):
        comptable_client.post('/regles-comptables/ajouter', data={
            'nom': 'Incomplète',
            # type_regle / cible / compte_comptable manquants
        }, follow_redirects=False)
        assert _count_regles(app, db) == 0

    def test_modifier_regle(self, app, db, comptable_client):
        with app.app_context():
            cur = db.execute(
                "INSERT INTO regles_comptables (nom, type_regle, cible, compte_comptable) "
                "VALUES (?, ?, ?, ?)", ('R1', 'fournisseur', 'ACME', '606400'),
            )
            rid = cur.lastrowid
            db.commit()

        comptable_client.post(f'/regles-comptables/{rid}/modifier', data={
            'nom': 'R1 modifiée',
            'type_regle': 'fournisseur',
            'cible': 'ACME',
            'compte_comptable': '607000',
            'statut': 'inactive',
        }, follow_redirects=False)

        with app.app_context():
            r = db.execute("SELECT * FROM regles_comptables WHERE id=?", (rid,)).fetchone()
        assert r['nom'] == 'R1 modifiée'
        assert r['compte_comptable'] == '607000'
        assert r['statut'] == 'inactive'

    def test_supprimer_regle(self, app, db, comptable_client):
        with app.app_context():
            cur = db.execute(
                "INSERT INTO regles_comptables (nom, type_regle, cible, compte_comptable) "
                "VALUES (?, ?, ?, ?)", ('À supprimer', 'fournisseur', 'X', '606400'),
            )
            rid = cur.lastrowid
            db.commit()

        comptable_client.post(f'/regles-comptables/{rid}/supprimer', follow_redirects=False)

        with app.app_context():
            r = db.execute("SELECT * FROM regles_comptables WHERE id=?", (rid,)).fetchone()
        assert r is None
