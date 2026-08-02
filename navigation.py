"""
Carte de navigation de l'interface sans menu.

L'interface « flux » remplace le menu latéral par trois choses :
- un fil d'actions sur l'accueil ;
- une barre intelligente qui s'ouvre dès la première touche frappée ;
- une vue d'ensemble (touche Échap) où l'application est représentée par zones.

Ce module est la source unique de cette représentation. Il décrit :
- les ZONES thématiques (cercle intérieur de la vue d'ensemble), qui regroupent
  les pages du menu historique en thèmes cohérents ;
- les ACCÈS DIRECTS (cercle extérieur), pour les pages qu'on ouvre sans passer
  par un thème (salles, planificateur, administration…).

Chaque page porte les profils qui y ont droit et, si besoin, une condition
nommée évaluée dans le contexte de l'utilisateur (délégation, option, rôle CSE).
Les listes reproduisent les droits du menu latéral historique : ce module ne
donne aucun accès nouveau, il réorganise seulement la présentation. Les routes
conservent leur propre contrôle d'accès.
"""
import logging

from flask import url_for

logger = logging.getLogger(__name__)

TOUS_PROFILS = ('directeur', 'comptable', 'responsable', 'salarie')

# Profils qui basculent d'office sur l'interface sans menu. Les salariés s'y
# ajoutent uniquement s'ils portent une délégation (voir `est_eligible`).
PROFILS_FLUX = ('directeur', 'comptable', 'responsable')


def _page(endpoint, label, profils=TOUS_PROFILS, condition=None, labels=None,
          resume=''):
    """Décrit une page de la carte.

    - `profils` : profils qui voient l'entrée sans condition supplémentaire.
    - `condition` : nom d'un drapeau du contexte utilisateur ; s'il est vrai,
      l'entrée est visible quel que soit le profil (délégation, rôle CSE) ou,
      combiné à `profils`, la restreint (option d'administration).
    - `labels` : libellés alternatifs par profil (une même page ne se nomme pas
      pareil selon qu'on gère son planning ou celui de l'équipe).
    """
    return {
        'endpoint': endpoint,
        'label': label,
        'labels': labels or {},
        'profils': tuple(profils),
        'condition': condition,
        'resume': resume,
    }


