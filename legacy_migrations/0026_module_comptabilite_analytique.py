"""
Migration 0026 : Module comptabilite analytique.

Cree les tables pour le plan comptable analytique et le bilan secteurs/actions :
- comptabilite_actions : liste des actions analytiques
- comptabilite_comptes : plan comptable analytique (compte, libelle, secteur, action)
- bilan_fec_imports : historique des imports FEC pour le bilan
- bilan_fec_donnees : donnees FEC (charges 6x, produits 7x) avec code analytique
- bilan_taux_logistique : taux de logistique par annee (site1, site2, global)
"""

NOM = "Module comptabilite analytique"
DESCRIPTION = (
    "Cree les tables comptabilite_actions, comptabilite_comptes, "
    "bilan_fec_imports, bilan_fec_donnees, bilan_taux_logistique."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='comptabilite_actions'")
    if not cursor.fetchone():
        cursor.execute('''
            CREATE TABLE comptabilite_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nom TEXT NOT NULL UNIQUE,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='comptabilite_comptes'")
    if not cursor.fetchone():
        cursor.execute('''
            CREATE TABLE comptabilite_comptes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                compte_num TEXT NOT NULL UNIQUE,
                libelle TEXT NOT NULL,
                secteur_id INTEGER,
                action_id INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (secteur_id) REFERENCES secteurs(id),
                FOREIGN KEY (action_id) REFERENCES comptabilite_actions(id)
            )
        ''')

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bilan_fec_imports'")
    if not cursor.fetchone():
        cursor.execute('''
            CREATE TABLE bilan_fec_imports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fichier_nom TEXT NOT NULL,
                annee INTEGER NOT NULL,
                nb_ecritures INTEGER DEFAULT 0,
                importe_par INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (importe_par) REFERENCES users(id)
            )
        ''')

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bilan_fec_donnees'")
    if not cursor.fetchone():
        cursor.execute('''
            CREATE TABLE bilan_fec_donnees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                compte_num TEXT NOT NULL,
                libelle TEXT,
                code_analytique TEXT,
                annee INTEGER NOT NULL,
                mois INTEGER NOT NULL,
                montant REAL NOT NULL DEFAULT 0,
                import_id INTEGER,
                FOREIGN KEY (import_id) REFERENCES bilan_fec_imports(id) ON DELETE CASCADE
            )
        ''')

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bilan_taux_logistique'")
    if not cursor.fetchone():
        cursor.execute('''
            CREATE TABLE bilan_taux_logistique (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                annee INTEGER NOT NULL UNIQUE,
                taux_site1 REAL DEFAULT 0,
                taux_site2 REAL DEFAULT 0,
                taux_global REAL DEFAULT 0,
                taux_selectionne TEXT DEFAULT 'global',
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
