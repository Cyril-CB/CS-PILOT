"""Installation isolée et reprise durable. Appelé uniquement par le superviseur.

Le journal est écrit AVANT chaque opération sur les données. La publication du
code actif et de la réussite constitue un seul remplacement atomique, effectué
avant de rouvrir les requêtes. Aucun retour arrière après cette publication.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import stat
import subprocess
import sys
import threading
import time
import zipfile

import requests

from stockage_restaure import FICHIER_CHEMINS, REPERTOIRES
from update_protocol import BUSY, PROTOCOL, ecrire_json, lire_json, valider_revision, verrou_exclusif

GITHUB_API = 'https://api.github.com/repos/Cyril-CB/CS-PILOT'
MAX_DOWNLOAD = 512 * 1024 * 1024
MAX_EXTRACTED = 2 * 1024 * 1024 * 1024
DATA_FILES = ('cspilot.db', 'cspilot.db-wal', 'cspilot.db-shm', '.env',
              FICHIER_CHEMINS, 'restauration-rapport.json')
PROTECTED = set(REPERTOIRES) | set(DATA_FILES) | {
    '.git', '.cspilot-updates', 'backups', 'logs', 'venv', '.venv', '__pycache__'}


class UpdateError(Exception):
    """Erreur sans donnée métier, à traduire en consigne dans l'interface."""


