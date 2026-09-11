"""Sauvegarde complète chiffrée, restauration vierge et diagnostic hors ligne.

Usage et prérequis d'arrêt : docs/resilience.md. Aucun service n'est démarré,
aucune migration appliquée et aucun appel réseau effectué par ces fonctions.
"""
import base64
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import sqlite3
import stat
import subprocess
import tempfile
import time
import zipfile

from cryptography.exceptions import InvalidTag
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from dotenv import dotenv_values

from stockage_restaure import FICHIER_CHEMINS, REPERTOIRES, resoudre_fichier

MAGIC = b'CSPILOT-BACKUP-1\n'
BLOC = 1024 * 1024
MAX_ARCHIVE = 32 * 1024 ** 3  # Sous la limite d'un message GCM ; pas de chargement en RAM.
ENV_DEMARRAGE = ('SECRET_KEY', 'BEHIND_PROXY', 'PORT', 'FLASK_DEBUG', 'APP_TIMEZONE', 'MAX_UPLOAD_MO')
# Liste fermée des références disque actuellement utilisées par l'application.
REFERENCES = (
    ('documents_salaries', 'fichier_path', 'documents'),
    ('contrats', 'fichier_path', 'documents'),
    ('absences', 'justificatif_path', 'documents'),
    ('subventions', 'justificatif_path', 'documents/subventions'),
    ('subventions_sous_elements', 'document_path', 'documents/subventions'),
    ('factures', 'fichier_path', 'factures'),
    ('modeles_contrats', 'fichier_path', 'modeles_contrats'),
    ('contrats_generes', 'fichier_path', 'contrats_generes'),
    ('archives_export', 'fichier_path', 'exports'),
)
# Ne pas annoncer une copie complète si un module historique a perdu sa table.
# Une vieille sauvegarde reste lisible avec les tables attendues à sa version.
TABLES_REQUISES = {
    '0001': ('users', 'secteurs', 'heures_reelles', 'planning_theorique', 'validations',
             'app_settings', 'demandes_recup', 'historique_modifications'),
    '0003': ('absences',),
    '0004': ('variables_paie',),
    '0005': ('contrats', 'documents_salaries'),
    '0006': ('prepa_paie_statut',),
    '0016': ('subventions', 'subventions_sous_elements'),
    '0022': ('factures', 'ecritures_comptables', 'facture_historique'),
    '0023': ('archives_export',),
    '0024': ('modeles_contrats', 'contrats_generes'),
    '0065': ('fiches_versions', 'fiches_evenements'),
    '0068': ('rh_projections',),
    '0069': ('export_lignes', 'comptabilite_evenements'),
    '0071': ('schema_migrations_tentatives', 'plan_comptable_general'),
}


class ErreurResilience(ValueError):
    """Message d'exploitation sans donnée métier ni secret."""


def ouvrir_lecture(db_path):
    return sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True)


def copier_sqlite(source, destination):
    """Copie SQLite cohérente, WAL inclus, vérifiée avant utilisation."""
    with closing(ouvrir_lecture(source)) as entree, closing(sqlite3.connect(destination)) as sortie:
        entree.backup(sortie)
        if sortie.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ErreurResilience('La copie SQLite ne passe pas le contrôle d’intégrité.')


def fernet_pour(cle):
    if not isinstance(cle, str) or not cle:
        raise ErreurResilience('SECRET_KEY absente.')
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(cle.encode()).digest()))


def verifier_parametres(conn, cle):
    fernet = fernet_pour(cle)
    nb = 0
    for valeur, in conn.execute('SELECT value FROM app_settings'):
        if valeur:
            try:
                fernet.decrypt(valeur.encode()).decode('utf-8')
            except (InvalidToken, ValueError, UnicodeError):
                raise ErreurResilience('Paramètres indéchiffrables : vérifiez la SECRET_KEY d’origine.') from None
            nb += 1
    return nb


