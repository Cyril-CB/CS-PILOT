"""
Migration 0005 : Ajout infos salaries (email, contrats, documents).

Ajoute le champ email a la table users, cree les tables contrats
et documents_salaries pour la gestion des fiches de renseignement.
"""

NOM = "Ajout infos salaries"
DESCRIPTION = (
    "Ajoute email dans users. Cree les tables contrats et "
    "documents_salaries pour la page infos salaries."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    # Ajouter colonne email a la table users si elle n'existe pas
    try:
        cursor.execute("SELECT email FROM users LIMIT 1")
    except Exception:
        cursor.execute("ALTER TABLE users ADD COLUMN email TEXT")

    # Table des contrats (plusieurs par salarie)
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='contrats'")
    if not cursor.fetchone():
        cursor.execute('''
            CREATE TABLE contrats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                type_contrat TEXT NOT NULL,
                date_debut TEXT NOT NULL,
                date_fin TEXT,
                fichier_path TEXT,
                fichier_nom TEXT,
                saisi_par INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (saisi_par) REFERENCES users(id)
            )
        ''')

    # Table des documents salaries
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='documents_salaries'")
    if not cursor.fetchone():
        cursor.execute('''
            CREATE TABLE documents_salaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                type_document TEXT NOT NULL,
                description TEXT,
                fichier_path TEXT NOT NULL,
                fichier_nom TEXT NOT NULL,
                saisi_par INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (saisi_par) REFERENCES users(id)
            )
        ''')
