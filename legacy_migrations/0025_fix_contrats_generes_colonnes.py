"""
Migration 0025 : Correction du schema de contrats_generes.

Corrige les bases dont la table contrats_generes a ete creee avec une version
intermediaire du schema (colonnes manquantes ou contraintes NOT NULL erronees
sur des colonnes inconnues comme fichier_pdf_path).

Strategie :
- Si la table possede une colonne tierce avec NOT NULL qui n'est pas connue
  de l'application, on recrée la table avec le schema canonique (en conservant
  les donnees des colonnes connues).
- Sinon, on ajoute simplement les colonnes manquantes.
"""

NOM = "Correction schema contrats_generes"
DESCRIPTION = (
    "Recreee la table contrats_generes si des colonnes NOT NULL inconnues "
    "bloquent les insertions, et ajoute les colonnes manquantes le cas echeant."
)

# Colonnes attendues par l'application (nom -> (type, has_default))
_COLONNES_CIBLES = [
    ('id',          'INTEGER', True),
    ('user_id',     'INTEGER', True),
    ('fichier_path','TEXT',    False),
    ('fichier_nom', 'TEXT',    False),
    ('type_contrat','TEXT',    False),
    ('created_by',  'INTEGER', False),
    ('created_at',  'TEXT',    False),
]

_NOMS_COLONNES_CIBLES = {c[0] for c in _COLONNES_CIBLES}


def _colonnes_existantes(cursor):
    """Retourne un dict {nom: row} depuis PRAGMA table_info."""
    cursor.execute("PRAGMA table_info(contrats_generes)")
    # row: (cid, name, type, notnull, dflt_value, pk)
    return {row[1]: row for row in cursor.fetchall()}


def _a_colonne_not_null_inconnue(cols_info):
    """Retourne True si la table a une colonne NOT NULL absente du schema cible."""
    for name, row in cols_info.items():
        notnull = row[3]
        if notnull and name not in _NOMS_COLONNES_CIBLES:
            return True
    return False


def _recreer_table(cursor, cols_info):
    """Recreee contrats_generes avec le schema canonique en preservant les donnees."""
    # Determiner les colonnes a copier : intersection old ∩ cible, hors id.
    # cols_a_copier ne contient que des noms provenant de _NOMS_COLONNES_CIBLES
    # (valeurs en dur), jamais de donnees utilisateur.
    cols_a_copier = [
        c for c in _NOMS_COLONNES_CIBLES
        if c != 'id' and c in cols_info
    ]
    cols_str = ', '.join(cols_a_copier)

    cursor.execute('''
        CREATE TABLE contrats_generes_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            fichier_path TEXT,
            fichier_nom TEXT,
            type_contrat TEXT,
            created_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    ''')
    if cols_a_copier:
        cursor.execute(  # noqa: S608
            f"INSERT INTO contrats_generes_new ({cols_str}) "
            f"SELECT {cols_str} FROM contrats_generes"
        )
    cursor.execute("DROP TABLE contrats_generes")
    cursor.execute("ALTER TABLE contrats_generes_new RENAME TO contrats_generes")


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='contrats_generes'"
    )
    if not cursor.fetchone():
        # La table n'existe pas encore : la creer avec le schema complet
        cursor.execute('''
            CREATE TABLE contrats_generes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                fichier_path TEXT,
                fichier_nom TEXT,
                type_contrat TEXT,
                created_by INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (created_by) REFERENCES users(id)
            )
        ''')
    else:
        cols_info = _colonnes_existantes(cursor)

        if _a_colonne_not_null_inconnue(cols_info):
            # Colonne tierce NOT NULL bloquante : recreer la table proprement
            _recreer_table(cursor, cols_info)
        else:
            # Ajouter uniquement les colonnes manquantes
            for col, typedef, _ in _COLONNES_CIBLES:
                if col in ('id', 'user_id'):
                    continue  # colonnes structurelles obligatoires, toujours presentes
                if col not in cols_info:
                    default = " DEFAULT CURRENT_TIMESTAMP" if col == 'created_at' else ""
                    cursor.execute(
                        f"ALTER TABLE contrats_generes ADD COLUMN {col} {typedef}{default}"
                    )

    conn.commit()
