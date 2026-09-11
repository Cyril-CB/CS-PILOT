"""Résoudre les anciens chemins absolus sans réécrire l'histoire en SQLite."""
import json
import os
from pathlib import Path, PurePosixPath

FICHIER_CHEMINS = 'restauration-chemins.json'
REPERTOIRES = ('documents', 'factures', 'modeles_contrats', 'contrats_generes', 'exports')


def chemin_relatif_sur(data_dir, relatif, racine):
    """Chemin strict, sans traversée ni lien symbolique hors du stockage."""
    p = PurePosixPath(relatif)
    if (p.is_absolute() or '..' in p.parts or '\\' in relatif or ':' in relatif
            or not p.parts or p.parts[0] != racine.split('/')[0]):
        raise ValueError('Chemin de stockage invalide')
    base = Path(data_dir).resolve()
    cible = base.joinpath(*p.parts)
    limite = base / racine
    if not cible.resolve().is_relative_to(limite.resolve()) or not limite.resolve().is_relative_to(base):
        raise ValueError('Chemin de stockage hors périmètre')
    return str(cible)


def resoudre_fichier(chemin, racine, data_dir=None):
    """Compatibilité des installations d'origine ; relocalisation explicite.

    En restauration, un ancien chemin absolu n'est jamais suivi sur le serveur
    source, même si celui-ci est encore accessible. La correspondance est créée
    à partir des références vérifiées lors de la sauvegarde.
    """
    if not chemin:
        return None
    if data_dir is None:
        from database import DATA_DIR
        data_dir = DATA_DIR
    mapping = Path(data_dir) / FICHIER_CHEMINS
    if mapping.is_file():
        correspondances = json.loads(mapping.read_text(encoding='utf-8'))
        if chemin in correspondances:
            return chemin_relatif_sur(data_dir, correspondances[chemin], racine)
        if os.path.isabs(chemin):
            try:
                relatif = Path(chemin).relative_to(Path(data_dir).resolve()).as_posix()
            except ValueError:
                return None
            return chemin_relatif_sur(data_dir, relatif, racine)
    if os.path.isabs(chemin):
        return chemin  # Compatibilité historique ; la sauvegarde contrôle son périmètre.
    return chemin_relatif_sur(data_dir, f'{racine}/{chemin}', racine)
