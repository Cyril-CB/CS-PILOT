"""
Migration 0018 : Ajout du module de gestion des salles.

- Cree la table salles (liste des salles disponibles)
- Cree la table recurrences_salles (reservations recurrentes)
- Cree la table reservations_salles (reservations ponctuelles et instances de recurrences)
"""

NOM = "Ajout gestion des salles"
DESCRIPTION = (
    "Ajoute les tables salles, recurrences_salles et reservations_salles "
    "pour la gestion des reservations de salles avec support des "
    "recurrences excluant vacances scolaires et jours feries."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS salles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            capacite INTEGER,
            description TEXT DEFAULT '',
            couleur TEXT DEFAULT '#2563eb',
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS recurrences_salles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            salle_id INTEGER NOT NULL,
            titre TEXT NOT NULL,
            description TEXT DEFAULT '',
            jour_semaine INTEGER NOT NULL,
            heure_debut TEXT NOT NULL,
            heure_fin TEXT NOT NULL,
            date_debut TEXT NOT NULL,
            date_fin TEXT NOT NULL,
            exclure_vacances INTEGER DEFAULT 1,
            exclure_feries INTEGER DEFAULT 1,
            active INTEGER DEFAULT 1,
            created_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (salle_id) REFERENCES salles(id),
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reservations_salles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            salle_id INTEGER NOT NULL,
            titre TEXT NOT NULL,
            description TEXT DEFAULT '',
            date TEXT NOT NULL,
            heure_debut TEXT NOT NULL,
            heure_fin TEXT NOT NULL,
            recurrence_id INTEGER,
            created_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (salle_id) REFERENCES salles(id),
            FOREIGN KEY (recurrence_id) REFERENCES recurrences_salles(id) ON DELETE CASCADE,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    ''')

    conn.commit()
