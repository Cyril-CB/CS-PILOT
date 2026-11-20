"""Propositions personnelles, sans écriture métier avant confirmation."""


def creer_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS assistant_actions (
        id TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        demande_id TEXT NOT NULL,
        signature TEXT NOT NULL,
        perimetre TEXT NOT NULL,
        statut TEXT NOT NULL DEFAULT 'attente',
        revision INTEGER NOT NULL DEFAULT 0,
        contenu TEXT NOT NULL,
        cree_le INTEGER NOT NULL,
        expire_le INTEGER NOT NULL,
        UNIQUE(user_id, demande_id)
    )''')
    conn.execute('''CREATE INDEX IF NOT EXISTS assistant_actions_auteur
        ON assistant_actions(user_id, statut, cree_le)''')
