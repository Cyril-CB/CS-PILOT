"""
Migration 0006 : Ajout prepa paie et champs CEE contrats.

Ajoute les colonnes forfait et nbr_jours a la table contrats (pour CEE),
et cree la table prepa_paie_statut pour le suivi mensuel de preparation de paie.
"""

NOM = "Ajout prepa paie et champs CEE contrats"
DESCRIPTION = (
    "Ajoute forfait et nbr_jours dans contrats. "
    "Cree la table prepa_paie_statut pour le suivi mensuel."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    # Ajouter colonnes forfait et nbr_jours a la table contrats
    try:
        cursor.execute("SELECT forfait FROM contrats LIMIT 1")
    except Exception:
        cursor.execute("ALTER TABLE contrats ADD COLUMN forfait TEXT")

    try:
        cursor.execute("SELECT nbr_jours FROM contrats LIMIT 1")
    except Exception:
        cursor.execute("ALTER TABLE contrats ADD COLUMN nbr_jours REAL")

    # Table de suivi du statut traite par mois (prepa paie)
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='prepa_paie_statut'")
    if not cursor.fetchone():
        cursor.execute('''
            CREATE TABLE prepa_paie_statut (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                mois INTEGER NOT NULL,
                annee INTEGER NOT NULL,
                traite INTEGER NOT NULL DEFAULT 0,
                traite_par INTEGER,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, mois, annee),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (traite_par) REFERENCES users(id)
            )
        ''')
