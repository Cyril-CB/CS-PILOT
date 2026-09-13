"""Frontal HTTP réel : formulaires, fichiers, sessions, proxy et maintenance."""
from contextlib import contextmanager
import hashlib
import http.client
import json
import threading
import time
from unittest.mock import Mock

import pytest
from waitress import create_server
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.test import EnvironBuilder

from superviseur import Service
from update_engine import UpdateError
from update_protocol import STATUS_PATH, HEALTH_PATH
from update_worker import WorkerMiddleware


@contextmanager
def serveur(app):
    mapping = {}
    server = create_server(app, host='127.0.0.1', port=0, threads=4, map=mapping,
                           clear_untrusted_proxy_headers=False, asyncore_loop_timeout=0.05)
    stop = threading.Event()
    def tourner():
        while not stop.is_set():
            server.asyncore.loop(timeout=0.02, map=mapping, count=1)
    thread = threading.Thread(target=tourner, daemon=True)
    thread.start()
    try:
        yield server.effective_port
    finally:
        stop.set()
        thread.join(timeout=2)
        server.task_dispatcher.shutdown(timeout=2)
        for channel in list(mapping.values()):
            channel.close()


def demander(port, path='/', method='GET', body=None, headers=None, chunked=False):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    try:
        conn.request(method, path, body=body, headers=headers or {}, encode_chunked=chunked)
        response = conn.getresponse()
        return response.status, response.getheaders(), response.read()
    finally:
        conn.close()


@pytest.fixture
def frontal(tmp_path, monkeypatch):
    monkeypatch.setenv('BEHIND_PROXY', 'true')
    service = Service(tmp_path, tmp_path)
    service.engine = Mock()
    service.engine.snapshot.return_value = {'job': {'phase': 'migration', 'id': 'test-public',
                                                   'raison': 'secret privé'}}
    service.token = 'jeton-prive-fictif'
    def app(environ, start_response):
        data = environ['wsgi.input'].read(int(environ.get('CONTENT_LENGTH') or 0))
        payload = json.dumps({'path': environ['PATH_INFO'], 'uri': environ['REQUEST_URI'],
            'query': environ['QUERY_STRING'], 'body_sha': hashlib.sha256(data).hexdigest(),
            'remote': environ['REMOTE_ADDR'], 'scheme': environ['wsgi.url_scheme'],
            'host': environ.get('HTTP_HOST'), 'cookie': environ.get('HTTP_COOKIE'),
            'csrf': environ.get('HTTP_X_CSRFTOKEN'), 'enleve': environ.get('HTTP_X_ENLEVER'),
            'token': environ.get('HTTP_X_CSPILOT_TOKEN')}).encode()
        start_response('200 OK', [('Content-Type', 'application/json'),
            ('Content-Length', str(len(payload))), ('Set-Cookie', 'session=fictive; HttpOnly; Secure'),
            ('Set-Cookie', 'autre=fictif; SameSite=Lax'), ('Content-Disposition', 'attachment; filename="test.json"')])
        return [payload]
    with serveur(WorkerMiddleware(ProxyFix(app, x_for=1, x_proto=1, x_host=1), service.token)) as prive:
        service.port = prive
        service.ouvrir()
        with serveur(service.application) as public:
            yield service, public, prive


