"""Page assistant autonome : lecture métier et mémoire personnelle explicite."""
from functools import wraps
import uuid

from flask import Blueprint, jsonify, render_template, request, session, send_file

from assistant_stockage import (AssistantErreur, compte, transaction, lire_etat,
                               sauver_memoire, oublier)
from assistant_agent import repondre
from blueprints.api_keys import get_available_models
from extensions import limiter
from utils import login_required
import assistant_reception as reception
from assistant_pdf import chemin_document, MAX_PDF

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
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) not in ({'message', 'model', 'request_id'},
            {'message', 'model', 'request_id', 'document_id'}):
        raise AssistantErreur('Données invalides.')
    if not isinstance(data['message'], str) or not 1 <= len(data['message'].strip()) <= 2000:
        raise AssistantErreur('Votre demande doit contenir entre 1 et 2 000 caractères.')
    if not isinstance(data['model'], str) or len(data['model']) > 100:
        raise AssistantErreur('Modèle invalide.')
    try:
        if str(uuid.UUID(data['request_id'])) != data['request_id']:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise AssistantErreur('Identifiant de demande invalide.') from None
    document_id = data.get('document_id')
    if document_id is not None:
        try:
            if str(uuid.UUID(document_id)) != document_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise AssistantErreur('Identifiant de document invalide.') from None
    try:
        return jsonify(repondre(data['message'].strip(), data['model'], data['request_id'], document_id))
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


def _reponse_document(fn, *args):
    try:
        return jsonify(fn(*args))
    except AssistantErreur:
        raise
    except Exception:
        raise AssistantErreur('Le traitement n’a pas abouti. Le PDF déposé reste disponible dans la boîte de réception.', 503) from None


@assistant_bp.route('/api/assistant/documents', methods=['GET'])
@assistant_required
def documents():
    return _reponse_document(lambda: {'documents': reception.lister()})


@assistant_bp.route('/api/assistant/documents', methods=['POST'])
@assistant_required
@limiter.limit('6 per minute', key_func=lambda: str(session.get('user_id')))
def deposer_document():
    if request.content_length and request.content_length > MAX_PDF + 65536:
        raise AssistantErreur('Le PDF doit peser au maximum 16 Mo.', 413)
    if (set(request.files) != {'fichier'} or len(request.files.getlist('fichier')) != 1
            or set(request.form) - {'commentaire', 'model', 'csrf_token'}):
        raise AssistantErreur('Déposez un seul PDF, avec un commentaire facultatif.')
    return _reponse_document(reception.recevoir, request.files['fichier'],
                             request.form.get('commentaire', ''), request.form.get('model', ''))


@assistant_bp.route('/api/assistant/documents/<uuid:identifiant>')
@assistant_required
def document(identifiant):
    return _reponse_document(reception.lire, str(identifiant))


@assistant_bp.route('/api/assistant/documents/<uuid:identifiant>', methods=['DELETE'])
@assistant_required
def supprimer_document(identifiant):
    data = corps(('revision',))
    try:
        return jsonify(reception.supprimer(str(identifiant), data['revision']))
    except AssistantErreur:
        raise
    except Exception:
        raise AssistantErreur('La suppression n’a pas abouti. Rechargez la boîte de réception et réessayez.', 503) from None


@assistant_bp.route('/api/assistant/documents/<uuid:identifiant>/analyser', methods=['POST'])
@assistant_required
@limiter.limit('6 per minute', key_func=lambda: str(session.get('user_id')))
def analyser_document(identifiant):
    data = request.get_json(silent=True)
    if (not isinstance(data, dict) or 'model' not in data
            or set(data) - {'model', 'commentaire', 'type_document'}):
        raise AssistantErreur('Données d’analyse invalides.')
    return _reponse_document(reception.analyser_document, str(identifiant), data['model'],
                             data.get('commentaire'), data.get('type_document'))


@assistant_bp.route('/api/assistant/documents/<uuid:identifiant>/precisions', methods=['POST'])
@assistant_required
def preciser_document(identifiant):
    data = corps(('revision', 'reponses'))
    return _reponse_document(reception.traiter, str(identifiant), data['revision'], data['reponses'])


@assistant_bp.route('/assistant/documents/<uuid:identifiant>/pdf')
@assistant_required
def document_pdf(identifiant):
    with transaction() as conn:
        user = compte(conn)
        doc, data = reception._document(conn, user, str(identifiant))
        path = chemin_document(doc['fichier_path'])
        if not path.is_file():
            raise AssistantErreur('PDF indisponible.', 404)
    response = send_file(path, mimetype='application/pdf', as_attachment=True, download_name=data['nom'])
    response.headers.update({'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})
    return response
