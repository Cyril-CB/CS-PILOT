"""Répartition hebdomadaire des lieux d'intervention, indépendante des horaires."""
def creer_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS equipe_lieux_options (
        secteur_id INTEGER PRIMARY KEY REFERENCES secteurs(id),
        actif INTEGER NOT NULL DEFAULT 0 CHECK(actif IN (0,1)),
        modifie_par INTEGER REFERENCES users(id),
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS equipe_lieux_affectations (
        secteur_id INTEGER NOT NULL REFERENCES secteurs(id),
        user_id INTEGER NOT NULL REFERENCES users(id),
        jour INTEGER NOT NULL CHECK(jour BETWEEN 0 AND 4),
        moment TEXT NOT NULL CHECK(moment IN ('matin','aprem')),
        lieu TEXT NOT NULL CHECK(length(lieu) BETWEEN 1 AND 100),
        PRIMARY KEY (secteur_id,user_id,jour,moment)
    )""")
