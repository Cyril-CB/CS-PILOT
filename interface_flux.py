"""
Activation et contexte de l'interface sans menu.

Trois questions, une réponse par requête (mémorisée dans `flask.g`) :
- l'interface est-elle active pour cet utilisateur ?
- quelles zones et quelles pages a-t-il le droit de voir ?
- que doit afficher la page courante en plus de son contenu ?

L'activation se décide à trois niveaux, du plus général au plus personnel :
1. l'option d'administration `interface_sans_menu_active` (tout le centre) ;
2. l'éligibilité du profil (`navigation.est_eligible`) ;
3. le choix de l'utilisateur, qui peut toujours revenir au menu historique.
"""
import logging
import re

from flask import has_request_context, request, session

import navigation
from utils import delete_setting, get_setting, save_setting

logger = logging.getLogger(__name__)

OPTION_GLOBALE = 'interface_sans_menu_active'

# Libellés de profil affichés sous le nom, en haut à droite.
LIBELLES_PROFIL = {
    'directeur': 'direction',
    'comptable': 'comptabilité',
    'responsable': 'responsable',
    'salarie': 'salarié',
    'prestataire': 'prestataire',
}


def _cle_preference(user_id):
    return f'interface_sans_menu_user_{user_id}'


def preference_utilisateur(user_id):
    """Choix personnel : True, False, ou None si l'utilisateur n'a rien choisi."""
    if not user_id:
        return None
    try:
        valeur = get_setting(_cle_preference(user_id))
    except Exception:
        logger.warning("Préférence d'interface illisible", exc_info=True)
        return None
    if valeur is None:
        return None
    return str(valeur).strip().lower() in ('1', 'true', 'yes', 'on')


def definir_preference_utilisateur(user_id, actif):
    """Enregistre le choix personnel d'un utilisateur."""
    if not user_id:
        return
    if actif:
        # Revenir au défaut plutôt que de figer un « oui » : si l'option
        # globale change un jour, l'utilisateur suit le centre.
        delete_setting(_cle_preference(user_id))
    else:
        save_setting(_cle_preference(user_id), '0')


def option_globale_active():
    """L'interface sans menu est-elle activée pour le centre ?"""
    try:
        from app_options import get_option_bool
        return get_option_bool(OPTION_GLOBALE)
    except Exception:
        logger.warning("Option interface sans menu illisible", exc_info=True)
        return False


# Marqueurs de téléphone dans l'en-tête User-Agent. « Mobi » est le marqueur
# normalisé, présent sur Chrome Android comme sur Safari iOS ; les autres
# couvrent les cas plus anciens. Une tablette n'en porte pas — un iPad récent
# annonce même un Safari de bureau — et garde donc l'interface sans menu, que
# son écran peut afficher.
_TELEPHONE = re.compile(r'Mobi|iPhone|iPod|Windows Phone|BlackBerry|Opera Mini',
                        re.IGNORECASE)


def est_telephone():
    """Vrai si la requête vient d'un téléphone.

    L'interface sans menu suppose un écran large : une barre fixe en haut, une
    autre en bas, et une vue d'ensemble en anneau. Sur un téléphone, le menu
    latéral historique — déjà responsive, avec son bouton hamburger — reste plus
    confortable. La détection se fait sur l'agent utilisateur car la largeur de
    l'écran n'est pas connue du serveur ; c'est une approximation assumée, et
    elle n'ouvre aucun droit : elle ne fait que choisir un habillage.
    """
    if not has_request_context():
        return False
    return bool(_TELEPHONE.search(request.headers.get('User-Agent', '')))


def interface_active(profil, user_id):
    """Décide si la requête courante doit être servie sans menu."""
    if not user_id:
        return False
    if not option_globale_active():
        return False
    if not navigation.est_eligible(profil, user_id):
        return False
    if est_telephone():
        return False
    return preference_utilisateur(user_id) is not False


