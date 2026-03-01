"""
Migration 0017 : Ajout du module de gestion des benevoles.

- Cree la table benevoles (liste des benevoles avec statut et informations)
"""

NOM = "Ajout gestion des benevoles"
DESCRIPTION = (
    "Ajoute la table benevoles pour la gestion de la liste des "
    "benevoles avec statut, responsable assigne, coordonnees "
    "et suivi des heures par semaine."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS benevoles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            groupe TEXT NOT NULL DEFAULT 'nouveau',
            responsable_id INTEGER,
            date_debut TEXT,
            email TEXT,
            telephone TEXT,
            adresse TEXT,
            competences TEXT,
            heures_semaine TEXT DEFAULT '',
            ordre INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (responsable_id) REFERENCES users(id)
        )
    ''')

    conn.commit()
