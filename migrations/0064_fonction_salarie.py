"""
Migration 0064 : fonction du salarié.

L'application connaissait le profil (droits) et le secteur, mais pas la
fonction occupée. Elle est désormais renseignée avec les informations de
contrat, et s'affiche sous le nom du salarié dans l'interface sans menu.

Deux objets :
- `users.fonction` : la fonction du salarié ;
- `fonctions` : la liste proposée, pré-remplie avec les fonctions courantes
  d'un centre social et complétable par la direction.
"""
import sqlite3

NOM = "Fonction du salarié"
DESCRIPTION = (
    "Ajoute users.fonction et la table fonctions (liste des fonctions "
    "proposées, complétable)."
)

# La liste de départ vit dans migrations/__init__.py : une base neuve
# (database.init_db) et une base migrée partent ainsi du même jeu.
from migrations import FONCTIONS_INITIALES


def upgrade(conn):
    """Applique la migration (idempotente)."""
    cursor = conn.cursor()

    try:
        cursor.execute('SELECT fonction FROM users LIMIT 1')
    except sqlite3.OperationalError:
        cursor.execute('ALTER TABLE users ADD COLUMN fonction TEXT')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS fonctions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            libelle TEXT NOT NULL UNIQUE,
            ordre INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    for ordre, libelle in enumerate(FONCTIONS_INITIALES):
        cursor.execute(
            'INSERT OR IGNORE INTO fonctions (libelle, ordre) VALUES (?, ?)',
            (libelle, ordre)
        )

    conn.commit()


def downgrade(conn):
    """Retire la liste des fonctions.

    SQLite ne supprime pas simplement une colonne : `users.fonction` reste en
    place, inerte tant que le code ne la lit pas.
    """
    cursor = conn.cursor()
    cursor.execute('DROP TABLE IF EXISTS fonctions')
    conn.commit()
