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


def interface_active(profil, user_id):
    """Décide si la requête courante doit être servie sans menu."""
    if not user_id:
        return False
    if not option_globale_active():
        return False
    if not navigation.est_eligible(profil, user_id):
        return False
    return preference_utilisateur(user_id) is not False


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
                                 and option_globale_active()
                                 and navigation.est_eligible(profil, user_id)),
        }
    else:
        drapeaux = _drapeaux(profil, user_id)
        carte = navigation.carte_navigation(drapeaux)
        zone, page = navigation.localiser(carte, request.endpoint)
        donnees = {
            'ui_flux': True,
            'ui_flux_eligible': True,
            'nav_carte': carte,
            'nav_zone': zone,
            'nav_page': page,
            'nav_identite': _identite(profil, user_id),
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
