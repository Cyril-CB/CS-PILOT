"""
Migration 0050 : Quantité sur les commandes salariés.

Ajoute la colonne quantite (entier, défaut 1) à la table commandes_salaries
afin de préciser le nombre d'unités demandées pour chaque fourniture.
"""

NOM = "Ajout quantité aux commandes salariés"
DESCRIPTION = "Ajoute la colonne commandes_salaries.quantite (nombre d'unités demandées, défaut 1)."


def upgrade(conn):
    """Applique la migration (idempotente)."""
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT quantite FROM commandes_salaries LIMIT 1")
    except Exception:
        cursor.execute(
            "ALTER TABLE commandes_salaries ADD COLUMN quantite INTEGER NOT NULL DEFAULT 1"
        )
    conn.commit()


def downgrade(conn):
    """Pas de downgrade (la colonne est conservée)."""
    conn.commit()
