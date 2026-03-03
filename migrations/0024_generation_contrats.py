"""
Migration 0024 : Module de generation de contrats.

Ajoute les champs adresse, date_naissance, numero_secu dans users.
Cree les tables modeles_contrats, lieux_travail, forfaits_cee, contrats_generes.
"""

NOM = "Ajout module generation contrats"
DESCRIPTION = (
    "Ajoute adresse, date_naissance, numero_secu dans users. "
    "Cree les tables modeles_contrats, lieux_travail, forfaits_cee, contrats_generes."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    # Ajouter colonnes dans users
    nouveaux_champs = {'adresse', 'date_naissance', 'numero_secu'}
    for col, typedef in [
        ('adresse', 'TEXT'),
        ('date_naissance', 'TEXT'),
        ('numero_secu', 'TEXT'),
    ]:
        if col not in nouveaux_champs:
            continue
        try:
            cursor.execute(f"SELECT {col} FROM users LIMIT 1")  # noqa: S608
        except Exception:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {typedef}")  # noqa: S608

    # Table des modeles de contrats (fichiers DOCX uploades)
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='modeles_contrats'")
    if not cursor.fetchone():
        cursor.execute('''
            CREATE TABLE modeles_contrats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nom TEXT NOT NULL,
                fichier_path TEXT NOT NULL,
                fichier_nom TEXT NOT NULL,
                created_by INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (created_by) REFERENCES users(id)
            )
        ''')

    # Table des lieux de travail
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='lieux_travail'")
    if not cursor.fetchone():
        cursor.execute('''
            CREATE TABLE lieux_travail (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nom TEXT NOT NULL,
                adresse TEXT NOT NULL,
                created_by INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (created_by) REFERENCES users(id)
            )
        ''')

    # Table des forfaits CEE
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='forfaits_cee'")
    if not cursor.fetchone():
        cursor.execute('''
            CREATE TABLE forfaits_cee (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                montant REAL NOT NULL,
                condition TEXT,
                created_by INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (created_by) REFERENCES users(id)
            )
        ''')

    # Table des contrats generes (seulement le dernier par utilisateur)
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='contrats_generes'")
    if not cursor.fetchone():
        cursor.execute('''
            CREATE TABLE contrats_generes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                fichier_path TEXT NOT NULL,
                fichier_nom TEXT NOT NULL,
                type_contrat TEXT,
                created_by INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (created_by) REFERENCES users(id)
            )
        ''')
    else:
        # Ajouter les colonnes manquantes si la table existait sans elles
        for col, typedef in [
            ('fichier_path', 'TEXT'),
            ('fichier_nom', 'TEXT'),
            ('type_contrat', 'TEXT'),
            ('created_by', 'INTEGER'),
        ]:
            try:
                cursor.execute(f"SELECT {col} FROM contrats_generes LIMIT 1")  # noqa: S608
            except Exception:
                cursor.execute(
                    f"ALTER TABLE contrats_generes ADD COLUMN {col} {typedef}"  # noqa: S608
                )
