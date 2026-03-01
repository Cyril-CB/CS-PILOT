"""
Migration 0004 : Ajout des tables variables_paie et variables_paie_defauts.

Page mensuelle Variables Paie (comptable) pour renseigner les donnees
de paie de chaque salarie : mutuelle, enfants, transport, acompte,
saisie sur salaire, pret/avance, regularisations, commentaire.
"""

NOM = "Ajout tables variables paie"
DESCRIPTION = (
    "Cree les tables variables_paie (donnees mensuelles) et "
    "variables_paie_defauts (valeurs persistantes par salarie)."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    # Table des valeurs par defaut / persistantes (une ligne par salarie)
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='variables_paie_defauts'")
    if not cursor.fetchone():
        cursor.execute('''
            CREATE TABLE variables_paie_defauts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                mutuelle INTEGER NOT NULL DEFAULT 0,
                nb_enfants INTEGER NOT NULL DEFAULT 0,
                saisie_salaire REAL NOT NULL DEFAULT 0,
                pret_avance REAL NOT NULL DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')

    # Table des donnees mensuelles (une ligne par salarie par mois)
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='variables_paie'")
    if not cursor.fetchone():
        cursor.execute('''
            CREATE TABLE variables_paie (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                mois INTEGER NOT NULL,
                annee INTEGER NOT NULL,
                mutuelle INTEGER NOT NULL DEFAULT 0,
                nb_enfants INTEGER NOT NULL DEFAULT 0,
                transport REAL NOT NULL DEFAULT 0,
                acompte REAL NOT NULL DEFAULT 0,
                saisie_salaire REAL NOT NULL DEFAULT 0,
                pret_avance REAL NOT NULL DEFAULT 0,
                autres_regularisation REAL NOT NULL DEFAULT 0,
                commentaire TEXT,
                saisi_par INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, mois, annee),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (saisi_par) REFERENCES users(id)
            )
        ''')
