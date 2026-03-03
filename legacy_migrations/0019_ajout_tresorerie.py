"""
Migration 0019 : Ajout du module de tresorerie.

- Cree la table tresorerie_imports (suivi des imports FEC)
- Cree la table tresorerie_comptes (configuration des comptes)
- Cree la table tresorerie_donnees (montants mensuels par compte)
- Cree la table tresorerie_solde_initial (solde de tresorerie de depart)
- Cree la table tresorerie_budget_n (ajustements Budget N par compte/mois)
"""

NOM = "Ajout module tresorerie"
DESCRIPTION = (
    "Ajoute les tables pour le module de tresorerie : suivi des imports FEC, "
    "configuration des comptes comptables, donnees mensuelles par compte, "
    "solde initial de tresorerie et ajustements Budget N."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    # Suivi des imports FEC
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tresorerie_imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type_import TEXT NOT NULL,
            fichier_nom TEXT NOT NULL,
            annee INTEGER,
            mois_debut INTEGER,
            mois_fin INTEGER,
            nb_ecritures INTEGER DEFAULT 0,
            nb_comptes INTEGER DEFAULT 0,
            importe_par INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (importe_par) REFERENCES users(id)
        )
    ''')

    # Configuration des comptes comptables pour la tresorerie
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tresorerie_comptes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            compte_num TEXT NOT NULL UNIQUE,
            libelle_original TEXT,
            libelle_affiche TEXT,
            type_compte TEXT NOT NULL DEFAULT 'charge',
            actif INTEGER DEFAULT 1,
            ordre_affichage INTEGER DEFAULT 999,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Donnees mensuelles par compte (montant net = Credit - Debit)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tresorerie_donnees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            compte_num TEXT NOT NULL,
            annee INTEGER NOT NULL,
            mois INTEGER NOT NULL,
            montant REAL NOT NULL DEFAULT 0,
            import_id INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (import_id) REFERENCES tresorerie_imports(id),
            UNIQUE(compte_num, annee, mois)
        )
    ''')

    # Solde initial de tresorerie (point de depart de la projection)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tresorerie_solde_initial (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            annee INTEGER NOT NULL,
            mois INTEGER NOT NULL,
            montant REAL NOT NULL DEFAULT 0,
            saisi_par INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (saisi_par) REFERENCES users(id),
            UNIQUE(annee, mois)
        )
    ''')

    # Ajustements Budget N par compte et par mois
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tresorerie_budget_n (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            compte_num TEXT NOT NULL,
            annee INTEGER NOT NULL,
            mois INTEGER NOT NULL,
            montant REAL NOT NULL DEFAULT 0,
            saisi_par INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (saisi_par) REFERENCES users(id),
            UNIQUE(compte_num, annee, mois)
        )
    ''')

    conn.commit()
