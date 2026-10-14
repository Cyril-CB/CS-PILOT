"""Références et événements append-only du suivi, sans reprise de données."""


def creer_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS budget_gels (
        id TEXT PRIMARY KEY, annee INTEGER NOT NULL, version INTEGER NOT NULL,
        donnees TEXT NOT NULL, empreinte TEXT NOT NULL, motif TEXT NOT NULL,
        auteur INTEGER NOT NULL, date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(annee, version))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS budget_suivis (
        annee INTEGER PRIMARY KEY, gel_id TEXT NOT NULL REFERENCES budget_gels(id),
        revision INTEGER NOT NULL DEFAULT 0)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS budget_evenements (
        id INTEGER PRIMARY KEY, annee INTEGER NOT NULL REFERENCES budget_suivis(annee),
        element_id TEXT NOT NULL, revision INTEGER NOT NULL, donnees TEXT NOT NULL,
        auteur INTEGER NOT NULL, date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(annee, revision))''')
    conn.execute('''CREATE INDEX IF NOT EXISTS idx_budget_evenement_element
        ON budget_evenements(annee, element_id, revision)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS budget_instantanes (
        id TEXT PRIMARY KEY, annee INTEGER NOT NULL, secteur_id INTEGER,
        gel_id TEXT NOT NULL REFERENCES budget_gels(id), revision INTEGER NOT NULL,
        donnees TEXT NOT NULL, pdf_synthese BLOB NOT NULL, pdf_detail BLOB NOT NULL,
        auteur INTEGER NOT NULL, date TEXT NOT NULL)''')
    # Liste fermée de tables : aucune interpolation de donnée utilisateur.
    for table in ('budget_gels', 'budget_evenements', 'budget_instantanes'):
        for operation in ('UPDATE', 'DELETE'):
            conn.execute(f'''CREATE TRIGGER IF NOT EXISTS {table}_sans_{operation.lower()}
                BEFORE {operation} ON {table} BEGIN
                SELECT RAISE(ABORT, 'Archive budgétaire immuable'); END''')
