"""
Migration 0034 : Prévention santé au travail.
"""

NOM = "Prévention santé au travail"
DESCRIPTION = "Ajoute la table prevention_dismissals pour l'accusé de réception des messages de prévention."


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS prevention_dismissals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            message_key TEXT NOT NULL,
            dismissed_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, message_key),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )
    conn.commit()


def downgrade(conn):
    """Annule la migration."""
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS prevention_dismissals")
    conn.commit()

