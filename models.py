"""
Modèles SQLAlchemy pour toutes les tables de l'application.
Utilisés par Flask-Migrate pour générer les migrations PostgreSQL.
Les blueprints continuent d'utiliser database.get_db() avec du SQL brut.
"""
from extensions import db


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nom = db.Column(db.Text, nullable=False)
    prenom = db.Column(db.Text, nullable=False)
    login = db.Column(db.Text, unique=True, nullable=False)
    password = db.Column(db.Text, nullable=False)
    profil = db.Column(db.Text, nullable=False)
    secteur_id = db.Column(db.Integer, db.ForeignKey('secteurs.id'))
    responsable_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    actif = db.Column(db.Integer, default=1)
    solde_initial = db.Column(db.Float, default=0)
    cp_acquis = db.Column(db.Float, default=0)
    cp_a_prendre = db.Column(db.Float, default=0)
    cp_pris = db.Column(db.Float, default=0)
    cc_solde = db.Column(db.Float, default=0)
    date_entree = db.Column(db.Text)
    pesee = db.Column(db.Integer)
    email = db.Column(db.Text)
    email_notifications_enabled = db.Column(db.Integer, default=0)
    adresse = db.Column(db.Text)
    date_naissance = db.Column(db.Text)
    numero_secu = db.Column(db.Text)


class Secteur(db.Model):
    __tablename__ = 'secteurs'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nom = db.Column(db.Text, unique=True, nullable=False)
    description = db.Column(db.Text)
    type_secteur = db.Column(db.Text)
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class PlanningTheorique(db.Model):
    __tablename__ = 'planning_theorique'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    type_periode = db.Column(db.Text, nullable=False)
    date_debut_validite = db.Column(db.Text, nullable=False, default='2000-01-01')
    type_alternance = db.Column(db.Text, default='fixe')
    lundi_matin_debut = db.Column(db.Text)
    lundi_matin_fin = db.Column(db.Text)
    lundi_aprem_debut = db.Column(db.Text)
    lundi_aprem_fin = db.Column(db.Text)
    mardi_matin_debut = db.Column(db.Text)
    mardi_matin_fin = db.Column(db.Text)
    mardi_aprem_debut = db.Column(db.Text)
    mardi_aprem_fin = db.Column(db.Text)
    mercredi_matin_debut = db.Column(db.Text)
    mercredi_matin_fin = db.Column(db.Text)
    mercredi_aprem_debut = db.Column(db.Text)
    mercredi_aprem_fin = db.Column(db.Text)
    jeudi_matin_debut = db.Column(db.Text)
    jeudi_matin_fin = db.Column(db.Text)
    jeudi_aprem_debut = db.Column(db.Text)
    jeudi_aprem_fin = db.Column(db.Text)
    vendredi_matin_debut = db.Column(db.Text)
    vendredi_matin_fin = db.Column(db.Text)
    vendredi_aprem_debut = db.Column(db.Text)
    vendredi_aprem_fin = db.Column(db.Text)
    total_hebdo = db.Column(db.Float)


class AlternanceReference(db.Model):
    __tablename__ = 'alternance_reference'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date_reference = db.Column(db.Text, nullable=False)
    date_debut_validite = db.Column(db.Text, nullable=False)


class Anomalie(db.Model):
    __tablename__ = 'anomalies'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date_modification = db.Column(db.Text, nullable=False)
    date_concernee = db.Column(db.Text, nullable=False)
    type_anomalie = db.Column(db.Text, nullable=False)
    gravite = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text)
    ancienne_valeur = db.Column(db.Text)
    nouvelle_valeur = db.Column(db.Text)
    traitee = db.Column(db.Integer, default=0)


class HeuresReelles(db.Model):
    __tablename__ = 'heures_reelles'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date = db.Column(db.Text, nullable=False)
    heure_debut_matin = db.Column(db.Text)
    heure_fin_matin = db.Column(db.Text)
    heure_debut_aprem = db.Column(db.Text)
    heure_fin_aprem = db.Column(db.Text)
    commentaire = db.Column(db.Text)
    type_saisie = db.Column(db.Text, default='heures_sup')
    declaration_conforme = db.Column(db.Integer, default=0)
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())
    __table_args__ = (db.UniqueConstraint('user_id', 'date'),)


