"""
Migration 0008 : Ajout table de suivi des clotures mensuelles de conges.

Permet de tracer quels mois ont deja ete clotures pour eviter les doublons.
"""

NOM = "Ajout table cloture conges mensuelle"
DESCRIPTION = (
    "Cree la table conges_cloture_mensuelle pour le suivi "
    "des clotures mensuelles de conges."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='conges_cloture_mensuelle'")
    if not cursor.fetchone():
        cursor.execute('''
            CREATE TABLE conges_cloture_mensuelle (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mois INTEGER NOT NULL,
                annee INTEGER NOT NULL,
                cloture_le TEXT DEFAULT CURRENT_TIMESTAMP,
                cloture_par INTEGER NOT NULL,
                nb_salaries_traites INTEGER DEFAULT 0,
                detail TEXT,
                UNIQUE(mois, annee),
                FOREIGN KEY (cloture_par) REFERENCES users(id)
            )
        ''')
