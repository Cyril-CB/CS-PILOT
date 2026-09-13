"""Mise à jour pilotée par un directeur/comptable ; exécution hors de Flask."""
import os
from pathlib import Path
import time

import requests
from flask import Blueprint, render_template, session, flash, redirect, url_for, jsonify

import app_version
from database import get_db
from sessions_securite import verifier_action
from update_engine import GITHUB_API
from update_protocol import demander_mise_a_jour, lire_json, valider_revision, STATUS_PATH
from utils import login_required

mise_a_jour_bp = Blueprint('mise_a_jour_bp', __name__)


def _check_admin():
    return session.get('profil') in ('directeur', 'comptable')


def _state_dir():
    if os.environ.get('CSPILOT_WORKER_TOKEN') and os.environ.get('CSPILOT_UPDATE_DIR'):
        return Path(os.environ['CSPILOT_UPDATE_DIR'])
    return None


def _etat():
    base = _state_dir()
    return lire_json(base / 'etat.json', {}) if base else {}


@mise_a_jour_bp.route('/mise-a-jour')
@login_required
def mise_a_jour():
    if not _check_admin():
        flash('Acces non autorise', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))
    return render_template('mise_a_jour.html', current_version=app_version.get_app_version(),
                           automatique=bool(_state_dir()), status_path=STATUS_PATH)


@mise_a_jour_bp.route('/api/mise-a-jour/verifier', methods=['POST'])
@login_required
def verifier_mise_a_jour():
    if not _check_admin():
        return jsonify(error='Acces non autorise'), 403
    try:
        response = requests.get(f'{GITHUB_API}/commits/main',
                                headers={'Accept': 'application/vnd.github+json'}, timeout=(5, 15))
        response.raise_for_status()
        commit = response.json()
        sha = valider_revision(commit['sha'])
        note = commit['commit']['message'].split('\n', 1)[0][:300]
        date = commit['commit']['committer']['date']
    except (requests.RequestException, ValueError, KeyError, TypeError):
        session.pop('mise_a_jour_cible', None)
        return jsonify(error='Impossible de vérifier les mises à jour. Réessayez dans quelques minutes.'), 502
    session['mise_a_jour_cible'] = {'sha': sha, 'verifie_le': time.time()}
    active = _etat().get('active') or {}
    return jsonify(success=True, revision=sha[:12], notes=note, published_at=date,
                   disponible=sha != active.get('sha'), automatique=bool(_state_dir()),
                   html_url=f'https://github.com/Cyril-CB/CS-PILOT/commit/{sha}')


@mise_a_jour_bp.route('/api/mise-a-jour/etat')
@login_required
def etat_mise_a_jour():
    if not _check_admin():
        return jsonify(error='Acces non autorise'), 403
    state = _etat()
    job = state.get('job') or {}
    active = state.get('active') or {}
    return jsonify(automatique=bool(_state_dir()), revision=active.get('sha', '')[:12],
                   phase=job.get('phase'), reference=job.get('id'), raison=job.get('raison'),
                   etape_echec=job.get('etape_echec'))


@mise_a_jour_bp.route('/api/mise-a-jour/lancer', methods=['POST'])
@login_required
def lancer_mise_a_jour():
    conn = get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        refus = verifier_action(conn)
        if refus:
            return refus
        if not _check_admin():
            return jsonify(error='Acces non autorise'), 403
        base = _state_dir()
        if base is None:
            return jsonify(error='La mise à jour automatique nécessite le lancement supervisé. '
                                 'Votre support doit activer ce mode une seule fois.'), 503
        cible = session.get('mise_a_jour_cible') or {}
        if time.time() - cible.get('verifie_le', 0) > 1800:
            return jsonify(error='Vérifiez à nouveau les mises à jour avant de lancer l’installation.'), 409
        try:
            sha = valider_revision(cible.get('sha'))
        except ValueError:
            return jsonify(error='Vérifiez d’abord les mises à jour.'), 409
        if (_etat().get('active') or {}).get('sha') == sha:
            return jsonify(error='Cette version est déjà installée.'), 409
        try:
            reference = demander_mise_a_jour(base, sha)
        except FileExistsError:
            return jsonify(error='Une mise à jour est déjà en cours. Consultez son avancement.'), 409
        except OSError:
            return jsonify(error='Impossible de préparer la mise à jour. Faites vérifier l’espace disque et les droits par votre support.'), 503
        return jsonify(success=True, reference=reference,
                       message='Mise à jour prise en charge. Vous pouvez fermer cet onglet.'), 202
    finally:
        conn.rollback()
        conn.close()