def extraire_sources(archive, destination):
    """ZIP borné, une racine GitHub, aucun lien, traversée ou fichier de données."""
    destination = Path(destination)
    destination.mkdir(mode=0o700)
    with zipfile.ZipFile(archive) as zf:
        infos = zf.infolist()
        if len(infos) > 50000 or sum(i.file_size for i in infos) > MAX_EXTRACTED:
            raise UpdateError('Archive trop volumineuse.')
        racine = None
        vus = set()
        for info in infos:
            path = PurePosixPath(info.filename)
            mode = info.external_attr >> 16
            if (not path.parts or path.is_absolute() or '..' in path.parts
                    or '\\' in info.filename or ':' in info.filename
                    or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                raise UpdateError('Chemin d’archive invalide.')
            racine = racine or path.parts[0]
            if path.parts[0] != racine:
                raise UpdateError('Plusieurs racines dans l’archive.')
            parts = path.parts[1:]
            if not parts:
                if not info.is_dir():
                    raise UpdateError('Racine d’archive invalide.')
                continue
            if any(p in PROTECTED for p in parts) or parts[-1].endswith(('.db', '.pyc')):
                continue
            relatif = '/'.join(parts).casefold()
            if relatif in vus:
                raise UpdateError('Chemin dupliqué dans l’archive.')
            vus.add(relatif)
            cible = destination.joinpath(*parts)
            if info.is_dir():
                cible.mkdir(parents=True, exist_ok=True)
            else:
                cible.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as source, cible.open('xb') as sortie:
                    shutil.copyfileobj(source, sortie, 65536)
    for nom in ('app.py', 'resilience_cli.py', 'requirements.txt', 'superviseur.py'):
        if not (destination / nom).is_file():
            raise UpdateError('Version incomplète.')
    contrat = lire_json(destination / 'update-protocol.json')
    if contrat != {'protocol': PROTOCOL, 'data_paths': list(REPERTOIRES)}:
        raise UpdateError('Cette version nécessite une adaptation du service par le support.')


def telecharger_sources(sha, archive):
    """L'URL est construite exclusivement à partir du SHA validé côté serveur."""
    valider_revision(sha)
    digest = hashlib.sha256()
    taille = 0
    debut = time.monotonic()
    with requests.get(f'{GITHUB_API}/zipball/{sha}', stream=True,
                      timeout=(15, 60)) as response:
        response.raise_for_status()
        with Path(archive).open('xb') as sortie:
            for bloc in response.iter_content(65536):
                taille += len(bloc)
                if taille > MAX_DOWNLOAD or time.monotonic() - debut > 900:
                    raise UpdateError('Téléchargement trop volumineux.')
                digest.update(bloc)
                sortie.write(bloc)
    return digest.hexdigest()


def python_venv(dossier):
    return Path(dossier) / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def enlever(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


class UpdateEngine:
    def __init__(self, install_dir, data_dir, service, python=None):
        self.install = Path(install_dir).resolve()
        self.data = Path(data_dir).resolve()
        self.base = self.data / '.cspilot-updates'
        if self.base.is_symlink():
            raise UpdateError('Le répertoire de mise à jour ne peut pas être un lien.')
        self.base.mkdir(mode=0o700, exist_ok=True)
        os.chmod(self.base, 0o700)
        self.releases = self.base / 'releases'
        self.releases.mkdir(mode=0o700, exist_ok=True)
        self.service = service
        self.python = str(python or os.environ.get('CSPILOT_PYTHON_ORIGINE') or sys.executable)
        self.lock = threading.RLock()
        self.state_path = self.base / 'etat.json'
        self.state = lire_json(self.state_path, {'active': None, 'job': None})
        self.command = None

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.state))

    def sauver(self):
        ecrire_json(self.state_path, self.state)

    def phase(self, phase, **details):
        with self.lock:
            self.state['job'].update(phase=phase, **details)
            self.sauver()

    def release_dir(self, identifiant):
        if not isinstance(identifiant, str) or not re.fullmatch('[0-9a-f]{32}', identifiant):
            raise UpdateError('Référence de mise à jour invalide.')
        dossier = self.releases / identifiant
        if dossier.is_symlink():
            raise UpdateError('Répertoire de version invalide.')
        return dossier

    def runtime(self, active):
        if active is None:
            return self.install, self.python
        valider_revision(active['sha'])
        dossier = self.release_dir(active['id'])
        return dossier / 'app', str(python_venv(dossier / 'venv'))

    def executer(self, args, code, log, timeout=900):
        """Le même environnement effectif que l'application, sans shell ni nouvelle clé."""
        env = os.environ.copy()
        env['CSPILOT_DATA_DIR'] = str(self.data)
        env['CSPILOT_UPDATE_DIR'] = str(self.base)
        env.pop('CSPILOT_WORKER_TOKEN', None)
        commande = [self.python, str(Path(__file__).with_name('update_task.py'))]
        if any(Path(str(a)).name == 'resilience_cli.py' for a in args):
            commande.append('--donnees')
        commande.extend(str(a) for a in args)
        with log.open('ab') as sortie:
            os.chmod(log, 0o600)
            self.command = subprocess.Popen(commande, cwd=code, env=env, stdin=subprocess.PIPE,
                                            stdout=sortie, stderr=subprocess.STDOUT,
                                            start_new_session=os.name == 'posix')
            try:
                if self.command.wait(timeout=timeout):
                    raise UpdateError('Une commande de préparation ou de migration a échoué.')
            except subprocess.TimeoutExpired:
                self.interrompre_commande()
                raise UpdateError('Délai de mise à jour dépassé.') from None
            finally:
                self.command.stdin.close()
                self.command = None

    def interrompre_commande(self):
        commande = self.command
        if commande is not None and commande.poll() is None:
            if os.name == 'posix':
                import signal
                os.killpg(commande.pid, signal.SIGKILL)
            else:
                subprocess.run(['taskkill', '/PID', str(commande.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            commande.wait()

    def espace_disponible(self):
        # Sauvegarde ZIP, enveloppe, restauration vérifiée et copie de secours.
        volume = 0
        for nom in (*REPERTOIRES, *DATA_FILES):
            path = self.data / nom
            if path.is_symlink():
                raise UpdateError('Stockage lié : une vérification par le support est nécessaire.')
            if path.is_file():
                volume += path.stat().st_size
            elif path.is_dir():
                for racine, dirs, fichiers in os.walk(path, followlinks=False):
                    for fichier in (*dirs, *fichiers):
                        entree = Path(racine) / fichier
                        if entree.is_symlink():
                            raise UpdateError('Stockage lié : vérification nécessaire.')
                        if entree.is_file():
                            volume += entree.stat().st_size
        if shutil.disk_usage(self.base).free < 6 * volume + 3 * 1024**3:
            raise UpdateError('Espace disque insuffisant pour préparer la mise à jour et sa restauration.')

    def preparer(self, job):
        self.espace_disponible()
        dossier = self.release_dir(job['id'])
        dossier.mkdir(mode=0o700)
        archive = dossier / 'sources.zip'
        digest = telecharger_sources(job['sha'], archive)
        code = dossier / 'app'
        extraire_sources(archive, code)
        (code / 'REVISION-SOURCES.txt').write_text(job['sha'] + '\n', encoding='ascii')
        log = dossier / 'operations.log'
        self.phase('preparation', archive_sha256=digest)
        self.executer([self.python, '-m', 'venv', dossier / 'venv'], self.install, log)
        python = python_venv(dossier / 'venv')
        self.executer([python, '-m', 'pip', 'install', '--disable-pip-version-check',
                       '-r', code / 'requirements.txt'], code, log)
        self.executer([python, '-m', 'pip', 'check'], code, log)
        self.executer([python, '-m', 'compileall', '-q', code], code, log)
        self.espace_disponible()

    def sauvegarder(self, job):
        dossier = self.release_dir(job['id'])
        phrase = dossier / 'phrase-secrete'
        with phrase.open('x', encoding='utf-8') as sortie:
            os.chmod(phrase, 0o600)
            sortie.write(secrets.token_urlsafe(48))
        code, python = self.runtime(job['previous'])
        self.executer([python, code / 'resilience_cli.py', 'sauvegarder',
                       '--data-dir', self.data, '--archive', dossier / 'avant.cspbackup',
                       '--phrase-fichier', phrase, '--application-arretee'],
                      code, dossier / 'operations.log', timeout=3600)

    def migrer(self, job):
        code, python = self.runtime(job)
        dossier = self.release_dir(job['id'])
        self.executer([python, code / 'resilience_cli.py', 'migrer', '--data-dir', self.data,
                       '--application-arretee'], code, dossier / 'operations.log', timeout=3600)

    def restaurer(self, job):
        """Rejouable après coupure : archive immuable, copie des données de l'échec.

        Ne remplace jamais DATA_DIR lui-même : il peut aussi contenir le dépôt,
        le superviseur, les environnements et les sauvegardes de l'utilisateur.
        """
        dossier = self.release_dir(job['id'])
        copie = dossier / 'restauration'
        enlever(copie)
        code, python = self.runtime(job['previous'])
        self.executer([python, code / 'resilience_cli.py', 'restaurer',
                       '--archive', dossier / 'avant.cspbackup', '--destination', copie,
                       '--phrase-fichier', dossier / 'phrase-secrete'],
                      code, dossier / 'operations.log', timeout=3600)
        quarantaine = dossier / 'donnees-echec'
        quarantaine.mkdir(mode=0o700, exist_ok=True)
        with verrou_exclusif(self.base / 'worker.lock'):
            for nom in (*REPERTOIRES, *DATA_FILES):
                actuel, ancien, restaure = self.data / nom, quarantaine / nom, copie / nom
                if actuel.is_symlink():
                    raise UpdateError('Restauration arrêtée : stockage devenu un lien.')
                if actuel.exists():
                    if not ancien.exists():
                        actuel.rename(ancien)
                    else:
                        # Reprise d'une copie déjà partiellement restaurée, jamais ouverte aux utilisateurs.
                        enlever(actuel)
                if restaure.exists():
                    restaure.rename(actuel)
        enlever(copie)

    def terminer(self, active, phase):
        with self.lock:
            publication = self.snapshot()
            publication['active'] = active
            publication['job']['phase'] = phase
            ecrire_json(self.state_path, publication)
            self.state = publication
        self.service.ouvrir()
        (self.base / 'demande.json').unlink(missing_ok=True)
        # La rétention concerne uniquement nos versions réussies. Une anomalie
        # de nettoyage ne doit jamais transformer une publication en rollback.
        if phase == 'terminee':
            try:
                dossier = self.release_dir(active['id'])
                ecrire_json(dossier / 'resultat.json', {'id': active['id'], 'termine_le': time.time()})
                self.nettoyer_versions()
            except (OSError, ValueError):
                pass

    def nettoyer_versions(self):
        protegees = {r['id'] for r in (self.state.get('active'), self.state['job'].get('previous')) if r}
        reussies = []
        for dossier in self.releases.iterdir():
            if dossier.is_symlink() or not re.fullmatch('[0-9a-f]{32}', dossier.name):
                continue
            resultat = lire_json(dossier / 'resultat.json')
            if (isinstance(resultat, dict) and resultat.get('id') == dossier.name
                    and isinstance(resultat.get('termine_le'), (int, float))
                    and resultat['termine_le'] >= 0):
                reussies.append((resultat['termine_le'], dossier))
        reussies.sort(key=lambda r: r[0], reverse=True)
        protegees.update(d.name for _, d in reussies[:2])
        for _, dossier in reussies:
            if dossier.name not in protegees:
                enlever(dossier)

    def recuperer(self):
        """Au démarrage, aucun processus applicatif n'a encore été lancé."""
        job = self.state.get('job')
        if not job or job['phase'] not in BUSY:
            if job and job['phase'] == 'intervention':
                return False
            demande = lire_json(self.base / 'demande.json')
            if demande and job and demande.get('id') == job.get('id'):
                (self.base / 'demande.json').unlink(missing_ok=True)
            return True
        try:
            if job['phase'] in {'migration', 'validation', 'restauration'}:
                self.phase('restauration')
                self.restaurer(job)
                finale = 'retablie'
            else:
                finale = 'annulee'
            self.service.demarrer(*self.runtime(job['previous']))
            self.terminer(job['previous'], finale)
            return False  # Le processus précédent est déjà démarré.
        except Exception:
            self.service.arreter()
            self.phase('intervention')
            return False

    def traiter(self, demande):
        valider_revision(demande['sha'])
        self.release_dir(demande['id'])
        job = {**demande, 'previous': self.state['active'], 'phase': 'preparation'}
        with self.lock:
            self.state['job'] = job
            self.sauver()
        arrete = False
        try:
            self.preparer(job)
            self.phase('maintenance')
            self.service.fermer()  # Refus de nouvelles requêtes et attente des réponses en cours.
            self.service.arreter()
            arrete = True
            self.phase('sauvegarde')
            self.sauvegarder(job)
            self.phase('migration')  # Avant toute écriture du nouveau code.
            self.migrer(job)
            self.phase('validation')
            self.service.demarrer(*self.runtime(job))
            self.terminer({'id': job['id'], 'sha': job['sha']}, 'terminee')
        except Exception as erreur:
            if self.service.stop.is_set():
                return  # Reprise au prochain démarrage, sans restauration pendant l'arrêt.
            if self.state['job']['phase'] == 'terminee':
                # La publication est le point de non-retour : des écritures ont pu être acceptées.
                self.service.arreter()
                self.phase('intervention')
                return
            # Le navigateur ne reçoit ni sortie de commande, ni chemin, ni exception métier.
            phase_echec = job['phase']
            raison = str(erreur) if isinstance(erreur, UpdateError) else 'Échec technique ; consulter le journal privé.'
            self.phase(phase_echec, raison=raison, etape_echec=phase_echec)
            try:
                if arrete:
                    self.service.arreter()
                    if phase_echec in {'migration', 'validation', 'restauration'}:
                        self.phase('restauration')
                        self.restaurer(job)
                        finale = 'retablie'
                    else:
                        finale = 'annulee'
                    self.service.demarrer(*self.runtime(job['previous']))
                else:
                    finale = 'annulee'
                self.terminer(job['previous'], finale)
            except Exception:
                self.service.arreter()
                self.phase('intervention')
