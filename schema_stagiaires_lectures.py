"""Lectures individuelles des annonces de stagiaires (migration 0076)."""


def creer_schema(conn):
    """Conserve chaque lecture pour son utilisateur, secteur et jour d'accueil."""
    conn.execute('''CREATE TABLE IF NOT EXISTS stagiaires_annonces_lectures (
        stagiaire_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        secteur_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        lu_le TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, secteur_id, stagiaire_id, date),
        FOREIGN KEY (stagiaire_id) REFERENCES stagiaires(id) ON DELETE CASCADE,
        FOREIGN KEY (secteur_id) REFERENCES secteurs(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )''')
