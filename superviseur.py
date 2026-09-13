"""Point d'entrée stable : Waitress reste accessible pendant les migrations.

Un unique processus Flask privé possède les données. Le frontal ne charge ni
Flask, ni la base, ni les dépendances de la version candidate. Voir
docs/mises-a-jour.md pour le contrat de déploiement et les limites.
"""
import http.client
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import quote_from_bytes

from dotenv import load_dotenv
from waitress import create_server

from update_engine import UpdateEngine, UpdateError
from update_protocol import BUSY, HEALTH_PATH, STATUS_PATH, etat_public, lire_json, verrou_exclusif

HOP_HEADERS = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
               'te', 'trailer', 'transfer-encoding', 'upgrade', 'proxy-connection'}
MAINTENANCE_HTML = '''<!doctype html><html lang="fr"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CS PILOT — Maintenance</title><style>
body{font:1.1rem system-ui,sans-serif;max-width:38rem;margin:10vh auto;padding:1.5rem;color:#19334b}
h1{font-size:1.7rem}a{color:#155b9e}p{line-height:1.6}</style>
<h1>CS PILOT se met à jour</h1><p id="etat" role="status" aria-live="polite">
L’application est temporairement en maintenance. Vos données sont conservées.</p>
<p id="reference"></p><p>Cette page se rafraîchit automatiquement. Vous pouvez fermer cet onglet.</p>
<script>async function suivre(){try{let r=await fetch('/__cspilot__/mise-a-jour',{cache:'no-store'});
if(r.ok){let s=await r.json();document.getElementById('etat').textContent=s.message;
document.getElementById('reference').textContent=s.reference?'Référence : '+s.reference:'';
if(s.disponible){location.replace('/');return;}}}catch(e){}setTimeout(suivre,2500);}suivre();</script>
<noscript><p><a href="/">Réessayer d’ouvrir l’application</a></p></noscript></html>'''


def repondre(start_response, status, body, content_type='text/html; charset=utf-8', head=False):
    if isinstance(body, str):
        body = body.encode('utf-8')
    headers = [('Content-Type', content_type), ('Content-Length', str(len(body))),
               ('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff')]
    if status.startswith('503'):
        headers.append(('Retry-After', '3'))
    start_response(status, headers)
    return [] if head else [body]