def recherche_globale_autorisee(profil):
    """La recherche métier (`POST /api/search`) est-elle ouverte à ce profil ?

    La barre intelligente propose deux choses : la navigation locale — zones et
    pages, qui remplace le menu et vaut pour tout le monde — et la recherche
    métier, qui route vers une facture, un fournisseur, un budget, la fiche
    temps d'un salarié… On lit la liste d'autorisation à la source, dans le
    blueprint qui la fait respecter, pour que la palette et l'API ne divergent
    jamais. Les responsables y figurent depuis que le moteur cadre leurs
    entités et filtre ses destinations par la carte de navigation.
    """
    try:
        from blueprints.recherche import PROFILS_AUTORISES
        return profil in PROFILS_AUTORISES
    except Exception:
        logger.warning("Profils de recherche illisibles", exc_info=True)
        return False


def carte_pour_utilisateur(profil, user_id):
    """Construit la même carte filtrée pour une page ou pour l'API de recherche."""
    return navigation.carte_navigation(_drapeaux(profil, user_id))


def endpoints_recherche_autorises(profil, user_id, carte=None):
    """Destinations métier autorisées, ou ``None`` pour le périmètre complet.

    Direction et comptabilité conservent le moteur transverse historique. Pour
    un responsable, la carte est la source de vérité et le détail d'une facture
    est autorisé dès lors que sa page d'approbation l'est ; le moteur filtre en
    plus le numéro sur le secteur du responsable.
    """
    if profil in ('directeur', 'comptable'):
        return None
    if profil != 'responsable':
        return set()
    carte = carte or carte_pour_utilisateur(profil, user_id)
    endpoints = {
        page['endpoint']
        for groupe in carte.get('zones', []) + carte.get('directs', [])
        for page in groupe.get('pages', [])
    }
    if 'factures_bp.approbation_factures' in endpoints:
        endpoints.add('factures_bp.detail_facture')
    return endpoints


def _drapeaux(profil, user_id):
    """Drapeaux de droits utilisés pour filtrer la carte de navigation.

    Reprend exactement les conditions du menu latéral historique : ce module
    n'ouvre aucune page qui n'était pas déjà proposée.
    """
    drapeaux = {
        'profil': profil,
        'user_id': user_id,
        'is_cse_membre': False,
        'is_delegue_benevoles': False,
        'can_access_vue_ensemble_validation': profil in ('directeur', 'comptable', 'responsable'),
        'generation_contrats_responsable_autorise': True,
        'budget_previsionnel_responsable_autorise': True,
    }

    try:
        from app_options import get_option_bool
        drapeaux['generation_contrats_responsable_autorise'] = get_option_bool(
            'generation_contrats_responsable_autorise')
        drapeaux['budget_previsionnel_responsable_autorise'] = get_option_bool(
            'budget_previsionnel_responsable_autorise')
    except Exception:
        logger.warning("Options applicatives illisibles", exc_info=True)

    # La direction et la comptabilité voient déjà les bénévoles, le CSE et la
    # vue d'ensemble par leur profil : inutile d'interroger la base pour des
    # droits qu'elles ont de toute façon. Ces lectures ne concernent que les
    # responsables et les salariés délégués.
    if profil in ('directeur', 'comptable'):
        return drapeaux

    try:
        from blueprints.delegations import (MISSION_SUIVI_VALIDATIONS_RELANCES,
                                            user_has_delegation,
                                            user_peut_gerer_benevoles)
        drapeaux['is_delegue_benevoles'] = user_peut_gerer_benevoles(user_id)
        if not drapeaux['can_access_vue_ensemble_validation']:
            drapeaux['can_access_vue_ensemble_validation'] = user_has_delegation(
                user_id, MISSION_SUIVI_VALIDATIONS_RELANCES)
    except Exception:
        logger.warning("Délégations illisibles", exc_info=True)

    try:
        from blueprints.cse import est_membre_cse
        from database import get_db
        conn = get_db()
        try:
            drapeaux['is_cse_membre'] = est_membre_cse(conn, user_id)
        finally:
            conn.close()
    except Exception:
        logger.warning("Appartenance au CSE illisible", exc_info=True)

    return drapeaux


