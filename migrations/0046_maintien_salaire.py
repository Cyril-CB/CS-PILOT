"""
Migration 0046 : Ajout du maintien de salaire.

Certains salariés disposent d'un « maintien » de salaire (mis en place lors du
changement de mode de calcul des salaires). Ce montant mensuel s'ajoute au brut
dans le simulateur de paie. Colonne users.maintien (défaut 0).
"""

NOM = "Ajout maintien de salaire"
DESCRIPTION = "Ajoute la colonne users.maintien (montant mensuel ajouté au brut)."


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT maintien FROM users LIMIT 1")
    except Exception:
        cursor.execute("ALTER TABLE users ADD COLUMN maintien REAL DEFAULT 0")


def downgrade(conn):
    """Pas de downgrade (la colonne est conservée)."""
    conn.commit()
