"""Fiche unique de l'installation ; schéma neuf et migration 0073."""


def creer_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS identite_centre (
        id INTEGER PRIMARY KEY CHECK(id=1),
        nom TEXT NOT NULL DEFAULT '',
        siren TEXT NOT NULL DEFAULT '',
        siret TEXT NOT NULL DEFAULT '',
        ape TEXT NOT NULL DEFAULT '',
        convention_collective_code TEXT NOT NULL DEFAULT '',
        revision INTEGER NOT NULL DEFAULT 0,
        modifie_le TEXT,
        modifie_par INTEGER REFERENCES users(id)
    )''')
    conn.execute('INSERT OR IGNORE INTO identite_centre(id) VALUES (1)')
    conn.execute('''CREATE TABLE IF NOT EXISTS identite_centre_champs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        libelle TEXT NOT NULL,
        libelle_cle TEXT NOT NULL UNIQUE,
        valeur TEXT NOT NULL
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS identite_centre_documents (
        id TEXT PRIMARY KEY,
        libelle TEXT NOT NULL,
        nom TEXT NOT NULL,
        fichier_path TEXT NOT NULL UNIQUE,
        taille INTEGER NOT NULL CHECK(taille>0),
        mime TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        cree_le TEXT NOT NULL,
        ajoute_par INTEGER NOT NULL REFERENCES users(id)
    )''')
