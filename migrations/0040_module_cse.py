"""
Migration 0040 : Module CSE (Comité Social et Économique).

Ajoute les tables nécessaires au module CSE accessible depuis RH & Paie :
- cse_membres          : désignation des salariés membres du CSE
- cse_messages         : messages à l'attention des salariés (avec date de validité)
- cse_soldes_initiaux  : soldes de départ banque / caisse (avec date)
- cse_mouvements       : entrées / sorties du budget du CSE
"""

NOM = "Module CSE"
DESCRIPTION = (
    "Ajoute les tables cse_membres, cse_messages, cse_soldes_initiaux et "
    "cse_mouvements pour la gestion du CSE (membres, messages aux salariés, "
    "budget simplifié et bilan annuel)."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS cse_membres (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            ajoute_par INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (ajoute_par) REFERENCES users(id)
        )
        '''
    )

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS cse_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titre TEXT,
            contenu TEXT NOT NULL,
            date_validite TEXT NOT NULL,
            statut TEXT NOT NULL DEFAULT 'actif',
            cree_par INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            archive_le TEXT,
            FOREIGN KEY (cree_par) REFERENCES users(id)
        )
        '''
    )

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS cse_soldes_initiaux (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            compte TEXT NOT NULL UNIQUE,
            date_solde TEXT NOT NULL,
            montant REAL NOT NULL DEFAULT 0,
            updated_par INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (updated_par) REFERENCES users(id)
        )
        '''
    )

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS cse_mouvements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            compte TEXT NOT NULL DEFAULT 'banque',
            type TEXT NOT NULL,
            date_mouvement TEXT NOT NULL,
            montant REAL NOT NULL,
            commentaire TEXT,
            cree_par INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cree_par) REFERENCES users(id)
        )
        '''
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_cse_mouvements_date ON cse_mouvements(date_mouvement)"
    )

    conn.commit()


def downgrade(conn):
    """Annule la migration."""
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS cse_mouvements")
    cursor.execute("DROP TABLE IF EXISTS cse_soldes_initiaux")
    cursor.execute("DROP TABLE IF EXISTS cse_messages")
    cursor.execute("DROP TABLE IF EXISTS cse_membres")
    conn.commit()
