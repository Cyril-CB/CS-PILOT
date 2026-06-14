"""
Migration 0039 : Journal des actions metier (audit).

Ajoute la table journal_actions pour tracer les actions qui modifient l'etat
de l'application (cloture mensuelle des conges, enregistrement des variables de
paie, statut de preparation de paie, ajout de contrats et de documents
salaries, generation de contrats...). Complementaire de journal_acces, qui ne
couvre que les evenements de connexion.
"""

NOM = "Journal des actions metier"
DESCRIPTION = (
    "Ajoute la table journal_actions pour tracer les actions sensibles qui "
    "modifient l'etat (qui a fait quoi, sur quelle cible, quand)."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS journal_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_heure TEXT DEFAULT CURRENT_TIMESTAMP,
            user_id INTEGER,
            action TEXT NOT NULL,
            cible_type TEXT,
            cible_id INTEGER,
            details TEXT,
            adresse_ip TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_journal_actions_date ON journal_actions(date_heure)"
    )
    conn.commit()


def downgrade(conn):
    """Annule la migration."""
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS journal_actions")
    conn.commit()