def _identite(profil, user_id):
    """Nom, fonction et initiales affichés en haut à droite.

    La fonction est celle renseignée sur la fiche du salarié, avec les
    informations de contrat. Tant qu'elle ne l'est pas, on retombe sur le
    profil précisé par le secteur — l'information dont dispose l'application.
    """
    prenom = (session.get('prenom') or '').strip()
    nom = (session.get('nom') or '').strip()
    fonction = LIBELLES_PROFIL.get(profil, profil or '')

    try:
        from database import get_db
        conn = get_db()
        try:
            row = conn.execute(
                '''SELECT u.fonction, s.nom AS secteur FROM users u
                   LEFT JOIN secteurs s ON s.id = u.secteur_id
                   WHERE u.id = ?''', (user_id,)
            ).fetchone()
        finally:
            conn.close()
        if row and (row['fonction'] or '').strip():
            fonction = row['fonction'].strip()
        elif row and row['secteur']:
            fonction = f"{fonction} · {row['secteur']}"
    except Exception:
        logger.warning("Fonction de l'utilisateur illisible", exc_info=True)

    initiales = ((prenom[:1] + nom[:1]) or '?').upper()
    return {
        'nom': f"{prenom} {nom}".strip() or 'Mon dossier',
        'fonction': fonction,
        'initiales': initiales,
    }


def contexte():
    """Contexte complet de l'interface sans menu pour la requête courante.

    Le résultat est mémorisé sur l'objet `request` : plusieurs gabarits peuvent
    lire la carte sans relancer les lectures de droits. La mémorisation est
    volontairement portée par la requête et non par `flask.g`, qui vit aussi
    longtemps que le contexte d'application — partagé entre plusieurs requêtes
    dans certains montages (les fixtures de test, notamment). Une carte mise en
    cache trop largement afficherait la zone d'une page précédente.
    """
    if not has_request_context():
        return {'ui_flux': False, 'ui_flux_eligible': False}

    memo = getattr(request, '_interface_flux', None)
    if memo is not None:
        return memo

    profil = session.get('profil')
    user_id = session.get('user_id')

    if not interface_active(profil, user_id):
        # « Essayer la nouvelle interface » ne s'affiche que si la bascule peut
        # réellement aboutir : quand l'option du centre est décochée, le bouton
        # mènerait à un accueil qui redirige aussitôt.
        donnees = {
            'ui_flux': False,
            'ui_flux_eligible': (bool(user_id)
                                 and not est_telephone()
                                 and option_globale_active()
                                 and navigation.est_eligible(profil, user_id)),
        }
    else:
        carte = carte_pour_utilisateur(profil, user_id)
        zone, page = navigation.localiser(carte, request.endpoint)
        donnees = {
            'ui_flux': True,
            'ui_flux_eligible': True,
            'nav_carte': carte,
            'nav_zone': zone,
            'nav_page': page,
            'nav_identite': _identite(profil, user_id),
            'nav_recherche_globale': recherche_globale_autorisee(profil),
        }

    try:
        request._interface_flux = donnees
    except Exception:   # objet Request immuable : on recalculera, sans casser
        pass
    return donnees


def flux_infos_page():
    """Flux d'information de la page courante (liste vide si elle n'en a pas)."""
    import flux_infos
    endpoint = request.endpoint
    if endpoint not in flux_infos.CONSTRUCTEURS:
        return []
    from database import get_db
    conn = get_db()
    try:
        return flux_infos.construire(conn, endpoint, {
            'profil': session.get('profil'),
            'user_id': session.get('user_id'),
        })
    finally:
        conn.close()
