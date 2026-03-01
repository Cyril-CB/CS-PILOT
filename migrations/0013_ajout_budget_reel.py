"""
Migration 0013 : Ajout de la table budget_reel_lignes.

Permet de stocker les depenses reelles par poste et par periode,
mises a jour periodiquement par la direction ou le comptable.
Les responsables peuvent comparer budget previsionnel vs reel.
"""

NOM = "Ajout budget reel (depenses effectives)"
DESCRIPTION = (
    "Ajoute la table budget_reel_lignes pour stocker les depenses "
    "reelles par poste de depense et par periode, permettant le suivi "
    "previsionnel vs reel."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS budget_reel_lignes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            budget_id INTEGER NOT NULL,
            poste_depense_id INTEGER NOT NULL,
            periode TEXT NOT NULL DEFAULT 'annuel',
            montant REAL NOT NULL DEFAULT 0,
            commentaire TEXT,
            modifie_par INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (budget_id) REFERENCES budgets(id) ON DELETE CASCADE,
            FOREIGN KEY (poste_depense_id) REFERENCES postes_depense(id) ON DELETE CASCADE,
            FOREIGN KEY (modifie_par) REFERENCES users(id),
            UNIQUE(budget_id, poste_depense_id, periode)
        )
    ''')

    conn.commit()
