"""
Migration 0063 : Délégation de la gestion des bénévoles.

Par défaut, le répertoire des bénévoles et le suivi des heures sont tenus par
la direction et la comptabilité. Cette table permet de confier l'intégralité de
la page bénévoles à un ou plusieurs salariés, depuis la page Délégation.
"""

NOM = "Délégation gestion des bénévoles"
DESCRIPTION = (
    "Ajoute la table delegations_benevoles (salariés chargés de la gestion "
    "complète de la page bénévoles : répertoire et suivi des heures)."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS delegations_benevoles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            granted_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (granted_by) REFERENCES users(id)
        )
    ''')


def downgrade(conn):
    """Suppression de la table de délégation des bénévoles."""
    cursor = conn.cursor()
    cursor.execute('DROP TABLE IF EXISTS delegations_benevoles')
    conn.commit()
