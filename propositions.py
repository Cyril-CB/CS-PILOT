"""Préparation des propositions et de leur email versionné, sans interpréter les pièces."""
from datetime import date, datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import uuid
import zipfile
from urllib.parse import urlsplit, urlunsplit

from flask import current_app

import database
from app_version import get_app_version
from document_files import nettoyer_document
from email_service import get_base_url, get_email_config
from interface_flux import carte_pour_utilisateur, endpoints_recherche_autorises
from search_engine import analyser_recherche, anonymiser_terme_salaries
from search_palette import construire_suggestions
from stockage_restaure import chemin_relatif_sur
from utils import aujourd_hui

DESTINATAIRE = 'cspilot@outlook.fr'
PROFILS = ('directeur', 'comptable', 'responsable', 'salarie', 'prestataire')
GESTIONNAIRES = ('directeur', 'comptable')
MAX_PIECES = 3
MAX_FICHIER = 5 * 1024**2
MAX_TOTAL = 8 * 1024**2
MAX_REQUETE = 10 * 1024**2
TYPES = {
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.xls': 'application/vnd.ms-excel',
    '.ods': 'application/vnd.oasis.opendocument.spreadsheet',
    '.csv': 'text/csv',
    '.pdf': 'application/pdf',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.txt': 'text/plain',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
}
FREQUENCES = {
    '': 'Non précisée', 'ponctuel': 'Une fois', 'quotidien': 'Chaque jour',
    'hebdomadaire': 'Chaque semaine', 'mensuel': 'Chaque mois',
    'annuel': 'Chaque année', 'occasionnel': 'À certaines occasions',
}
ORIGINES = {
    'sans_resultat': 'Recherche sans résultat',
    'insatisfait': 'Les résultats ne répondent pas au besoin',
    'recherche_indisponible': 'Recherche indisponible',
    'spontanee': 'Proposition depuis l’application',
}
ERREURS_ENVOI = {
    'configuration': 'Les emails du centre ne sont pas configurés ou sont désactivés.',
    'smtp': 'Le service de messagerie a refusé l’envoi. La demande est conservée.',
    'connexion': 'La connexion au service de messagerie a échoué. La demande est conservée.',
    'incertain': 'L’envoi a été interrompu : le mail a peut-être été transmis.',
    'piece': 'Une pièce jointe est absente ou altérée. Contactez la direction avec la référence.',
}


class PropositionInvalide(ValueError):
    def __init__(self, erreurs):
        self.erreurs = erreurs
        super().__init__('Proposition invalide')


def horodatage():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def charger_auteur(conn, user_id):
    return conn.execute('''SELECT u.id, u.nom, u.prenom, u.profil, u.email,
        u.session_version, s.nom AS secteur
        FROM users u LEFT JOIN secteurs s ON s.id=u.secteur_id WHERE u.id=?''',
        (user_id,)).fetchone()


def contexte_initial(user, recherche='', origine='spontanee', endpoint=''):
    """L'origine/page est déclarée par le navigateur, sans URL ni paramètres métier."""
    page = next((r for r in current_app.url_map.iter_rules() if r.endpoint == endpoint), None)
    return {
        'reference': uuid.uuid4().hex, 'user_id': user['id'],
        'session_version': user['session_version'],
        'recherche': recherche.strip()[:200],
        'origine': origine if origine in ORIGINES else 'spontanee',
        'page': {'endpoint': page.endpoint, 'route': page.rule} if page else None,
    }


