"""
Migration 0001 : Schema initial de la base de donnees.

Cette migration represente l'etat actuel de la base de donnees.
Elle est automatiquement marquee comme appliquee lors de la premiere
initialisation du systeme de migrations sur une base existante.
"""

NOM = "Schema initial"
DESCRIPTION = "Tables de base : users, secteurs, planning_theorique, heures_reelles, validations, periodes_vacances, historique_modifications, demandes_recup, jours_feries, anomalies, alternance_reference, app_settings, presence_forfait_jour, validation_forfait_jour, planning_enfance_config"


def upgrade(conn):
    """Cree toutes les tables de base si elles n'existent pas."""
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            prenom TEXT NOT NULL,
            login TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            profil TEXT NOT NULL,
            secteur_id INTEGER,
            responsable_id INTEGER,
            actif INTEGER DEFAULT 1,
            solde_initial REAL DEFAULT 0,
            FOREIGN KEY (secteur_id) REFERENCES secteurs(id),
            FOREIGN KEY (responsable_id) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS secteurs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS planning_theorique (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type_periode TEXT NOT NULL,
            date_debut_validite TEXT NOT NULL DEFAULT '2000-01-01',
            type_alternance TEXT DEFAULT 'fixe',
            lundi_matin_debut TEXT, lundi_matin_fin TEXT,
            lundi_aprem_debut TEXT, lundi_aprem_fin TEXT,
            mardi_matin_debut TEXT, mardi_matin_fin TEXT,
            mardi_aprem_debut TEXT, mardi_aprem_fin TEXT,
            mercredi_matin_debut TEXT, mercredi_matin_fin TEXT,
            mercredi_aprem_debut TEXT, mercredi_aprem_fin TEXT,
            jeudi_matin_debut TEXT, jeudi_matin_fin TEXT,
            jeudi_aprem_debut TEXT, jeudi_aprem_fin TEXT,
            vendredi_matin_debut TEXT, vendredi_matin_fin TEXT,
            vendredi_aprem_debut TEXT, vendredi_aprem_fin TEXT,
            total_hebdo REAL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS alternance_reference (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date_reference TEXT NOT NULL,
            date_debut_validite TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS anomalies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date_modification TEXT NOT NULL,
            date_concernee TEXT NOT NULL,
            type_anomalie TEXT NOT NULL,
            gravite TEXT NOT NULL,
            description TEXT,
            ancienne_valeur TEXT,
            nouvelle_valeur TEXT,
            traitee INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS heures_reelles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            heure_debut_matin TEXT, heure_fin_matin TEXT,
            heure_debut_aprem TEXT, heure_fin_aprem TEXT,
            commentaire TEXT,
            type_saisie TEXT DEFAULT 'heures_sup',
            declaration_conforme INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, date)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS validations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            mois INTEGER NOT NULL,
            annee INTEGER NOT NULL,
            validation_salarie TEXT,
            validation_responsable TEXT,
            validation_directeur TEXT,
            date_salarie TEXT, date_responsable TEXT, date_directeur TEXT,
            bloque INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, mois, annee)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS periodes_vacances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            date_debut TEXT NOT NULL,
            date_fin TEXT NOT NULL,
            created_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS historique_modifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id_modifie INTEGER NOT NULL,
            date_concernee TEXT NOT NULL,
            modifie_par INTEGER NOT NULL,
            date_modification TEXT DEFAULT CURRENT_TIMESTAMP,
            action TEXT NOT NULL,
            anciennes_valeurs TEXT,
            nouvelles_valeurs TEXT,
            FOREIGN KEY (user_id_modifie) REFERENCES users(id),
            FOREIGN KEY (modifie_par) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS demandes_recup (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date_demande TEXT DEFAULT CURRENT_TIMESTAMP,
            date_debut TEXT NOT NULL,
            date_fin TEXT NOT NULL,
            nb_jours REAL NOT NULL,
            nb_heures REAL NOT NULL,
            motif_demande TEXT,
            statut TEXT DEFAULT 'en_attente_responsable',
            validation_responsable TEXT,
            date_validation_responsable TEXT,
            validation_direction TEXT,
            date_validation_direction TEXT,
            motif_refus TEXT,
            refuse_par INTEGER,
            date_refus TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (refuse_par) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS jours_feries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            annee INTEGER NOT NULL,
            date TEXT NOT NULL,
            libelle TEXT NOT NULL,
            UNIQUE(date)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS planning_enfance_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            annee INTEGER NOT NULL,
            config_json TEXT NOT NULL,
            created_by INTEGER,
            updated_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (created_by) REFERENCES users(id),
            FOREIGN KEY (updated_by) REFERENCES users(id),
            UNIQUE(user_id, annee)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS app_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL UNIQUE,
            value TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS presence_forfait_jour (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            type_journee TEXT NOT NULL,
            commentaire TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, date)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS validation_forfait_jour (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            mois INTEGER NOT NULL,
            annee INTEGER NOT NULL,
            date_validation TEXT DEFAULT CURRENT_TIMESTAMP,
            valide_par INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (valide_par) REFERENCES users(id),
            UNIQUE(user_id, mois, annee)
        )
    ''')
