"""
Migration 0031 : Ajout de la table demandes_conges.

Table de gestion des demandes de conges payes et conventionnels,
avec circuit de validation responsable / direction.
"""

NOM = "Ajout demandes conges"
DESCRIPTION = "Cree la table demandes_conges pour les demandes de conges payes et conventionnels."


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='demandes_conges'")
    if not cursor.fetchone():
        cursor.execute('''
            CREATE TABLE demandes_conges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                type_conge TEXT NOT NULL,
                date_demande TEXT DEFAULT CURRENT_TIMESTAMP,
                date_debut TEXT NOT NULL,
                date_fin TEXT NOT NULL,
                nb_jours REAL NOT NULL,
                motif_demande TEXT,
                statut TEXT DEFAULT 'en_attente_responsable',
                validation_responsable TEXT,
                date_validation_responsable TEXT,
                validation_direction TEXT,
                date_validation_direction TEXT,
                motif_refus TEXT,
                refuse_par INTEGER,
                date_refus TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (refuse_par) REFERENCES users(id)
            )
        ''')

    conn.commit()


def downgrade(conn):
    """Annule la migration."""
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS demandes_conges")
    conn.commit()