def rechiffrer_parametres(conn, ancienne, nouvelle):
    """Tout déchiffrer avant la première écriture ; l'appelant possède le commit."""
    verifier_parametres(conn, ancienne)
    avant, apres = fernet_pour(ancienne), fernet_pour(nouvelle)
    valeurs = [(apres.encrypt(avant.decrypt(v.encode())).decode(), k)
               for k, v in conn.execute('SELECT key, value FROM app_settings') if v]
    conn.executemany('UPDATE app_settings SET value=? WHERE key=?', valeurs)


def _hash(fichier):
    with open(fichier, 'rb') as flux:
        return hashlib.file_digest(flux, 'sha256').hexdigest()


def _inventaire(data_dir):
    """Tous les fichiers, y compris orphelins ; aucun lien ni fichier spécial."""
    resultat = {}
    for dossier in REPERTOIRES:
        racine = data_dir / dossier
        if racine.is_symlink():
            raise ErreurResilience('Un stockage est un lien symbolique : régularisation nécessaire.')
        if not racine.exists():
            continue
        if not racine.is_dir():
            raise ErreurResilience('Un stockage métier n’est pas un répertoire.')
        for parent, dirs, noms in os.walk(racine, followlinks=False):
            for nom in dirs + noms:
                p = Path(parent) / nom
                st = p.lstat()
                if not (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode)):
                    raise ErreurResilience('Lien ou fichier spécial dans un stockage métier.')
                if stat.S_ISREG(st.st_mode):
                    resultat[p.relative_to(data_dir).as_posix()] = (st.st_size, st.st_mtime_ns, st.st_ino)
    return resultat


def _references(conn, data_dir):
    refs, absentes, mapping = set(), [], {}
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table, colonne, racine in REFERENCES:
        if table not in tables:
            continue  # Une sauvegarde ancienne peut précéder un module.
        champs = {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}
        if colonne not in champs:
            continue
        condition = ' AND preuve_version=0' if table == 'archives_export' and 'preuve_version' in champs else ''
        for identifiant, chemin in conn.execute(
                f"SELECT id, {colonne} FROM {table} WHERE {colonne} IS NOT NULL AND {colonne} != ''{condition}"):
            try:
                resolu = resoudre_fichier(chemin, racine, data_dir)
                cible = Path(resolu).resolve() if resolu else None
                if cible is None or not cible.is_relative_to((data_dir / racine).resolve()):
                    raise ValueError('Hors stockage')
                relatif = cible.relative_to(data_dir).as_posix()
                refs.add(relatif)
                if not cible.is_file():
                    raise ValueError('Absent')
                if os.path.isabs(chemin):
                    mapping[chemin] = relatif
            except (ValueError, OSError):
                absentes.append({'table': table, 'id': identifiant, 'colonne': colonne})
    return refs, absentes, mapping


