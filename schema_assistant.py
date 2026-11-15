"""Stockage personnel de l'assistant, commun à l'installation et à la migration."""


def creer_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS assistant_etats (
        user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        perimetre TEXT NOT NULL,
        revision INTEGER NOT NULL DEFAULT 0,
        contenu TEXT NOT NULL,
        jour TEXT NOT NULL,
        tours INTEGER NOT NULL DEFAULT 0,
        en_cours TEXT,
        verrou_jusqua INTEGER NOT NULL DEFAULT 0,
        actualise_le INTEGER NOT NULL
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS assistant_memoires (
        id TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        categorie TEXT NOT NULL CHECK(categorie IN ('preference', 'suivi')),
        contenu TEXT NOT NULL,
        cree_le INTEGER NOT NULL,
        expire_le INTEGER
    )''')
    conn.execute('''CREATE INDEX IF NOT EXISTS assistant_memoires_auteur
        ON assistant_memoires(user_id, expire_le)''')
