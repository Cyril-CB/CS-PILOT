"""
Migration 0021 : Ajout des tables d'epargne pour la tresorerie.

- tresorerie_epargne_solde : solde initial de l'epargne (un seul enregistrement global)
- tresorerie_epargne_mouvements : placements et retraits (mois/annee)
"""

NOM = "Ajout epargne tresorerie"
DESCRIPTION = (
    "Ajoute les tables tresorerie_epargne_solde et tresorerie_epargne_mouvements "
    "pour gerer les comptes d'epargne separes de la tresorerie courante."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tresorerie_epargne_solde (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            montant REAL NOT NULL DEFAULT 0,
            saisi_par INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (saisi_par) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tresorerie_epargne_mouvements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type_mouvement TEXT NOT NULL,
            annee INTEGER NOT NULL,
            mois INTEGER NOT NULL,
            montant REAL NOT NULL,
            commentaire TEXT,
            saisi_par INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (saisi_par) REFERENCES users(id)
        )
    ''')

    conn.commit()
