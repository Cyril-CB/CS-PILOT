"""
Migration 0014 : Ajout table frequentation_creche.

Stocke le nombre moyen d'enfants par tranche horaire pour chaque secteur creche.
Utilise pour calculer le taux d'encadrement requis sur la page mon_equipe.
"""

NOM = "Ajout frequentation creche"
DESCRIPTION = (
    "Cree la table frequentation_creche pour stocker le nombre moyen "
    "d'enfants par tranche horaire (calcul taux d'encadrement)."
)


def upgrade(conn):
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='frequentation_creche'")
    if not cursor.fetchone():
        cursor.execute('''
            CREATE TABLE frequentation_creche (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                secteur_id INTEGER NOT NULL,
                tranche TEXT NOT NULL,
                nb_enfants REAL DEFAULT 0,
                updated_by INTEGER,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (secteur_id) REFERENCES secteurs(id),
                FOREIGN KEY (updated_by) REFERENCES users(id),
                UNIQUE(secteur_id, tranche)
            )
        ''')
