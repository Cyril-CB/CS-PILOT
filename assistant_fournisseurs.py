"""Transport JSON de l'agent, avec les clés existantes et sans outil arbitraire.

Le protocole de consultation est interprété exclusivement par le serveur. Il
fonctionne avec les trois fournisseurs, indépendamment de leurs API de tools.
"""
import json

import requests

from assistant_stockage import AssistantErreur
from blueprints.api_keys import (AI_PROVIDERS, MODEL_TO_PROVIDER, anthropic_response_text,
                                 anthropic_supports_temperature, get_openai_reasoning_effort,
                                 groq_reasoning_parameters)
from utils import get_setting


def cle_pour(model):
    provider = MODEL_TO_PROVIDER.get(model) if isinstance(model, str) else None
    if provider is None:
        raise AssistantErreur('Choisissez un modèle proposé dans la liste.')
    key = get_setting(AI_PROVIDERS[provider]['key_setting'])
    if not key:
        raise AssistantErreur('La clé API de ce fournisseur est absente. Contactez la direction.', 409)
    return provider, key


def appel_json(model, messages):
    provider, key = cle_pour(model)
    payload = {'model': model}
    if provider == 'anthropic':
        url = 'https://api.anthropic.com/v1/messages'
        headers = {'x-api-key': key, 'anthropic-version': '2023-06-01'}
        payload.update(system=messages[0]['content'], messages=messages[1:], max_tokens=3000)
        if anthropic_supports_temperature(model):
            payload['temperature'] = 0
    else:
        url = ('https://api.openai.com/v1/chat/completions' if provider == 'openai'
               else 'https://api.groq.com/openai/v1/chat/completions')
        headers = {'Authorization': 'Bearer ' + key}
        payload.update(messages=messages, max_completion_tokens=3000,
                       response_format={'type': 'json_object'})
        if provider == 'openai':
            payload['reasoning_effort'] = get_openai_reasoning_effort()
        else:
            payload.update(groq_reasoning_parameters(model))
    headers['Content-Type'] = 'application/json'
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=(5, 45))
        if response.status_code == 429:
            raise AssistantErreur('Le fournisseur a atteint sa limite de requêtes ou de crédit. Réessayez plus tard.', 503)
        if response.status_code != 200:
            raise AssistantErreur('Le fournisseur a refusé la demande. Vérifiez le modèle et la clé dans Clés API.', 503)
        data = response.json()
        if provider == 'anthropic':
            if data.get('stop_reason') == 'max_tokens':
                raise ValueError('Truncated')
            raw = anthropic_response_text(data)
        else:
            choice = data['choices'][0]
            if choice.get('finish_reason') in ('length', 'content_filter'):
                raise ValueError('Incomplete')
            raw = choice['message']['content']
        if not isinstance(raw, str) or len(raw) > 24000:
            raise ValueError('Invalid response')
        raw = raw.strip()
        if raw.startswith('```json') and raw.endswith('```'):
            raw = raw[7:-3].strip()
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError('Expected object')
        return result
    except AssistantErreur:
        raise
    except requests.RequestException:
        raise AssistantErreur('Le fournisseur est indisponible. Votre demande peut être réessayée.', 503) from None
    except (ValueError, KeyError, IndexError, TypeError):
        raise AssistantErreur('La réponse du modèle est inexploitable. Essayez une demande plus courte.', 502) from None
