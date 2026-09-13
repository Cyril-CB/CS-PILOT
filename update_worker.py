"""Accès au processus privé : seul le superviseur peut l'appeler."""
import hmac
import json
import os
from pathlib import Path
import sys
import threading

from update_protocol import HEALTH_PATH, verrou_exclusif


def surveiller_superviseur():
    verrou = verrou_exclusif(Path(os.environ['CSPILOT_UPDATE_DIR']) / 'worker.lock')

    def surveiller():
        while os.read(sys.stdin.fileno(), 4096):
            pass
        os._exit(1)

    threading.Thread(target=surveiller, daemon=True).start()
    return verrou


class WorkerMiddleware:
    def __init__(self, application, token):
        self.application = application
        self.token = token

    def __call__(self, environ, start_response):
        fourni = environ.pop('HTTP_X_CSPILOT_TOKEN', '')
        if not hmac.compare_digest(fourni.encode('utf-8'), self.token.encode('utf-8')):
            start_response('404 Not Found', [('Content-Length', '0')])
            return [b'']
        if environ.get('PATH_INFO') == HEALTH_PATH:
            body = json.dumps({'ok': True, 'pid': os.getpid()}).encode()
            start_response('200 OK', [('Content-Type', 'application/json'),
                                     ('Content-Length', str(len(body))), ('Cache-Control', 'no-store')])
            return [body]
        # Rétablir le contexte de la connexion publique AVANT le ProxyFix existant.
        environ['REMOTE_ADDR'] = environ.pop('HTTP_X_CSPILOT_REMOTE', '127.0.0.1')
        environ['wsgi.url_scheme'] = environ.pop('HTTP_X_CSPILOT_SCHEME', 'http')
        return self.application(environ, start_response)