def test_aller_retour_formulaire_fichiers_cookies_et_proxy(frontal):
    service, public, prive = frontal
    contenu = b'contenu-fictif\x00\xff' * 15000
    status, headers, body = demander(public, '/document/%C3%A9t%C3%A9%2Ffiche?nom=a%2Bb',
        'POST', contenu, {'Content-Type': 'application/octet-stream', 'Cookie': 'session=fictive',
         'X-CSRFToken': 'jeton-csrf-fictif', 'X-Forwarded-For': '192.0.2.44',
         'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': 'centre.example',
         'X-Cspilot-Token': 'faux', 'X-Cspilot-Remote': 'adresse-usurpee',
         'Connection': 'X-Enlever', 'X-Enlever': 'secret'})
    assert status == 200
    data = json.loads(body)
    assert data['uri'] == '/document/%C3%A9t%C3%A9%2Ffiche?nom=a%2Bb'
    assert data['body_sha'] == hashlib.sha256(contenu).hexdigest()
    assert data['remote'] == '192.0.2.44' and data['scheme'] == 'https'
    assert data['host'] == 'centre.example' and data['cookie'] == 'session=fictive'
    assert data['csrf'] == 'jeton-csrf-fictif' and data['enleve'] is None
    assert data['token'] is None
    assert len([v for k,v in headers if k.lower() == 'set-cookie']) == 2
    assert dict(headers)['Content-Disposition'] == 'attachment; filename="test.json"'
    assert service.actives == 0


def test_televersement_chunked_et_head(frontal):
    service, public, _ = frontal
    blocs = [b'abc'*1000, b'xyz'*2000]
    status, _, body = demander(public, '/', 'POST', iter(blocs), chunked=True)
    assert status == 200
    assert json.loads(body)['body_sha'] == hashlib.sha256(b''.join(blocs)).hexdigest()
    status, headers, body = demander(public, '/', 'HEAD')
    assert status == 200 and body == b'' and int(dict(headers)['Content-Length']) > 0
    assert service.actives == 0


def test_processus_prive_refuse_les_appels_directs(frontal):
    _, public, prive = frontal
    assert demander(prive)[0] == 404
    assert demander(prive, HEALTH_PATH, headers={'X-Cspilot-Token': 'incorrect'})[0] == 404
    assert demander(public, HEALTH_PATH)[0] == 404


def test_maintenance_independante_du_processus_et_sans_mutation(frontal):
    service, public, prive = frontal
    service.fermer()
    for method in ('GET', 'POST', 'DELETE'):
        status, headers, body = demander(public, '/api/action', method)
        assert status == 503 and dict(headers)['Retry-After'] == '3'
        assert b'CS PILOT' in body
    status, _, body = demander(public, STATUS_PATH)
    assert status == 200
    data = json.loads(body)
    assert not data['disponible'] and data['en_cours']
    assert b'secret' not in body
    assert demander(public, STATUS_PATH, 'POST')[0] == 404


def test_transfert_sans_proxy_ne_change_pas_ip(tmp_path, monkeypatch):
    monkeypatch.delenv('BEHIND_PROXY', raising=False)
    service = Service(tmp_path, tmp_path)
    service.token = 'jeton'
    service.engine = Mock()
    def app(environ, start_response):
        body = json.dumps({'remote': environ['REMOTE_ADDR'],
            'proxy_headers': {k: v for k, v in environ.items()
                if k.startswith('HTTP_X_FORWARDED_')
                or k in ('HTTP_FORWARDED', 'HTTP_X_REAL_IP')}}).encode()
        start_response('200 OK', [('Content-Length', str(len(body)))])
        return [body]
    with serveur(WorkerMiddleware(app, service.token)) as prive:
        service.port = prive
        service.ouvrir()
        with serveur(service.application) as public:
            status, _, body = demander(public, headers={
                'X-Forwarded-For': '192.0.2.12', 'X-Real-IP': '192.0.2.13',
                'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': 'faux.example',
                'X-Forwarded-Port': '443', 'X-Forwarded-Prefix': '/faux',
                'Forwarded': 'for=192.0.2.14;proto=https',
                'X-Cspilot-Remote': '192.0.2.99'})
            assert status == 200
            assert json.loads(body) == {'remote': '127.0.0.1', 'proxy_headers': {}}


