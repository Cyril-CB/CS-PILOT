"""Validation et stockage bornés, sans calcul ni interprétation des documents."""
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re

import database
from document_files import nettoyer_document
from propositions import lire_pieces, PropositionInvalide
from stockage_restaure import chemin_relatif_sur

LECTEURS = ('directeur', 'comptable', 'responsable')
GESTIONNAIRES = ('directeur', 'comptable')
MAX_CHAMPS = 30
MAX_DOCUMENTS = 50
MAX_FICHIER = 5 * 1024**2
MAX_REQUETE = 6 * 1024**2
RACINE = 'documents/identite-centre'


def horodatage():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def texte(valeur, maximum, libelle, obligatoire=False):
    valeur = valeur.replace('\r\n', '\n').strip()
    if len(valeur) > maximum or any(ord(c) < 32 and c not in '\n\t' for c in valeur):
        raise ValueError(f'{libelle} : utilisez au maximum {maximum} caractères de texte.')
    if obligatoire and not valeur:
        raise ValueError(f'{libelle} est obligatoire.')
    return valeur


def valider_identite(form):
    valeurs = {k: texte(form.get(k, ''), maximum, libelle) for k, maximum, libelle in (
        ('nom', 160, 'Nom du centre'), ('siren', 20, 'SIREN'),
        ('siret', 25, 'SIRET'), ('ape', 10, 'Code APE'),
        ('convention_collective_code', 50, 'Code de convention collective'))}
    # Les identifiants restent du texte : conserver les zéros initiaux.
    for k, longueur in (('siren', 9), ('siret', 14)):
        valeurs[k] = valeurs[k].replace(' ', '')
        if valeurs[k] and not re.fullmatch(r'[0-9]{%d}' % longueur, valeurs[k]):
            raise ValueError(f'{k.upper()} : indiquez {longueur} chiffres ou laissez vide.')
    if valeurs['siren'] and valeurs['siret'] and not valeurs['siret'].startswith(valeurs['siren']):
        raise ValueError('Le SIRET doit commencer par le SIREN renseigné.')
    valeurs['ape'] = valeurs['ape'].replace('.', '').replace(' ', '').upper()
    if valeurs['ape'] and not re.fullmatch(r'[0-9]{4}[A-Z]', valeurs['ape']):
        raise ValueError('Code APE : indiquez quatre chiffres et une lettre ou laissez vide.')
    return valeurs


def chemin_document(piece):
    # Refuser aussi une référence à une autre catégorie de documents.
    relatif = piece['fichier_path']
    if not re.fullmatch(r'identite-centre/[a-f0-9]{32}\.[a-z0-9]+', relatif):
        raise ValueError('Référence de document invalide')
    return Path(chemin_relatif_sur(database.DATA_DIR, 'documents/' + relatif, RACINE))


def ajouter_document(conn, form, fichiers, user_id, ecrits):
    libelle = texte(form.get('libelle_document', ''), 120, 'Titre du document', True)
    if len(fichiers) != 1 or not fichiers[0].filename:
        raise ValueError('Sélectionnez un seul document.')
    if conn.execute('SELECT COUNT(*) FROM identite_centre_documents').fetchone()[0] >= MAX_DOCUMENTS:
        raise ValueError(f'La fiche peut contenir au maximum {MAX_DOCUMENTS} documents.')
    try:
        piece = lire_pieces(fichiers)[0]
    except PropositionInvalide as exc:
        raise ValueError(next(iter(exc.erreurs.values()))) from exc
    relatif = f"identite-centre/{piece['id']}{piece['extension']}"
    chemin = chemin_document({'fichier_path': relatif})
    chemin.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with chemin.open('xb') as sortie:
        ecrits.append(chemin)
        os.chmod(chemin, 0o600)
        sortie.write(piece['contenu'])
        sortie.flush()
        os.fsync(sortie.fileno())
    conn.execute('''INSERT INTO identite_centre_documents
        (id, libelle, nom, fichier_path, taille, mime, sha256, cree_le, ajoute_par)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (piece['id'], libelle, piece['nom'], relatif, piece['taille'], piece['mime'],
         piece['sha256'], horodatage(), user_id))


def contenu_document(piece):
    with chemin_document(piece).open('rb') as entree:
        contenu = entree.read(MAX_FICHIER + 1)
    if len(contenu) != piece['taille'] or hashlib.sha256(contenu).hexdigest() != piece['sha256']:
        raise ValueError('Document absent ou altéré')
    return contenu


def nettoyer(chemins):
    for chemin in chemins:
        nettoyer_document(str(chemin.parent), chemin.name)
