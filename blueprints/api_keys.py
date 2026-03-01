"""
Blueprint api_keys_bp.
Page d'administration des clés API (OpenAI/ChatGPT, Groq, Anthropic Claude).
Accès : directeur, comptable.
"""
from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify
import requests as http_requests
from utils import login_required, get_setting, save_setting, delete_setting

api_keys_bp = Blueprint('api_keys_bp', __name__)

PROFILS_AUTORISES = ['directeur', 'comptable']

# ── Définition des fournisseurs et modèles ──

AI_PROVIDERS = {
    'openai': {
        'name': 'OpenAI',
        'key_setting': 'openai_api_key',
        'key_prefix': 'sk-',
        'models': [
            {'id': 'gpt-5.2', 'label': 'gpt-5.2 (recommande)'},
            {'id': 'gpt-4.1-mini', 'label': 'gpt-4.1-mini (~gratuit)'},
        ],
    },
    'anthropic': {
        'name': 'Anthropic',
        'key_setting': 'anthropic_api_key',
        'key_prefix': 'sk-ant-',
        'models': [
            {'id': 'claude-sonnet-4-5-20250929', 'label': 'claude-sonnet-4-5 (recommande)'},
            {'id': 'claude-opus-4-6', 'label': 'claude-opus-4-6 (+ puissant)'},
            {'id': 'claude-haiku-4-5-20251001', 'label': 'claude-haiku-4-5'},
        ],
    },
    'groq': {
        'name': 'Groq',
        'key_setting': 'groq_api_key',
        'key_prefix': 'gsk_',
        'models': [
            {'id': 'meta-llama/llama-4-scout-17b-16e-instruct', 'label': 'llama-4-scout-17b-16e-instruct (gratuit)'},
            {'id': 'llama-3.3-70b-versatile', 'label': 'llama-3.3-70b-versatile (gratuit)'},
        ],
    },
}

# Mapping modèle → fournisseur (pour déterminer quel provider utiliser)
MODEL_TO_PROVIDER = {}
for provider_id, provider_info in AI_PROVIDERS.items():
    for model in provider_info['models']:
        MODEL_TO_PROVIDER[model['id']] = provider_id


def get_provider_for_model(model_id):
    """Retourne l'identifiant du fournisseur pour un modèle donné."""
    return MODEL_TO_PROVIDER.get(model_id)


def get_configured_providers():
    """Retourne un dict {provider_id: True/False} selon les clés configurées."""
    result = {}
    for provider_id, info in AI_PROVIDERS.items():
        result[provider_id] = get_setting(info['key_setting']) is not None
    return result


def get_available_models():
    """Retourne la liste des modèles disponibles (dont le fournisseur a une clé configurée)."""
    configured = get_configured_providers()
    models = []
    for provider_id, info in AI_PROVIDERS.items():
        if configured.get(provider_id):
            for m in info['models']:
                models.append({
                    'id': m['id'],
                    'label': m['label'],
                    'provider': provider_id,
                    'provider_name': info['name'],
                })
    return models


# ── Validation des clés API ──

def _test_openai_key(api_key):
    """Teste une clé API OpenAI avec un appel minimal."""
    resp = http_requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": "gpt-4.1-mini", "messages": [{"role": "user", "content": "test"}], "max_tokens": 5},
        timeout=15,
    )
    if resp.status_code == 401:
        return False, "Clé API invalide ou expirée"
    if resp.status_code not in [200, 429]:
        return False, f"Erreur API: {resp.status_code}"
    return True, None


def _test_groq_key(api_key):
    """Teste une clé API Groq avec un appel minimal."""
    resp = http_requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": "test"}], "max_tokens": 5},
        timeout=15,
    )
    if resp.status_code == 401:
        return False, "Clé API invalide ou expirée"
    if resp.status_code not in [200, 429]:
        return False, f"Erreur API: {resp.status_code}"
    return True, None


def _test_anthropic_key(api_key):
    """Teste une clé API Anthropic avec un appel minimal."""
    resp = http_requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        },
        json={
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 5,
            "messages": [{"role": "user", "content": "test"}],
        },
        timeout=15,
    )
    if resp.status_code in [401, 403]:
        return False, "Clé API invalide ou expirée"
    if resp.status_code not in [200, 429]:
        return False, f"Erreur API: {resp.status_code}"
    return True, None


TEST_FUNCTIONS = {
    'openai': _test_openai_key,
    'groq': _test_groq_key,
    'anthropic': _test_anthropic_key,
}


# ── Routes ──

@api_keys_bp.route('/gestion_cles_api')
@login_required
def gestion_cles_api():
    if session.get('profil') not in PROFILS_AUTORISES:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard_bp.dashboard'))

    providers_status = {}
    for provider_id, info in AI_PROVIDERS.items():
        providers_status[provider_id] = {
            'name': info['name'],
            'has_key': get_setting(info['key_setting']) is not None,
            'models': info['models'],
            'key_prefix': info['key_prefix'],
        }

    return render_template('gestion_cles_api.html', providers=AI_PROVIDERS, providers_status=providers_status)


@api_keys_bp.route('/api/api_keys/save', methods=['POST'])
@login_required
def api_save_key():
    if session.get('profil') not in PROFILS_AUTORISES:
        return jsonify({'error': 'Accès non autorisé'}), 403

    data = request.get_json()
    provider_id = data.get('provider', '').strip()
    api_key = data.get('api_key', '').strip()

    if provider_id not in AI_PROVIDERS:
        return jsonify({'error': 'Fournisseur inconnu'}), 400

    provider = AI_PROVIDERS[provider_id]

    if not api_key:
        return jsonify({'error': 'Clé API vide'}), 400

    # Test de la clé
    test_fn = TEST_FUNCTIONS.get(provider_id)
    if test_fn:
        try:
            ok, err = test_fn(api_key)
            if not ok:
                return jsonify({'error': err}), 400
        except Exception as e:
            return jsonify({'error': f'Impossible de vérifier la clé: {str(e)}'}), 400

    save_setting(provider['key_setting'], api_key)
    return jsonify({'success': True})


@api_keys_bp.route('/api/api_keys/delete', methods=['POST'])
@login_required
def api_delete_key():
    if session.get('profil') not in PROFILS_AUTORISES:
        return jsonify({'error': 'Accès non autorisé'}), 403

    data = request.get_json()
    provider_id = data.get('provider', '').strip()

    if provider_id not in AI_PROVIDERS:
        return jsonify({'error': 'Fournisseur inconnu'}), 400

    delete_setting(AI_PROVIDERS[provider_id]['key_setting'])
    return jsonify({'success': True})


@api_keys_bp.route('/api/api_keys/status')
@login_required
def api_keys_status():
    """Retourne le statut des clés et les modèles disponibles (utilisé par pesee_alisfa)."""
    if session.get('profil') not in PROFILS_AUTORISES:
        return jsonify({'error': 'Accès non autorisé'}), 403

    return jsonify({
        'configured': get_configured_providers(),
        'models': get_available_models(),
    })
