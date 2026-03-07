"""
Migration 0028 : Ajout du module Analyse ALSH.

- alsh_tranches_age : tranches d'âge configurables (3-5 ans, 6-11 ans par défaut)
- alsh_periodes     : lignes du tableau (mercredis, vacances scolaires, personnalisées)
- alsh_config_codes : mapping codes analytiques par (année, période, tranche d'âge)
- alsh_saisie_noe   : données NOÉ (heures présence, nb enfants) par (année, période, tranche d'âge)
"""

NOM = "Ajout module Analyse ALSH"
DESCRIPTION = (
    "Ajoute les tables pour le module Analyse ALSH : tranches d'âge, "
    "périodes, codes analytiques par période/tranche, saisie données NOÉ."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    # Tranches d'âge ALSH
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS alsh_tranches_age (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            libelle TEXT NOT NULL,
            ordre INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Lignes/Périodes ALSH (globales, indépendantes de l'année)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS alsh_periodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            type TEXT NOT NULL DEFAULT 'custom',
            ordre INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Mapping codes analytiques (par année + période + tranche d'âge)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS alsh_config_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            annee INTEGER NOT NULL,
            periode_id INTEGER NOT NULL,
            tranche_age_id INTEGER NOT NULL,
            code1 TEXT,
            code2 TEXT,
            code3 TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (periode_id) REFERENCES alsh_periodes(id) ON DELETE CASCADE,
            FOREIGN KEY (tranche_age_id) REFERENCES alsh_tranches_age(id) ON DELETE CASCADE,
            UNIQUE(annee, periode_id, tranche_age_id)
        )
    ''')

    # Saisie données NOÉ (par année + période + tranche d'âge)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS alsh_saisie_noe (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            annee INTEGER NOT NULL,
            periode_id INTEGER NOT NULL,
            tranche_age_id INTEGER NOT NULL,
            heures_presence REAL DEFAULT 0,
            nb_enfants INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (periode_id) REFERENCES alsh_periodes(id) ON DELETE CASCADE,
            FOREIGN KEY (tranche_age_id) REFERENCES alsh_tranches_age(id) ON DELETE CASCADE,
            UNIQUE(annee, periode_id, tranche_age_id)
        )
    ''')

    # Données initiales : tranches d'âge par défaut
    for libelle, ordre in [('3-5 ans', 1), ('6-11 ans', 2)]:
        cursor.execute(
            'INSERT OR IGNORE INTO alsh_tranches_age (libelle, ordre) VALUES (?, ?)',
            (libelle, ordre)
        )

    # Données initiales : périodes par défaut
    periodes_defaut = [
        ('Mercredis', 'mercredi', 1),
        ("Vacances d'hiver", 'vacances', 2),
        ('Vacances de printemps', 'vacances', 3),
        ("Vacances d'été", 'vacances', 4),
        ('Vacances de Toussaint', 'vacances', 5),
        ('Vacances de Noël', 'vacances', 6),
    ]
    for nom, type_p, ordre in periodes_defaut:
        cursor.execute(
            'INSERT OR IGNORE INTO alsh_periodes (nom, type, ordre) VALUES (?, ?, ?)',
            (nom, type_p, ordre)
        )

    conn.commit()