# ── Zones thématiques : le cercle intérieur ────────────────────────────────
# `mots` alimente la recherche locale de la barre intelligente (sans accents,
# la comparaison étant faite sur une forme normalisée).
ZONES = [
    {
        'id': 'validations',
        'nom': 'Validations & suivi',
        'icone': '✓',
        'description': "Demandes, fiches d'heures, anomalies et factures en attente de votre décision.",
        'mots': 'validation valider suivi demande conge recup anomalie surcharge facture approbation fiche heures historique',
        'pages': [
            _page('validation_bp.vue_ensemble_validation', "Vue d'ensemble",
                  profils=('directeur', 'comptable', 'responsable'),
                  condition='can_access_vue_ensemble_validation',
                  resume="L'état de validation des fiches, mois par mois."),
            _page('recup_bp.validation_demandes_recup', 'Validation des demandes',
                  profils=('directeur', 'comptable', 'responsable'),
                  resume='Congés et récupérations à valider ou refuser.'),
            _page('recup_bp.historique_demandes_recup', 'Historique des demandes',
                  profils=('directeur', 'comptable')),
            _page('suivi_bp.historique_modifications', 'Historique des modifications',
                  profils=('directeur',)),
            _page('suivi_bp.suivi_anomalies', 'Suivi des anomalies',
                  profils=('directeur', 'comptable')),
            _page('suivi_bp.alertes_surcharge', 'Alertes de surcharge',
                  profils=('directeur', 'comptable')),
            _page('factures_bp.approbation_factures', 'Approbation des factures',
                  profils=('directeur', 'responsable')),
        ],
    },
    {
        'id': 'temps',
        'nom': 'Temps & plannings',
        'icone': '◷',
        'description': "Saisie des heures, plannings, présence de l'équipe et temps annualisé.",
        'mots': 'temps heure saisie saisir planning plannings mensuelle calendrier equipe presence effectif annualise forfait jour',
        'pages': [
            _page('saisie_bp.saisie_heures', 'Saisir mes heures',
                  profils=('comptable', 'responsable', 'salarie')),
            _page('validation_bp.vue_mensuelle', 'Vue mensuelle',
                  profils=('comptable', 'responsable', 'salarie')),
            _page('validation_bp.vue_calendrier', 'Vue calendrier',
                  profils=('comptable', 'responsable', 'salarie')),
            _page('planning_bp.planning_theorique', 'Mon planning',
                  labels={'directeur': 'Plannings des salariés',
                          'comptable': 'Plannings des salariés'}),
            _page('mon_equipe_bp.mon_equipe', 'Mon équipe',
                  profils=('comptable', 'responsable', 'salarie')),
            _page('presence_effectif_bp.presence_effectif', "Présence de l'effectif",
                  profils=('directeur', 'comptable')),
            _page('planning_enfance_bp.planning_enfance', 'Temps annualisé',
                  profils=('directeur', 'comptable', 'responsable')),
            _page('forfait_bp.dashboard_forfait_jour', 'Forfait jour',
                  profils=('directeur',)),
            _page('forfait_bp.calendrier_forfait_jour', 'Calendrier forfait jour',
                  profils=('directeur',)),
        ],
    },
    {
        'id': 'rh',
        'nom': 'RH & Paie',
        'icone': '◈',
        'description': 'Dossiers salariés, contrats, absences, variables et préparation de la paie.',
        'mots': 'rh paie salarie contrat absence maladie solde conge statistique alisfa pesee poste assistant variable prepa embauche',
        'pages': [
            _page('infos_salaries_bp.infos_salaries', 'Infos salariés',
                  profils=('directeur', 'comptable', 'responsable')),
            _page('generation_contrats_bp.generation_contrats', 'Génération de contrats',
                  profils=('directeur', 'comptable')),
            _page('generation_contrats_bp.generation_contrats', 'Génération de contrats',
                  profils=('responsable',),
                  condition='generation_contrats_responsable_autorise'),
            _page('absences_bp.absences', 'Absences',
                  profils=('directeur', 'comptable')),
            _page('infos_salaries_bp.soldes_conges', 'Soldes de congés',
                  profils=('directeur', 'comptable')),
            _page('rh_statistiques_bp.rh_statistiques', 'Statistiques RH',
                  profils=('directeur', 'comptable')),
            _page('pesee_alisfa_bp.pesee_alisfa', 'Pesée ALISFA',
                  profils=('directeur', 'comptable')),
            _page('pesee_alisfa_bp.postes_alisfa', 'Postes ALISFA',
                  profils=('directeur', 'comptable')),
            _page('assistant_rh_bp.assistant_rh', 'Assistant RH',
                  profils=('directeur', 'comptable')),
            _page('variables_paie_bp.variables_paie', 'Variables de paie',
                  profils=('directeur', 'comptable')),
            _page('prepa_paie_bp.prepa_paie', 'Préparation de la paie',
                  profils=('directeur', 'comptable')),
        ],
    },
    {
        'id': 'factures',
        'nom': 'Factures & achats',
        'icone': '▤',
        'description': 'Factures fournisseurs, règles comptables, écritures et exportation.',
        'mots': 'facture fournisseur achat commande ecriture export exportation regle comptable piece justificatif',
        'pages': [
            _page('factures_bp.liste_factures', 'Factures',
                  profils=('directeur', 'comptable'),
                  resume='Le suivi des factures reçues, de leur import à leur approbation.'),
            _page('fournisseurs_bp.liste_fournisseurs', 'Fournisseurs',
                  profils=('directeur', 'comptable')),
            _page('regles_comptables_bp.liste_regles', 'Règles comptables',
                  profils=('directeur', 'comptable')),
            _page('ecritures_bp.liste_ecritures', 'Écritures',
                  profils=('directeur', 'comptable')),
            _page('exportation_bp.liste_exportation', 'Exportation',
                  profils=('directeur', 'comptable')),
            _page('commandes_salaries_bp.commandes_salaries', 'Commandes salariés'),
        ],
    },
    {
        'id': 'comptabilite',
        'nom': 'Comptabilité',
        'icone': '∑',
        'description': "Compte de résultat, bilan, indicateurs et plans comptables.",
        'mots': 'comptabilite comptable bilan compte resultat indicateur financier import bi plan analytique general grand livre',
        'pages': [
            _page('compte_resultat_bp.compte_resultat', 'Compte de résultat & bilan',
                  profils=('directeur', 'comptable')),
            _page('indicateurs_financiers_bp.indicateurs_financiers', 'Indicateurs financiers',
                  profils=('directeur', 'comptable')),
            _page('import_bi_bp.import_bi', 'Import BI',
                  profils=('directeur', 'comptable')),
            _page('comptabilite_analytique_bp.plan_comptable_analytique', 'Plan comptable analytique',
                  profils=('directeur', 'comptable')),
            _page('plan_comptable_general_bp.plan_comptable_general', 'Plan comptable général',
                  profils=('directeur', 'comptable')),
        ],
    },
    {
        'id': 'financier',
        'nom': 'Financier',
        'icone': '◇',
        'description': 'Budgets, subventions, trésorerie et bilans par secteur.',
        'mots': 'financier budget previsionnel subvention convention tresorerie secteur action alsh bilan caf',
        'pages': [
            _page('budget_bp.gestion_budgets', 'Budgets',
                  profils=('directeur', 'comptable')),
            _page('budget_bp.mon_budget', 'Mon budget',
                  profils=('responsable',)),
            _page('budget_bp.budget_previsionnel', 'Budget prévisionnel',
                  profils=('directeur', 'comptable')),
            _page('budget_bp.budget_previsionnel', 'Budget prévisionnel',
                  profils=('responsable',),
                  condition='budget_previsionnel_responsable_autorise'),
            _page('subventions_bp.gestion_subventions', 'Subventions',
                  profils=('directeur', 'comptable', 'responsable'),
                  resume='Les dossiers, leurs étapes et leurs échéances.'),
            _page('tresorerie_bp.tresorerie', 'Trésorerie',
                  profils=('directeur', 'comptable')),
            _page('bilan_secteurs_bp.bilan_secteurs', 'Bilan secteurs & actions',
                  profils=('directeur', 'comptable', 'responsable')),
            _page('bilan_action_bp.bilan_action', 'Budget action',
                  profils=('directeur', 'comptable')),
            _page('alsh_bp.analyse_alsh', 'Analyse ALSH',
                  profils=('directeur', 'comptable')),
        ],
    },
    {
        'id': 'vie_associative',
        'nom': 'Vie associative',
        'icone': '✚',
        'description': "Bénévoles, heures valorisées et espace du comité social et économique.",
        'mots': 'benevole benevolat association cse comite social economique message budget heures valorisees',
        'pages': [
            _page('benevoles_bp.gestion_benevoles', 'Bénévoles',
                  profils=('directeur', 'comptable')),
            _page('benevoles_bp.gestion_benevoles', 'Bénévoles',
                  profils=(), condition='is_delegue_benevoles'),
            _page('cse_bp.cse_accueil', 'Espace CSE',
                  profils=('directeur', 'comptable')),
            _page('cse_bp.cse_accueil', 'Espace CSE',
                  profils=(), condition='is_cse_membre'),
        ],
    },
    {
        'id': 'moi',
        'nom': 'Mon espace',
        'icone': '◉',
        'description': 'Vos compteurs de congés et de récupérations, et vos demandes.',
        'mots': 'moi mon espace dossier personnel compteur solde conge recuperation recup demande poser absence vacances parametre',
        'pages': [
            _page('accueil_bp.mon_espace', 'Mes compteurs',
                  resume='Congés, récupérations et demandes en cours.'),
            _page('recup_bp.demande_conge', 'Demander un congé'),
            _page('recup_bp.demande_recup', 'Demander une récupération',
                  profils=('comptable', 'responsable', 'salarie')),
            _page('recup_bp.mes_demandes_conges', 'Mes demandes de congés'),
            _page('recup_bp.mes_demandes_recup', 'Mes demandes de récupération',
                  profils=('comptable', 'responsable', 'salarie')),
            _page('parametres_bp.parametres', 'Mes paramètres',
                  profils=('salarie',)),
        ],
    },
]

