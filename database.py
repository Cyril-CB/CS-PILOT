"""
Module de gestion de la base de données SQLite.
Contient l'initialisation du schéma et la connexion.
"""
import os
import sys
import sqlite3

# En mode exécutable (.exe / frozen PyInstaller), stocker les données dans un
# répertoire utilisateur inscriptible pour qu'elles survivent entre les exécutions :
#   - Windows : %LOCALAPPDATA%\cspilot
#   - Linux/Mac : ~/.local/share/cspilot
# En mode script normal, utiliser le dossier du projet (comportement d'origine).
if getattr(sys, 'frozen', False):
    if os.name == 'nt':
        DATA_DIR = os.path.join(
            os.environ.get('LOCALAPPDATA', os.path.join(os.path.expanduser('~'), 'AppData', 'Local')),
            'cspilot'
        )
    else:
        DATA_DIR = os.path.join(os.path.expanduser('~'), '.local', 'share', 'cspilot')
else:
    DATA_DIR = os.path.dirname(os.path.abspath(__file__))

os.makedirs(DATA_DIR, exist_ok=True)
DATABASE = os.path.join(DATA_DIR, 'cspilot.db')


def get_db():
    """Connexion à la base de données"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# Liste de toutes les versions de migration connues.
# Quand init_db() cree une base neuve, il les marque toutes comme appliquees
# pour eviter que le migration_manager ne tente de les re-executer.
ALL_MIGRATION_VERSIONS = [
    ('0001', 'Schema initial'),
    ('0003', 'Ajout table absences'),
    ('0004', 'Ajout tables variables paie'),
    ('0005', 'Ajout infos salaries'),
    ('0006', 'Ajout prepa paie'),
    ('0007', 'Ajout conges salaries'),
    ('0008', 'Ajout cloture conges'),
    ('0009', 'Ajout postes ALISFA'),
    ('0010', 'Ajout heures reelles supps'),
    ('0011', 'Ajout consentement email'),
    ('0012', 'Ajout systeme budgetaire'),
    ('0013', 'Ajout budget reel'),
    ('0014', 'Ajout frequentation creche'),
    ('0015', 'Ajout responsable terrain creche'),
    ('0016', 'Ajout subventions'),
    ('0017', 'Ajout benevoles'),
    ('0018', 'Ajout gestion des salles'),
    ('0019', 'Ajout module tresorerie'),
    ('0020', 'Solde initial global tresorerie'),
    ('0021', 'Ajout epargne tresorerie'),
    ('0022', 'Module comptable factures'),
    ('0023', 'Archivage exportations ecritures'),
    ('0024', 'Ajout module generation contrats'),
    ('0025', 'Correctif colonnes contrats generes'),
    ('0026', 'Module comptabilite analytique'),
    ('0027', 'Ajout gestion types secteur'),
    ('0028', 'Ajout module analyse ALSH'),
    ('0029', 'Ajout module budget previsionnel'),
    ('0030', 'Ameliorations subventions'),
    ('0031', 'Ajout demandes conges'),
]

# Postes de depense par defaut (migration 0012)
_POSTES_DEPENSE_DEFAUT = [
    ('Alimentation', ['creche', 'accueil_loisirs', 'famille', 'emploi_formation', 'administratif', 'entretien']),
    ("Fournitures d'activites", ['creche', 'accueil_loisirs', 'famille', 'emploi_formation', 'administratif']),
    ('Petit equipement', ['creche', 'accueil_loisirs', 'famille', 'emploi_formation', 'administratif', 'entretien']),
    ("Petit equipement d'activite", ['creche', 'accueil_loisirs', 'famille', 'emploi_formation', 'administratif']),
    ('Honoraires', ['creche', 'accueil_loisirs', 'famille', 'emploi_formation', 'administratif', 'entretien']),
    ('Mission/reception', ['creche', 'accueil_loisirs', 'famille', 'emploi_formation', 'administratif']),
    ('Restauration', ['creche', 'accueil_loisirs']),
    ('Couches', ['creche']),
    ('Reparation', ['creche', 'entretien']),
    ('Transport', ['famille', 'accueil_loisirs']),
    ('Sorties', ['famille', 'accueil_loisirs']),
    ('Fournitures de bureau', ['administratif']),
    ("Produit d'entretien", ['administratif', 'entretien']),
]


def init_db():
    """Initialisation de la base de données avec le schema complet."""
    conn = get_db()
    cursor = conn.cursor()

    # ===== Table des utilisateurs =====
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
            cp_acquis REAL DEFAULT 0,
            cp_a_prendre REAL DEFAULT 0,
            cp_pris REAL DEFAULT 0,
            cc_solde REAL DEFAULT 0,
            date_entree TEXT,
            pesee INTEGER,
            email TEXT,
            email_notifications_enabled INTEGER DEFAULT 0,
            force_password_change INTEGER DEFAULT 0,
            adresse TEXT,
            date_naissance TEXT,
            numero_secu TEXT,
            FOREIGN KEY (secteur_id) REFERENCES secteurs(id),
            FOREIGN KEY (responsable_id) REFERENCES users(id)
        )
    ''')

    # ===== Table des secteurs =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS secteurs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL UNIQUE,
            description TEXT,
            type_secteur TEXT DEFAULT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # ===== Table des plannings theoriques =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS planning_theorique (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type_periode TEXT NOT NULL,
            date_debut_validite TEXT NOT NULL DEFAULT '2000-01-01',
            type_alternance TEXT DEFAULT 'fixe',
            lundi_matin_debut TEXT,
            lundi_matin_fin TEXT,
            lundi_aprem_debut TEXT,
            lundi_aprem_fin TEXT,
            mardi_matin_debut TEXT,
            mardi_matin_fin TEXT,
            mardi_aprem_debut TEXT,
            mardi_aprem_fin TEXT,
            mercredi_matin_debut TEXT,
            mercredi_matin_fin TEXT,
            mercredi_aprem_debut TEXT,
            mercredi_aprem_fin TEXT,
            jeudi_matin_debut TEXT,
            jeudi_matin_fin TEXT,
            jeudi_aprem_debut TEXT,
            jeudi_aprem_fin TEXT,
            vendredi_matin_debut TEXT,
            vendredi_matin_fin TEXT,
            vendredi_aprem_debut TEXT,
            vendredi_aprem_fin TEXT,
            total_hebdo REAL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    # ===== Table alternance reference =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS alternance_reference (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date_reference TEXT NOT NULL,
            date_debut_validite TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    # ===== Table des anomalies =====
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

    # ===== Table des heures reelles =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS heures_reelles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            heure_debut_matin TEXT,
            heure_fin_matin TEXT,
            heure_debut_aprem TEXT,
            heure_fin_aprem TEXT,
            commentaire TEXT,
            type_saisie TEXT DEFAULT 'heures_sup',
            declaration_conforme INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, date)
        )
    ''')

    # ===== Table des validations mensuelles =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS validations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            mois INTEGER NOT NULL,
            annee INTEGER NOT NULL,
            validation_salarie TEXT,
            validation_responsable TEXT,
            validation_directeur TEXT,
            date_salarie TEXT,
            date_responsable TEXT,
            date_directeur TEXT,
            bloque INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, mois, annee)
        )
    ''')

    # ===== Table des periodes de vacances scolaires =====
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

    # ===== Table d'historique des modifications =====
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

    # ===== Table des demandes de recuperation =====
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

    # ===== Table des demandes de conges =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS demandes_conges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type_conge TEXT NOT NULL,
            date_demande TEXT DEFAULT CURRENT_TIMESTAMP,
            date_debut TEXT NOT NULL,
            date_fin TEXT NOT NULL,
            nb_jours REAL NOT NULL,
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

    # ===== Table des jours feries =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS jours_feries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            annee INTEGER NOT NULL,
            date TEXT NOT NULL,
            libelle TEXT NOT NULL,
            UNIQUE(date)
        )
    ''')

    # ===== Table planning enfance =====
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

    # ===== Table des absences (migration 0003) =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS absences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            motif TEXT NOT NULL,
            date_debut TEXT NOT NULL,
            date_fin TEXT NOT NULL,
            date_reprise TEXT,
            commentaire TEXT,
            jours_ouvres REAL NOT NULL,
            justificatif_path TEXT,
            justificatif_nom TEXT,
            saisi_par INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (saisi_par) REFERENCES users(id)
        )
    ''')

    # ===== Table parametres applicatifs =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS app_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL UNIQUE,
            value TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # ===== Table forfait jour =====
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

    # ===== Table variables paie defauts (migration 0004) =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS variables_paie_defauts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            mutuelle TEXT,
            nb_enfants INTEGER DEFAULT 0,
            saisie_salaire TEXT,
            pret_avance TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    # ===== Table variables paie mensuelles (migration 0004 + 0010) =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS variables_paie (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            mois INTEGER NOT NULL,
            annee INTEGER NOT NULL,
            mutuelle TEXT,
            nb_enfants INTEGER DEFAULT 0,
            transport TEXT,
            acompte TEXT,
            saisie_salaire TEXT,
            pret_avance TEXT,
            autres_regularisation TEXT,
            commentaire TEXT,
            heures_reelles REAL,
            heures_supps REAL,
            saisi_par INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (saisi_par) REFERENCES users(id),
            UNIQUE(user_id, mois, annee)
        )
    ''')

    # ===== Table contrats (migration 0005 + 0006) =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contrats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type_contrat TEXT NOT NULL,
            date_debut TEXT NOT NULL,
            date_fin TEXT,
            forfait TEXT,
            nbr_jours REAL,
            temps_hebdo REAL,
            fichier_path TEXT,
            fichier_nom TEXT,
            saisi_par INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (saisi_par) REFERENCES users(id)
        )
    ''')

    # ===== Table documents salaries (migration 0005) =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS documents_salaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type_document TEXT NOT NULL,
            description TEXT,
            fichier_path TEXT NOT NULL,
            fichier_nom TEXT NOT NULL,
            saisi_par INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (saisi_par) REFERENCES users(id)
        )
    ''')

    # ===== Table statut preparation paie (migration 0006) =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS prepa_paie_statut (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            mois INTEGER NOT NULL,
            annee INTEGER NOT NULL,
            traite INTEGER DEFAULT 0,
            traite_par INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (traite_par) REFERENCES users(id),
            UNIQUE(user_id, mois, annee)
        )
    ''')

    # ===== Table cloture conges mensuelle (migration 0008) =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conges_cloture_mensuelle (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mois INTEGER NOT NULL,
            annee INTEGER NOT NULL,
            cloture_le TEXT DEFAULT CURRENT_TIMESTAMP,
            cloture_par INTEGER NOT NULL,
            nb_salaries_traites INTEGER DEFAULT 0,
            detail TEXT,
            UNIQUE(mois, annee),
            FOREIGN KEY (cloture_par) REFERENCES users(id)
        )
    ''')

    # ===== Table postes ALISFA (migration 0009) =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS postes_alisfa (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            intitule TEXT NOT NULL,
            famille_metier TEXT NOT NULL,
            emploi_repere TEXT,
            formation_niveau INTEGER DEFAULT 1,
            complexite_niveau INTEGER DEFAULT 1,
            autonomie_niveau INTEGER DEFAULT 1,
            relationnel_niveau INTEGER DEFAULT 1,
            finances_niveau INTEGER DEFAULT 1,
            rh_niveau INTEGER DEFAULT 1,
            securite_niveau INTEGER DEFAULT 1,
            projet_niveau INTEGER DEFAULT 1,
            total_points INTEGER DEFAULT 0,
            created_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    ''')

    # ===== Tables budget (migration 0012) =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS postes_depense (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL UNIQUE,
            actif INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS postes_depense_secteur_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            poste_depense_id INTEGER NOT NULL,
            type_secteur TEXT NOT NULL,
            FOREIGN KEY (poste_depense_id) REFERENCES postes_depense(id) ON DELETE CASCADE,
            UNIQUE(poste_depense_id, type_secteur)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            secteur_id INTEGER NOT NULL,
            annee INTEGER NOT NULL,
            montant_global REAL NOT NULL DEFAULT 0,
            cree_par INTEGER,
            modifie_par INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (secteur_id) REFERENCES secteurs(id) ON DELETE CASCADE,
            FOREIGN KEY (cree_par) REFERENCES users(id),
            FOREIGN KEY (modifie_par) REFERENCES users(id),
            UNIQUE(secteur_id, annee)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS budget_lignes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            budget_id INTEGER NOT NULL,
            poste_depense_id INTEGER NOT NULL,
            periode TEXT NOT NULL DEFAULT 'annuel',
            montant REAL NOT NULL DEFAULT 0,
            modifie_par INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (budget_id) REFERENCES budgets(id) ON DELETE CASCADE,
            FOREIGN KEY (poste_depense_id) REFERENCES postes_depense(id) ON DELETE CASCADE,
            FOREIGN KEY (modifie_par) REFERENCES users(id),
            UNIQUE(budget_id, poste_depense_id, periode)
        )
    ''')

    # ===== Table budget reel (migration 0013) =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS budget_reel_lignes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            budget_id INTEGER NOT NULL,
            poste_depense_id INTEGER NOT NULL,
            periode TEXT NOT NULL DEFAULT 'annuel',
            montant REAL NOT NULL DEFAULT 0,
            commentaire TEXT,
            modifie_par INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (budget_id) REFERENCES budgets(id) ON DELETE CASCADE,
            FOREIGN KEY (poste_depense_id) REFERENCES postes_depense(id) ON DELETE CASCADE,
            FOREIGN KEY (modifie_par) REFERENCES users(id),
            UNIQUE(budget_id, poste_depense_id, periode)
        )
    ''')

    # ===== Table frequentation creche (migration 0014 + 0015) =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS frequentation_creche (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            secteur_id INTEGER NOT NULL,
            tranche TEXT NOT NULL,
            nb_enfants REAL DEFAULT 0,
            responsable_terrain INTEGER DEFAULT 0,
            updated_by INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (secteur_id) REFERENCES secteurs(id),
            FOREIGN KEY (updated_by) REFERENCES users(id),
            UNIQUE(secteur_id, tranche)
        )
    ''')

    # ===== Tables subventions (migration 0016) =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subventions_analytiques (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL UNIQUE,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subventions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            groupe TEXT NOT NULL DEFAULT 'nouveau_projet',
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
            ordre INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (assignee_1_id) REFERENCES users(id),
            FOREIGN KEY (assignee_2_id) REFERENCES users(id),
            FOREIGN KEY (analytique_id) REFERENCES subventions_analytiques(id),
            FOREIGN KEY (compte_comptable_1_id) REFERENCES comptabilite_comptes(id),
            FOREIGN KEY (compte_comptable_2_id) REFERENCES comptabilite_comptes(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subventions_sous_elements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subvention_id INTEGER NOT NULL,
            nom TEXT NOT NULL,
            assignee_id INTEGER,
            statut TEXT NOT NULL DEFAULT 'non_commence',
            date_echeance TEXT,
            document_path TEXT,
            document_nom TEXT,
            ordre INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (subvention_id) REFERENCES subventions(id) ON DELETE CASCADE,
            FOREIGN KEY (assignee_id) REFERENCES users(id)
        )
    ''')

    # ===== Table benevoles (migration 0017) =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS benevoles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            groupe TEXT NOT NULL DEFAULT 'nouveau',
            responsable_id INTEGER,
            date_debut TEXT,
            email TEXT,
            telephone TEXT,
            adresse TEXT,
            competences TEXT,
            heures_semaine TEXT DEFAULT '',
            ordre INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (responsable_id) REFERENCES users(id)
        )
    ''')

    # ===== Tables salles (migration 0018) =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS salles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            capacite INTEGER,
            description TEXT DEFAULT '',
            couleur TEXT DEFAULT '#2563eb',
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS recurrences_salles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            salle_id INTEGER NOT NULL,
            titre TEXT NOT NULL,
            description TEXT DEFAULT '',
            jour_semaine INTEGER NOT NULL,
            heure_debut TEXT NOT NULL,
            heure_fin TEXT NOT NULL,
            date_debut TEXT NOT NULL,
            date_fin TEXT NOT NULL,
            exclure_vacances INTEGER DEFAULT 1,
            exclure_feries INTEGER DEFAULT 1,
            active INTEGER DEFAULT 1,
            created_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (salle_id) REFERENCES salles(id),
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reservations_salles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            salle_id INTEGER NOT NULL,
            titre TEXT NOT NULL,
            description TEXT DEFAULT '',
            date TEXT NOT NULL,
            heure_debut TEXT NOT NULL,
            heure_fin TEXT NOT NULL,
            recurrence_id INTEGER,
            created_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (salle_id) REFERENCES salles(id),
            FOREIGN KEY (recurrence_id) REFERENCES recurrences_salles(id) ON DELETE CASCADE,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    ''')

    # ===== Tables tresorerie (migration 0019) =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tresorerie_imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type_import TEXT NOT NULL,
            fichier_nom TEXT NOT NULL,
            annee INTEGER,
            mois_debut INTEGER,
            mois_fin INTEGER,
            nb_ecritures INTEGER DEFAULT 0,
            nb_comptes INTEGER DEFAULT 0,
            importe_par INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (importe_par) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tresorerie_comptes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            compte_num TEXT NOT NULL UNIQUE,
            libelle_original TEXT,
            libelle_affiche TEXT,
            type_compte TEXT NOT NULL DEFAULT 'charge',
            actif INTEGER DEFAULT 1,
            ordre_affichage INTEGER DEFAULT 999,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tresorerie_donnees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            compte_num TEXT NOT NULL,
            annee INTEGER NOT NULL,
            mois INTEGER NOT NULL,
            montant REAL NOT NULL DEFAULT 0,
            import_id INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (import_id) REFERENCES tresorerie_imports(id),
            UNIQUE(compte_num, annee, mois)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tresorerie_solde_initial (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            annee INTEGER NOT NULL,
            mois INTEGER NOT NULL,
            montant REAL NOT NULL DEFAULT 0,
            annee_ref INTEGER,
            mois_ref INTEGER,
            saisi_par INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (saisi_par) REFERENCES users(id),
            UNIQUE(annee, mois)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tresorerie_budget_n (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            compte_num TEXT NOT NULL,
            annee INTEGER NOT NULL,
            mois INTEGER NOT NULL,
            montant REAL NOT NULL DEFAULT 0,
            saisi_par INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (saisi_par) REFERENCES users(id),
            UNIQUE(compte_num, annee, mois)
        )
    ''')

    # ===== Tables epargne tresorerie (migration 0021) =====
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

    # ===== Table fournisseurs (migration 0022) =====
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

    # ===== Table factures (migration 0022) =====
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

    # ===== Table historique factures (migration 0022) =====
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

    # ===== Table commentaires factures (migration 0022) =====
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

    # ===== Table regles comptables (migration 0022) =====
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

    # ===== Table ecritures comptables (migration 0022) =====
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

    # ===== Table archives export (migration 0023) =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS archives_export (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom_fichier TEXT NOT NULL,
            fichier_path TEXT NOT NULL,
            nb_ecritures INTEGER DEFAULT 0,
            created_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    ''')

    # ===== Table des modeles de contrats (DOCX) =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS modeles_contrats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            fichier_path TEXT NOT NULL,
            fichier_nom TEXT NOT NULL,
            created_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    ''')

    # ===== Table des lieux de travail =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS lieux_travail (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            adresse TEXT NOT NULL,
            created_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    ''')

    # ===== Table des forfaits CEE =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS forfaits_cee (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            montant REAL NOT NULL,
            condition TEXT,
            created_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    ''')

    # ===== Table des contrats generes (dernier contrat par salarie) =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contrats_generes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            fichier_path TEXT NOT NULL,
            fichier_nom TEXT NOT NULL,
            type_contrat TEXT,
            created_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    ''')

    # ===== Tables comptabilite analytique (migration 0026) =====

    # Actions analytiques (liste libre, ajoutables par l'utilisateur)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS comptabilite_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL UNIQUE,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Plan comptable general (comptes saisis ou importes)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS plan_comptable_general (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            compte_num TEXT NOT NULL UNIQUE,
            libelle TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Plan comptable analytique (comptes saisis ou importes)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS comptabilite_comptes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            compte_num TEXT NOT NULL UNIQUE,
            libelle TEXT NOT NULL,
            secteur_id INTEGER,
            action_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (secteur_id) REFERENCES secteurs(id),
            FOREIGN KEY (action_id) REFERENCES comptabilite_actions(id)
        )
    ''')

    # Imports FEC pour le bilan secteurs/actions
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bilan_fec_imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fichier_nom TEXT NOT NULL,
            annee INTEGER NOT NULL,
            nb_ecritures INTEGER DEFAULT 0,
            importe_par INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (importe_par) REFERENCES users(id)
        )
    ''')

    # Donnees FEC pour le bilan (charges 6x, produits 7x avec code analytique)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bilan_fec_donnees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            compte_num TEXT NOT NULL,
            libelle TEXT,
            code_analytique TEXT,
            annee INTEGER NOT NULL,
            mois INTEGER NOT NULL,
            montant REAL NOT NULL DEFAULT 0,
            import_id INTEGER,
            FOREIGN KEY (import_id) REFERENCES bilan_fec_imports(id) ON DELETE CASCADE
        )
    ''')

    # Taux de logistique par annee
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bilan_taux_logistique (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            annee INTEGER NOT NULL UNIQUE,
            taux_site1 REAL DEFAULT 0,
            taux_site2 REAL DEFAULT 0,
            taux_global REAL DEFAULT 0,
            taux_selectionne TEXT DEFAULT 'global',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # ===== Table types de secteur (migration 0027) =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS types_secteur (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            libelle TEXT NOT NULL,
            ordre INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # ===== Tables module Analyse ALSH (migration 0028) =====

    # Tranches d'âge ALSH (3-5 ans, 6-11 ans, ...)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS alsh_tranches_age (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            libelle TEXT NOT NULL,
            ordre INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Périodes ALSH (Mercredis, Vacances d'hiver, ...)
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

    # ===== Tables module Budget Prévisionnel (migration 0029) =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS budget_prev_config_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code_analytique TEXT NOT NULL UNIQUE,
            secteur_id INTEGER NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (secteur_id) REFERENCES secteurs(id) ON DELETE CASCADE
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS budget_prev_saisies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type_budget TEXT NOT NULL CHECK(type_budget IN ('initial', 'actualise')),
            annee INTEGER NOT NULL,
            secteur_id INTEGER NOT NULL,
            compte_num TEXT NOT NULL,
            valeur_temp REAL,
            valeur_def REAL DEFAULT 0,
            commentaire TEXT,
            updated_by INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (secteur_id) REFERENCES secteurs(id) ON DELETE CASCADE,
            FOREIGN KEY (updated_by) REFERENCES users(id),
            UNIQUE(type_budget, annee, secteur_id, compte_num)
        )
    ''')

    # ===== Table de suivi des migrations de schema =====
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version TEXT NOT NULL UNIQUE,
            nom TEXT NOT NULL,
            description TEXT,
            appliquee_le TEXT DEFAULT CURRENT_TIMESTAMP,
            appliquee_par TEXT,
            duree_ms INTEGER,
            statut TEXT DEFAULT 'ok'
        )
    ''')

    # --- Donnees initiales ---

    # Marquer toutes les migrations comme appliquees pour les nouvelles installations
    cursor.execute("SELECT COUNT(*) as nb FROM schema_migrations")
    if cursor.fetchone()[0] == 0:
        for version, nom in ALL_MIGRATION_VERSIONS:
            cursor.execute(
                "INSERT INTO schema_migrations (version, nom, description, appliquee_par, duree_ms, statut) "
                "VALUES (?, ?, 'Inclus dans le schema initial', 'systeme', 0, 'ok')",
                (version, nom)
            )

    # Inserer les postes de depense par defaut (migration 0012) si la table est vide
    existing_postes = cursor.execute('SELECT COUNT(*) FROM postes_depense').fetchone()[0]
    if existing_postes == 0:
        for nom_poste, types in _POSTES_DEPENSE_DEFAUT:
            cursor.execute('INSERT INTO postes_depense (nom) VALUES (?)', (nom_poste,))
            poste_id = cursor.lastrowid
            for type_s in types:
                cursor.execute(
                    'INSERT OR IGNORE INTO postes_depense_secteur_types (poste_depense_id, type_secteur) VALUES (?, ?)',
                    (poste_id, type_s)
                )

    # Inserer les types de secteur par defaut (migration 0027) si la table est vide
    existing_types = cursor.execute('SELECT COUNT(*) FROM types_secteur').fetchone()[0]
    if existing_types == 0:
        types_defaut = [
            ('creche', 'Crèche', 1),
            ('accueil_loisirs', 'Accueil de loisirs', 2),
            ('famille', 'Secteur famille', 3),
            ('emploi_formation', 'Emploi/formation', 4),
            ('administratif', 'Administratif', 5),
            ('entretien', 'Entretien', 6),
        ]
        for code, libelle, ordre in types_defaut:
            cursor.execute(
                'INSERT OR IGNORE INTO types_secteur (code, libelle, ordre) VALUES (?, ?, ?)',
                (code, libelle, ordre)
            )

    # Inserer les tranches d'age ALSH par defaut (migration 0028) si la table est vide
    existing_tranches = cursor.execute('SELECT COUNT(*) FROM alsh_tranches_age').fetchone()[0]
    if existing_tranches == 0:
        for libelle, ordre in [('3-5 ans', 1), ('6-11 ans', 2)]:
            cursor.execute(
                'INSERT OR IGNORE INTO alsh_tranches_age (libelle, ordre) VALUES (?, ?)',
                (libelle, ordre)
            )

    # Inserer les periodes ALSH par defaut (migration 0028) si la table est vide
    existing_periodes = cursor.execute('SELECT COUNT(*) FROM alsh_periodes').fetchone()[0]
    if existing_periodes == 0:
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

    # --- Migrations incrementales pour bases existantes ---
    # Ces blocs ne s'executent que si les colonnes manquent (anciennes installations).

    # Migration : ajouter solde_initial si n'existe pas
    try:
        cursor.execute("SELECT solde_initial FROM users LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE users ADD COLUMN solde_initial REAL DEFAULT 0")

    # Migration : ajouter colonnes conges si n'existent pas
    for col, col_type in [('cp_acquis', 'REAL DEFAULT 0'), ('cp_a_prendre', 'REAL DEFAULT 0'),
                          ('cp_pris', 'REAL DEFAULT 0'), ('cc_solde', 'REAL DEFAULT 0'),
                          ('date_entree', 'TEXT')]:
        try:
            cursor.execute(f"SELECT {col} FROM users LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")

    # Migration : ajouter date_debut_validite si n'existe pas
    try:
        cursor.execute("SELECT date_debut_validite FROM planning_theorique LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE planning_theorique ADD COLUMN date_debut_validite TEXT NOT NULL DEFAULT '2000-01-01'")

    # Migration : ajouter type_alternance si n'existe pas
    try:
        cursor.execute("SELECT type_alternance FROM planning_theorique LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE planning_theorique ADD COLUMN type_alternance TEXT DEFAULT 'fixe'")

    # Migration : ajouter pesee si n'existe pas
    try:
        cursor.execute("SELECT pesee FROM users LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE users ADD COLUMN pesee INTEGER")

    # Migration : ajouter email si n'existe pas
    try:
        cursor.execute("SELECT email FROM users LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE users ADD COLUMN email TEXT")

    # Migration : ajouter email_notifications_enabled si n'existe pas
    try:
        cursor.execute("SELECT email_notifications_enabled FROM users LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE users ADD COLUMN email_notifications_enabled INTEGER DEFAULT 0")

    # Migration : ajouter force_password_change si n'existe pas
    try:
        cursor.execute("SELECT force_password_change FROM users LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE users ADD COLUMN force_password_change INTEGER DEFAULT 0")

    # Migration : ajouter type_secteur si n'existe pas
    try:
        cursor.execute("SELECT type_secteur FROM secteurs LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE secteurs ADD COLUMN type_secteur TEXT DEFAULT NULL")

    # Migration : ajouter temps_hebdo si n'existe pas dans contrats
    try:
        cursor.execute("SELECT temps_hebdo FROM contrats LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE contrats ADD COLUMN temps_hebdo REAL")

    conn.commit()
    conn.close()
