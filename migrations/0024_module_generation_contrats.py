"""
Migration 0024 : Module generation contrats.
Ajoute les champs salarie utiles aux contrats et les tables du module.
"""

NOM = "Module generation contrats"
DESCRIPTION = (
    "Ajoute adresse/SS/date de naissance sur users et "
    "les tables de generation de contrats."
)


def _add_column_if_missing(cursor, table, column, column_def):
    cursor.execute(f"PRAGMA table_info({table})")
    columns = {row[1] for row in cursor.fetchall()}
    if column not in columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}")


def upgrade(conn):
    cursor = conn.cursor()

    _add_column_if_missing(cursor, "users", "adresse_postale", "TEXT")
    _add_column_if_missing(cursor, "users", "numero_securite_sociale", "TEXT")
    _add_column_if_missing(cursor, "users", "date_naissance", "TEXT")

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contrats_modeles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom_modele TEXT NOT NULL,
            fichier_path TEXT NOT NULL,
            saisi_par INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (saisi_par) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contrats_lieux (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL UNIQUE,
            adresse TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contrats_forfaits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            montant TEXT NOT NULL,
            condition_label TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contrats_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            salaire_socle REAL NOT NULL DEFAULT 23000,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO contrats_settings (id, salaire_socle)
        VALUES (1, 23000)
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contrats_generes (
            user_id INTEGER PRIMARY KEY,
            template_id INTEGER,
            fichier_pdf_path TEXT NOT NULL,
            fichier_pdf_nom TEXT NOT NULL,
            generated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            generated_by INTEGER,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (template_id) REFERENCES contrats_modeles(id),
            FOREIGN KEY (generated_by) REFERENCES users(id)
        )
    ''')