# ── Accès directs : le cercle extérieur ────────────────────────────────────
# Des pages qu'on ouvre pour elles-mêmes, sans passer par un thème. Un accès
# direct qui ne porte qu'une page y mène d'un clic ; s'il en porte plusieurs,
# il se déplie comme une zone.
ACCES_DIRECTS = [
    {
        'id': 'salles',
        'nom': 'Salles',
        'icone': '⌂',
        'description': 'Réservations et calendrier d\'occupation des salles.',
        'mots': 'salle reservation reserver occupation calendrier disponibilite creneau',
        'pages': [
            _page('salles_bp.salles', 'Réserver une salle'),
        ],
    },
    {
        'id': 'planificateur',
        'nom': 'Planificateur',
        'icone': '◴',
        'description': 'Vos tâches et échéances organisées en blocs de temps.',
        'mots': 'planificateur tache echeance bloc organiser semaine deadline',
        'pages': [
            _page('planificateur_bp.planificateur', 'Planificateur'),
        ],
    },
    {
        'id': 'administration',
        'nom': 'Administration',
        'icone': '⚙',
        'description': 'Comptes, sécurité, options, sauvegardes et mises à jour.',
        'mots': 'administration parametre option compte utilisateur securite droit vacances ferie cle api email delegation sauvegarde mise a jour base',
        'pages': [
            _page('admin_bp.gestion_users', 'Utilisateurs',
                  profils=('directeur', 'comptable')),
            _page('securite_bp.journal_acces', 'Sécurité',
                  profils=('directeur', 'comptable')),
            _page('admin_bp.gestion_vacances', 'Vacances scolaires',
                  profils=('directeur', 'comptable')),
            _page('admin_bp.gestion_jours_feries', 'Jours fériés',
                  profils=('directeur', 'comptable')),
            _page('api_keys_bp.gestion_cles_api', 'Clés API',
                  profils=('directeur', 'comptable')),
            _page('notifications_bp.configuration_email', 'Notifications email',
                  profils=('directeur', 'comptable')),
            _page('admin_bp.delegations', 'Délégations',
                  profils=('directeur', 'comptable')),
            _page('administration_bp.options', 'Options',
                  profils=('directeur', 'comptable')),
            _page('backup_bp.liste_sauvegardes', 'Sauvegardes',
                  profils=('directeur', 'comptable')),
            _page('administration_bp.administration', 'Mises à jour de la base',
                  profils=('directeur', 'comptable')),
            _page('mise_a_jour_bp.mise_a_jour', "Mise à jour de l'application",
                  profils=('directeur', 'comptable')),
        ],
    },
]


