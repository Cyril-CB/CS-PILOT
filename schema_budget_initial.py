"""Lot 1 : données de construction uniquement, sans conversion des budgets."""


def creer_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS budget_initial_hypotheses (
        annee INTEGER PRIMARY KEY CHECK(annee BETWEEN 1900 AND 2200),
        revision INTEGER NOT NULL DEFAULT 0,
        donnees TEXT NOT NULL DEFAULT '{}',
        updated_by INTEGER REFERENCES users(id),
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS budget_initial_lignes (
        id TEXT PRIMARY KEY,
        annee INTEGER NOT NULL REFERENCES budget_initial_hypotheses(annee),
        donnees TEXT NOT NULL,
        lien_type TEXT, lien_id TEXT,
        updated_by INTEGER REFERENCES users(id),
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    conn.execute('''CREATE INDEX IF NOT EXISTS idx_budget_initial_annee
        ON budget_initial_lignes(annee)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS budget_initial_reports (
        annee INTEGER NOT NULL REFERENCES budget_initial_hypotheses(annee),
        secteur_id INTEGER NOT NULL REFERENCES secteurs(id),
        compte_num TEXT NOT NULL,
        montant TEXT NOT NULL,
        updated_by INTEGER REFERENCES users(id),
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(annee, secteur_id, compte_num))''')
