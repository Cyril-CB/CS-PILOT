"""
Migration 0048 : Délégation des réservations de salle récurrentes.

Par défaut, seuls les responsables (et la direction) peuvent créer des
réservations de salle récurrentes. Cette table permet à la direction de
déléguer ce droit à un ou plusieurs salariés, depuis la page Délégation.
"""

NOM = "Délégation récurrences de salle"
DESCRIPTION = (
    "Ajoute la table delegations_salles_recurrence (salariés autorisés à créer "
    "des réservations de salle récurrentes)."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS delegations_salles_recurrence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            granted_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (granted_by) REFERENCES users(id)
        )
    ''')


def downgrade(conn):
    """Suppression de la table de délégation des récurrences."""
    cursor = conn.cursor()
    cursor.execute('DROP TABLE IF EXISTS delegations_salles_recurrence')
    conn.commit()