def _page_visible(page, contexte):
    """Une page est visible si le profil y a droit, ou si sa condition est vraie.

    Deux usages de `condition` cohabitent :
    - avec `profils` vide, la condition SUFFIT (délégation, rôle CSE) ;
    - avec `profils` renseignés, elle RESTREINT (option d'administration).
    """
    profil = contexte.get('profil')
    condition = page['condition']
    if not page['profils']:
        return bool(condition) and bool(contexte.get(condition))
    if profil not in page['profils']:
        return False
    if condition and not contexte.get(condition):
        return False
    return True


def _lien(endpoint):
    """URL d'un endpoint, ou None s'il n'est pas monté (blueprint absent)."""
    try:
        return url_for(endpoint)
    except Exception:
        logger.warning("Navigation : endpoint inconnu %s, entrée masquée", endpoint)
        return None


def _construire_groupe(groupe, contexte):
    """Filtre les pages d'une zone pour un utilisateur ; None si tout est masqué."""
    pages = []
    vus = set()
    for page in groupe['pages']:
        if not _page_visible(page, contexte):
            continue
        if page['endpoint'] in vus:
            continue
        lien = _lien(page['endpoint'])
        if lien is None:
            continue
        vus.add(page['endpoint'])
        pages.append({
            'endpoint': page['endpoint'],
            'label': page['labels'].get(contexte.get('profil'), page['label']),
            'resume': page['resume'],
            'lien': lien,
        })
    if not pages:
        return None
    return {
        'id': groupe['id'],
        'nom': groupe['nom'],
        'icone': groupe['icone'],
        'description': groupe['description'],
        'mots': groupe['mots'],
        'pages': pages,
    }


def carte_navigation(contexte):
    """Zones et accès directs visibles par un utilisateur.

    Retourne `{'zones': [...], 'directs': [...]}`, chaque entrée portant ses
    pages déjà filtrées et leurs URL résolues.
    """
    zones = [z for z in (_construire_groupe(g, contexte) for g in ZONES) if z]
    directs = [d for d in (_construire_groupe(g, contexte) for g in ACCES_DIRECTS) if d]
    return {'zones': zones, 'directs': directs}


def localiser(carte, endpoint):
    """Zone (ou accès direct) contenant un endpoint, et la page elle-même.

    Retourne `(groupe, page)` ou `(None, None)`. Sert à afficher, en haut de
    chaque page, le titre et les boutons des pages voisines — ce qui remplace
    le sous-menu du menu latéral.
    """
    if not endpoint:
        return None, None
    for groupe in carte['zones'] + carte['directs']:
        for page in groupe['pages']:
            if page['endpoint'] == endpoint:
                return groupe, page
    return None, None


def est_eligible(profil, user_id):
    """Indique si un utilisateur relève de l'interface sans menu.

    Direction, comptabilité et responsables y basculent. Un salarié n'y bascule
    que s'il porte une délégation qui lui donne des pages à suivre — la seule
    délégation des récurrences de salle ne compte pas, elle n'ouvre aucune page
    supplémentaire. Les prestataires gardent leur page unique.
    """
    if profil in PROFILS_FLUX:
        return True
    if profil != 'salarie' or not user_id:
        return False
    from blueprints.delegations import (MISSION_SUIVI_COMMANDES_FOURNITURES,
                                        MISSION_SUIVI_VALIDATIONS_RELANCES,
                                        user_has_delegation,
                                        user_peut_gerer_benevoles)
    try:
        return bool(
            user_has_delegation(user_id, MISSION_SUIVI_VALIDATIONS_RELANCES)
            or user_has_delegation(user_id, MISSION_SUIVI_COMMANDES_FOURNITURES)
            or user_peut_gerer_benevoles(user_id)
        )
    except Exception:
        # Base non migrée ou verrouillée : on retombe sur l'interface historique
        # plutôt que de priver l'utilisateur de son menu.
        logger.warning("Éligibilité interface sans menu illisible", exc_info=True)
        return False