class Service:
    def __init__(self, data_dir, install_dir):
        self.data = Path(data_dir)
        self.install = Path(install_dir)
        self.behind_proxy = os.environ.get('BEHIND_PROXY', '').lower() in ('1', 'true', 'yes')
        self.condition = threading.Condition()
        self.disponible = False
        self.actives = 0
        self.process = None
        self.port = None
        self.token = None
        self.engine = None
        self.stop = threading.Event()

    def ouvrir(self):
        with self.condition:
            self.disponible = True

    def fermer(self, timeout=120):
        with self.condition:
            self.disponible = False
            if not self.condition.wait_for(lambda: self.actives == 0, timeout):
                # L'ancien processus continue ; aucune sauvegarde/migration n'a commencé.
                self.disponible = True
                raise UpdateError('Des opérations sont encore en cours. Réessayez dans quelques minutes.')

    def arreter(self):
        with self.condition:
            self.disponible = False
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            if self.process.stdin:
                self.process.stdin.close()
            self.process = None

    def attendre_arret_precedent(self, timeout=15):
        fin = time.monotonic() + timeout
        while not self.stop.is_set():
            try:
                verrou = verrou_exclusif(self.engine.base / 'worker.lock')
                verrou.close()
                return
            except OSError:
                if time.monotonic() >= fin:
                    raise UpdateError('Un ancien processus utilise encore les données.') from None
                self.stop.wait(0.1)
        raise UpdateError('Service arrêté.')

    def demarrer(self, code, python, timeout=90):
        if self.process is not None:
            raise UpdateError('Un processus applicatif est déjà présent.')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        self.token = secrets.token_urlsafe(48)
        env = os.environ.copy()
        env.update(CSPILOT_DATA_DIR=str(self.data), CSPILOT_INSTALL_DIR=str(self.install),
                   CSPILOT_WORKER_PORT=str(self.port), CSPILOT_WORKER_TOKEN=self.token,
                   CSPILOT_UPDATE_DIR=str(self.engine.base), CSPILOT_SUPERVISED_STDIN='1', FLASK_DEBUG='0')
        # La sortie applicative conserve sa journalisation habituelle ; aucun secret en argument.
        self.process = subprocess.Popen([str(python), str(Path(code) / 'app.py')],
                                        cwd=code, env=env, stdin=subprocess.PIPE)
        fin = time.monotonic() + timeout
        while time.monotonic() < fin and not self.stop.is_set():
            if self.process.poll() is not None:
                break
            conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=2)
            try:
                headers = {'X-Cspilot-Token': self.token, 'Host': 'localhost'}
                conn.request('GET', HEALTH_PATH, headers=headers)
                response = conn.getresponse()
                if response.status == 200 and json.loads(response.read(4096)) == {'ok': True, 'pid': self.process.pid}:
                    conn.close()
                    conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
                    conn.request('GET', '/login', headers=headers)
                    response = conn.getresponse()
                    response.read()
                    if 200 <= response.status < 400:
                        return
                    break
            except (OSError, http.client.HTTPException, ValueError):
                pass
            finally:
                conn.close()
            self.stop.wait(0.2)
        self.arreter()
        raise UpdateError('La nouvelle version n’a pas réussi son contrôle de démarrage.')

    def application(self, environ, start_response):
        path = environ.get('PATH_INFO', '')
        head = environ['REQUEST_METHOD'] == 'HEAD'
        if path == STATUS_PATH and environ['REQUEST_METHOD'] in ('GET', 'HEAD'):
            return repondre(start_response, '200 OK', json.dumps(
                etat_public(self.engine.snapshot(), self.disponible), ensure_ascii=False),
                'application/json; charset=utf-8', head)
        if path.startswith('/__cspilot__/'):
            return repondre(start_response, '404 Not Found', '', head=head)
        # La réponse reste comptée jusqu'à consommation/fermeture de l'itérateur WSGI.
        return self.transmettre(environ, start_response)

    def transmettre(self, environ, start_response):
        with self.condition:
            disponible = self.disponible
            if disponible:
                self.actives += 1
        if not disponible:
            yield from repondre(start_response, '503 Service Unavailable', MAINTENANCE_HTML,
                                head=environ['REQUEST_METHOD'] == 'HEAD')
            return
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=600)
        try:
            chemin = (environ.get('SCRIPT_NAME', '') + environ.get('PATH_INFO', '')).encode('latin-1')
            cible = quote_from_bytes(chemin, safe="/!$&'()*+,;=:@~")
            if environ.get('QUERY_STRING'):
                cible += '?' + environ['QUERY_STRING']
            original = environ.get('REQUEST_URI', '')
            if original.startswith('/') and not original.startswith('//'):
                cible = original
            interdits = HOP_HEADERS | {v.strip().lower() for v in environ.get('HTTP_CONNECTION', '').split(',')}
            conn.putrequest(environ['REQUEST_METHOD'], cible, skip_host=True, skip_accept_encoding=True)
            for name, value in environ.items():
                if not name.startswith('HTTP_'):
                    continue
                header = name[5:].replace('_', '-')
                if header.lower() in interdits or header.lower().startswith('x-cspilot-'):
                    continue
                # En accès direct, ces valeurs viennent du client. Les retirer
                # aussi pour les helpers d'audit qui lisent X-Real-IP sans ProxyFix.
                if not self.behind_proxy and (header.lower().startswith('x-forwarded-')
                        or header.lower() in ('forwarded', 'x-real-ip')):
                    continue
                conn.putheader(header, value)
            if environ.get('CONTENT_TYPE'):
                conn.putheader('Content-Type', environ['CONTENT_TYPE'])
            longueur = int(environ.get('CONTENT_LENGTH') or 0)
            if longueur < 0:
                raise ValueError('Longueur invalide')
            if environ.get('CONTENT_LENGTH') or longueur:
                conn.putheader('Content-Length', str(longueur))
            conn.putheader('X-Cspilot-Token', self.token)
            conn.putheader('X-Cspilot-Remote', environ.get('REMOTE_ADDR', ''))
            conn.putheader('X-Cspilot-Scheme', environ.get('wsgi.url_scheme', 'http'))
            conn.putheader('Connection', 'close')
            conn.endheaders()
            while longueur:
                bloc = environ['wsgi.input'].read(min(longueur, 65536))
                if not bloc:
                    raise OSError('Corps de requête incomplet')
                conn.send(bloc)
                longueur -= len(bloc)
            response = conn.getresponse()
            interdits = HOP_HEADERS | {v.strip().lower() for v in (response.getheader('Connection') or '').split(',')}
            # Liste, et non dictionnaire : conserver chaque Set-Cookie, ainsi que les téléchargements.
            headers = [(k, v) for k, v in response.getheaders() if k.lower() not in interdits]
            start_response(f'{response.status} {response.reason}', headers)
            while bloc := response.read(65536):
                yield bloc
        except (OSError, ValueError, http.client.HTTPException):
            if 'response' not in locals():
                yield from repondre(start_response, '503 Service Unavailable', MAINTENANCE_HTML,
                                    head=environ['REQUEST_METHOD'] == 'HEAD')
            else:
                # L'en-tête est déjà envoyé : interrompre le flux plutôt que fabriquer une réussite.
                raise
        finally:
            conn.close()
            with self.condition:
                self.actives -= 1
                self.condition.notify_all()

    def travailler(self):
        try:
            self.attendre_arret_precedent()
            if self.engine.recuperer():
                self.demarrer(*self.engine.runtime(self.engine.state['active']))
                self.ouvrir()
        except Exception:
            self.arreter()
            with self.engine.lock:
                job = self.engine.state.get('job') or {'id': secrets.token_hex(16)}
                job['phase'] = 'intervention'
                self.engine.state['job'] = job
                self.engine.sauver()
        while not self.stop.wait(0.5):
            if self.disponible and self.process and self.process.poll() is not None:
                self.arreter()
                with self.engine.lock:
                    self.engine.state['job'] = {'phase': 'intervention', 'id': secrets.token_hex(16)}
                    self.engine.sauver()
            if not self.disponible:
                continue
            demande = lire_json(self.engine.base / 'demande.json')
            if demande:
                self.engine.traiter(demande)


