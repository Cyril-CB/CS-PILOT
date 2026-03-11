"""
Migration 0029 : Ajout du module Budget Prévisionnel.

- budget_prev_config_codes : mapping code analytique -> secteur
- budget_prev_saisies      : saisies budget par type/année/secteur/compte
"""

NOM = "Ajout module budget previsionnel"
DESCRIPTION = (
    "Ajoute les tables du module Budget Prévisionnel et la colonne valeur_temp "
    "pour la reprise des budgets par type et année."
)
def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS budget_prev_config_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code_analytique TEXT NOT NULL UNIQUE,
            secteur_id INTEGER NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (secteur_id) REFERENCES secteurs(id) ON DELETE CASCADE
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS budget_prev_saisies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type_budget TEXT NOT NULL CHECK(type_budget IN ('initial', 'actualise')),
            annee INTEGER NOT NULL,
            secteur_id INTEGER NOT NULL,
            compte_num TEXT NOT NULL,
            valeur_temp REAL,
            valeur_def REAL DEFAULT 0,
            commentaire TEXT,
            updated_by INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (secteur_id) REFERENCES secteurs(id) ON DELETE CASCADE,
            FOREIGN KEY (updated_by) REFERENCES users(id),
            UNIQUE(type_budget, annee, secteur_id, compte_num)
        )
    ''')

    conn.commit()
