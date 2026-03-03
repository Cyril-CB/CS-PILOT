"""
Tests pour le module database.py :
- Initialisation du schéma (toutes les tables)
- Vérification qu'aucun compte par défaut n'est créé (setup wizard)
- Marquage de toutes les migrations comme appliquées
- Données initiales (postes de dépense)
- Connexion et row_factory
"""
from database import get_db, init_db, ALL_MIGRATION_VERSIONS


class TestInitDb:
    """Vérifie que init_db crée bien toutes les tables attendues."""

    TABLES_ATTENDUES = [
        'users', 'secteurs', 'planning_theorique', 'alternance_reference',
        'anomalies', 'heures_reelles', 'validations', 'periodes_vacances',
        'historique_modifications', 'demandes_recup', 'jours_feries',
        'planning_enfance_config', 'absences', 'app_settings',
        'presence_forfait_jour', 'validation_forfait_jour', 'schema_migrations',
        # Tables ajoutées par les migrations, maintenant dans le schéma initial
        'variables_paie_defauts', 'variables_paie', 'contrats',
        'documents_salaries', 'prepa_paie_statut', 'conges_cloture_mensuelle',
        'postes_alisfa', 'postes_depense', 'postes_depense_secteur_types',
        'budgets', 'budget_lignes', 'budget_reel_lignes', 'frequentation_creche',
    ]

    def test_tables_creees(self, app, db):
        """Toutes les tables du schéma doivent exister après init_db."""
        with app.app_context():
            tables = db.execute(
                "SELECT table_name as name FROM information_schema.tables WHERE table_schema='public'"
            ).fetchall()
            noms_tables = {t['name'] for t in tables}

            for table in self.TABLES_ATTENDUES:
                assert table in noms_tables, f"Table manquante : {table}"

    def test_aucun_compte_par_defaut(self, app, db):
        """Aucun compte ne doit être créé par init_db (le setup wizard s'en charge)."""
        with app.app_context():
            row = db.execute("SELECT COUNT(*) as nb FROM users").fetchone()
            assert row['nb'] == 0

    def test_toutes_migrations_marquees(self, app, db):
        """Toutes les migrations connues doivent être marquées comme appliquées."""
        with app.app_context():
            for version, nom in ALL_MIGRATION_VERSIONS:
                migration = db.execute(
                    "SELECT * FROM schema_migrations WHERE version = %s", (version,)
                ).fetchone()
                assert migration is not None, f"Migration {version} non enregistrée"
                assert migration['statut'] == 'ok', f"Migration {version} en erreur"

    def test_postes_depense_initialises(self, app, db):
        """Les postes de dépense par défaut doivent être créés."""
        with app.app_context():
            row = db.execute("SELECT COUNT(*) as nb FROM postes_depense").fetchone()
            assert row['nb'] == 13  # 13 postes de dépense par défaut

    def test_postes_depense_associations(self, app, db):
        """Les associations postes/types de secteur doivent être créées."""
        with app.app_context():
            row = db.execute("SELECT COUNT(*) as nb FROM postes_depense_secteur_types").fetchone()
            assert row['nb'] > 0


class TestGetDb:
    """Vérifie le comportement de get_db."""

    def test_row_factory(self, app, db):
        """Les résultats doivent être accessibles par nom de colonne."""
        with app.app_context():
            row = db.execute("SELECT 1 as test_col").fetchone()
            assert row['test_col'] == 1

    def test_connexion_fonctionnelle(self, app, db):
        """La connexion doit permettre des opérations basiques."""
        with app.app_context():
            db.execute("CREATE TABLE IF NOT EXISTS _test_tmp (id INTEGER)")
            db.execute("INSERT INTO _test_tmp VALUES (42)")
            row = db.execute("SELECT id FROM _test_tmp").fetchone()
            assert row['id'] == 42
            db.execute("DROP TABLE _test_tmp")
