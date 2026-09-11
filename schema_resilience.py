"""Schéma 0071 : journal des tentatives et convergence sans effacer de preuves."""


def creer_journal_migrations(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations_tentatives (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        version TEXT NOT NULL,
        statut TEXT NOT NULL CHECK(statut IN ('ok', 'erreur')),
        detail TEXT NOT NULL,
        appliquee_le TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        appliquee_par TEXT,
        duree_ms INTEGER,
        transaction_annulee INTEGER NOT NULL DEFAULT 0
    )""")
    # Conserver la vraie date d'un ancien échec, sans inventer son atomicité.
    conn.execute("""INSERT INTO schema_migrations_tentatives
        (version, statut, detail, appliquee_le, appliquee_par, duree_ms)
        SELECT version, 'erreur', 'Ancien échec : exécution partielle possible',
               COALESCE(appliquee_le, ''), appliquee_par, duree_ms
        FROM schema_migrations m WHERE statut != 'ok' AND NOT EXISTS
        (SELECT 1 FROM schema_migrations_tentatives t WHERE t.version=m.version)
    """)


# Noms et DDL issus du schéma applicatif, jamais d'une entrée utilisateur.
_SCHEMAS = {
    'prepa_paie_statut': """CREATE TABLE prepa_paie_statut (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            mois INTEGER NOT NULL,
            annee INTEGER NOT NULL,
            traite INTEGER NOT NULL DEFAULT 0,
            traite_par INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            empreinte_verifiee TEXT,
            verifie_le TEXT,
            modifie_le TEXT,
            revision INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (traite_par) REFERENCES users(id),
            UNIQUE(user_id, mois, annee)
        )""",
    'subventions': """CREATE TABLE subventions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            groupe TEXT NOT NULL DEFAULT 'nouveau_projet',
            type_id INTEGER,
            assignee_1_id INTEGER,
            assignee_2_id INTEGER,
            date_echeance TEXT,
            montant_demande REAL DEFAULT 0,
            montant_accorde REAL DEFAULT 0,
            date_notification TEXT,
            justificatif_path TEXT,
            justificatif_nom TEXT,
            analytique_id INTEGER,
            contact_email TEXT,
            compte_comptable TEXT,
            annee_action TEXT,
            compte_comptable_1_id INTEGER,
            compte_comptable_2_id INTEGER,
            benevoles_ids TEXT DEFAULT '[]',
            action_budget_id INTEGER,
            ordre INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (assignee_1_id) REFERENCES users(id),
            FOREIGN KEY (assignee_2_id) REFERENCES users(id),
            FOREIGN KEY (analytique_id) REFERENCES subventions_analytiques(id),
            FOREIGN KEY (compte_comptable_1_id) REFERENCES comptabilite_comptes(id),
            FOREIGN KEY (compte_comptable_2_id) REFERENCES comptabilite_comptes(id),
            FOREIGN KEY (action_budget_id) REFERENCES comptabilite_actions(id),
            FOREIGN KEY (type_id) REFERENCES subventions_types(id)
        )""",
}


def _reconstruire(conn, table):
    if table not in _SCHEMAS:
        raise ValueError('Table non prévue par la migration')
    if conn.execute('PRAGMA foreign_keys').fetchone()[0]:
        raise RuntimeError('Utilisez le gestionnaire de migrations hors ligne pour reconstruire les contraintes.')
    # Refuser une variante de schéma inconnue au lieu de perdre des colonnes.
    colonnes = [r[1] for r in conn.execute(f'PRAGMA table_info({table})')]
    sql = _SCHEMAS[table]
    conn.execute(sql.replace(f'CREATE TABLE {table} (', f'CREATE TABLE {table}_resilience (', 1))
    attendues = {r[1] for r in conn.execute(f'PRAGMA table_info({table}_resilience)')}
    if set(colonnes) != attendues:
        raise RuntimeError('Schéma personnalisé : contrôle manuel nécessaire')
    objets = conn.execute(
        "SELECT sql FROM sqlite_master WHERE tbl_name=? AND type IN ('index', 'trigger') AND sql IS NOT NULL",
        (table,)).fetchall()
    # Les triggers d'autres tables qui consultent cette table rendraient le
    # schéma temporairement invalide pendant ALTER TABLE RENAME. Les suspendre
    # dans la même transaction, puis les recréer à l'identique.
    import re
    dependants = [(nom, ddl) for nom, ddl in conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name != ?", (table,))
        if re.search(r'\b' + table + r'\b', ddl)]
    for nom, _ in dependants:
        conn.execute('DROP TRIGGER "' + nom.replace('"', '""') + '"')
    sequence = conn.execute('SELECT seq FROM sqlite_sequence WHERE name=?', (table,)).fetchone()
    # Les colonnes sont validées contre les constantes ci-dessus. Aucune
    # conversion : un NULL incompatible provoque le rollback et un diagnostic.
    noms = ', '.join('"' + col + '"' for col in colonnes)
    conn.execute(f'INSERT INTO {table}_resilience ({noms}) SELECT {noms} FROM {table}')
    conn.execute(f'DROP TABLE {table}')
    conn.execute(f'ALTER TABLE {table}_resilience RENAME TO {table}')
    if sequence:
        conn.execute('UPDATE sqlite_sequence SET seq=MAX(seq, ?) WHERE name=?', (sequence[0], table))
    for objet in objets:
        conn.execute(objet[0])
    for _, ddl in dependants:
        conn.execute(ddl)


def creer_schema(conn):
    creer_journal_migrations(conn)
    conn.execute("""CREATE TABLE IF NOT EXISTS plan_comptable_general (
        id INTEGER PRIMARY KEY AUTOINCREMENT, compte_num TEXT NOT NULL UNIQUE,
        libelle TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    if 'temps_hebdo' not in {r[1] for r in conn.execute('PRAGMA table_info(contrats)')}:
        conn.execute('ALTER TABLE contrats ADD COLUMN temps_hebdo REAL')
    colonnes = {r[1]: r for r in conn.execute('PRAGMA table_info(prepa_paie_statut)')}
    if not colonnes['traite'][3]:
        _reconstruire(conn, 'prepa_paie_statut')
    if not any(r[3] == 'action_budget_id' for r in conn.execute('PRAGMA foreign_key_list(subventions)')):
        _reconstruire(conn, 'subventions')