def diagnostiquer(data_dir, secret_key=None, *, db_path=None):
    """Lecture seule ; les anomalies listent des IDs, jamais le contenu sensible."""
    data_dir = Path(data_dir).resolve()
    rapport = {'integrite': False, 'erreurs': [], 'references_absentes': [], 'orphelins': [],
               'exports_verifies': 0, 'instantanes_verifies': 0, 'parametres_verifies': 0}
    try:
        with closing(ouvrir_lecture(db_path or data_dir / 'cspilot.db')) as conn:
            conn.row_factory = sqlite3.Row
            rapport['integrite'] = [r[0] for r in conn.execute('PRAGMA integrity_check')] == ['ok']
            if not rapport['integrite']:
                raise ErreurResilience('Intégrité SQLite incorrecte.')
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'schema_migrations' not in tables:
                raise ErreurResilience('État des migrations absent : diagnostic manuel nécessaire.')
            etats = {r['version']: r['statut'] for r in conn.execute('SELECT version, statut FROM schema_migrations')}
            catalogue = sorted(p.name[:4] for p in (Path(__file__).parent / 'migrations').glob('[0-9]*.py'))
            rapport['migrations'] = {
                'version': max((v for v, statut in etats.items() if statut == 'ok'), default='0000'),
                'erreurs': sorted(v for v, statut in etats.items() if statut != 'ok'),
                'en_attente': [v for v in catalogue if etats.get(v) != 'ok'],
                'inconnues': sorted(set(etats) - set(catalogue)),
            }
            requises = {table for version, liste in TABLES_REQUISES.items()
                        if version <= rapport['migrations']['version'] for table in liste}
            rapport['tables_absentes'] = sorted(requises - tables)
            if rapport['tables_absentes']:
                raise ErreurResilience('Tables métier ou de preuves absentes : installation incomplète.')
            refs, rapport['references_absentes'], _ = _references(conn, data_dir)
            fichiers = _inventaire(data_dir)
            rapport['orphelins'] = sorted(set(fichiers) - refs)
            for table in ('archives_export', 'fiches_versions'):
                if table not in tables:
                    continue
                if table == 'archives_export':
                    if 'preuve_version' not in {r[1] for r in conn.execute('PRAGMA table_info(archives_export)')}:
                        continue
                    rows = conn.execute('SELECT id, contenu, empreinte FROM archives_export WHERE preuve_version=1')
                else:
                    rows = conn.execute('SELECT id, contenu, empreinte FROM fiches_versions')
                for row in rows:
                    try:
                        contenu = row['contenu']
                        if table == 'fiches_versions':
                            objet = json.loads(contenu)
                            if not isinstance(objet, dict) or not isinstance(objet.get('journees'), list):
                                raise ValueError('Instantané illisible')
                            for jour in objet['journees']:
                                datetime.fromisoformat(jour['date_obj'])
                            contenu = json.dumps(objet, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
                        if not isinstance(contenu, bytes) or hashlib.sha256(contenu).hexdigest() != row['empreinte']:
                            raise ValueError('Empreinte incorrecte')
                    except (KeyError, TypeError, ValueError):
                        rapport['erreurs'].append(f"Preuve illisible ou altérée : {table}, id {row['id']}")
                    else:
                        rapport['exports_verifies' if table == 'archives_export' else 'instantanes_verifies'] += 1
            rapport['parametres_verifies'] = verifier_parametres(conn, secret_key)
            rapport['references_fk_invalides'] = len(conn.execute('PRAGMA foreign_key_check').fetchall())
            if rapport['references_fk_invalides']:
                rapport['erreurs'].append('Des références de base sont invalides.')
    except (sqlite3.Error, ErreurResilience, OSError) as erreur:
        rapport['erreurs'].append(str(erreur) if isinstance(erreur, ErreurResilience) else
                                 'Base ou stockage illisible : vérifier les fichiers et les droits.')
    rapport['donnees_valides'] = rapport['integrite'] and not rapport['erreurs'] and not rapport['references_absentes']
    migrations = rapport.get('migrations', {})
    rapport['ok'] = rapport['donnees_valides'] and bool(migrations) and not any(
        migrations[k] for k in ('erreurs', 'en_attente', 'inconnues'))
    return rapport


def _configuration(data_dir, secret_key):
    valeurs = {k: v for k, v in dotenv_values(data_dir / '.env').items() if v is not None}
    # Même priorité que load_dotenv au démarrage : environnement > fichier.
    valeurs.update({k: os.environ[k] for k in ENV_DEMARRAGE if k in os.environ})
    valeurs.pop('CSPILOT_DATA_DIR', None)
    if secret_key is not None:
        valeurs['SECRET_KEY'] = secret_key
    fernet_pour(valeurs.get('SECRET_KEY'))
    return valeurs


def _cle_archive(password, salt):
    if not isinstance(password, str) or len(password) < 16:
        raise ErreurResilience('Utilisez une phrase secrète de sauvegarde d’au moins 16 caractères.')
    return Scrypt(salt=salt, length=32, n=2**17, r=8, p=1).derive(password.encode())


def _chiffrer(source, destination, password):
    if source.stat().st_size > MAX_ARCHIVE:
        raise ErreurResilience('Archive supérieure à la limite de 32 Gio.')
    salt, nonce = os.urandom(16), os.urandom(12)
    header = MAGIC + salt + nonce
    chiffreur = Cipher(algorithms.AES(_cle_archive(password, salt)), modes.GCM(nonce)).encryptor()
    chiffreur.authenticate_additional_data(header)
    with source.open('rb') as entree, destination.open('xb') as sortie:
        os.chmod(destination, 0o600)
        sortie.write(header)
        while bloc := entree.read(BLOC):
            sortie.write(chiffreur.update(bloc))
        sortie.write(chiffreur.finalize())
        sortie.write(chiffreur.tag)
        sortie.flush()
        os.fsync(sortie.fileno())


def _dechiffrer(source, destination, password):
    taille = source.stat().st_size
    header_size = len(MAGIC) + 28
    if not header_size + 16 < taille <= MAX_ARCHIVE + header_size + 16:
        raise ErreurResilience('Format ou taille d’archive invalide.')
    try:
        with source.open('rb') as entree, destination.open('xb') as sortie:
            os.chmod(destination, 0o600)
            header = entree.read(header_size)
            if not header.startswith(MAGIC):
                raise ErreurResilience('Format d’archive inconnu.')
            salt, nonce = header[len(MAGIC):len(MAGIC)+16], header[-12:]
            entree.seek(-16, 2)
            tag = entree.read(16)
            entree.seek(header_size)
            dechiffreur = Cipher(algorithms.AES(_cle_archive(password, salt)), modes.GCM(nonce, tag)).decryptor()
            dechiffreur.authenticate_additional_data(header)
            restant = taille - header_size - 16
            while restant:
                bloc = entree.read(min(BLOC, restant))
                if not bloc:
                    raise ErreurResilience('Archive tronquée.')
                sortie.write(dechiffreur.update(bloc))
                restant -= len(bloc)
            sortie.write(dechiffreur.finalize())
            # Aucune ouverture du ZIP ni extraction AVANT l'authentification GCM.
    except InvalidTag:
        raise ErreurResilience('Phrase secrète incorrecte ou archive altérée.') from None


def sauvegarder(data_dir, archive_path, password, *, arret_confirme=False, secret_key=None):
    """Exporter vers un fichier nouveau. Tous les processus écrivains doivent être arrêtés."""
    if not arret_confirme:
        raise ErreurResilience('Arrêtez CS PILOT et ses tâches avant une sauvegarde complète.')
    debut = time.monotonic()
    data_dir, destination = Path(data_dir).resolve(), Path(archive_path).absolute()
    if destination.exists() or destination.is_symlink():
        raise ErreurResilience('Le fichier de destination existe déjà.')
    if any(destination.is_relative_to(data_dir / r) for r in REPERTOIRES):
        raise ErreurResilience('Placez l’archive hors des stockages métier.')
    configuration = _configuration(data_dir, secret_key)
    db_path = data_dir / 'cspilot.db'
    if not db_path.is_file() or db_path.is_symlink():
        raise ErreurResilience('Base source absente ou lien symbolique.')
    with tempfile.TemporaryDirectory(prefix='.cspilot-backup-', dir=destination.parent) as tmp:
        travail = Path(tmp)
        with closing(sqlite3.connect(db_path, timeout=5)) as verrou:
            verrou.execute('BEGIN IMMEDIATE')  # Empêche une nouvelle écriture DB durant la copie.
            avant = _inventaire(data_dir)
            if sum(st[0] for st in avant.values()) + db_path.stat().st_size > MAX_ARCHIVE:
                raise ErreurResilience('Volume décompressé supérieur à la limite de 32 Gio.')
            copie = travail / 'cspilot.db'
            copier_sqlite(db_path, copie)
            rapport = diagnostiquer(data_dir, configuration['SECRET_KEY'], db_path=copie)
            if not rapport['donnees_valides']:
                raise ErreurResilience('Sauvegarde complète refusée : exécutez le diagnostic (fichiers, preuves, clé).')
            with closing(ouvrir_lecture(copie)) as conn:
                _, _, correspondances = _references(conn, data_dir)
            manifeste = {'format': 1, 'cree_le': datetime.now(timezone.utc).isoformat(),
                         'stockages': list(REPERTOIRES), 'fichiers': {}, 'diagnostic': rapport,
                         'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version}
            code = Path(__file__).resolve().parent
            revision = subprocess.run(['git', '-C', str(code), 'rev-parse', 'HEAD'],
                                      capture_output=True, text=True, check=False)
            manifeste['revision_code'] = revision.stdout.strip() if revision.returncode == 0 else 'inconnue'
            etat_code = subprocess.run(['git', '-C', str(code), 'status', '--porcelain', '--untracked-files=normal'],
                                       capture_output=True, text=True, check=False)
            manifeste['code_modifie'] = etat_code.returncode != 0 or bool(etat_code.stdout.strip())
            manifeste['requirements_sha256'] = _hash(code / 'requirements.txt')
            zip_path = travail / 'sauvegarde.zip'
            with zipfile.ZipFile(zip_path, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
                os.chmod(zip_path, 0o600)
                fichiers = {'cspilot.db': copie, **{nom: data_dir / nom for nom in avant}}
                for nom, chemin in fichiers.items():
                    digest = hashlib.sha256()
                    with chemin.open('rb') as source, archive.open(nom, 'w', force_zip64=True) as sortie:
                        while bloc := source.read(BLOC):
                            digest.update(bloc)
                            sortie.write(bloc)
                    manifeste['fichiers'][nom] = {'sha256': digest.hexdigest(), 'taille': chemin.stat().st_size}
                for nom, objet in (('configuration.json', configuration), (FICHIER_CHEMINS, correspondances)):
                    contenu = json.dumps(objet, ensure_ascii=False).encode()
                    archive.writestr(nom, contenu)
                    manifeste['fichiers'][nom] = {'sha256': hashlib.sha256(contenu).hexdigest(), 'taille': len(contenu)}
                if _inventaire(data_dir) != avant:
                    raise ErreurResilience('Des fichiers ont changé pendant la sauvegarde ; recommencez après arrêt.')
                manifeste_bytes = json.dumps(manifeste, ensure_ascii=False).encode()
                if len(manifeste_bytes) > 16 * BLOC or sum(
                        f['taille'] for f in manifeste['fichiers'].values()) + len(manifeste_bytes) > MAX_ARCHIVE:
                    raise ErreurResilience('Archive au-delà des limites de restauration (volume ou manifeste).')
                archive.writestr('manifest.json', manifeste_bytes)
            verrou.rollback()
        crypte = travail / 'sauvegarde.cspbackup'
        _chiffrer(zip_path, crypte, password)
        # Publication atomique sans écrasement (création exclusive du lien).
        os.link(crypte, destination)
    return {'ok': True, 'diagnostic': rapport, 'secondes': round(time.monotonic() - debut, 3),
            'fichiers': len(manifeste['fichiers']), 'sha256': _hash(destination),
            'code_modifie': manifeste['code_modifie'],
            'avertissement_code': ('Conservez séparément les sources modifiées ; la révision Git seule ne suffit pas.'
                                  if manifeste['code_modifie'] else None)}


def _extraire_verifie(zip_path, cible):
    with zipfile.ZipFile(zip_path) as archive:
        infos = archive.infolist()
        noms = [i.filename for i in infos]
        if len(noms) != len(set(noms)) or sum(i.file_size for i in infos) > MAX_ARCHIVE:
            raise ErreurResilience('Archive invalide (doublon ou volume excessif).')
        if 'manifest.json' not in noms or archive.getinfo('manifest.json').file_size > 16 * BLOC:
            raise ErreurResilience('Manifeste absent ou trop volumineux.')
        manifeste = json.loads(archive.read('manifest.json'))
        if manifeste.get('format') != 1 or manifeste.get('stockages') != list(REPERTOIRES):
            raise ErreurResilience('Périmètre de sauvegarde inconnu.')
        attendus = manifeste['fichiers']
        if set(noms) != set(attendus) | {'manifest.json'} or not {
                'cspilot.db', 'configuration.json', FICHIER_CHEMINS} <= set(attendus):
            raise ErreurResilience('Archive incomplète ou fichiers non déclarés.')
        for info in infos:
            nom = info.filename
            p = PurePosixPath(nom)
            mode = info.external_attr >> 16
            if (not p.parts or p.is_absolute() or '..' in p.parts or '\\' in nom or ':' in nom
                    or p.as_posix() != nom or info.is_dir() or stat.S_ISLNK(mode)
                    or p.parts[0] not in (*REPERTOIRES, 'manifest.json', 'configuration.json', 'cspilot.db', FICHIER_CHEMINS)):
                raise ErreurResilience('Chemin ou type de fichier interdit dans l’archive.')
            destination = cible.joinpath(*p.parts)
            if not destination.resolve().is_relative_to(cible.resolve()):
                raise ErreurResilience('Chemin hors de la destination.')
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            digest = hashlib.sha256()
            with archive.open(info) as entree, destination.open('xb') as sortie:
                os.chmod(destination, 0o600)
                while bloc := entree.read(BLOC):
                    digest.update(bloc)
                    sortie.write(bloc)
            if nom != 'manifest.json' and (digest.hexdigest() != attendus[nom]['sha256'] or
                                          info.file_size != attendus[nom]['taille']):
                raise ErreurResilience('Empreinte de fichier incorrecte.')
        for dossier in REPERTOIRES:
            (cible / dossier).mkdir(exist_ok=True, mode=0o700)
    return manifeste


def restaurer(archive_path, destination, password, *, nouvelle_cle=None):
    """Authentifier, vérifier, puis publier une installation de données vierge.

    Aucun écrasement, démarrage, migration ni rotation. Le code correspondant
    doit être installé séparément ; son identifiant figure dans le manifeste.
    """
    debut = time.monotonic()
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ErreurResilience('La destination doit être inexistante ; conservez l’installation actuelle.')
    with tempfile.TemporaryDirectory(prefix='.cspilot-restore-', dir=destination.parent) as tmp:
        travail = Path(tmp)
        zip_path = travail / 'sauvegarde.zip'
        _dechiffrer(Path(archive_path), zip_path, password)
        donnees = travail / 'donnees'
        donnees.mkdir(mode=0o700)
        try:
            manifeste = _extraire_verifie(zip_path, donnees)
            config = json.loads((donnees / 'configuration.json').read_text())
            ancienne = config.get('SECRET_KEY')
            with closing(sqlite3.connect(donnees / 'cspilot.db')) as conn:
                verifier_parametres(conn, ancienne)
                if nouvelle_cle is not None:
                    with conn:
                        rechiffrer_parametres(conn, ancienne, nouvelle_cle)
                    config['SECRET_KEY'] = nouvelle_cle
            rapport = diagnostiquer(donnees, config['SECRET_KEY'])
            if not rapport['donnees_valides']:
                raise ErreurResilience('Restauration refusée : données ou références incohérentes.')
            # dotenv, pas un script shell : ne jamais « source » ce fichier.
            from dotenv import set_key
            env = donnees / '.env'
            env.touch(mode=0o600)
            for cle, valeur in config.items():
                if not cle.replace('_', '').isalnum() or not isinstance(valeur, str):
                    raise ErreurResilience('Configuration invalide.')
                set_key(str(env), cle, valeur, quote_mode='always')
            os.chmod(env, 0o600)
            (donnees / 'configuration.json').unlink()
            bilan = {'ok': rapport['ok'], 'diagnostic': rapport, 'rechiffrement': nouvelle_cle is not None,
                     'revision_code': manifeste['revision_code'], 'restaure_le': datetime.now(timezone.utc).isoformat()}
            (donnees / 'restauration-rapport.json').write_text(json.dumps(bilan, ensure_ascii=False, indent=2))
            os.chmod(donnees / 'restauration-rapport.json', 0o600)
            if destination.exists() or destination.is_symlink():
                raise ErreurResilience('La destination existe désormais : restauration annulée.')
            donnees.rename(destination)
        except (zipfile.BadZipFile, KeyError, TypeError, json.JSONDecodeError):
            raise ErreurResilience('Archive ou manifeste invalide.') from None
    bilan['secondes'] = round(time.monotonic() - debut, 3)
    return bilan