def valider_champs(form):
    bornes = {'titre': 120, 'besoin': 10000, 'email_reponse': 254,
              'resultat_attendu': 2000, 'solution_actuelle': 2000,
              'personnes_concernees': 1000, 'raison_echeance': 1000,
              'frequence': 20, 'echeance': 10, 'recherche': 200}
    valeurs, erreurs = {}, {}
    for nom, maximum in bornes.items():
        texte = form.get(nom, '').replace('\r\n', '\n').strip()
        valeurs[nom] = texte
        if len(texte) > maximum:
            erreurs[nom] = f'Limitez ce champ à {maximum} caractères.'
        elif any(ord(c) < 32 and c not in '\n\t' for c in texte):
            erreurs[nom] = 'Ce champ contient des caractères non valides.'
    if len(valeurs['besoin']) < 20:
        erreurs['besoin'] = 'Décrivez votre besoin en une phrase ou deux (20 caractères minimum).'
    adresse = valeurs['email_reponse']
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}", adresse):
        erreurs['email_reponse'] = 'Indiquez une seule adresse email valide pour vous répondre.'
    elif len(adresse.split('@')[0]) > 64 or '..' in adresse or adresse.startswith('.') or '.@' in adresse:
        erreurs['email_reponse'] = 'Indiquez une adresse email valide.'
    if '\n' in valeurs['titre'] or '\t' in valeurs['titre']:
        erreurs['titre'] = 'Le titre doit tenir sur une seule ligne.'
    if valeurs['frequence'] not in FREQUENCES:
        erreurs['frequence'] = 'Choisissez une fréquence dans la liste.'
    if valeurs['echeance']:
        try:
            if date.fromisoformat(valeurs['echeance']).isoformat() != valeurs['echeance']:
                raise ValueError()
        except ValueError:
            erreurs['echeance'] = 'Indiquez une date valide.'
    if erreurs:
        raise PropositionInvalide(erreurs)
    valeurs['titre'] = valeurs['titre'] or ' '.join(valeurs['besoin'].split())[:100]
    return valeurs


def _verifier_type(contenu, extension):
    """Vérifications bornées de format ; aucune formule, macro ou lien exécuté."""
    if extension in ('.xlsx', '.docx', '.ods'):
        try:
            with zipfile.ZipFile(io.BytesIO(contenu)) as archive:
                infos = archive.infolist()
                noms = {i.filename for i in infos}
                if (len(infos) > 1000 or len(noms) != len(infos)
                        or sum(i.file_size for i in infos) > 50 * 1024**2
                        or any(i.flag_bits & 1 or 'vbaproject' in i.filename.lower()
                               or '..' in Path(i.filename).parts or '\\' in i.filename
                               or i.filename.startswith('/') for i in infos)):
                    return False
                if extension == '.ods':
                    info = archive.getinfo('mimetype')
                    return info.file_size < 100 and archive.read(info) == TYPES['.ods'].encode()
                return ('[Content_Types].xml' in noms
                        and ('xl/workbook.xml' if extension == '.xlsx' else 'word/document.xml') in noms)
        except (zipfile.BadZipFile, KeyError, OSError, ValueError):
            return False
    signatures = {'.xls': b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1',
                  '.pdf': b'%PDF-', '.png': b'\x89PNG\r\n\x1a\n',
                  '.jpg': b'\xff\xd8\xff', '.jpeg': b'\xff\xd8\xff'}
    if extension in signatures:
        return contenu.startswith(signatures[extension])
    try:
        if contenu.startswith((b'\xff\xfe', b'\xfe\xff')):
            texte = contenu.decode('utf-16')
        else:
            texte = contenu.decode('utf-8-sig')
    except UnicodeError:
        try:
            texte = contenu.decode('cp1252')
        except UnicodeError:
            return False
    return not any(ord(c) < 32 and c not in '\r\n\t' for c in texte)


def lire_pieces(fichiers):
    fichiers = [f for f in fichiers if f.filename]
    if len(fichiers) > MAX_PIECES:
        raise PropositionInvalide({'pieces': 'Joignez au maximum 3 fichiers.'})
    maximum_fichier, maximum_total = limites_pieces()
    pieces, total = [], 0
    for numero, fichier in enumerate(fichiers, 1):
        nom = fichier.filename.strip()
        extension = Path(nom).suffix.lower()
        if (not nom or len(nom) > 150 or any(c in nom for c in '/\\:')
                or any(ord(c) < 32 or ord(c) == 127 for c in nom)):
            raise PropositionInvalide({'pieces': 'Un nom de fichier est invalide.'})
        if extension not in TYPES:
            raise PropositionInvalide({'pieces': 'Format non accepté. Utilisez un des formats indiqués sous le champ.'})
        contenu = fichier.stream.read(maximum_fichier + 1)
        total += len(contenu)
        if not contenu or len(contenu) > maximum_fichier or total > maximum_total:
            raise PropositionInvalide({'pieces': 'Un fichier est vide ou dépasse les limites de taille indiquées.'})
        if not _verifier_type(contenu, extension):
            raise PropositionInvalide({'pieces': 'Un fichier ne correspond pas au format annoncé, est chiffré ou dépasse les limites de lecture.'})
        pieces.append({'id': uuid.uuid4().hex, 'nom': nom,
            'nom_email': f'{numero:02d}-{nom}', 'extension': extension,
            'taille': len(contenu), 'mime': TYPES[extension],
            'sha256': hashlib.sha256(contenu).hexdigest(), 'contenu': contenu})
    return pieces