def main():
    install = Path(os.environ.get('CSPILOT_INSTALL_DIR', Path(__file__).resolve().parent)).resolve()
    data = Path(os.environ.get('CSPILOT_DATA_DIR', install)).resolve()
    load_dotenv(data / '.env')
    service = Service(data, install)
    engine = UpdateEngine(install, data, service)
    service.engine = engine
    # Un redémarrage ultérieur reprend aussi le code/dépendances du contrôleur
    # actif. Une reprise interrompue reste confiée au contrôleur d'origine.
    phase = (engine.state.get('job') or {}).get('phase')
    if engine.state.get('active') and phase not in BUSY | {'intervention'}:
        code, python = engine.runtime(engine.state['active'])
        if code.resolve() != Path(__file__).resolve().parent:
            env = os.environ.copy()
            env.update(CSPILOT_INSTALL_DIR=str(install), CSPILOT_DATA_DIR=str(data),
                       CSPILOT_PYTHON_ORIGINE=engine.python)
            os.execve(python, [python, str(code / 'superviseur.py')], env)
    # Un verrou de fichier détenu pour toute la vie du service interdit deux superviseurs,
    # même avec des ports différents. Le noyau le libère aussi après une coupure.
    verrou = verrou_exclusif(engine.base / 'service.lock')
    port = int(os.environ.get('PORT', '5000'))
    try:
        max_mo = int(os.environ.get('MAX_UPLOAD_MO', '256'))
    except ValueError:
        max_mo = 256
    server = create_server(service.application, host='0.0.0.0', port=port, threads=8,
                           max_request_body_size=(max_mo if max_mo > 0 else 256) * 1024**2,
                           clear_untrusted_proxy_headers=not service.behind_proxy)

    def interrompre(signum, frame):
        service.stop.set()
        # Ne pas tenter une restauration pendant l'arrêt du service : le journal guidera la reprise.
        engine.interrompre_commande()
        service.arreter()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, interrompre)
    signal.signal(signal.SIGINT, interrompre)
    thread = threading.Thread(target=service.travailler, daemon=True)
    thread.start()
    try:
        server.run()
    finally:
        service.stop.set()
        service.arreter()
        server.close()
        verrou.close()


if __name__ == '__main__':
    main()
