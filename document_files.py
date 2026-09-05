"""Nettoyage non bloquant des pièces après un commit ou un rollback métier."""
import logging
import os

from werkzeug.security import safe_join

logger = logging.getLogger(__name__)


def nettoyer_document(dossier, nom_fichier):
    """Supprime une pièce interne ; un échec disque est journalisé séparément.

    Les pièces sont enregistrées à plat dans un dossier géré par l'application.
    Ne jamais transformer un chemin refusé en un autre nom de fichier valide.
    Ce nettoyage ne remplace pas une suppression requise avant un commit.
    """
    if not nom_fichier:
        return True
    if nom_fichier in ('.', '..') or any(c in nom_fichier for c in ('/', '\\', ':', '\x00')):
        logger.warning('Chemin de document refusé : %r.', nom_fichier)
        return False
    try:
        dossier_reel = os.path.realpath(dossier)
        chemin = safe_join(dossier_reel, nom_fichier)
        if chemin is None or not os.path.realpath(chemin).startswith(dossier_reel + os.sep):
            logger.warning('Chemin de document refusé : %r.', nom_fichier)
            return False
        os.remove(chemin)
    except FileNotFoundError:
        return True  # Une pièce déjà absente ne nécessite aucun nettoyage.
    except OSError as exc:
        # Conserver le nom pour permettre un nettoyage manuel, sans exposer
        # le chemin système ni l'exception dans la réponse HTTP.
        logger.warning('Nettoyage du document %r impossible (%s).',
                       nom_fichier, type(exc).__name__)
        return False
    return True
