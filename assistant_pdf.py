"""Extraction textuelle des PDF, annexes scannées signalées sans OCR."""
import os
import logging
from pathlib import Path
import shutil
import uuid

import pdfplumber

from assistant_stockage import AssistantErreur
from database import DATA_DIR
from stockage_restaure import resoudre_fichier

MAX_PDF = 16 * 1024 * 1024
MAX_PAGES = 60
MAX_TEXTE = 150000
DOSSIER = 'assistant_reception'


def extraire_pdf(contenu):
    import io
    if not contenu or len(contenu) > MAX_PDF:
        raise AssistantErreur('Le PDF doit peser au maximum 16 Mo.')
    if not contenu.startswith(b'%PDF-'):
        raise AssistantErreur('Le fichier reçu n’est pas un PDF valide.')
    pages, taille = [], 0
    try:
        with pdfplumber.open(io.BytesIO(contenu)) as pdf:
            if not 1 <= len(pdf.pages) <= MAX_PAGES:
                raise AssistantErreur('Le PDF doit contenir entre 1 et 60 pages.')
            for numero, page in enumerate(pdf.pages, 1):
                texte = page.extract_text() or ''
                surface = max(1, page.width * page.height)
                images = sum(max(0, i['x1'] - i['x0']) * max(0, i['bottom'] - i['top'])
                             for i in page.images)
                if images / surface > 0.8 or (page.images and len(texte.strip()) < 20):
                    pages.append({'page': numero, 'texte': '', 'scannee': True})
                    continue
                taille += len(texte)
                if taille > MAX_TEXTE:
                    raise AssistantErreur('Le texte du PDF est trop volumineux pour cette première version.')
                pages.append({'page': numero, 'texte': texte})
    except AssistantErreur:
        raise
    except Exception:
        raise AssistantErreur('PDF illisible ou protégé. Fournissez un original numérique non protégé.') from None
    if sum(len(p['texte'].strip()) for p in pages) < 40:
        raise AssistantErreur('Ce PDF ne contient pas assez de texte exploitable. Fournissez le PDF numérique original, pas un scan.')
    return pages


def avertissement_pages(pages):
    numeros = [str(p['page']) for p in pages if p.get('scannee')]
    if not numeros:
        return ''
    sujet = ('La page ' if len(numeros) == 1 else 'Les pages ') + ', '.join(numeros)
    suite = (' semble scannée et n’a pas été analysée.' if len(numeros) == 1
             else ' semblent scannées et n’ont pas été analysées.')
    return sujet + suite + ' L’analyse porte sur les pages lisibles. Le PDF complet est conservé.'


def chemin_document(chemin):
    resolu = resoudre_fichier(chemin, 'documents')
    racine = (Path(DATA_DIR) / 'documents' / DOSSIER).resolve()
    if not resolu or not Path(resolu).resolve().is_relative_to(racine):
        raise AssistantErreur('Document indisponible.', 404)
    return Path(resolu)


def enregistrer_pdf(contenu, identifiant):
    dossier = Path(DATA_DIR) / 'documents' / DOSSIER
    dossier.mkdir(parents=True, exist_ok=True)
    if not dossier.resolve().is_relative_to(Path(DATA_DIR).resolve()):
        raise AssistantErreur('Stockage documentaire indisponible.', 503)
    nom = identifiant + '.pdf'
    with (dossier / nom).open('xb') as fichier:
        fichier.write(contenu)
    return DOSSIER + '/' + nom


def copier_piece(source, dossier, nom, fichiers_crees):
    """Copie exclusive ; la transaction appelante nettoie ses seuls nouveaux fichiers."""
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    if not dossier.resolve().is_relative_to(Path(DATA_DIR).resolve()):
        raise AssistantErreur('Stockage documentaire indisponible.', 503)
    if Path(nom).name != nom or any(c in nom for c in ('\\', ':', '\x00')):
        raise AssistantErreur('Nom de pièce invalide.')
    cible = dossier / (Path(nom).stem + '_' + uuid.uuid4().hex + Path(nom).suffix)
    with cible.open('xb') as sortie:
        fichiers_crees.append(cible)
        with Path(source).open('rb') as entree:
            shutil.copyfileobj(entree, sortie)
    return cible


def nettoyer_creations(chemins):
    # Seulement des copies réservées dans cette opération, jamais une pièce métier préexistante.
    for chemin in chemins:
        try:
            os.unlink(chemin)
        except FileNotFoundError:
            pass
        except OSError as exc:
            logging.getLogger(__name__).warning('Copie documentaire à nettoyer (%s).', type(exc).__name__)
