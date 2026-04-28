"""
Migration 0032 : Commandes salariés et délégations.
"""

NOM = "Ajout commandes salariés et délégations"
DESCRIPTION = (
    "Ajoute les tables commandes_salaries et delegations_missions "
    "pour le suivi des fournitures et la délégation de mission."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS commandes_salaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date_demande TEXT NOT NULL,
            description TEXT NOT NULL,
            reference TEXT,
            prix REAL,
            urgence TEXT NOT NULL DEFAULT 'normal',
            groupe TEXT NOT NULL DEFAULT 'en_cours',
            traite_par INTEGER,
            date_traitement TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (traite_par) REFERENCES users(id)
        )
        '''
    )

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS delegations_missions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mission_key TEXT NOT NULL UNIQUE,
            delegated_user_id INTEGER NOT NULL,
            delegated_by_user_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (delegated_user_id) REFERENCES users(id),
            FOREIGN KEY (delegated_by_user_id) REFERENCES users(id)
        )
        '''
    )

    conn.commit()