class Validation(db.Model):
    __tablename__ = 'validations'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    mois = db.Column(db.Integer, nullable=False)
    annee = db.Column(db.Integer, nullable=False)
    validation_salarie = db.Column(db.Text)
    validation_responsable = db.Column(db.Text)
    validation_directeur = db.Column(db.Text)
    date_salarie = db.Column(db.Text)
    date_responsable = db.Column(db.Text)
    date_directeur = db.Column(db.Text)
    bloque = db.Column(db.Integer, default=0)
    __table_args__ = (db.UniqueConstraint('user_id', 'mois', 'annee'),)


class PeriodeVacances(db.Model):
    __tablename__ = 'periodes_vacances'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nom = db.Column(db.Text, nullable=False)
    date_debut = db.Column(db.Text, nullable=False)
    date_fin = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class HistoriqueModification(db.Model):
    __tablename__ = 'historique_modifications'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id_modifie = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date_concernee = db.Column(db.Text, nullable=False)
    modifie_par = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date_modification = db.Column(db.Text, server_default=db.func.current_timestamp())
    action = db.Column(db.Text, nullable=False)
    anciennes_valeurs = db.Column(db.Text)
    nouvelles_valeurs = db.Column(db.Text)


class DemandeRecup(db.Model):
    __tablename__ = 'demandes_recup'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date_demande = db.Column(db.Text, server_default=db.func.current_timestamp())
    date_debut = db.Column(db.Text, nullable=False)
    date_fin = db.Column(db.Text, nullable=False)
    nb_jours = db.Column(db.Float, nullable=False)
    nb_heures = db.Column(db.Float, nullable=False)
    motif_demande = db.Column(db.Text)
    statut = db.Column(db.Text, default='en_attente_responsable')
    validation_responsable = db.Column(db.Text)
    date_validation_responsable = db.Column(db.Text)
    validation_direction = db.Column(db.Text)
    date_validation_direction = db.Column(db.Text)
    motif_refus = db.Column(db.Text)
    refuse_par = db.Column(db.Integer, db.ForeignKey('users.id'))
    date_refus = db.Column(db.Text)


class JourFerie(db.Model):
    __tablename__ = 'jours_feries'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    annee = db.Column(db.Integer, nullable=False)
    date = db.Column(db.Text, nullable=False)
    libelle = db.Column(db.Text, nullable=False)
    __table_args__ = (db.UniqueConstraint('date'),)


class PlanningEnfanceConfig(db.Model):
    __tablename__ = 'planning_enfance_config'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    annee = db.Column(db.Integer, nullable=False)
    config_json = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())
    updated_at = db.Column(db.Text, server_default=db.func.current_timestamp())
    __table_args__ = (db.UniqueConstraint('user_id', 'annee'),)


class Absence(db.Model):
    __tablename__ = 'absences'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    motif = db.Column(db.Text, nullable=False)
    date_debut = db.Column(db.Text, nullable=False)
    date_fin = db.Column(db.Text, nullable=False)
    date_reprise = db.Column(db.Text)
    commentaire = db.Column(db.Text)
    jours_ouvres = db.Column(db.Float, nullable=False)
    justificatif_path = db.Column(db.Text)
    justificatif_nom = db.Column(db.Text)
    saisi_par = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class AppSetting(db.Model):
    __tablename__ = 'app_settings'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    key = db.Column(db.Text, unique=True, nullable=False)
    value = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class PresenceForfaitJour(db.Model):
    __tablename__ = 'presence_forfait_jour'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date = db.Column(db.Text, nullable=False)
    type_journee = db.Column(db.Text, nullable=False)
    commentaire = db.Column(db.Text)
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())
    __table_args__ = (db.UniqueConstraint('user_id', 'date'),)


