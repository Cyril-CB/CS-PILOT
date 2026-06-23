"""
Migration 0042 : Ajout du simulateur de Prestation de Service (PS) CAF.

- budget_ps_comptes     : comptes de produits (70x) rattachés à une PS CAF
                          (type EAJE = crèche, ALSH = accueil de loisirs)
- budget_ps_simulations : saisies du simulateur, attachées au compte, à
                          l'année et au type de budget (initial/actualisé)
"""

NOM = "Ajout simulateur PS CAF"
DESCRIPTION = (
    "Ajoute les tables du simulateur de Prestation de Service CAF "
    "(comptes paramétrés et saisies des simulateurs EAJE/ALSH)."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS budget_ps_comptes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            compte_num TEXT NOT NULL UNIQUE,
            type_ps TEXT NOT NULL CHECK(type_ps IN ('eaje', 'alsh')),
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS budget_ps_simulations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            compte_num TEXT NOT NULL,
            annee INTEGER NOT NULL,
            type_budget TEXT NOT NULL CHECK(type_budget IN ('initial', 'actualise')),
            type_ps TEXT NOT NULL,
            secteur_id INTEGER,
            donnees TEXT,
            total REAL DEFAULT 0,
            updated_by INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (secteur_id) REFERENCES secteurs(id) ON DELETE SET NULL,
            FOREIGN KEY (updated_by) REFERENCES users(id),
            UNIQUE(compte_num, annee, type_budget)
        )
    ''')


def downgrade(conn):
    """Supprime les tables du simulateur de PS."""
    cursor = conn.cursor()
    cursor.execute('DROP TABLE IF EXISTS budget_ps_simulations')
    cursor.execute('DROP TABLE IF EXISTS budget_ps_comptes')
