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
          resume='', mots='', expressions=()):
    """Décrit une page de la carte.

    - `profils` : profils qui voient l'entrée sans condition supplémentaire.
    - `condition` : nom d'un drapeau du contexte utilisateur ; s'il est vrai,
      l'entrée est visible quel que soit le profil (délégation, rôle CSE) ou,
      combiné à `profils`, la restreint (option d'administration).
    - `labels` : libellés alternatifs par profil (une même page ne se nomme pas
      pareil selon qu'on gère son planning ou celui de l'équipe).
    - `mots` : vocabulaire propre à la page, distinct des mots généraux de sa
      zone. Il évite qu'une recherche « facture » fasse remonter toutes les
      pages de « Validations & suivi ».
    - `expressions` : formulations qui désignent précisément cette page. Une
      expression exacte passe avant les correspondances par mots isolés.
    """
    return {
        'endpoint': endpoint,
        'label': label,
        'labels': labels or {},
        'profils': tuple(profils),
        'condition': condition,
        'resume': resume,
        'mots': mots,
        'expressions': tuple(expressions),
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
                  resume="L'état de validation des fiches, mois par mois.",
                  mots='fiche heure validation relance retard manquant non valide',
                  expressions=('fiches à valider', 'fiches non validées',
                               'relancer les responsables')),
            # La délégation « suivi des validations et relances » ouvre cette
            # page à un salarié — c'est même elle qui le fait basculer sur
            # l'interface sans menu. Sans cette seconde déclaration, la page
            # que la délégation accorde disparaîtrait de sa carte.
            _page('validation_bp.vue_ensemble_validation', "Vue d'ensemble",
                  profils=(), condition='can_access_vue_ensemble_validation',
                  resume="L'état de validation des fiches, mois par mois.",
                  mots='fiche heure validation relance retard manquant non valide',
                  expressions=('fiches à valider', 'fiches non validées',
                               'relancer les responsables')),
            _page('recup_bp.validation_demandes_recup', 'Validation des demandes',
                  profils=('directeur', 'comptable', 'responsable'),
                  resume='Congés et récupérations à valider ou refuser.',
                  mots='conge recuperation recup validation attente accepter refuser',
                  expressions=('congés à valider', 'récupérations à valider',
                               'demandes en attente')),
            _page('recup_bp.historique_demandes_recup', 'Historique des demandes',
                  profils=('directeur', 'comptable'),
                  mots='ancienne demande conge recup acceptee refusee traitee'),
            _page('suivi_bp.historique_modifications', 'Historique des modifications',
                  profils=('directeur',),
                  mots='journal changement modifie modification audit trace'),
            _page('suivi_bp.suivi_anomalies', 'Suivi des anomalies',
                  profils=('directeur', 'comptable'),
                  mots='erreur incoherence fiche heure anomalie corriger saisie oubli'),
            _page('suivi_bp.alertes_surcharge', 'Alertes de surcharge',
                  profils=('directeur', 'comptable'),
                  mots='charge travail prevention amplitude horaire repos alerte'),
            _page('factures_bp.approbation_factures', 'Approbation des factures',
                  profils=('directeur', 'responsable'),
                  mots='facture validation approbation attente accepter refuser',
                  expressions=('factures à valider', 'factures à approuver',
                               'factures en attente')),
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
                  profils=('comptable', 'responsable', 'salarie'),
                  mots='heure temps pointage pointer saisie travail fiche',
                  expressions=('mes heures', "ma fiche d'heures", 'saisir mon temps')),
            _page('validation_bp.vue_mensuelle', 'Vue mensuelle',
                  profils=('comptable', 'responsable', 'salarie'),
                  mots='heure temps feuille fiche mois solde historique',
                  expressions=('feuille de temps', "fiche d'heures", 'heures du mois')),
            _page('validation_bp.vue_calendrier', 'Vue calendrier',
                  profils=('comptable', 'responsable', 'salarie'),
                  mots='heure temps calendrier jour semaine mois'),
            _page('planning_bp.planning_theorique', 'Mon planning',
                  labels={'directeur': 'Plannings des salariés',
                          'comptable': 'Plannings des salariés'},
                  mots='planning horaire emploi temps theorique salarie',
                  expressions=('mon planning', 'mes horaires',
                               'planning des salariés')),
            _page('mon_equipe_bp.mon_equipe', 'Mon équipe',
                  profils=('comptable', 'responsable', 'salarie'),
                  mots='equipe salarie collaborateur semaine presence'),
            _page('presence_effectif_bp.presence_effectif', "Présence de l'effectif",
                  profils=('directeur', 'comptable'),
                  mots='presence absent present effectif aujourd hui',
                  expressions=('qui est présent', "présence aujourd'hui")),
            _page('planning_enfance_bp.planning_enfance', 'Temps annualisé',
                  profils=('directeur', 'comptable', 'responsable'),
                  mots='annualisation annualise modulation enfance alsh planning'),
            _page('forfait_bp.dashboard_forfait_jour', 'Forfait jour',
                  profils=('directeur',),
                  mots='forfait jour jours cadre travaille repos 210'),
            _page('forfait_bp.calendrier_forfait_jour', 'Calendrier forfait jour',
                  profils=('directeur',),
                  mots='forfait jour calendrier absence travaille repos'),
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
                  profils=('directeur', 'comptable', 'responsable'),
                  mots='salarie personnel employe dossier fiche coordonnee document contrat'),
            _page('generation_contrats_bp.generation_contrats', 'Génération de contrats',
                  profils=('directeur', 'comptable'),
                  mots='contrat modele document creer generer rediger embauche cdd cdi'),
            _page('generation_contrats_bp.generation_contrats', 'Génération de contrats',
                  profils=('responsable',),
                  condition='generation_contrats_responsable_autorise',
                  mots='contrat modele document creer generer rediger embauche cdd cdi'),
            _page('contrats_bp.salaries_sans_contrat', 'Salariés sans contrat',
                  profils=('directeur', 'comptable'),
                  mots='contrat manquant sans oublie bloque saisie regulariser echu '
                       'renouveler embauche dossier',
                  expressions=('salariés sans contrat', 'sans contrat',
                               'contrats manquants', 'qui n\'a pas de contrat',
                               'contrat oublié')),
            _page('absences_bp.absences', 'Absences',
                  profils=('directeur', 'comptable'),
                  mots='absence maladie arret travail justificatif suivi retour'),
            _page('infos_salaries_bp.soldes_conges', 'Soldes de congés',
                  profils=('directeur', 'comptable'),
                  mots='solde compteur conge cp restant effectif equipe',
                  expressions=('congés restants', 'soldes de congés',
                               'compteurs de congés')),
            _page('rh_statistiques_bp.rh_statistiques', 'Statistiques RH',
                  profils=('directeur', 'comptable'),
                  mots='rh statistique effectif etp anciennete age pyramide contrat absent'),
            _page('pesee_alisfa_bp.pesee_alisfa', 'Pesée ALISFA',
                  profils=('directeur', 'comptable'),
                  mots='pesee cotation classification alisfa emploi repere point analyse poste'),
            _page('pesee_alisfa_bp.postes_alisfa', 'Postes ALISFA',
                  profils=('directeur', 'comptable'),
                  mots='poste alisfa pesee cotation emploi classification salarie'),
            _page('assistant_rh_bp.assistant_rh', 'Assistant RH',
                  profils=('directeur', 'comptable'),
                  mots='assistant rh question droit convention alisfa aide'),
            _page('variables_paie_bp.variables_paie', 'Variables de paie',
                  profils=('directeur', 'comptable'),
                  mots='paie paye variable element evp prime absence salaire mois'),
            _page('prepa_paie_bp.prepa_paie', 'Préparation de la paie',
                  profils=('directeur', 'comptable'),
                  mots='paie paye preparation controle prestataire salaire bulletin',
                  expressions=('préparer la paie', 'paie du mois',
                               'contrôler la paie')),
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
                  resume='Le suivi des factures reçues, de leur import à leur approbation.',
                  mots='facture achat depense avoir pdf import suivi fournisseur'),
            _page('fournisseurs_bp.liste_fournisseurs', 'Fournisseurs',
                  profils=('directeur', 'comptable'),
                  mots='fournisseur prestataire tiers entreprise societe annuaire'),
            _page('regles_comptables_bp.liste_regles', 'Règles comptables',
                  profils=('directeur', 'comptable'),
                  mots='regle comptable automatisation automatique imputation compte analytique ia'),
            _page('ecritures_bp.liste_ecritures', 'Écritures',
                  profils=('directeur', 'comptable'),
                  mots='ecriture saisie journal piece comptable brouillon validation'),
            _page('exportation_bp.liste_exportation', 'Exportation',
                  profils=('directeur', 'comptable'),
                  mots='export exportation aiga txt ecriture comptable'),
            _page('commandes_salaries_bp.commandes_salaries', 'Commandes salariés',
                  mots='commande achat fourniture approvisionnement demande salarie',
                  expressions=('commander des fournitures', 'achat de fournitures')),
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
                  profils=('directeur', 'comptable'),
                  mots='compte resultat cr bilan actif passif charge produit exploitation'),
            _page('indicateurs_financiers_bp.indicateurs_financiers', 'Indicateurs financiers',
                  profils=('directeur', 'comptable'),
                  mots='indicateur ratio financier caf bfr fonds roulement sante'),
            _page('import_bi_bp.import_bi', 'Import BI',
                  profils=('directeur', 'comptable'),
                  mots='import bi fec fichier comptable ecriture realise'),
            _page('comptabilite_analytique_bp.plan_comptable_analytique', 'Plan comptable analytique',
                  profils=('directeur', 'comptable'),
                  mots='plan comptable analytique imputation secteur action compte code'),
            _page('plan_comptable_general_bp.plan_comptable_general', 'Plan comptable général',
                  profils=('directeur', 'comptable'),
                  mots='plan comptable general pcg compte numero libelle grand livre'),
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
                  profils=('directeur', 'comptable'),
                  mots='budget enveloppe secteur repartition montant gestion'),
            _page('budget_bp.mon_budget', 'Mon budget',
                  profils=('responsable',),
                  mots='budget enveloppe secteur repartition depense montant',
                  expressions=('mon budget', 'budget de mon secteur')),
            _page('budget_bp.budget_previsionnel', 'Budget prévisionnel',
                  profils=('directeur', 'comptable'),
                  mots='budget previsionnel actualise prev bp bpa inflation projection'),
            _page('budget_bp.budget_previsionnel', 'Budget prévisionnel',
                  profils=('responsable',),
                  condition='budget_previsionnel_responsable_autorise',
                  mots='budget previsionnel actualise prev bp bpa inflation projection'),
            _page('subventions_bp.gestion_subventions', 'Subventions',
                  profils=('directeur', 'comptable', 'responsable'),
                  resume='Les dossiers, leurs étapes et leurs échéances.',
                  mots='subvention financement financeur convention caf ville dossier echeance'),
            _page('tresorerie_bp.tresorerie', 'Trésorerie',
                  profils=('directeur', 'comptable'),
                  mots='tresorerie treso banque solde bancaire liquidite prevision fec'),
            _page('bilan_secteurs_bp.bilan_secteurs', 'Bilan secteurs & actions',
                  profils=('directeur', 'comptable', 'responsable'),
                  mots='bilan realise cloture resultat secteur action analytique consultation'),
            _page('bilan_action_bp.bilan_action', 'Budget action',
                  profils=('directeur', 'comptable'),
                  mots='budget action construction analytique previsionnel realise'),
            _page('alsh_bp.analyse_alsh', 'Analyse ALSH',
                  profils=('directeur', 'comptable'),
                  mots='alsh accueil loisirs centre enfance frequentation caf analyse'),
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
                  profils=('directeur', 'comptable'),
                  mots='benevole benevolat volontaire heure valorisee valorisation'),
            _page('benevoles_bp.gestion_benevoles', 'Bénévoles',
                  profils=(), condition='is_delegue_benevoles',
                  mots='benevole benevolat volontaire heure valorisee valorisation'),
            _page('cse_bp.cse_accueil', 'Espace CSE',
                  profils=('directeur', 'comptable'),
                  mots='cse comite social economique elu representant personnel budget message'),
            _page('cse_bp.cse_accueil', 'Espace CSE',
                  profils=(), condition='is_cse_membre',
                  mots='cse comite social economique elu representant personnel budget message'),
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
                  resume='Congés, récupérations et demandes en cours.',
                  mots='moi espace solde compteur conge cp recuperation recup demande personnel',
                  expressions=('mon espace', 'mes congés', 'mon solde de congés',
                               'congés restants', 'mes récupérations',
                               'mon compteur')),
            _page('recup_bp.demande_conge', 'Demander un congé',
                  mots='conge cp vacances demande poser prendre repos',
                  expressions=('poser un congé', 'prendre un congé',
                               'demander des congés')),
            _page('recup_bp.demande_recup', 'Demander une récupération',
                  profils=('comptable', 'responsable', 'salarie'),
                  mots='recup recuperation heure demande poser prendre'),
            _page('recup_bp.mes_demandes_conges', 'Mes demandes de congés',
                  mots='conge cp demande attente acceptee refusee historique'),
            _page('recup_bp.mes_demandes_recup', 'Mes demandes de récupération',
                  profils=('comptable', 'responsable', 'salarie'),
                  mots='recup recuperation demande attente acceptee refusee historique'),
            _page('parametres_bp.parametres', 'Mes paramètres',
                  profils=('salarie',),
                  mots='parametre preference notification email personnel profil'),
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
        'mots': 'salle reservation reserver location louer local libre occupation calendrier disponibilite creneau',
        'pages': [
            _page('salles_bp.salles', 'Réserver une salle',
                  mots='salle reservation location louer local libre occupation creneau',
                  expressions=('louer une salle', 'salle disponible', 'salle libre')),
        ],
    },
    {
        'id': 'planificateur',
        'nom': 'Planificateur',
        'icone': '◴',
        'description': 'Vos tâches et échéances organisées en blocs de temps.',
        'mots': 'planificateur tache todo mission echeance bloc organiser semaine deadline agenda evenement rdv reporter replanifier',
        'pages': [
            _page('planificateur_bp.planificateur', 'Planificateur',
                  mots='tache todo mission echeance bloc agenda evenement rdv reporter replanifier'),
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
                  profils=('directeur', 'comptable'),
                  mots='utilisateur compte login profil droit acces gerer creer mot passe salarie'),
            _page('securite_bp.journal_acces', 'Sécurité',
                  profils=('directeur', 'comptable'),
                  mots='securite journal acces connexion log audit mot passe',
                  expressions=('journal des accès', 'historique des connexions')),
            _page('admin_bp.gestion_vacances', 'Vacances scolaires',
                  profils=('directeur', 'comptable'),
                  mots='vacance scolaire zone fermeture calendrier'),
            _page('admin_bp.gestion_jours_feries', 'Jours fériés',
                  profils=('directeur', 'comptable'),
                  mots='jour ferie calendrier fermeture chomage'),
            _page('api_keys_bp.gestion_cles_api', 'Clés API',
                  profils=('directeur', 'comptable'),
                  mots='cle api intelligence artificielle modele fournisseur ia'),
            _page('notifications_bp.configuration_email', 'Notifications email',
                  profils=('directeur', 'comptable'),
                  mots='notification email mail smtp gmail configuration message'),
            _page('admin_bp.delegations', 'Délégations',
                  profils=('directeur', 'comptable'),
                  mots='delegation mission droit acces confier salarie'),
            _page('administration_bp.options', 'Options',
                  profils=('directeur', 'comptable'),
                  mots='option reglage configuration module activation parametre'),
            _page('backup_bp.liste_sauvegardes', 'Sauvegardes',
                  profils=('directeur', 'comptable'),
                  mots='sauvegarde backup restauration archive base donnee'),
            _page('administration_bp.administration', 'Mises à jour de la base',
                  profils=('directeur', 'comptable'),
                  mots='mise jour base donnee migration schema version'),
            _page('mise_a_jour_bp.mise_a_jour', "Mise à jour de l'application",
                  profils=('directeur', 'comptable'),
                  mots='mise jour application logiciel version telecharger installer update'),
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
            'mots': page['mots'],
            'expressions': list(page['expressions']),
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