class ValidationForfaitJour(db.Model):
    __tablename__ = 'validation_forfait_jour'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    mois = db.Column(db.Integer, nullable=False)
    annee = db.Column(db.Integer, nullable=False)
    date_validation = db.Column(db.Text, server_default=db.func.current_timestamp())
    valide_par = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('user_id', 'mois', 'annee'),)


class VariablesPaieDefauts(db.Model):
    __tablename__ = 'variables_paie_defauts'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    mutuelle = db.Column(db.Text)
    nb_enfants = db.Column(db.Integer, default=0)
    saisie_salaire = db.Column(db.Text)
    pret_avance = db.Column(db.Text)


class VariablesPaie(db.Model):
    __tablename__ = 'variables_paie'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    mois = db.Column(db.Integer, nullable=False)
    annee = db.Column(db.Integer, nullable=False)
    mutuelle = db.Column(db.Text)
    nb_enfants = db.Column(db.Integer, default=0)
    transport = db.Column(db.Text)
    acompte = db.Column(db.Text)
    saisie_salaire = db.Column(db.Text)
    pret_avance = db.Column(db.Text)
    autres_regularisation = db.Column(db.Text)
    commentaire = db.Column(db.Text)
    heures_reelles = db.Column(db.Float)
    heures_supps = db.Column(db.Float)
    saisi_par = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())
    updated_at = db.Column(db.Text, server_default=db.func.current_timestamp())
    __table_args__ = (db.UniqueConstraint('user_id', 'mois', 'annee'),)


class Contrat(db.Model):
    __tablename__ = 'contrats'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    type_contrat = db.Column(db.Text, nullable=False)
    date_debut = db.Column(db.Text, nullable=False)
    date_fin = db.Column(db.Text)
    forfait = db.Column(db.Text)
    nbr_jours = db.Column(db.Float)
    fichier_path = db.Column(db.Text)
    fichier_nom = db.Column(db.Text)
    saisi_par = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class DocumentSalarie(db.Model):
    __tablename__ = 'documents_salaries'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    type_document = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text)
    fichier_path = db.Column(db.Text, nullable=False)
    fichier_nom = db.Column(db.Text, nullable=False)
    saisi_par = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class PrepaPaieStatut(db.Model):
    __tablename__ = 'prepa_paie_statut'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    mois = db.Column(db.Integer, nullable=False)
    annee = db.Column(db.Integer, nullable=False)
    traite = db.Column(db.Integer, default=0)
    traite_par = db.Column(db.Integer, db.ForeignKey('users.id'))
    updated_at = db.Column(db.Text, server_default=db.func.current_timestamp())
    __table_args__ = (db.UniqueConstraint('user_id', 'mois', 'annee'),)


class CongesClotureMensuelle(db.Model):
    __tablename__ = 'conges_cloture_mensuelle'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    mois = db.Column(db.Integer, nullable=False)
    annee = db.Column(db.Integer, nullable=False)
    cloture_le = db.Column(db.Text, server_default=db.func.current_timestamp())
    cloture_par = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    nb_salaries_traites = db.Column(db.Integer, default=0)
    detail = db.Column(db.Text)
    __table_args__ = (db.UniqueConstraint('mois', 'annee'),)


class PosteAlisfa(db.Model):
    __tablename__ = 'postes_alisfa'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    intitule = db.Column(db.Text, nullable=False)
    famille_metier = db.Column(db.Text, nullable=False)
    emploi_repere = db.Column(db.Text)
    formation_niveau = db.Column(db.Integer, default=1)
    complexite_niveau = db.Column(db.Integer, default=1)
    autonomie_niveau = db.Column(db.Integer, default=1)
    relationnel_niveau = db.Column(db.Integer, default=1)
    finances_niveau = db.Column(db.Integer, default=1)
    rh_niveau = db.Column(db.Integer, default=1)
    securite_niveau = db.Column(db.Integer, default=1)
    projet_niveau = db.Column(db.Integer, default=1)
    total_points = db.Column(db.Integer, default=0)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())
    updated_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class PosteDepense(db.Model):
    __tablename__ = 'postes_depense'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nom = db.Column(db.Text, unique=True, nullable=False)
    actif = db.Column(db.Integer, default=1)
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class PosteDepenseSecteurType(db.Model):
    __tablename__ = 'postes_depense_secteur_types'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    poste_depense_id = db.Column(db.Integer, db.ForeignKey('postes_depense.id', ondelete='CASCADE'), nullable=False)
    type_secteur = db.Column(db.Text, nullable=False)
    __table_args__ = (db.UniqueConstraint('poste_depense_id', 'type_secteur'),)


