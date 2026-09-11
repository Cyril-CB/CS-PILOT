"""Connexion applicative : invariants des fiches vérifiés avant chaque commit.

L'authorizer SQLite repère les tables écrites par execute, cursor et executemany,
sans analyser le texte SQL. Le contrôle lit la transaction sur la même connexion.
Les connexions brutes de sauvegarde/restauration restent des opérations
d'exploitation distinctes, jamais des chemins normaux de modification métier.
"""
import sqlite3
from contextlib import contextmanager


TABLES_CONTENU = frozenset({
    'heures_reelles', 'planning_theorique', 'alternance_reference', 'contrats',
    'periodes_vacances', 'jours_feries', 'users', 'variables_paie', 'validations',
    'absences', 'fiches_a_recalculer', 'paie_a_recalculer', 'rh_projections_a_verifier',
})


class ConnexionFiches(sqlite3.Connection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tables_ecrites = set()
        self._commit_controle = False
        self._migration_en_cours = False
        self.set_authorizer(self._observer)

    def _observer(self, action, table, colonne, base, source):
        if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE):
            if table in TABLES_CONTENU:
                # Ne pas vider entre deux commits : l'authorizer intervient à la
                # préparation SQL et les requêtes préparées peuvent être réutilisées.
                self._tables_ecrites.add(table)
        if action == sqlite3.SQLITE_TRANSACTION and table == 'COMMIT' and not self._commit_controle:
            return sqlite3.SQLITE_DENY  # un COMMIT SQL direct contournerait le contrôle
        if self._migration_en_cours and action == sqlite3.SQLITE_TRANSACTION and table == 'ROLLBACK':
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def commit(self):
        if self._migration_en_cours:
            # Compatibilité des migrations déjà livrées : leurs commit() ne
            # doivent pas séparer la reprise de données du journal de succès.
            return
        try:
            if self.in_transaction and self._tables_ecrites:
                schema = self.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='fiches_versions'"
                ).fetchone()
                if schema:
                    # Import local : le calcul commun utilise utils/database.
                    from fiches_versions import actualiser_versions
                    ids = [r[0] for r in self.execute('SELECT user_id FROM fiches_a_recalculer')]
                    actualiser_versions(self, ids)
                    self.execute('DELETE FROM fiches_a_recalculer')
                if self.execute("SELECT 1 FROM sqlite_master WHERE name='rh_projections'").fetchone():
                    from absences_coherence import verifier_projections
                    verifier_projections(self)
                if self.execute("SELECT 1 FROM sqlite_master WHERE name='paie_a_recalculer'").fetchone():
                    from prepa_paie_donnees import actualiser_statuts
                    actualiser_statuts(self)
            self._commit_controle = True
            return super().commit()
        except Exception:
            super().rollback()
            raise
        finally:
            self._commit_controle = False

    @contextmanager
    def migration_atomique(self):
        """Un seul commit contrôlé, DDL compris ; interruption = rollback."""
        if self.in_transaction or self._migration_en_cours:
            raise RuntimeError('Une transaction est déjà en cours')
        self.execute('BEGIN IMMEDIATE')
        self._migration_en_cours = True
        try:
            yield self
            self._migration_en_cours = False
            self.commit()
        except BaseException:
            self._migration_en_cours = False
            self.rollback()
            raise
        finally:
            self._migration_en_cours = False

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False