def limites_pieces():
    # Réserver la place du texte et de l'enveloppe multipart lorsque le centre
    # a choisi un plafond inférieur à celui des propositions.
    plafond = min(current_app.config.get('MAX_CONTENT_LENGTH') or MAX_REQUETE, MAX_REQUETE)
    total = min(MAX_TOTAL, max(0, plafond - 64 * 1024))
    return min(MAX_FICHIER, total), total


def _revision_sources():
    racine = Path(__file__).resolve().parent
    marqueur = racine / 'REVISION-SOURCES.txt'
    try:
        if marqueur.is_file():
            valeur = marqueur.read_text(encoding='ascii').strip()
        elif (racine / '.git').exists():
            valeur = subprocess.run(['git', '-C', str(racine), 'rev-parse', 'HEAD'],
                capture_output=True, text=True, timeout=2, check=True).stdout.strip()
        else:
            return None
        return valeur if re.fullmatch('[a-f0-9]{40}', valeur) else None
    except (OSError, UnicodeError, subprocess.SubprocessError):
        return None


def construire_contenu(conn, auteur, valeurs, contexte, pieces):
    recherche = valeurs['recherche']
    carte = carte_pour_utilisateur(auteur['profil'], auteur['id'])
    verdict = None
    if recherche and auteur['profil'] in ('directeur', 'comptable', 'responsable'):
        verdict = analyser_recherche(conn, recherche, auteur['profil'], aujourd_hui(),
            user_id=auteur['id'], endpoints_autorises=endpoints_recherche_autorises(
                auteur['profil'], auteur['id'], carte))
    suggestions = construire_suggestions(carte, recherche, verdict) if recherche else []
    precis = [s for s in suggestions if s.get('action') != 'ensemble']
    config = get_email_config()
    try:
        base_url = urlsplit(get_base_url() or '')
        url_centre = (urlunsplit((base_url.scheme, base_url.netloc, base_url.path, '', ''))
                      if base_url.scheme in ('http', 'https') and base_url.hostname
                      and not base_url.username and not base_url.password else None)
    except ValueError:
        # Une URL de centre mal configurée ne doit pas empêcher de proposer.
        url_centre = None
    return {
        'format': 'cspilot.proposition', 'version': 1,
        'reference': contexte['reference'], 'cree_le': horodatage(),
        'demande': {k: v for k, v in valeurs.items() if k not in ('email_reponse', 'recherche')},
        'auteur': {'id_local': auteur['id'], 'nom': auteur['nom'], 'prenom': auteur['prenom'],
            'profil': auteur['profil'], 'secteur': auteur['secteur'],
            'email_reponse': valeurs['email_reponse']},
        'centre': {'nom_expediteur': config.get('sender_name') or 'CS-PILOT',
                   'url_configuree': url_centre},
        'contexte': {
            'recherche': recherche, 'origine_declaree': contexte['origine'],
            'page_declaree': contexte['page'],
            'recherche_recalculee': {'effectuee': bool(recherche), 'nombre_resultats': len(precis),
                'suggestions': [{'type': s.get('action'),
                    'titre': anonymiser_terme_salaries(conn, s.get('titre', ''))} for s in precis[:5]]},
            'application': {'version': get_app_version(), 'revision': _revision_sources(),
                'migration': conn.execute("SELECT MAX(version) FROM schema_migrations WHERE statut='ok'").fetchone()[0]},
        },
        'pieces_jointes': [{k: p[k] for k in ('id', 'nom', 'nom_email', 'taille', 'mime', 'sha256')} for p in pieces],
    }


