"""
Migration 0027 : Ajout du module de gestion des types de secteur.

- Cree la table types_secteur pour gerer dynamiquement les types de secteur
- Ajoute les types par defaut existants + Entretien
"""

NOM = "Ajout gestion des types de secteur"
DESCRIPTION = (
    "Ajoute la table types_secteur pour permettre la gestion dynamique "
    "des types de secteur (Creche, Accueil de loisirs, Entretien, etc.)"
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    # Creer la table types_secteur
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS types_secteur (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            libelle TEXT NOT NULL,
            ordre INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Inserer les types par defaut (incluant le nouveau type Entretien)
    types_defaut = [
        ('creche', 'Crèche', 1),
        ('accueil_loisirs', 'Accueil de loisirs', 2),
        ('famille', 'Secteur famille', 3),
        ('emploi_formation', 'Emploi/formation', 4),
        ('administratif', 'Administratif', 5),
        ('entretien', 'Entretien', 6),
    ]

    for code, libelle, ordre in types_defaut:
        cursor.execute('''
            INSERT OR IGNORE INTO types_secteur (code, libelle, ordre)
            VALUES (?, ?, ?)
        ''', (code, libelle, ordre))

    conn.commit()
