"""
Tests de cohérence et de compatibilité des modèles d'IA.

Couvre :
- la cohérence du catalogue de modèles (chaque modèle proposé se rattache bien
  à son fournisseur) ;
- les prédicats de compatibilité de paramètres ;
- la construction des requêtes : les modèles récents (Anthropic Opus 4.7+ /
  Fable, OpenAI o-series / GPT-5) n'acceptent pas `temperature`/`seed` et
  renverraient une erreur 400 si ces paramètres étaient envoyés.
"""
from unittest.mock import MagicMock, patch

import importlib.util
import os
import pytest

from blueprints.api_keys import (
    AI_PROVIDERS, MODEL_TO_PROVIDER, get_provider_for_model,
    get_available_models, anthropic_supports_temperature, is_openai_reasoning_model,
    EFFORT_LEVELS, get_openai_reasoning_effort,
)
from blueprints import pesee_alisfa


def _load_migration_0041():
    path = os.path.join(os.path.dirname(__file__), '..', 'migrations',
                        '0041_maj_modeles_ia_chatbot.py')
    spec = importlib.util.spec_from_file_location('mig0041', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake_anthropic_response():
    return MagicMock(status_code=200, json=lambda: {'content': [{'text': '{}'}]})


def _fake_openai_response():
    return MagicMock(status_code=200,
                     json=lambda: {'choices': [{'message': {'content': '{}'}}]})


class TestCatalogueModeles:
    def test_chaque_modele_se_rattache_a_son_fournisseur(self):
        for provider_id, info in AI_PROVIDERS.items():
            for model in info['models']:
                assert get_provider_for_model(model['id']) == provider_id

    def test_pas_de_modele_en_doublon(self):
        ids = [m['id'] for info in AI_PROVIDERS.values() for m in info['models']]
        assert len(ids) == len(set(ids))

    def test_mapping_complet(self):
        ids = {m['id'] for info in AI_PROVIDERS.values() for m in info['models']}
        assert set(MODEL_TO_PROVIDER) == ids

    def test_modeles_anthropic_a_jour(self):
        """Les identifiants Anthropic doivent être ceux des modèles actuels."""
        anthropic_ids = [m['id'] for m in AI_PROVIDERS['anthropic']['models']]
        assert 'claude-sonnet-5-5' in anthropic_ids
        assert 'claude-opus-5-5' in anthropic_ids
        # Les anciens identifiants ne doivent plus être proposés
        assert 'claude-sonnet-4-5-20250929' not in anthropic_ids
        assert 'claude-opus-4-6' not in anthropic_ids

    def test_modeles_openai_a_jour(self):
        """Les nouveaux modèles OpenAI (GPT-5.5 / GPT-5.4) sont proposés."""
        openai_ids = [m['id'] for m in AI_PROVIDERS['openai']['models']]
        assert 'gpt-5.5' in openai_ids
        assert 'gpt-5.4' in openai_ids


class TestPredicatsCompatibilite:
    def test_anthropic_temperature(self):
        assert anthropic_supports_temperature('claude-sonnet-4-6') is True
        assert anthropic_supports_temperature('claude-haiku-4-5') is True
        assert anthropic_supports_temperature('claude-opus-4-8') is False
        assert anthropic_supports_temperature('claude-opus-4-7') is False
        assert anthropic_supports_temperature('claude-fable-5') is False

    def test_openai_raisonnement(self):
        assert is_openai_reasoning_model('gpt-5.5') is True
        assert is_openai_reasoning_model('gpt-5.4') is True
        assert is_openai_reasoning_model('gpt-5.2') is True
        assert is_openai_reasoning_model('o3-mini') is True
        assert is_openai_reasoning_model('o1') is True
        assert is_openai_reasoning_model('gpt-4.1-mini') is False


class TestPayloadAnthropic:
    def test_modele_recent_sans_temperature(self):
        with patch.object(pesee_alisfa.http_requests, 'post',
                          return_value=_fake_anthropic_response()) as mock_post:
            pesee_alisfa.call_anthropic('sk-ant-x', [{'role': 'user', 'content': 'hi'}],
                                        'claude-opus-4-8')
        payload = mock_post.call_args.kwargs['json']
        assert 'temperature' not in payload
        assert payload['model'] == 'claude-opus-4-8'

    def test_modele_compatible_avec_temperature(self):
        with patch.object(pesee_alisfa.http_requests, 'post',
                          return_value=_fake_anthropic_response()) as mock_post:
            pesee_alisfa.call_anthropic('sk-ant-x', [{'role': 'user', 'content': 'hi'}],
                                        'claude-sonnet-4-6')
        payload = mock_post.call_args.kwargs['json']
        assert payload['temperature'] == 0


class TestPayloadOpenAI:
    def test_modele_raisonnement_sans_temperature_ni_seed(self):
        with patch.object(pesee_alisfa.http_requests, 'post',
                          return_value=_fake_openai_response()) as mock_post:
            pesee_alisfa.call_openai('sk-x', [{'role': 'user', 'content': 'hi'}], 'gpt-5.2')
        payload = mock_post.call_args.kwargs['json']
        assert 'temperature' not in payload
        assert 'seed' not in payload

    def test_modele_standard_avec_temperature_et_seed(self):
        with patch.object(pesee_alisfa.http_requests, 'post',
                          return_value=_fake_openai_response()) as mock_post:
            pesee_alisfa.call_openai('sk-x', [{'role': 'user', 'content': 'hi'}],
                                     'gpt-4.1-mini')
        payload = mock_post.call_args.kwargs['json']
        assert payload['temperature'] == 0
        assert payload['seed'] == 42


class TestEffortRaisonnement:
    def test_niveaux_effort(self):
        assert EFFORT_LEVELS == ['low', 'medium', 'high', 'xhigh']

    def test_defaut_medium(self, app):
        with app.app_context():
            assert get_openai_reasoning_effort() == 'medium'

    def test_respecte_le_reglage(self, app):
        from utils import save_setting
        with app.app_context():
            save_setting('openai_reasoning_effort', 'xhigh')
            assert get_openai_reasoning_effort() == 'xhigh'

    def test_valeur_invalide_retombe_sur_defaut(self, app):
        from utils import save_setting
        with app.app_context():
            save_setting('openai_reasoning_effort', 'nawak')
            assert get_openai_reasoning_effort() == 'medium'

    def test_payload_reasoning_inclut_effort(self, app):
        from utils import save_setting
        with app.app_context():
            save_setting('openai_reasoning_effort', 'high')
            with patch.object(pesee_alisfa.http_requests, 'post',
                              return_value=_fake_openai_response()) as mock_post:
                pesee_alisfa.call_openai('sk-x', [{'role': 'user', 'content': 'hi'}], 'gpt-5.5')
            payload = mock_post.call_args.kwargs['json']
        assert payload['reasoning_effort'] == 'high'
        assert 'temperature' not in payload and 'seed' not in payload

    def test_payload_modele_standard_sans_effort(self, app):
        with app.app_context():
            with patch.object(pesee_alisfa.http_requests, 'post',
                              return_value=_fake_openai_response()) as mock_post:
                pesee_alisfa.call_openai('sk-x', [{'role': 'user', 'content': 'hi'}], 'gpt-4.1-mini')
            payload = mock_post.call_args.kwargs['json']
        assert 'reasoning_effort' not in payload

    def test_route_effort_enregistre(self, app, admin_client):
        r = admin_client.post('/api/api_keys/effort', json={'effort': 'high'})
        assert r.status_code == 200 and r.get_json()['effort'] == 'high'
        from utils import get_setting
        with app.app_context():
            assert get_setting('openai_reasoning_effort') == 'high'

    def test_route_effort_invalide_refusee(self, admin_client):
        r = admin_client.post('/api/api_keys/effort', json={'effort': 'nawak'})
        assert r.status_code == 400

    def test_route_effort_refuse_salarie(self, auth_client):
        r = auth_client.post('/api/api_keys/effort', json={'effort': 'high'})
        assert r.status_code == 403


class TestModelesDisponibles:
    def test_get_available_models_suit_les_cles_configurees(self, app):
        from utils import save_setting
        with app.app_context():
            assert get_available_models() == []  # aucune clé configurée
            save_setting('anthropic_api_key', 'sk-ant-test')
            models = get_available_models()
        ids = {m['id'] for m in models}
        assert 'claude-sonnet-5-5' in ids
        assert all(m['provider'] == 'anthropic' for m in models)


class TestCompatibiliteAscendante:
    """Une valeur déjà persistée avec un ancien identifiant ne doit pas casser."""

    def test_anciens_identifiants_resolus(self):
        # Retirés du catalogue mais encore résolus pour accepter un formulaire métier déjà ouvert
        assert get_provider_for_model('claude-sonnet-4-5-20250929') == 'anthropic'
        assert get_provider_for_model('claude-opus-4-6') == 'anthropic'
        assert get_provider_for_model('claude-haiku-4-5-20251001') == 'anthropic'
        # Ne sont pas pour autant proposés dans le catalogue
        assert 'claude-opus-4-6' not in MODEL_TO_PROVIDER

    def test_identifiant_reellement_inconnu_non_resolu(self):
        assert get_provider_for_model('modele-bidon') is None

    def test_migration_remappe_chatbot_model(self, app):
        import database
        from utils import save_setting, get_setting
        mig = _load_migration_0041()
        with app.app_context():
            save_setting('chatbot_model', 'claude-opus-4-6')
            conn = database.get_db()
            mig.upgrade(conn)
            conn.close()
            assert get_setting('chatbot_model') == 'claude-opus-4-8'

    def test_migration_laisse_un_modele_a_jour_intact(self, app):
        import database
        from utils import save_setting, get_setting
        mig = _load_migration_0041()
        with app.app_context():
            save_setting('chatbot_model', 'claude-sonnet-4-6')
            conn = database.get_db()
            mig.upgrade(conn)
            conn.close()
            assert get_setting('chatbot_model') == 'claude-sonnet-4-6'


class TestCatalogue20261115:
    def test_exclusions_et_groq_exact(self):
        ids = set(MODEL_TO_PROVIDER)
        assert not any(x in m.lower() for m in ids for x in ('mini', 'nano', 'astra', 'fable'))
        assert 'gpt-5.2' not in ids and 'gpt-4o' not in ids
        assert {m['id'] for m in AI_PROVIDERS['groq']['models']} == {
            'openai/gpt-oss-120b', 'qwen/qwen3.8-27b'}

    @pytest.mark.parametrize('model', [m['id'] for m in AI_PROVIDERS['openai']['models']])
    def test_payload_openai_tous_modeles(self, model):
        with patch.object(pesee_alisfa.http_requests, 'post', return_value=_fake_openai_response()) as post:
            pesee_alisfa.call_openai('cle-factice', [{'role': 'user', 'content': 'JSON'}], model)
        payload = post.call_args.kwargs['json']
        assert payload['model'] == model
        assert payload['response_format'] == {'type': 'json_object'}
        assert 'max_completion_tokens' in payload
        assert payload['reasoning_effort'] == 'medium'
        assert not {'temperature', 'seed', 'max_tokens'} & payload.keys()

    @pytest.mark.parametrize('model', [m['id'] for m in AI_PROVIDERS['anthropic']['models']])
    def test_payload_et_reponse_claude(self, model):
        response = MagicMock(status_code=200, json=lambda: {'content': [
            {'type': 'thinking', 'thinking': 'raisonnement'},
            {'type': 'text', 'text': '{"ok":'}, {'type': 'text', 'text': 'true}'}]})
        with patch.object(pesee_alisfa.http_requests, 'post', return_value=response) as post:
            text = pesee_alisfa.call_anthropic('cle-factice', [
                {'role': 'system', 'content': 'Contexte'}, {'role': 'user', 'content': 'JSON'}], model)
        payload = post.call_args.kwargs['json']
        assert text == '{"ok":true}'
        assert payload['system'] == 'Contexte'
        assert not {'temperature', 'top_p', 'top_k'} & payload.keys()
        assert payload['messages'] == [{'role': 'user', 'content': 'JSON'}]

    @pytest.mark.parametrize('model', ['openai/gpt-oss-120b', 'qwen/qwen3.8-27b'])
    def test_payload_groq(self, model):
        with patch.object(pesee_alisfa.http_requests, 'post', return_value=_fake_openai_response()) as post:
            pesee_alisfa.call_groq('cle-factice', [{'role': 'user', 'content': 'JSON'}], model)
        payload = post.call_args.kwargs['json']
        assert payload['max_completion_tokens'] == 8000
        assert 'max_tokens' not in payload
        assert payload['reasoning_effort'] == 'medium'
        if model.startswith('openai/'):
            assert payload['include_reasoning'] is False
            assert 'reasoning_format' not in payload
        else:
            assert payload['reasoning_format'] == 'hidden'
            assert 'include_reasoning' not in payload

    def test_reponse_claude_sans_texte_refusee(self):
        from blueprints.api_keys import anthropic_response_text
        with pytest.raises(ValueError, match='aucun texte'):
            anthropic_response_text({'content': [{'type': 'thinking', 'thinking': '...'}]})

    def test_dispatch_anciens_modeles_et_inconnus(self, app):
        from blueprints.api_keys import MODEL_REPLACEMENTS, resolve_model
        for old, new in MODEL_REPLACEMENTS.items():
            assert new in MODEL_TO_PROVIDER
            assert resolve_model(old) == new
        with app.app_context(), patch('blueprints.pesee_alisfa.get_setting', return_value='factice'):
            with patch.object(pesee_alisfa, 'call_groq', return_value='{}') as call:
                pesee_alisfa.call_ai([], 'llama-3.3-70b-versatile')
                assert call.call_args.args[2] == 'openai/gpt-oss-120b'
            with pytest.raises(Exception, match='Modèle inconnu'):
                pesee_alisfa.call_ai([], 'gpt-6-astra')

    @pytest.mark.parametrize('provider,expected', [
        ('openai', 'gpt-5.4'), ('groq', 'openai/gpt-oss-120b'), ('anthropic', 'claude-haiku-5-5')])
    def test_verification_cle_modele_actuel(self, provider, expected):
        from blueprints.api_keys import TEST_FUNCTIONS
        with patch('blueprints.api_keys.http_requests.post', return_value=MagicMock(status_code=200)) as post:
            assert TEST_FUNCTIONS[provider]('factice') == (True, None)
        assert post.call_args.kwargs['json']['model'] == expected

    @pytest.mark.parametrize('fixture,status', [('client', 302), ('auth_client', 403), ('resp_client', 403)])
    def test_catalogue_acces_refuse(self, request, fixture, status):
        response = request.getfixturevalue(fixture).get('/api/api_keys/status')
        assert response.status_code == status

    def test_catalogue_et_page_sans_exclusions(self, app, admin_client):
        from utils import save_setting
        with app.app_context():
            for key in ['openai_api_key', 'anthropic_api_key', 'groq_api_key']:
                save_setting(key, 'cle-factice')
        response = admin_client.get('/api/api_keys/status')
        assert response.status_code == 200
        assert {m['id'] for m in response.json['models']} == set(MODEL_TO_PROVIDER)
        assert 'cle-factice' not in response.get_data(as_text=True)


@pytest.mark.parametrize('model,provider', [
    ('gpt-6.1-sol', 'openai'), ('claude-sonnet-5-5', 'anthropic'),
    ('openai/gpt-oss-120b', 'groq'), ('qwen/qwen3.8-27b', 'groq')])
def test_assistant_rh_modele_bien_route(app, admin_client, model, provider):
    from utils import save_setting
    with app.app_context():
        save_setting(provider + '_api_key', 'cle-factice')
    response = _fake_anthropic_response() if provider == 'anthropic' else _fake_openai_response()
    with patch('blueprints.pesee_alisfa.http_requests.post', return_value=response) as post:
        result = admin_client.post('/api/assistant_rh/chat', json={
            'model': model, 'messages': [{'role': 'user', 'content': 'Question de test'}]})
    assert result.status_code == 200 and result.json['success'] is True
    assert post.call_args.kwargs['json']['model'] == model
    domains = {'openai': 'api.openai.com', 'anthropic': 'api.anthropic.com', 'groq': 'api.groq.com'}
    assert domains[provider] in post.call_args.args[0]


@pytest.mark.parametrize('model', ['gpt-6-astra', 'claude-fable-5-2', 'modele-inconnu'])
def test_modele_exclu_aucun_appel_externe(admin_client, model):
    with patch('requests.post') as post:
        result = admin_client.post('/api/assistant_rh/chat', json={
            'model': model, 'messages': [{'role': 'user', 'content': 'Question'}]})
    assert 'Modèle inconnu' in result.json['error']
    post.assert_not_called()
