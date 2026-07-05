"""
Migration 0052 : Types de subvention (categories par type).

- Cree la table subventions_types (types manageables : creation / suppression)
- Insere les types par defaut (SUBV. GLOBAL, CAF PS, CAF, VILLE, METROPOLE,
  ETAT, AUTRES)
- Ajoute la colonne subventions.type_id (FK subventions_types)

La page subventions regroupe desormais les dossiers par type de subvention
(organisme financeur) au lieu du statut. Le statut (groupe) est conserve pour
les tableaux de bord.
"""

NOM = "Types de subvention"
DESCRIPTION = (
    "Ajoute la table subventions_types (types manageables) et la colonne "
    "subventions.type_id pour regrouper les subventions par type."
)

# (nom, couleur, ordre)
TYPES_DEFAUT = [
    ('SUBV. GLOBAL', '#579bfc', 0),
    ('CAF PS', '#00c875', 1),
    ('CAF', '#a25ddc', 2),
    ('VILLE', '#fdab3d', 3),
    ('METROPOLE', '#e2445c', 4),
    ('ETAT', '#037f4c', 5),
    ('AUTRES', '#808080', 6),
]


def _column_exists(cursor, table, column):
    """Verifie si une colonne existe dans une table."""
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def upgrade(conn):
    """Applique la migration (idempotente)."""
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subventions_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL UNIQUE,
            couleur TEXT DEFAULT '#579bfc',
            ordre INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Seed des types par defaut uniquement si la table est vide.
    cursor.execute("SELECT COUNT(*) FROM subventions_types")
    if cursor.fetchone()[0] == 0:
        for nom, couleur, ordre in TYPES_DEFAUT:
            cursor.execute(
                'INSERT INTO subventions_types (nom, couleur, ordre) VALUES (?, ?, ?)',
                (nom, couleur, ordre)
            )

    if not _column_exists(cursor, 'subventions', 'type_id'):
        cursor.execute(
            "ALTER TABLE subventions ADD COLUMN type_id INTEGER REFERENCES subventions_types(id)"
        )

    conn.commit()


def downgrade(conn):
    """Pas de downgrade (les donnees sont conservees)."""
    conn.commit()
