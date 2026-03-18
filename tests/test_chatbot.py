"""
Tests pour le blueprint chatbot.
Vérifie les endpoints API et la configuration du chatbot.
"""
import pytest
from unittest.mock import patch, MagicMock


class TestChatbotConfig:
    """Tests pour l'endpoint de configuration du chatbot."""

    def test_chatbot_config_not_logged_in(self, client):
        """Non authentifié → redirection."""
        resp = client.get('/api/chatbot/config')
        assert resp.status_code == 302

    def test_chatbot_config_logged_in(self, admin_client):
        """Authentifié → retourne la config."""
        resp = admin_client.get('/api/chatbot/config')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'enabled' in data
        assert data['enabled'] is False  # Pas de modèle configuré par défaut

    def test_chatbot_config_as_salarie(self, auth_client):
        """Salarié → peut accéder à la config (lecture seule)."""
        resp = auth_client.get('/api/chatbot/config')
        assert resp.status_code == 200


class TestChatbotSetModel:
    """Tests pour la sélection du modèle chatbot."""

    def test_set_model_not_directeur(self, resp_client):
        """Responsable → accès refusé."""
        resp = resp_client.post('/api/chatbot/model',
                                json={'model': 'gpt-4.1-mini'},
                                content_type='application/json')
        assert resp.status_code == 403

    def test_set_model_no_data(self, admin_client):
        """Pas de données → erreur."""
        resp = admin_client.post('/api/chatbot/model',
                                 content_type='application/json')
        assert resp.status_code == 400

    def test_set_model_unknown(self, admin_client):
        """Modèle inconnu → erreur."""
        resp = admin_client.post('/api/chatbot/model',
                                 json={'model': 'unknown-model'},
                                 content_type='application/json')
        assert resp.status_code == 400

    def test_disable_chatbot(self, admin_client):
        """Désactiver le chatbot (model vide)."""
        resp = admin_client.post('/api/chatbot/model',
                                 json={'model': ''},
                                 content_type='application/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['enabled'] is False


class TestChatbotMessage:
    """Tests pour l'envoi de messages au chatbot."""

    def test_message_not_logged_in(self, client):
        """Non authentifié → redirection."""
        resp = client.post('/api/chatbot/message',
                           json={'message': 'hello', 'page': 'dashboard'},
                           content_type='application/json')
        assert resp.status_code == 302

    def test_message_no_data(self, admin_client):
        """Pas de données → erreur."""
        resp = admin_client.post('/api/chatbot/message',
                                 content_type='application/json')
        assert resp.status_code == 400

    def test_message_empty(self, admin_client):
        """Message vide → erreur."""
        resp = admin_client.post('/api/chatbot/message',
                                 json={'message': '', 'page': 'dashboard'},
                                 content_type='application/json')
        assert resp.status_code == 400

    def test_message_no_model_configured(self, admin_client):
        """Pas de modèle configuré → erreur explicite."""
        resp = admin_client.post('/api/chatbot/message',
                                 json={'message': 'Bonjour', 'page': 'dashboard'},
                                 content_type='application/json')
        assert resp.status_code == 400
        data = resp.get_json()
        assert 'modèle' in data['error'].lower() or 'modele' in data['error'].lower()

    @patch('blueprints.chatbot._call_ai')
    @patch('blueprints.chatbot.get_setting')
    def test_message_success(self, mock_get_setting, mock_call_ai, admin_client):
        """Message avec modèle configuré → réponse IA."""
        mock_get_setting.return_value = 'gpt-4.1-mini'
        mock_call_ai.return_value = 'Voici ma réponse.'

        resp = admin_client.post('/api/chatbot/message',
                                 json={'message': 'Comment ça marche ?', 'page': 'factures'},
                                 content_type='application/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['response'] == 'Voici ma réponse.'

    @patch('blueprints.chatbot._call_ai')
    @patch('blueprints.chatbot.get_setting')
    def test_message_with_history(self, mock_get_setting, mock_call_ai, admin_client):
        """Message avec historique de conversation."""
        mock_get_setting.return_value = 'gpt-4.1-mini'
        mock_call_ai.return_value = 'Réponse avec contexte.'

        history = [
            {'role': 'user', 'content': 'Bonjour'},
            {'role': 'assistant', 'content': 'Bonjour !'},
        ]
        resp = admin_client.post('/api/chatbot/message',
                                 json={'message': 'Et ensuite ?', 'page': 'dashboard', 'history': history},
                                 content_type='application/json')
        assert resp.status_code == 200
        # Vérifier que l'historique est passé dans les messages
        call_args = mock_call_ai.call_args
        messages = call_args[0][0]
        assert len(messages) >= 4  # system + 2 history + 1 current

    @patch('blueprints.chatbot._call_ai')
    @patch('blueprints.chatbot.get_setting')
    def test_message_ai_error(self, mock_get_setting, mock_call_ai, admin_client):
        """Erreur API IA → erreur 500."""
        mock_get_setting.return_value = 'gpt-4.1-mini'
        mock_call_ai.side_effect = Exception('API timeout')

        resp = admin_client.post('/api/chatbot/message',
                                 json={'message': 'Test', 'page': 'dashboard'},
                                 content_type='application/json')
        assert resp.status_code == 500
        data = resp.get_json()
        assert 'API timeout' in data['error']


class TestChatbotPrompts:
    """Tests pour les prompts contextuels."""

    def test_system_prompt_known_page(self):
        """Page connue → prompt contextuel spécifique."""
        from blueprints.chatbot import _get_system_prompt
        prompt = _get_system_prompt('approbation_factures')
        assert 'approbation' in prompt.lower()
        assert 'Détail' in prompt or 'bouton' in prompt.lower()

    def test_system_prompt_unknown_page(self):
        """Page inconnue → prompt générique."""
        from blueprints.chatbot import _get_system_prompt
        prompt = _get_system_prompt('page_inconnue')
        assert 'CS-PILOT' in prompt
        assert 'page_inconnue' in prompt

    def test_system_prompt_factures(self):
        """Page factures → mentionne le circuit complet."""
        from blueprints.chatbot import _get_system_prompt
        prompt = _get_system_prompt('factures')
        assert 'fournisseur' in prompt.lower()
        assert 'écriture' in prompt.lower() or 'critures' in prompt.lower()

    def test_system_prompt_planning_enfance(self):
        """Page planning_enfance → mentionne attention double saisie."""
        from blueprints.chatbot import _get_system_prompt
        prompt = _get_system_prompt('planning_enfance')
        assert 'double' in prompt.lower() or 'deux fois' in prompt.lower()


class TestFactureDetailBackButton:
    """Tests pour le bouton retour sur la page détail facture."""

    def test_detail_from_approbation_has_approbation_link(self, admin_client, db, sample_users):
        """Accès depuis approbation → bouton retour vers approbation."""
        # Créer un fournisseur et une facture
        db.execute("INSERT INTO fournisseurs (nom) VALUES ('Test')")
        fournisseur_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute(
            "INSERT INTO factures (fournisseur_id, montant_ttc, approbation) VALUES (?, ?, ?)",
            (fournisseur_id, 100.0, 'en_attente')
        )
        facture_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()

        resp = admin_client.get(f'/factures/{facture_id}/detail?from=approbation')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'approbation_factures' in html or 'approbation' in html
        assert 'Retour aux approbations' in html

    def test_detail_without_from_has_factures_link(self, admin_client, db, sample_users):
        """Accès direct → bouton retour vers factures."""
        db.execute("INSERT INTO fournisseurs (nom) VALUES ('Test2')")
        fournisseur_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute(
            "INSERT INTO factures (fournisseur_id, montant_ttc, approbation) VALUES (?, ?, ?)",
            (fournisseur_id, 200.0, 'en_attente')
        )
        facture_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()

        resp = admin_client.get(f'/factures/{facture_id}/detail')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'Retour aux factures' in html

    def test_approbation_detail_link_has_from_param(self, resp_client, db, sample_users):
        """Page approbation → lien détail contient ?from=approbation."""
        # Créer une facture dans le secteur du responsable
        db.execute("INSERT INTO fournisseurs (nom) VALUES ('TestF')")
        fournisseur_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute(
            "INSERT INTO factures (fournisseur_id, montant_ttc, approbation, secteur_id) VALUES (?, ?, ?, ?)",
            (fournisseur_id, 150.0, 'en_attente', sample_users['secteur_id'])
        )
        db.commit()

        resp = resp_client.get('/factures/approbation')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'from=approbation' in html
