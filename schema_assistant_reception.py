"""Boîte de réception privée, commune au schéma neuf et à la migration."""


def creer_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS assistant_documents (
        id TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        empreinte TEXT NOT NULL,
        fichier_path TEXT NOT NULL,
        contenu TEXT NOT NULL,
        statut TEXT NOT NULL DEFAULT 'recu',
        revision INTEGER NOT NULL DEFAULT 0,
        en_cours TEXT,
        verrou_jusqua INTEGER NOT NULL DEFAULT 0,
        cree_le INTEGER NOT NULL,
        actualise_le INTEGER NOT NULL,
        UNIQUE(user_id, empreinte)
    )''')
    conn.execute('''CREATE INDEX IF NOT EXISTS assistant_documents_auteur
        ON assistant_documents(user_id, cree_le)''')
