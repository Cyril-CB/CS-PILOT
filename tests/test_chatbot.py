"""Le retrait de l’assistant global ne doit laisser ni route ni activation."""
import pytest
from unittest.mock import patch


@pytest.mark.parametrize('path,method', [
    ('/api/chatbot/config', 'get'),
    ('/api/chatbot/model', 'post'),
    ('/api/chatbot/message', 'post'),
])
@pytest.mark.parametrize('fixture', ['client', 'auth_client', 'admin_client'])
def test_routes_retirees(request, fixture, path, method):
    client = request.getfixturevalue(fixture)
    with patch('requests.post') as post:
        response = getattr(client, method)(path, json={'model': 'gpt-5.5', 'message': 'aide'})
    assert response.status_code == 404
    post.assert_not_called()


@pytest.mark.parametrize('flux', [False, True])
def test_aucun_widget_meme_avec_ancienne_configuration(app, admin_client, flux):
    from utils import save_setting
    with app.app_context():
        save_setting('chatbot_model', 'gpt-4.1-mini')
        save_setting('interface_sans_menu_active', '1' if flux else '0')
        save_setting('openai_api_key', 'cle-factice')
    for path in ['/gestion_cles_api', '/assistant_rh']:
        response = admin_client.get(path, follow_redirects=True)
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert ('<body class="flx">' in html) is flux
        assert 'cspChat' not in html
        assert '/api/chatbot/' not in html
        assert 'akChatbotModel' not in html
        if path == '/assistant_rh':
            assert 'gpt-5.5' in html