def enregistrer(conn, contenu, pieces, ecrits):
    """L'appelant possède la transaction et nettoie ecrits en cas d'échec."""
    reference = contenu['reference']
    conn.execute('''INSERT INTO propositions_amelioration
        (id, user_id, cree_le, contenu_json) VALUES (?, ?, ?, ?)''',
        (reference, contenu['auteur']['id_local'], contenu['cree_le'],
         json.dumps(contenu, ensure_ascii=False)))
    for piece in pieces:
        relatif = f"propositions/{piece['id']}{piece['extension']}"
        chemin = Path(chemin_relatif_sur(database.DATA_DIR, 'documents/' + relatif, 'documents'))
        chemin.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with chemin.open('xb') as sortie:
            ecrits.append(chemin)
            os.chmod(chemin, 0o600)
            sortie.write(piece['contenu'])
            sortie.flush()
            os.fsync(sortie.fileno())
        conn.execute('''INSERT INTO propositions_pieces
            (id, proposition_id, nom, fichier_path, taille, mime, sha256)
            VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (piece['id'], reference, piece['nom'], relatif, piece['taille'], piece['mime'], piece['sha256']))


def nettoyer_pieces(ecrits):
    for chemin in ecrits:
        nettoyer_document(str(chemin.parent), chemin.name)


def contenu_piece(piece):
    chemin = chemin_relatif_sur(database.DATA_DIR, 'documents/' + piece['fichier_path'], 'documents')
    with open(chemin, 'rb') as entree:
        contenu = entree.read(MAX_FICHIER + 1)
    if len(contenu) != piece['taille'] or hashlib.sha256(contenu).hexdigest() != piece['sha256']:
        raise ValueError('Pièce altérée')
    return contenu


def construire_message(contenu, pieces):
    reference = contenu['reference']
    demande, auteur, contexte = contenu['demande'], contenu['auteur'], contenu['contexte']
    lignes = [
        'PROPOSITION D’AMÉLIORATION CS PILOT', f'Référence : {reference}',
        f"Créée le : {contenu['cree_le']}", f"Titre : {demande['titre']}",
        f"Auteur : {auteur['prenom']} {auteur['nom']} ({auteur['profil']})",
        f"Secteur : {auteur['secteur'] or 'Non renseigné'}",
        f"Répondre à : {auteur['email_reponse']}",
        f"Centre : {contenu['centre']['nom_expediteur']}",
        f"Site configuré : {contenu['centre']['url_configuree'] or 'Non renseigné'}",
        '', 'BESOIN EXPRIMÉ', demande['besoin'], '',
    ]
    for cle, libelle in (('resultat_attendu', 'Résultat attendu'),
                         ('solution_actuelle', 'Solution actuelle'),
                         ('personnes_concernees', 'Personnes concernées'),
                         ('echeance', 'Échéance'), ('raison_echeance', 'Raison de cette échéance')):
        lignes.extend([libelle + ' :', demande[cle] or 'Non précisé', ''])
    lignes += ['Fréquence : ' + FREQUENCES[demande['frequence']],
        '', 'CONTEXTE', 'Recherche : ' + (contexte['recherche'] or 'Aucune'),
        'Origine déclarée : ' + ORIGINES[contexte['origine_declaree']],
        'Page déclarée : ' + ((contexte['page_declaree'] or {}).get('route') or 'Non précisée'),
        'Version : ' + contexte['application']['version'],
        '', 'La fiche cspilot-proposition-v1.json contient les données structurées et les empreintes des pièces.',
        'Cette proposition est à étudier ; elle ne vaut pas autorisation automatique de développement.',
    ]
    message = EmailMessage()
    message['Subject'] = f"[CS-PILOT][Proposition {reference}] {demande['titre']}"
    message['Reply-To'] = auteur['email_reponse']
    message['Message-ID'] = f'<proposition.{reference}@cs-pilot.fr>'
    message['Date'] = format_datetime(datetime.fromisoformat(contenu['cree_le']))
    message['X-CS-PILOT-Type'] = 'proposition-v1'
    message['X-CS-PILOT-Reference'] = reference
    message.set_content('\n'.join(lignes))
    message.add_attachment(json.dumps(contenu, ensure_ascii=False, indent=2).encode('utf-8'),
        maintype='application', subtype='json', filename='cspilot-proposition-v1.json')
    index = {p['id']: p for p in pieces}
    for metadata in contenu['pieces_jointes']:
        piece = index[metadata['id']]
        if any(piece[k] != metadata[k] for k in ('nom', 'taille', 'mime', 'sha256')):
            raise ValueError('Métadonnées de pièce altérées')
        principal, secondaire = piece['mime'].split('/')
        message.add_attachment(contenu_piece(piece), maintype=principal, subtype=secondaire,
                               filename=metadata['nom_email'])
    return message
