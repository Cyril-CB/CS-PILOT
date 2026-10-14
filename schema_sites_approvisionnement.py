"""Sites physiques et approvisionnement : schéma commun neuf/migration 0079.

Aucune déduction à partir des secteurs, des noms de salariés ou des anciens
lieux de contrats. Les anciennes fournitures restent explicitement globales.
"""


def creer_schema(conn):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS sites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL COLLATE NOCASE UNIQUE CHECK(length(trim(nom)) BETWEEN 1 AND 100),
            actif INTEGER NOT NULL DEFAULT 1 CHECK(actif IN (0, 1)),
            revision INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS sites_utilisateurs (
            site_id INTEGER NOT NULL REFERENCES sites(id),
            user_id INTEGER NOT NULL REFERENCES users(id),
            PRIMARY KEY (site_id, user_id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS sites_responsables_modules (
            site_id INTEGER NOT NULL REFERENCES sites(id),
            module TEXT NOT NULL CHECK(module IN ('fournitures', 'entretien')),
            user_id INTEGER NOT NULL REFERENCES users(id),
            PRIMARY KEY (site_id, module)
        )
    ''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_sites_utilisateurs_user ON sites_utilisateurs(user_id, site_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_sites_responsables_user ON sites_responsables_modules(user_id, module, site_id)')
    colonnes = {r[1] for r in conn.execute('PRAGMA table_info(commandes_salaries)')}
    if 'site_id' not in colonnes:
        conn.execute('ALTER TABLE commandes_salaries ADD COLUMN site_id INTEGER REFERENCES sites(id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_commandes_salaries_site ON commandes_salaries(site_id, groupe)')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS entretien_lieux (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id INTEGER NOT NULL REFERENCES sites(id),
            nom TEXT NOT NULL COLLATE NOCASE CHECK(length(trim(nom)) BETWEEN 1 AND 100),
            demandeur_id INTEGER NOT NULL REFERENCES users(id),
            actif INTEGER NOT NULL DEFAULT 1 CHECK(actif IN (0, 1)),
            revision INTEGER NOT NULL DEFAULT 1,
            UNIQUE (site_id, nom),
            UNIQUE (id, site_id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS entretien_produits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id INTEGER NOT NULL REFERENCES sites(id),
            nom TEXT NOT NULL COLLATE NOCASE CHECK(length(trim(nom)) BETWEEN 1 AND 150),
            unite TEXT NOT NULL CHECK(length(trim(unite)) BETWEEN 1 AND 40),
            actif INTEGER NOT NULL DEFAULT 1 CHECK(actif IN (0, 1)),
            revision INTEGER NOT NULL DEFAULT 1,
            UNIQUE (site_id, nom),
            UNIQUE (id, site_id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS entretien_demandes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id INTEGER NOT NULL REFERENCES sites(id),
            lieu_id INTEGER NOT NULL,
            lieu_nom TEXT NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id),
            cle_envoi TEXT NOT NULL UNIQUE,
            empreinte TEXT NOT NULL,
            statut TEXT NOT NULL DEFAULT 'en_cours' CHECK(statut IN ('en_cours', 'commandee', 'recue', 'annulee')),
            commentaire TEXT NOT NULL DEFAULT '',
            reception_note TEXT NOT NULL DEFAULT '',
            revision INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            commandee_at TEXT,
            recue_at TEXT,
            traite_par INTEGER REFERENCES users(id),
            UNIQUE (id, site_id),
            FOREIGN KEY (lieu_id, site_id) REFERENCES entretien_lieux(id, site_id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS entretien_lignes (
            demande_id INTEGER NOT NULL,
            site_id INTEGER NOT NULL,
            produit_id INTEGER NOT NULL,
            produit_nom TEXT NOT NULL,
            unite TEXT NOT NULL,
            quantite INTEGER NOT NULL CHECK(quantite BETWEEN 1 AND 9999),
            PRIMARY KEY (demande_id, produit_id),
            FOREIGN KEY (demande_id, site_id) REFERENCES entretien_demandes(id, site_id),
            FOREIGN KEY (produit_id, site_id) REFERENCES entretien_produits(id, site_id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS entretien_notifications (
            demande_id INTEGER NOT NULL REFERENCES entretien_demandes(id),
            user_id INTEGER NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            lu_le TEXT,
            PRIMARY KEY (demande_id, user_id)
        )
    ''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_entretien_lieux_demandeur ON entretien_lieux(demandeur_id, site_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_entretien_demandes_site ON entretien_demandes(site_id, statut, id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_entretien_notifications_user ON entretien_notifications(user_id, lu_le)')
