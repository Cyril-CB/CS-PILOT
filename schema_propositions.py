"""Schéma commun à l'installation neuve et à la migration 0072."""


def creer_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS propositions_amelioration (
        id TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        cree_le TEXT NOT NULL,
        contenu_json TEXT NOT NULL,
        statut TEXT NOT NULL DEFAULT 'a_envoyer'
            CHECK(statut IN ('a_envoyer', 'en_cours', 'envoyee', 'incertain')),
        tentatives INTEGER NOT NULL DEFAULT 0,
        tentative_id TEXT,
        derniere_tentative TEXT,
        envoyee_le TEXT,
        erreur_code TEXT
    )''')
    conn.execute('''CREATE INDEX IF NOT EXISTS propositions_par_auteur
        ON propositions_amelioration(user_id, cree_le)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS propositions_pieces (
        id TEXT PRIMARY KEY,
        proposition_id TEXT NOT NULL REFERENCES propositions_amelioration(id),
        nom TEXT NOT NULL,
        fichier_path TEXT NOT NULL UNIQUE,
        taille INTEGER NOT NULL,
        mime TEXT NOT NULL,
        sha256 TEXT NOT NULL
    )''')
    conn.execute('''CREATE INDEX IF NOT EXISTS propositions_pieces_parent
        ON propositions_pieces(proposition_id)''')