class Budget(db.Model):
    __tablename__ = 'budgets'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    secteur_id = db.Column(db.Integer, db.ForeignKey('secteurs.id', ondelete='CASCADE'), nullable=False)
    annee = db.Column(db.Integer, nullable=False)
    montant_global = db.Column(db.Float, nullable=False, default=0)
    cree_par = db.Column(db.Integer, db.ForeignKey('users.id'))
    modifie_par = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())
    updated_at = db.Column(db.Text, server_default=db.func.current_timestamp())
    __table_args__ = (db.UniqueConstraint('secteur_id', 'annee'),)


class BudgetLigne(db.Model):
    __tablename__ = 'budget_lignes'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    budget_id = db.Column(db.Integer, db.ForeignKey('budgets.id', ondelete='CASCADE'), nullable=False)
    poste_depense_id = db.Column(db.Integer, db.ForeignKey('postes_depense.id', ondelete='CASCADE'), nullable=False)
    periode = db.Column(db.Text, nullable=False, default='annuel')
    montant = db.Column(db.Float, nullable=False, default=0)
    modifie_par = db.Column(db.Integer, db.ForeignKey('users.id'))
    updated_at = db.Column(db.Text, server_default=db.func.current_timestamp())
    __table_args__ = (db.UniqueConstraint('budget_id', 'poste_depense_id', 'periode'),)


class BudgetReelLigne(db.Model):
    __tablename__ = 'budget_reel_lignes'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    budget_id = db.Column(db.Integer, db.ForeignKey('budgets.id', ondelete='CASCADE'), nullable=False)
    poste_depense_id = db.Column(db.Integer, db.ForeignKey('postes_depense.id', ondelete='CASCADE'), nullable=False)
    periode = db.Column(db.Text, nullable=False, default='annuel')
    montant = db.Column(db.Float, nullable=False, default=0)
    commentaire = db.Column(db.Text)
    modifie_par = db.Column(db.Integer, db.ForeignKey('users.id'))
    updated_at = db.Column(db.Text, server_default=db.func.current_timestamp())
    __table_args__ = (db.UniqueConstraint('budget_id', 'poste_depense_id', 'periode'),)


class FrequentationCreche(db.Model):
    __tablename__ = 'frequentation_creche'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    secteur_id = db.Column(db.Integer, db.ForeignKey('secteurs.id'), nullable=False)
    tranche = db.Column(db.Text, nullable=False)
    nb_enfants = db.Column(db.Float, default=0)
    responsable_terrain = db.Column(db.Integer, default=0)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    updated_at = db.Column(db.Text, server_default=db.func.current_timestamp())
    __table_args__ = (db.UniqueConstraint('secteur_id', 'tranche'),)


