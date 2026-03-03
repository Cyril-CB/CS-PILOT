"""
Migration 0009 : Ajout gestion des postes ALISFA et pesee salaries.

Cree la table postes_alisfa pour gerer les postes de l'association
avec classification CCN ALISFA, et ajoute la colonne pesee aux utilisateurs.
"""

NOM = "Ajout postes ALISFA et pesee salaries"
DESCRIPTION = (
    "Cree la table postes_alisfa pour la gestion des postes avec "
    "classification CCN ALISFA, et ajoute la colonne pesee aux utilisateurs."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    # Table des postes ALISFA
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='postes_alisfa'")
    if not cursor.fetchone():
        cursor.execute('''
            CREATE TABLE postes_alisfa (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                intitule TEXT NOT NULL,
                famille_metier TEXT NOT NULL,
                emploi_repere TEXT,
                formation_niveau INTEGER DEFAULT 1,
                complexite_niveau INTEGER DEFAULT 1,
                autonomie_niveau INTEGER DEFAULT 1,
                relationnel_niveau INTEGER DEFAULT 1,
                finances_niveau INTEGER DEFAULT 1,
                rh_niveau INTEGER DEFAULT 1,
                securite_niveau INTEGER DEFAULT 1,
                projet_niveau INTEGER DEFAULT 1,
                total_points INTEGER DEFAULT 0,
                created_by INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (created_by) REFERENCES users(id)
            )
        ''')

    # Ajouter la colonne pesee aux users
    try:
        cursor.execute("SELECT pesee FROM users LIMIT 1")
    except Exception:
        cursor.execute("ALTER TABLE users ADD COLUMN pesee INTEGER")
