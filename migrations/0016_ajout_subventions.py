"""
Migration 0016 : Ajout du module de gestion des subventions.

- Cree la table subventions_analytiques (projets / lignes analytiques)
- Cree la table subventions (dossiers de subvention)
- Cree la table subventions_sous_elements (etapes par subvention)
"""

NOM = "Ajout gestion des subventions"
DESCRIPTION = (
    "Ajoute les tables pour la gestion des subventions : "
    "dossiers de subvention avec suivi par statut, sous-elements "
    "(etapes), projets analytiques et justificatifs PDF."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    # --- Table des projets analytiques ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subventions_analytiques (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL UNIQUE,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # --- Table des subventions ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subventions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            groupe TEXT NOT NULL DEFAULT 'nouveau_projet',
            assignee_1_id INTEGER,
            assignee_2_id INTEGER,
            date_echeance TEXT,
            montant_demande REAL DEFAULT 0,
            montant_accorde REAL DEFAULT 0,
            date_notification TEXT,
            justificatif_path TEXT,
            justificatif_nom TEXT,
            analytique_id INTEGER,
            contact_email TEXT,
            compte_comptable TEXT,
            ordre INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (assignee_1_id) REFERENCES users(id),
            FOREIGN KEY (assignee_2_id) REFERENCES users(id),
            FOREIGN KEY (analytique_id) REFERENCES subventions_analytiques(id)
        )
    ''')

    # --- Table des sous-elements (etapes) ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subventions_sous_elements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subvention_id INTEGER NOT NULL,
            nom TEXT NOT NULL,
            assignee_id INTEGER,
            statut TEXT NOT NULL DEFAULT 'non_commence',
            date_echeance TEXT,
            ordre INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (subvention_id) REFERENCES subventions(id) ON DELETE CASCADE,
            FOREIGN KEY (assignee_id) REFERENCES users(id)
        )
    ''')

    conn.commit()
