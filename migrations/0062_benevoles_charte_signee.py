"""
Migration 0062 : charte du bénévolat signée.

La fiche contact tenue sur tableur porte une case « Charte signée » ; elle
manquait sur la liste des bénévoles. Colonne `charte_signee` (0/1, non signée
par défaut : l'information n'est pas connue rétroactivement).
"""

NOM = "Charte du bénévolat signée"
DESCRIPTION = (
    "Ajoute benevoles.charte_signee (INTEGER 0/1) pour suivre la signature "
    "de la charte du bénévolat."
)


def upgrade(conn):
    """Applique la migration (idempotente)."""
    import sqlite3
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT charte_signee FROM benevoles LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute(
            "ALTER TABLE benevoles ADD COLUMN charte_signee INTEGER DEFAULT 0")
    conn.commit()


def downgrade(conn):
    """SQLite ne supprime pas simplement une colonne : downgrade non destructif
    (la colonne reste, inerte tant que le code ne la lit pas)."""
    pass
