"""Contrat local entre le superviseur et l'application ; aucune donnée métier."""
import json
import os
from pathlib import Path
import re
import secrets
import tempfile

PROTOCOL = 1
STATUS_PATH = '/__cspilot__/mise-a-jour'
HEALTH_PATH = '/__cspilot__/sante'
BUSY = {'preparation', 'maintenance', 'sauvegarde', 'migration', 'validation', 'restauration'}
MESSAGES = {
    'disponible': 'L’application est disponible.',
    'preparation': 'Préparation de la nouvelle version. Vous pouvez encore travailler.',
    'maintenance': 'Mise en maintenance : les opérations en cours se terminent.',
    'sauvegarde': 'Sauvegarde automatique de la base, des documents et de la configuration.',
    'migration': 'Mise à jour des données.',
    'validation': 'Redémarrage et vérification de la nouvelle version.',
    'restauration': 'La mise à jour a échoué. Rétablissement de la version précédente.',
    'terminee': 'Mise à jour terminée. L’application a été vérifiée et est disponible.',
    'annulee': 'Mise à jour annulée. La version précédente reste disponible. Vous pouvez réessayer.',
    'retablie': 'Mise à jour annulée. La version précédente et ses données ont été rétablies.',
    'intervention': 'L’application reste en maintenance. Contactez votre support avec la référence affichée.',
}


def lire_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default


def verrou_exclusif(path):
    """Verrou libéré par le noyau, y compris après une coupure ; garder le handle ouvert."""
    stream = Path(path).open('a+b')
    os.chmod(path, 0o600)
    try:
        if os.name == 'nt':
            import msvcrt
            if stream.tell() == 0:
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return stream
    except OSError:
        stream.close()
        raise


def ecrire_json(path, value):
    """Publication atomique et privée, y compris en cas d'arrêt du processus."""
    path = Path(path)
    fd, temporaire = tempfile.mkstemp(prefix='.etat-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporaire, path)
        if os.name == 'posix':
            fd_dir = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd_dir)
            finally:
                os.close(fd_dir)
    finally:
        if os.path.exists(temporaire):
            os.unlink(temporaire)


def valider_revision(sha):
    if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('Révision invalide.')
    return sha


def demander_mise_a_jour(state_dir, sha):
    """Une seule demande durable. Le superviseur reste propriétaire de son journal."""
    sha = valider_revision(sha)
    base = Path(state_dir)
    demande = {'id': secrets.token_hex(16), 'sha': sha}
    temporaire = base / ('.demande-' + demande['id'])
    ecrire_json(temporaire, demande)
    try:
        # Contrairement à replace(), link() refuse d'écraser une demande en cours.
        os.link(temporaire, base / 'demande.json')
    finally:
        temporaire.unlink()
    return demande['id']


def etat_public(state, disponible):
    job = (state or {}).get('job') or {}
    phase = job.get('phase', 'disponible' if disponible else 'validation')
    if phase not in MESSAGES:
        phase = 'intervention'
    return {'phase': phase, 'message': MESSAGES[phase], 'disponible': disponible,
            'en_cours': phase in BUSY, 'reference': job.get('id', '')}
