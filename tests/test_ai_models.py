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
        assert 'claude-sonnet-4-6' in anthropic_ids
        assert 'claude-opus-4-8' in anthropic_ids
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
        assert 'claude-sonnet-4-6' in ids
        assert all(m['provider'] == 'anthropic' for m in models)


class TestCompatibiliteAscendante:
    """Une valeur déjà persistée avec un ancien identifiant ne doit pas casser."""

    def test_anciens_identifiants_resolus(self):
        # Retirés du catalogue mais encore résolus pour ne pas casser le chatbot
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
