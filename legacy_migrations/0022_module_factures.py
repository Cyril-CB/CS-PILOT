"""
Migration 0022 : Module comptable factures.

Ajoute les tables necessaires au traitement des factures :
- fournisseurs : repertoire des fournisseurs avec aliases et code comptable
- factures : factures importees avec pre-traitement IA
- facture_historique : historique des actions sur chaque facture
- facture_commentaires : commentaires par les utilisateurs
- regles_comptables : regles pour la generation d'ecritures par l'IA
- ecritures_comptables : ecritures generees et validees
"""

NOM = "Module comptable factures"
DESCRIPTION = (
    "Ajoute les tables fournisseurs, factures, facture_historique, "
    "facture_commentaires, regles_comptables et ecritures_comptables "
    "pour le module de traitement des factures avec IA."
)


def upgrade(conn):
    """Applique la migration."""
    cursor = conn.cursor()

    # ===== Table fournisseurs =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS fournisseurs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            alias1 TEXT,
            alias2 TEXT,
            code_comptable TEXT,
            email_contact TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # ===== Table factures =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS factures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fournisseur_id INTEGER,
            numero_facture TEXT,
            date_facture TEXT,
            date_echeance TEXT,
            montant_ttc REAL,
            description TEXT,
            fichier_path TEXT,
            fichier_nom TEXT,
            fichier_original TEXT,
            secteur_id INTEGER,
            assigned_direction INTEGER DEFAULT 0,
            statut TEXT DEFAULT 'a_traiter',
            approbation TEXT DEFAULT 'en_attente',
            approuve_par INTEGER,
            date_approbation TEXT,
            created_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (fournisseur_id) REFERENCES fournisseurs(id),
            FOREIGN KEY (secteur_id) REFERENCES secteurs(id),
            FOREIGN KEY (created_by) REFERENCES users(id),
            FOREIGN KEY (approuve_par) REFERENCES users(id)
        )
    ''')

    # ===== Table historique factures =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS facture_historique (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            facture_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            user_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (facture_id) REFERENCES factures(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    # ===== Table commentaires factures =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS facture_commentaires (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            facture_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            commentaire TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (facture_id) REFERENCES factures(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    # ===== Table regles comptables =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS regles_comptables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            type_regle TEXT NOT NULL,
            cible TEXT NOT NULL,
            compte_comptable TEXT NOT NULL,
            code_analytique_1 TEXT,
            code_analytique_2 TEXT,
            pourcentage_analytique_1 REAL DEFAULT 100,
            pourcentage_analytique_2 REAL DEFAULT 0,
            modele_libelle TEXT DEFAULT '{supplier} {invoice_number} {date} {period}',
            statut TEXT DEFAULT 'active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # ===== Table ecritures comptables =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ecritures_comptables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            facture_id INTEGER NOT NULL,
            date_ecriture TEXT NOT NULL,
            compte TEXT NOT NULL,
            libelle TEXT NOT NULL,
            numero_facture TEXT,
            debit REAL DEFAULT 0,
            credit REAL DEFAULT 0,
            code_analytique TEXT,
            echeance TEXT,
            statut TEXT DEFAULT 'brouillon',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (facture_id) REFERENCES factures(id) ON DELETE CASCADE
        )
    ''')

    conn.commit()
