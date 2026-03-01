"""
Migration 0003 : Ajout de la table absences.

Gestion des arrets maladie, conges payes, conges conventionnels, etc.
Stockage des justificatifs (PDF/images) sur le serveur.
"""

NOM = "Ajout table absences"
DESCRIPTION = "Cree la table absences pour la gestion des arrets maladie et conges avec justificatifs."


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    # Verifier si la table existe deja
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='absences'")
    if not cursor.fetchone():
        cursor.execute('''
            CREATE TABLE absences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                motif TEXT NOT NULL,
                date_debut TEXT NOT NULL,
                date_fin TEXT NOT NULL,
                date_reprise TEXT,
                commentaire TEXT,
                jours_ouvres REAL NOT NULL,
                justificatif_path TEXT,
                justificatif_nom TEXT,
                saisi_par INTEGER NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (saisi_par) REFERENCES users(id)
            )
        ''')
