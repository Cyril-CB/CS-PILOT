"""Page assistant autonome : lecture métier et mémoire personnelle explicite."""
from functools import wraps
import uuid

from flask import Blueprint, jsonify, render_template, request, session

from assistant_stockage import (AssistantErreur, compte, transaction, lire_etat,
                               sauver_memoire, oublier)
from assistant_agent import repondre
from blueprints.api_keys import get_available_models
from extensions import limiter
from utils import login_required

assistant_bp = Blueprint('assistant_bp', __name__)


def assistant_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        try:
            with transaction() as conn:
                compte(conn)
            return fn(*args, **kwargs)
        except AssistantErreur as exc:
            if request.path.startswith('/api/'):
                return jsonify({'error': exc.message}), exc.statut
            return render_template('assistant.html', interdit=exc.message, models=[]), exc.statut
    return wrapper


def corps(cles):
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != set(cles):
        raise AssistantErreur('Données invalides.')
    return data


@assistant_bp.route('/assistant')
@assistant_required
def assistant():
    return render_template('assistant.html', models=get_available_models(), interdit='')


@assistant_bp.route('/api/assistant/etat')
@assistant_required
def etat():
    return jsonify(lire_etat())


@assistant_bp.route('/api/assistant/message', methods=['POST'])
@assistant_required
@limiter.limit('6 per minute', key_func=lambda: str(session.get('user_id')))
def message():
    data = corps(('message', 'model', 'request_id'))
    if not isinstance(data['message'], str) or not 1 <= len(data['message'].strip()) <= 2000:
        raise AssistantErreur('Votre demande doit contenir entre 1 et 2 000 caractères.')
    if not isinstance(data['model'], str) or len(data['model']) > 100:
        raise AssistantErreur('Modèle invalide.')
    try:
        if str(uuid.UUID(data['request_id'])) != data['request_id']:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise AssistantErreur('Identifiant de demande invalide.') from None
    try:
        return jsonify(repondre(data['message'].strip(), data['model'], data['request_id']))
    except AssistantErreur:
        raise
    except Exception:
        # Ne jamais exposer les messages techniques des fournisseurs, ni les
        # données ou secrets qui pourraient s'y trouver.
        raise AssistantErreur('La demande n’a pas pu aboutir. Réessayez dans quelques instants.', 503) from None


@assistant_bp.route('/api/assistant/memoires', methods=['POST'])
@assistant_required
def ajouter_memoire():
    data = corps(('texte', 'categorie'))
    sauver_memoire(data['texte'], data['categorie'])
    return jsonify(lire_etat())


@assistant_bp.route('/api/assistant/memoires/<uuid:identifiant>', methods=['PUT'])
@assistant_required
def modifier_memoire(identifiant):
    data = corps(('texte', 'categorie'))
    sauver_memoire(data['texte'], data['categorie'], str(identifiant))
    return jsonify(lire_etat())


@assistant_bp.route('/api/assistant/memoires/<uuid:identifiant>', methods=['DELETE'])
@assistant_required
def supprimer_memoire(identifiant):
    oublier(str(identifiant))
    return jsonify(lire_etat())


@assistant_bp.route('/api/assistant/oublier', methods=['POST'])
@assistant_required
def reinitialiser():
    data = corps(('tout',))
    if not isinstance(data['tout'], bool):
        raise AssistantErreur('Choix de suppression invalide.')
    oublier(tout=data['tout'])
    return jsonify(lire_etat())
