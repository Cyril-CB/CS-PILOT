"""
Migration 0023 : Archivage des exportations d'ecritures.

Ajoute la table archives_export pour conserver les fichiers exportes.
"""

NOM = "Archivage exportations ecritures"
DESCRIPTION = "Ajoute la table archives_export pour l'historique des exports."


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS archives_export (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom_fichier TEXT NOT NULL,
            fichier_path TEXT NOT NULL,
            nb_ecritures INTEGER DEFAULT 0,
            created_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    ''')

    conn.commit()
