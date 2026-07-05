"""
Migration 0053 : Synonymes de secteurs.

Ajoute la colonne secteurs.synonymes (liste de termes séparés par des virgules)
utilisée par la barre de recherche intelligente pour reconnaître un secteur
depuis un alias (ex. « bab » → « Babilhome »).
"""

NOM = "Synonymes de secteurs"
DESCRIPTION = (
    "Ajoute la colonne secteurs.synonymes pour la reconnaissance des secteurs "
    "par la barre de recherche intelligente."
)


def _column_exists(cursor, table, column):
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def upgrade(conn):
    """Applique la migration (idempotente)."""
    cursor = conn.cursor()
    if not _column_exists(cursor, 'secteurs', 'synonymes'):
        cursor.execute("ALTER TABLE secteurs ADD COLUMN synonymes TEXT")
    conn.commit()


def downgrade(conn):
    """Pas de downgrade (la colonne est conservée)."""
    conn.commit()