class SubventionAnalytique(db.Model):
    __tablename__ = 'subventions_analytiques'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nom = db.Column(db.Text, unique=True, nullable=False)
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class Subvention(db.Model):
    __tablename__ = 'subventions'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nom = db.Column(db.Text, nullable=False)
    groupe = db.Column(db.Text, nullable=False, default='nouveau_projet')
    assignee_1_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    assignee_2_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    date_echeance = db.Column(db.Text)
    montant_demande = db.Column(db.Float, default=0)
    montant_accorde = db.Column(db.Float, default=0)
    date_notification = db.Column(db.Text)
    justificatif_path = db.Column(db.Text)
    justificatif_nom = db.Column(db.Text)
    analytique_id = db.Column(db.Integer, db.ForeignKey('subventions_analytiques.id'))
    contact_email = db.Column(db.Text)
    compte_comptable = db.Column(db.Text)
    ordre = db.Column(db.Integer, default=0)
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())
    updated_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class SubventionSousElement(db.Model):
    __tablename__ = 'subventions_sous_elements'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    subvention_id = db.Column(db.Integer, db.ForeignKey('subventions.id', ondelete='CASCADE'), nullable=False)
    nom = db.Column(db.Text, nullable=False)
    assignee_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    statut = db.Column(db.Text, nullable=False, default='non_commence')
    date_echeance = db.Column(db.Text)
    ordre = db.Column(db.Integer, default=0)
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class Benevole(db.Model):
    __tablename__ = 'benevoles'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nom = db.Column(db.Text, nullable=False)
    groupe = db.Column(db.Text, nullable=False, default='nouveau')
    responsable_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    date_debut = db.Column(db.Text)
    email = db.Column(db.Text)
    telephone = db.Column(db.Text)
    adresse = db.Column(db.Text)
    competences = db.Column(db.Text)
    heures_semaine = db.Column(db.Text, default='')
    ordre = db.Column(db.Integer, default=0)
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())
    updated_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class Salle(db.Model):
    __tablename__ = 'salles'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nom = db.Column(db.Text, nullable=False)
    capacite = db.Column(db.Integer)
    description = db.Column(db.Text, default='')
    couleur = db.Column(db.Text, default='#2563eb')
    active = db.Column(db.Integer, default=1)
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class RecurrenceSalle(db.Model):
    __tablename__ = 'recurrences_salles'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    salle_id = db.Column(db.Integer, db.ForeignKey('salles.id'), nullable=False)
    titre = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, default='')
    jour_semaine = db.Column(db.Integer, nullable=False)
    heure_debut = db.Column(db.Text, nullable=False)
    heure_fin = db.Column(db.Text, nullable=False)
    date_debut = db.Column(db.Text, nullable=False)
    date_fin = db.Column(db.Text, nullable=False)
    exclure_vacances = db.Column(db.Integer, default=1)
    exclure_feries = db.Column(db.Integer, default=1)
    active = db.Column(db.Integer, default=1)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class ReservationSalle(db.Model):
    __tablename__ = 'reservations_salles'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    salle_id = db.Column(db.Integer, db.ForeignKey('salles.id'), nullable=False)
    titre = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, default='')
    date = db.Column(db.Text, nullable=False)
    heure_debut = db.Column(db.Text, nullable=False)
    heure_fin = db.Column(db.Text, nullable=False)
    recurrence_id = db.Column(db.Integer, db.ForeignKey('recurrences_salles.id', ondelete='CASCADE'))
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class TresorerieImport(db.Model):
    __tablename__ = 'tresorerie_imports'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    type_import = db.Column(db.Text, nullable=False)
    fichier_nom = db.Column(db.Text, nullable=False)
    annee = db.Column(db.Integer)
    mois_debut = db.Column(db.Integer)
    mois_fin = db.Column(db.Integer)
    nb_ecritures = db.Column(db.Integer, default=0)
    nb_comptes = db.Column(db.Integer, default=0)
    importe_par = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class TresorerieCompte(db.Model):
    __tablename__ = 'tresorerie_comptes'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    compte_num = db.Column(db.Text, unique=True, nullable=False)
    libelle_original = db.Column(db.Text)
    libelle_affiche = db.Column(db.Text)
    type_compte = db.Column(db.Text, nullable=False, default='charge')
    actif = db.Column(db.Integer, default=1)
    ordre_affichage = db.Column(db.Integer, default=999)
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())
    updated_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class TresorerieDonnee(db.Model):
    __tablename__ = 'tresorerie_donnees'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    compte_num = db.Column(db.Text, nullable=False)
    annee = db.Column(db.Integer, nullable=False)
    mois = db.Column(db.Integer, nullable=False)
    montant = db.Column(db.Float, nullable=False, default=0)
    import_id = db.Column(db.Integer, db.ForeignKey('tresorerie_imports.id'))
    updated_at = db.Column(db.Text, server_default=db.func.current_timestamp())
    __table_args__ = (db.UniqueConstraint('compte_num', 'annee', 'mois'),)


