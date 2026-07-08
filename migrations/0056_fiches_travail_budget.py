"""
Migration 0056 : Fiches de travail du budget actualisé.

Table budget_fiches_travail : pour chaque compte non paramétré (ni PS, ni
paie), la fiche construit la valeur définitive du budget actualisé à partir
du réel à date + une projection sur les mois restants (méthode au choix :
N-1, moyenne N-1/N-2, tendance du réel, solde du budget initial, saisie
mensuelle) + des lignes d'ajustement libres. Le détail est stocké en JSON,
le total est reporté sur la valeur définitive du compte.
"""

NOM = "Fiches de travail budget actualisé"
DESCRIPTION = (
    "Ajoute la table budget_fiches_travail (réel + projection + ajustements "
    "par compte) pour la construction du budget actualisé."
)


def upgrade(conn):
    """Applique la migration."""
    conn.cursor().execute('''
        CREATE TABLE IF NOT EXISTS budget_fiches_travail (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            compte_num TEXT NOT NULL,
            annee INTEGER NOT NULL,
            secteur_id INTEGER NOT NULL,
            type_budget TEXT NOT NULL CHECK(type_budget IN ('initial', 'actualise')),
            donnees TEXT,
            total REAL DEFAULT 0,
            updated_by INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (secteur_id) REFERENCES secteurs(id) ON DELETE CASCADE,
            FOREIGN KEY (updated_by) REFERENCES users(id),
            UNIQUE(compte_num, annee, secteur_id, type_budget)
        )
    ''')


def downgrade(conn):
    """Supprime la table des fiches de travail."""
    conn.cursor().execute('DROP TABLE IF EXISTS budget_fiches_travail')
