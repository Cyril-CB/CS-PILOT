"""
Tests pour le module database.py :
- Initialisation du schéma (toutes les tables)
- Vérification qu'aucun compte par défaut n'est créé (setup wizard)
- Marquage de toutes les migrations comme appliquées
- Données initiales (postes de dépense)
- Connexion et row_factory
- Résolution conditionnelle de DATA_DIR (mode script vs mode frozen)
"""
from collections import Counter
import importlib
import os
import sys

import pytest

import database
from database import get_db, init_db, ALL_MIGRATION_VERSIONS
from migration_manager import lister_fichiers_migrations


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
        'budget_prev_config_codes', 'budget_prev_saisies',
    ]

    def test_tables_creees(self, app, db):
        """Toutes les tables du schéma doivent exister après init_db."""
        with app.app_context():
            tables = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
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
                    "SELECT * FROM schema_migrations WHERE version = ?", (version,)
                ).fetchone()
                assert migration is not None, f"Migration {version} non enregistrée"
                assert migration['statut'] == 'ok', f"Migration {version} en erreur"

    def test_fichier_migration_0029_present(self):
        """La migration 0029 doit exister sous forme de fichier."""
        versions = {m['version'] for m in lister_fichiers_migrations()}
        assert '0029' in versions

    def test_versions_migrations_uniques(self):
        """Chaque fichier de migration doit avoir une version unique."""
        versions = [m['version'] for m in lister_fichiers_migrations()]
        duplicates = sorted([version for version, count in Counter(versions).items() if count > 1])
        assert len(versions) == len(set(versions)), f"Versions dupliquées: {', '.join(duplicates)}"

    def test_fichier_migration_0033_present(self):
        """La migration 0033 doit exister sous forme de fichier."""
        versions = {m['version'] for m in lister_fichiers_migrations()}
        assert '0033' in versions

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


class TestDataDir:
    """Vérifie la résolution conditionnelle de DATA_DIR selon sys.frozen."""

    def _reload_database(self):
        """Recharge le module database et retourne les nouvelles valeurs DATA_DIR / DATABASE."""
        importlib.reload(database)
        return database.DATA_DIR, database.DATABASE

    def test_script_mode_utilise_dossier_projet(self, monkeypatch):
        """En mode script (sys.frozen absent), DATA_DIR doit être le dossier du projet."""
        monkeypatch.delattr(sys, 'frozen', raising=False)
        try:
            data_dir, db_path = self._reload_database()
            projet_dir = os.path.dirname(os.path.abspath(database.__file__))
            assert data_dir == projet_dir, (
                f"En mode script, DATA_DIR devrait être le dossier du projet "
                f"({projet_dir}), pas {data_dir}"
            )
            assert db_path == os.path.join(data_dir, 'cspilot.db')
        finally:
            importlib.reload(database)

    @pytest.mark.skipif(os.name == 'nt', reason='Linux/Mac specific test')
    def test_frozen_linux_utilise_local_share(self, monkeypatch):
        """En mode frozen sur Linux/Mac, DATA_DIR doit être ~/.local/share/cspilot."""
        monkeypatch.setattr(sys, 'frozen', True, raising=False)
        try:
            data_dir, db_path = self._reload_database()
            attendu = os.path.join(os.path.expanduser('~'), '.local', 'share', 'cspilot')
            assert data_dir == attendu, (
                f"En mode frozen (Linux), DATA_DIR devrait être {attendu}, pas {data_dir}"
            )
            assert db_path == os.path.join(data_dir, 'cspilot.db')
        finally:
            importlib.reload(database)

    def test_frozen_windows_utilise_localappdata(self, monkeypatch):
        """En mode frozen sur Windows (simulé), DATA_DIR doit être %LOCALAPPDATA%\\cspilot."""
        original_os_name = os.name
        monkeypatch.setenv('LOCALAPPDATA', r'C:\Users\Test\AppData\Local')
        monkeypatch.setattr(os, 'name', 'nt')
        monkeypatch.setattr(sys, 'frozen', True, raising=False)
        try:
            data_dir, db_path = self._reload_database()
            attendu = os.path.join(r'C:\Users\Test\AppData\Local', 'cspilot')
            assert data_dir == attendu, (
                f"En mode frozen (Windows), DATA_DIR devrait être {attendu}, pas {data_dir}"
            )
            assert db_path == os.path.join(data_dir, 'cspilot.db')
        finally:
            monkeypatch.setattr(os, 'name', original_os_name)
            importlib.reload(database)

    def test_database_dans_data_dir(self):
        """DATABASE doit toujours être data_dir/cspilot.db."""
        assert database.DATABASE == os.path.join(database.DATA_DIR, 'cspilot.db')
