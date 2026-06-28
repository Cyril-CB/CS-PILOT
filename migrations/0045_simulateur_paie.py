"""
Migration 0045 : Ajout du simulateur de paie (masse salariale).

- users.competence       : points de compétence (à côté de la pesée ALISFA),
                           utilisés dans le calcul du brut.
- budget_paie_simulations : saisies du simulateur de paie, attachées à l'année,
                           au secteur et au type de budget (initial/actualisé).
"""

NOM = "Ajout simulateur de paie"
DESCRIPTION = (
    "Ajoute la colonne users.competence et la table budget_paie_simulations "
    "pour le simulateur de masse salariale du budget prévisionnel."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    # Colonne competence sur users (si absente)
    try:
        cursor.execute("SELECT competence FROM users LIMIT 1")
    except Exception:
        cursor.execute("ALTER TABLE users ADD COLUMN competence INTEGER")

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS budget_paie_simulations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            annee INTEGER NOT NULL,
            secteur_id INTEGER NOT NULL,
            type_budget TEXT NOT NULL CHECK(type_budget IN ('initial', 'actualise')),
            compte_num TEXT,
            donnees TEXT,
            total REAL DEFAULT 0,
            updated_by INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (secteur_id) REFERENCES secteurs(id) ON DELETE CASCADE,
            FOREIGN KEY (updated_by) REFERENCES users(id),
            UNIQUE(annee, secteur_id, type_budget)
        )
    ''')


def downgrade(conn):
    """Supprime la table de simulation (la colonne competence est conservée)."""
    conn.cursor().execute('DROP TABLE IF EXISTS budget_paie_simulations')
