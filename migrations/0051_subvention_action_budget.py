"""
Migration 0051 : Colonne « Budget » (action analytique) sur les subventions.

Remplace les anciennes colonnes analytiques de la page subventions par un
rattachement direct a une action du plan comptable analytique / bilan-action.
Ajoute subventions.action_budget_id (FK comptabilite_actions).
"""

NOM = "Ajout action budget aux subventions"
DESCRIPTION = "Ajoute la colonne subventions.action_budget_id (action analytique liee au budget)."


def upgrade(conn):
    """Applique la migration (idempotente)."""
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT action_budget_id FROM subventions LIMIT 1")
    except Exception:
        cursor.execute("ALTER TABLE subventions ADD COLUMN action_budget_id INTEGER")
    conn.commit()


def downgrade(conn):
    """Pas de downgrade (la colonne est conservée)."""
    conn.commit()