class TresorerieSoldeInitial(db.Model):
    __tablename__ = 'tresorerie_solde_initial'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    annee = db.Column(db.Integer, nullable=False)
    mois = db.Column(db.Integer, nullable=False)
    montant = db.Column(db.Float, nullable=False, default=0)
    annee_ref = db.Column(db.Integer)
    mois_ref = db.Column(db.Integer)
    saisi_par = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())
    __table_args__ = (db.UniqueConstraint('annee', 'mois'),)


class TresorerieBudgetN(db.Model):
    __tablename__ = 'tresorerie_budget_n'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    compte_num = db.Column(db.Text, nullable=False)
    annee = db.Column(db.Integer, nullable=False)
    mois = db.Column(db.Integer, nullable=False)
    montant = db.Column(db.Float, nullable=False, default=0)
    saisi_par = db.Column(db.Integer, db.ForeignKey('users.id'))
    updated_at = db.Column(db.Text, server_default=db.func.current_timestamp())
    __table_args__ = (db.UniqueConstraint('compte_num', 'annee', 'mois'),)


class TresorerieEpargneSolde(db.Model):
    __tablename__ = 'tresorerie_epargne_solde'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    montant = db.Column(db.Float, nullable=False, default=0)
    saisi_par = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class TresorerieEpargneMouvement(db.Model):
    __tablename__ = 'tresorerie_epargne_mouvements'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    type_mouvement = db.Column(db.Text, nullable=False)
    annee = db.Column(db.Integer, nullable=False)
    mois = db.Column(db.Integer, nullable=False)
    montant = db.Column(db.Float, nullable=False)
    commentaire = db.Column(db.Text)
    saisi_par = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class Fournisseur(db.Model):
    __tablename__ = 'fournisseurs'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nom = db.Column(db.Text, nullable=False)
    alias1 = db.Column(db.Text)
    alias2 = db.Column(db.Text)
    code_comptable = db.Column(db.Text)
    email_contact = db.Column(db.Text)
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())
    updated_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class Facture(db.Model):
    __tablename__ = 'factures'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    fournisseur_id = db.Column(db.Integer, db.ForeignKey('fournisseurs.id'))
    numero_facture = db.Column(db.Text)
    date_facture = db.Column(db.Text)
    date_echeance = db.Column(db.Text)
    montant_ttc = db.Column(db.Float)
    description = db.Column(db.Text)
    fichier_path = db.Column(db.Text)
    fichier_nom = db.Column(db.Text)
    fichier_original = db.Column(db.Text)
    secteur_id = db.Column(db.Integer, db.ForeignKey('secteurs.id'))
    assigned_direction = db.Column(db.Integer, default=0)
    statut = db.Column(db.Text, default='a_traiter')
    approbation = db.Column(db.Text, default='en_attente')
    approuve_par = db.Column(db.Integer, db.ForeignKey('users.id'))
    date_approbation = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())
    updated_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class FactureHistorique(db.Model):
    __tablename__ = 'facture_historique'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    facture_id = db.Column(db.Integer, db.ForeignKey('factures.id', ondelete='CASCADE'), nullable=False)
    action = db.Column(db.Text, nullable=False)
    details = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class FactureCommentaire(db.Model):
    __tablename__ = 'facture_commentaires'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    facture_id = db.Column(db.Integer, db.ForeignKey('factures.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    commentaire = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class RegleComptable(db.Model):
    __tablename__ = 'regles_comptables'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nom = db.Column(db.Text, nullable=False)
    type_regle = db.Column(db.Text, nullable=False)
    cible = db.Column(db.Text, nullable=False)
    compte_comptable = db.Column(db.Text, nullable=False)
    code_analytique_1 = db.Column(db.Text)
    code_analytique_2 = db.Column(db.Text)
    pourcentage_analytique_1 = db.Column(db.Float, default=100)
    pourcentage_analytique_2 = db.Column(db.Float, default=0)
    modele_libelle = db.Column(db.Text, default='{supplier} {invoice_number} {date} {period}')
    statut = db.Column(db.Text, default='active')
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())
    updated_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class EcritureComptable(db.Model):
    __tablename__ = 'ecritures_comptables'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    facture_id = db.Column(db.Integer, db.ForeignKey('factures.id', ondelete='CASCADE'), nullable=False)
    date_ecriture = db.Column(db.Text, nullable=False)
    compte = db.Column(db.Text, nullable=False)
    libelle = db.Column(db.Text, nullable=False)
    numero_facture = db.Column(db.Text)
    debit = db.Column(db.Float, default=0)
    credit = db.Column(db.Float, default=0)
    code_analytique = db.Column(db.Text)
    echeance = db.Column(db.Text)
    statut = db.Column(db.Text, default='brouillon')
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())
    updated_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class ArchiveExport(db.Model):
    __tablename__ = 'archives_export'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nom_fichier = db.Column(db.Text, nullable=False)
    fichier_path = db.Column(db.Text, nullable=False)
    nb_ecritures = db.Column(db.Integer, default=0)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class ModeleContrat(db.Model):
    __tablename__ = 'modeles_contrats'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nom = db.Column(db.Text, nullable=False)
    fichier_path = db.Column(db.Text, nullable=False)
    fichier_nom = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class LieuTravail(db.Model):
    __tablename__ = 'lieux_travail'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nom = db.Column(db.Text, nullable=False)
    adresse = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class ForfaitCee(db.Model):
    __tablename__ = 'forfaits_cee'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    montant = db.Column(db.Float, nullable=False)
    condition = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class ContratGenere(db.Model):
    __tablename__ = 'contrats_generes'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    fichier_path = db.Column(db.Text, nullable=False)
    fichier_nom = db.Column(db.Text, nullable=False)
    type_contrat = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class ComptabiliteAction(db.Model):
    __tablename__ = 'comptabilite_actions'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nom = db.Column(db.Text, unique=True, nullable=False)
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class PlanComptableGeneral(db.Model):
    __tablename__ = 'plan_comptable_general'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    compte_num = db.Column(db.Text, unique=True, nullable=False)
    libelle = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())
    updated_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class ComptabiliteCompte(db.Model):
    __tablename__ = 'comptabilite_comptes'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    compte_num = db.Column(db.Text, unique=True, nullable=False)
    libelle = db.Column(db.Text, nullable=False)
    secteur_id = db.Column(db.Integer, db.ForeignKey('secteurs.id'))
    action_id = db.Column(db.Integer, db.ForeignKey('comptabilite_actions.id'))
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())
    updated_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class BilanFecImport(db.Model):
    __tablename__ = 'bilan_fec_imports'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    fichier_nom = db.Column(db.Text, nullable=False)
    annee = db.Column(db.Integer, nullable=False)
    nb_ecritures = db.Column(db.Integer, default=0)
    importe_par = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class BilanFecDonnee(db.Model):
    __tablename__ = 'bilan_fec_donnees'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    compte_num = db.Column(db.Text, nullable=False)
    libelle = db.Column(db.Text)
    code_analytique = db.Column(db.Text)
    annee = db.Column(db.Integer, nullable=False)
    mois = db.Column(db.Integer, nullable=False)
    montant = db.Column(db.Float, nullable=False, default=0)
    import_id = db.Column(db.Integer, db.ForeignKey('bilan_fec_imports.id', ondelete='CASCADE'))


class BilanTauxLogistique(db.Model):
    __tablename__ = 'bilan_taux_logistique'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    annee = db.Column(db.Integer, unique=True, nullable=False)
    taux_site1 = db.Column(db.Float, default=0)
    taux_site2 = db.Column(db.Float, default=0)
    taux_global = db.Column(db.Float, default=0)
    taux_selectionne = db.Column(db.Text, default='global')
    updated_at = db.Column(db.Text, server_default=db.func.current_timestamp())


class SchemaMigration(db.Model):
    __tablename__ = 'schema_migrations'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    version = db.Column(db.Text, unique=True, nullable=False)
    nom = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text)
    appliquee_le = db.Column(db.Text, server_default=db.func.current_timestamp())
    appliquee_par = db.Column(db.Text)
    duree_ms = db.Column(db.Integer)
    statut = db.Column(db.Text, default='ok')
