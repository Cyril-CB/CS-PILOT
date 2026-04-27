"""
Migration 0032 : ajout du flag de changement obligatoire du mot de passe.
"""

NOM = "Ajout force_password_change"
DESCRIPTION = "Ajoute le flag force_password_change sur les utilisateurs."


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()
    cols = {row[1] for row in cursor.execute("PRAGMA table_info(users)").fetchall()}
    if 'force_password_change' not in cols:
        cursor.execute("ALTER TABLE users ADD COLUMN force_password_change INTEGER DEFAULT 0")
    conn.commit()


def downgrade(conn):
    """Pas de downgrade automatique sur SQLite pour cette colonne."""
    conn.commit()
