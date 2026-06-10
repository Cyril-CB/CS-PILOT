"""
Journalisation des acces a l'application (securite).

Enregistre les evenements lies aux connexions : connexions reussies, echecs de
connexion, demandes de reinitialisation et modifications de mot de passe. Le
journal est consultable par la direction via le menu Administration > Securite.

La journalisation est concue pour ne JAMAIS interrompre le parcours
utilisateur : toute erreur lors de l'enregistrement est tracee dans les logs
applicatifs mais reste silencieuse vis-a-vis de l'appelant.
"""
import logging

from database import get_db

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
            'INSERT INTO journal_acces (login_saisi, user_id, evenement, adresse_ip) '
            'VALUES (?, ?, ?, ?)',
            (login_saisi, user_id, evenement, adresse_ip)
        )
        conn.commit()
    except Exception:
        logger.exception("Impossible d'enregistrer l'evenement d'acces %s", evenement)
    finally:
        if conn:
            conn.close()
