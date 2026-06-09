"""
Migration 0037 : Journal des acces (securite).

Ajoute la table journal_acces pour la journalisation des connexions a
l'application : connexions reussies, echecs de connexion, demandes de
reinitialisation et modifications de mot de passe. Le journal est consultable
par la direction via le menu Administration > Securite.
"""

NOM = "Journal des acces"
DESCRIPTION = (
    "Ajoute la table journal_acces pour tracer les connexions a l'application "
    "(connexions reussies, echecs, reinitialisations et changements de mot de passe)."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS journal_acces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_heure TEXT DEFAULT CURRENT_TIMESTAMP,
            login_saisi TEXT,
            user_id INTEGER,
            evenement TEXT NOT NULL,
            adresse_ip TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_journal_acces_date ON journal_acces(date_heure)"
    )
    conn.commit()


def downgrade(conn):
    """Annule la migration."""
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS journal_acces")
    conn.commit()
