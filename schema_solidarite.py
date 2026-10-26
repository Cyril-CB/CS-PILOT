"""Désignation annuelle d'un férié comme journée de solidarité (0081)."""


def creer_schema(conn):
    colonnes = {r[1] for r in conn.execute('PRAGMA table_info(jours_feries)')}
    if 'solidarite' not in colonnes:
        conn.execute('ALTER TABLE jours_feries ADD COLUMN solidarite INTEGER NOT NULL DEFAULT 0 CHECK (solidarite IN (0, 1))')
    conn.execute('''CREATE UNIQUE INDEX IF NOT EXISTS idx_solidarite_annee
                    ON jours_feries(annee) WHERE solidarite = 1''')
