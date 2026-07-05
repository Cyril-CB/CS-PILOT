"""
Migration 0054 : Journal des recherches (barre intelligente).

Crée la table recherche_log qui trace les termes saisis dans la barre de
recherche intelligente des tableaux de bord (Direction / Comptable) et le fait
que la recherche ait abouti ou non. Permet à la direction de consulter les
termes réellement utilisés (onglet « Barre intelligente » du journal de
sécurité) afin d'enrichir les synonymes reconnus par le moteur.

Aucune donnée sensible n'est stockée : uniquement le terme saisi, le type de
résultat (redirect / choices / none) et un libellé de destination.
"""

NOM = "Journal des recherches (barre intelligente)"
DESCRIPTION = (
    "Crée la table recherche_log pour tracer les termes de la barre de "
    "recherche intelligente et savoir s'ils ont abouti."
)


def upgrade(conn):
    """Applique la migration (idempotente)."""
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS recherche_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_heure TEXT DEFAULT CURRENT_TIMESTAMP,
            user_id INTEGER,
            terme TEXT NOT NULL,
            type_resultat TEXT,
            a_resultat INTEGER DEFAULT 0,
            libelle TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_recherche_log_date ON recherche_log(date_heure)"
    )
    conn.commit()


def downgrade(conn):
    """Supprime la table du journal des recherches."""
    conn.cursor().execute("DROP TABLE IF EXISTS recherche_log")
    conn.commit()