@pytest.mark.parametrize('proxy', [None, 'false', 'true'])
@pytest.mark.parametrize('header', ['X-Forwarded-For', 'X-Real-IP'])
def test_ip_journal_connexions_via_frontal(app, db, sample_users, tmp_path,
                                        monkeypatch, proxy, header):
    """Le journal réel ne doit pas prendre une IP fournie par un client direct."""
    if proxy is None:
        monkeypatch.delenv('BEHIND_PROXY', raising=False)
    else:
        monkeypatch.setenv('BEHIND_PROXY', proxy)
    service = Service(tmp_path, tmp_path)
    service.token = 'jeton-fictif-journal'
    application = app
    if proxy == 'true':
        application = ProxyFix(application, x_for=1, x_proto=1, x_host=1)
    with serveur(WorkerMiddleware(application, service.token)) as prive:
        service.port = prive
        service.ouvrir()
        with serveur(service.application) as public:
            for password, statut in (('incorrect', 200), ('Admin1234', 302)):
                assert demander(public, '/login', 'POST',
                    f'login=admin&password={password}',
                    {'Content-Type': 'application/x-www-form-urlencoded',
                     header: '192.0.2.45', 'X-Cspilot-Remote': '192.0.2.99'})[0] == statut
    rows = db.execute(
        'SELECT evenement, adresse_ip FROM journal_acces ORDER BY id'
    ).fetchall()
    adresse = '192.0.2.45' if proxy == 'true' else '127.0.0.1'
    assert [tuple(row) for row in rows] == [
        ('echec_connexion', adresse), ('connexion_reussie', adresse)]


def test_attente_des_requetes_et_annulation_du_drain(tmp_path):
    service = Service(tmp_path, tmp_path)
    service.ouvrir()
    service.actives = 1
    with pytest.raises(UpdateError, match='opérations'):
        service.fermer(timeout=0.01)
    assert service.disponible and service.actives == 1
    termine = threading.Event()
    thread = threading.Thread(target=lambda: (service.fermer(timeout=2), termine.set()))
    thread.start()
    time.sleep(0.03)
    assert not service.disponible and not termine.is_set()
    with service.condition:
        service.actives = 0
        service.condition.notify_all()
    thread.join(timeout=1)
    assert termine.is_set()


def test_iterateur_non_consomme_ne_bloque_pas_maintenance(frontal):
    service, _, _ = frontal
    env = EnvironBuilder('/').get_environ()
    iterator = service.application(env, Mock())
    iterator.close()
    assert service.actives == 0
    service.fermer(timeout=0.01)


@pytest.mark.parametrize('base_invalide', [False, True])
def test_lanceur_reel_garde_http_disponible(tmp_path, base_invalide):
    """Même si app.py refuse le schéma, le processus public répond en maintenance."""
    import os
    from pathlib import Path
    import socket
    import sqlite3
    import subprocess
    import sys
    if base_invalide:
        with sqlite3.connect(tmp_path / 'cspilot.db') as conn:
            conn.execute('CREATE TABLE inconnu(id INTEGER)')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = os.environ.copy()
    for nom in ('CSPILOT_WORKER_TOKEN', 'CSPILOT_UPDATE_DIR', 'CSPILOT_INSTALL_DIR'):
        env.pop(nom, None)
    env.update(CSPILOT_DATA_DIR=str(tmp_path), PORT=str(port), SECRET_KEY='cle-fictive-lanceur')
    root = Path(__file__).resolve().parents[1]
    process = subprocess.Popen([sys.executable, root / 'superviseur.py'], cwd=root,
                               env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        fin = time.monotonic() + 15
        state = {}
        while time.monotonic() < fin:
            assert process.poll() is None
            try:
                status, _, body = demander(port, STATUS_PATH)
                state = json.loads(body)
                if state['disponible'] or state['phase'] == 'intervention':
                    break
            except OSError:
                pass
            time.sleep(0.05)
        if base_invalide:
            assert not state['disponible'] and state['phase'] == 'intervention'
            assert demander(port, '/login')[0] == 503
        else:
            assert state['disponible']
            assert demander(port, '/login')[0] == 302  # Installation neuve : création du premier compte.
            assert demander(port, '/setup')[0] == 200
    finally:
        process.terminate()
        process.wait(timeout=10)
