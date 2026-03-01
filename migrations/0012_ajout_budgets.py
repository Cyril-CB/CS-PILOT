"""
Migration 0012 : Ajout du systeme de gestion budgetaire.

- Ajoute type_secteur a la table secteurs
- Cree la table postes_depense (categories de depenses)
- Cree la table postes_depense_secteur_types (association postes <-> types de secteur)
- Cree la table budgets (budget global par secteur/annee)
- Cree la table budget_lignes (repartition par poste et periode)
- Insere les postes de depense par defaut avec leurs associations
"""

NOM = "Ajout systeme budgetaire"
DESCRIPTION = (
    "Ajoute les tables pour la gestion des budgets par secteur : "
    "postes de depense configurables, budgets globaux et repartition "
    "par type de depense avec support des periodes pour l'accueil de loisirs."
)

# Types de secteur disponibles
TYPES_SECTEUR = [
    'creche',
    'accueil_loisirs',
    'famille',
    'emploi_formation',
    'administratif',
]

# Postes de depense par defaut avec les types de secteur associes
POSTES_DEFAUT = [
    # Communs a tous
    ('Alimentation', ['creche', 'accueil_loisirs', 'famille', 'emploi_formation', 'administratif']),
    ("Fournitures d'activites", ['creche', 'accueil_loisirs', 'famille', 'emploi_formation', 'administratif']),
    ('Petit equipement', ['creche', 'accueil_loisirs', 'famille', 'emploi_formation', 'administratif']),
    ("Petit equipement d'activite", ['creche', 'accueil_loisirs', 'famille', 'emploi_formation', 'administratif']),
    ('Honoraires', ['creche', 'accueil_loisirs', 'famille', 'emploi_formation', 'administratif']),
    ('Mission/reception', ['creche', 'accueil_loisirs', 'famille', 'emploi_formation', 'administratif']),
    # Creche + Accueil de loisirs
    ('Restauration', ['creche', 'accueil_loisirs']),
    # Creche uniquement
    ('Couches', ['creche']),
    ('Reparation', ['creche']),
    # Famille + Accueil de loisirs
    ('Transport', ['famille', 'accueil_loisirs']),
    ('Sorties', ['famille', 'accueil_loisirs']),
    # Administratif uniquement
    ('Fournitures de bureau', ['administratif']),
    ("Produit d'entretien", ['administratif']),
]


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    # --- Ajouter type_secteur a la table secteurs ---
    cols = [row[1] for row in cursor.execute('PRAGMA table_info(secteurs)').fetchall()]
    if 'type_secteur' not in cols:
        cursor.execute("ALTER TABLE secteurs ADD COLUMN type_secteur TEXT DEFAULT NULL")

    # --- Table des postes de depense ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS postes_depense (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL UNIQUE,
            actif INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # --- Table d'association postes <-> types de secteur ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS postes_depense_secteur_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            poste_depense_id INTEGER NOT NULL,
            type_secteur TEXT NOT NULL,
            FOREIGN KEY (poste_depense_id) REFERENCES postes_depense(id) ON DELETE CASCADE,
            UNIQUE(poste_depense_id, type_secteur)
        )
    ''')

    # --- Table des budgets (un budget global par secteur et par annee) ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            secteur_id INTEGER NOT NULL,
            annee INTEGER NOT NULL,
            montant_global REAL NOT NULL DEFAULT 0,
            cree_par INTEGER,
            modifie_par INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (secteur_id) REFERENCES secteurs(id) ON DELETE CASCADE,
            FOREIGN KEY (cree_par) REFERENCES users(id),
            FOREIGN KEY (modifie_par) REFERENCES users(id),
            UNIQUE(secteur_id, annee)
        )
    ''')

    # --- Table des lignes budgetaires (repartition par poste et periode) ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS budget_lignes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            budget_id INTEGER NOT NULL,
            poste_depense_id INTEGER NOT NULL,
            periode TEXT NOT NULL DEFAULT 'annuel',
            montant REAL NOT NULL DEFAULT 0,
            modifie_par INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (budget_id) REFERENCES budgets(id) ON DELETE CASCADE,
            FOREIGN KEY (poste_depense_id) REFERENCES postes_depense(id) ON DELETE CASCADE,
            FOREIGN KEY (modifie_par) REFERENCES users(id),
            UNIQUE(budget_id, poste_depense_id, periode)
        )
    ''')

    # --- Inserer les postes de depense par defaut ---
    for nom_poste, types in POSTES_DEFAUT:
        # Inserer le poste s'il n'existe pas
        existing = cursor.execute(
            'SELECT id FROM postes_depense WHERE nom = ?', (nom_poste,)
        ).fetchone()
        if existing:
            poste_id = existing[0]
        else:
            cursor.execute(
                'INSERT INTO postes_depense (nom) VALUES (?)', (nom_poste,)
            )
            poste_id = cursor.lastrowid

        # Inserer les associations avec les types de secteur
        for type_s in types:
            cursor.execute('''
                INSERT OR IGNORE INTO postes_depense_secteur_types (poste_depense_id, type_secteur)
                VALUES (?, ?)
            ''', (poste_id, type_s))

    conn.commit()
