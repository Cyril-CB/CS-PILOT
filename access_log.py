"""
Journalisation de l'application : acces (securite) et actions metier (audit).

- enregistrer_acces() trace les evenements de connexion (connexions reussies,
  echecs, demandes de reinitialisation, changements de mot de passe). Il ouvre
  sa propre connexion et ne doit JAMAIS interrompre le parcours utilisateur :
  toute erreur reste silencieuse vis-a-vis de l'appelant (tracee dans les logs).

- journaliser_action() trace les actions qui modifient l'etat (cloture conges,
  variables de paie, documents salaries, generation de contrats...). A la
  difference de enregistrer_acces(), il ecrit dans la transaction de
  l'appelant (atomicite : la ligne d'audit est validee avec l'action) et ne
  capture pas les exceptions : une action sensible ne doit pas etre validee
  sans sa trace.

Les deux journaux sont consultables par la direction via Administration > Securite.
"""
import logging

from database import get_db
from utils import maintenant

logger = logging.getLogger(__name__)

# Types d'evenements journalises
EVT_CONNEXION_REUSSIE = 'connexion_reussie'
EVT_ECHEC_CONNEXION = 'echec_connexion'
EVT_REINITIALISATION_DEMANDEE = 'reinitialisation_demandee'
EVT_MOT_DE_PASSE_MODIFIE = 'mot_de_passe_modifie'

# Libelles lisibles pour l'affichage et l'export
EVENEMENTS_LABELS = {
    EVT_CONNEXION_REUSSIE: 'Connexion réussie',
    EVT_ECHEC_CONNEXION: 'Échec de connexion',
    EVT_REINITIALISATION_DEMANDEE: 'Réinitialisation demandée',
    EVT_MOT_DE_PASSE_MODIFIE: 'Mot de passe modifié',
}

# Types d'actions metier journalisees (audit). Valeurs stables : ne pas
# renommer une fois en production (l'historique y fait reference).
ACTION_CLOTURE_CONGES = 'cloture_conges'
ACTION_ENREG_VARIABLES_PAIE = 'enregistrement_variables_paie'
ACTION_MAJ_STATUT_PREPA_PAIE = 'maj_statut_prepa_paie'
ACTION_AJOUT_CONTRAT = 'ajout_contrat'
ACTION_AJOUT_PDF_CONTRAT = 'ajout_pdf_contrat'
ACTION_ENREG_DOCUMENT_SALARIE = 'enregistrement_document_salarie'
ACTION_GENERATION_CONTRAT = 'generation_contrat'
ACTION_CREATION_USER = 'creation_user'
ACTION_MODIF_USER = 'modification_user'
ACTION_STATUT_USER = 'changement_statut_user'
ACTION_VALIDATION_MOIS = 'validation_mois'
ACTION_DEVERROUILLAGE_MOIS = 'deverrouillage_mois'
ACTION_AJOUT_MEMBRE_CSE = 'ajout_membre_cse'
ACTION_RETRAIT_MEMBRE_CSE = 'retrait_membre_cse'

# Libelles lisibles des actions metier
ACTIONS_LABELS = {
    ACTION_CLOTURE_CONGES: 'Clôture mensuelle des congés',
    ACTION_ENREG_VARIABLES_PAIE: 'Enregistrement des variables de paie',
    ACTION_MAJ_STATUT_PREPA_PAIE: 'Mise à jour du statut de préparation de paie',
    ACTION_AJOUT_CONTRAT: 'Ajout d\'un contrat',
    ACTION_AJOUT_PDF_CONTRAT: 'Ajout du PDF d\'un contrat',
    ACTION_ENREG_DOCUMENT_SALARIE: 'Enregistrement d\'un document salarié',
    ACTION_GENERATION_CONTRAT: 'Génération d\'un contrat',
    ACTION_CREATION_USER: 'Création d\'un utilisateur',
    ACTION_MODIF_USER: 'Modification d\'un utilisateur',
    ACTION_STATUT_USER: 'Activation / désactivation d\'un utilisateur',
    ACTION_VALIDATION_MOIS: 'Validation mensuelle d\'une fiche',
    ACTION_DEVERROUILLAGE_MOIS: 'Déverrouillage d\'une fiche validée',
    ACTION_AJOUT_MEMBRE_CSE: 'Ajout d\'un membre du CSE',
    ACTION_RETRAIT_MEMBRE_CSE: 'Retrait d\'un membre du CSE',
}


def _adresse_ip():
    """Retourne l'adresse IP du client (et non celle du serveur/proxy).

    Derriere un proxy ou un tunnel (ngrok, Cloudflare, reverse proxy...),
    request.remote_addr vaut l'adresse du proxy local et serait donc toujours
    identique. On privilegie l'en-tete X-Forwarded-For (la premiere adresse de
    la liste correspond au client d'origine), puis X-Real-IP, avec repli sur
    request.remote_addr lorsqu'aucun en-tete n'est present.
    """
    try:
        from flask import request, has_request_context
        if not has_request_context():
            return None
        forwarded = request.headers.get('X-Forwarded-For', '')
        if forwarded:
            # Format "client, proxy1, proxy2" : la 1re adresse = client d'origine
            client = forwarded.split(',')[0].strip()
            if client:
                return client
        real_ip = (request.headers.get('X-Real-IP') or '').strip()
        if real_ip:
            return real_ip
        return request.remote_addr
    except Exception:
        return None


def enregistrer_acces(evenement, login_saisi=None, user_id=None, adresse_ip=None):
    """Enregistre un evenement d'acces dans le journal.

    Args:
        evenement: un des EVT_* (type d'evenement).
        login_saisi: identifiant saisi dans le formulaire (peut etre inconnu).
        user_id: identifiant de l'utilisateur concerne s'il est connu.
        adresse_ip: adresse IP du client (detectee automatiquement si absente).
    """
    if adresse_ip is None:
        adresse_ip = _adresse_ip()

    conn = None
    try:
        conn = get_db()
        conn.execute(
            'INSERT INTO journal_acces (date_heure, login_saisi, user_id, evenement, adresse_ip) '
            'VALUES (?, ?, ?, ?, ?)',
            (maintenant().strftime('%Y-%m-%d %H:%M:%S'), login_saisi, user_id, evenement, adresse_ip)
        )
        conn.commit()
    except Exception:
        logger.exception("Impossible d'enregistrer l'evenement d'acces %s", evenement)
    finally:
        if conn:
            conn.close()


def journaliser_action(conn, action, user_id=None, cible_type=None,
                       cible_id=None, details=None):
    """Enregistre une action metier sensible dans le journal d'audit.

    Ecrit la ligne d'audit dans la transaction de l'appelant (`conn`) : elle est
    donc validee atomiquement avec l'action elle-meme (c'est l'appelant qui
    appelle commit()). Contrairement a enregistrer_acces(), cette fonction ne
    capture PAS les exceptions : si l'audit echoue, l'action doit echouer avec,
    pour ne jamais laisser une modification sensible sans trace. Appeler depuis
    le bloc try de l'action, juste avant conn.commit().

    Args:
        conn: connexion/transaction de l'appelant (l'INSERT y est rattache).
        action: un des ACTION_* (type d'action).
        user_id: auteur de l'action ; a defaut, repris de la session courante.
        cible_type: type d'entite visee (ex: 'user', 'mois_paie').
        cible_id: identifiant de l'entite visee, si applicable.
        details: contexte libre, NON sensible (compteurs, mois/annee, type).
            Ne JAMAIS y mettre de donnee personnelle (salaire, numero secu...).
    """
    if user_id is None:
        try:
            from flask import session, has_request_context
            if has_request_context():
                user_id = session.get('user_id')
        except Exception:
            user_id = None
    conn.execute(
        'INSERT INTO journal_actions '
        '(date_heure, user_id, action, cible_type, cible_id, details, adresse_ip) '
        'VALUES (?, ?, ?, ?, ?, ?, ?)',
        (maintenant().strftime('%Y-%m-%d %H:%M:%S'), user_id, action,
         cible_type, cible_id, details, _adresse_ip())
    )
