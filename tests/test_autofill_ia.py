"""Clés et recherche ne doivent pas former un formulaire de connexion."""
from html.parser import HTMLParser
from unittest.mock import patch

import pytest


class Fields(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.fields = []
        self.forms = []
        self.current = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            assert self.current is None, 'Formulaires imbriqués'
            self.current = attrs
            self.forms.append(attrs)
        if tag == 'input':
            self.fields.append((attrs, self.current))

    def handle_endtag(self, tag):
        if tag == 'form':
            self.current = None


@pytest.mark.parametrize('configured', [False, True])
@pytest.mark.parametrize('flux', [False, True])
def test_cles_isolees_et_recherche_identifiee(app, admin_client, configured, flux):
    from utils import save_setting
    with app.app_context():
        save_setting('interface_sans_menu_active', '1' if flux else '0')
        if configured:
            for provider in ['openai', 'groq', 'anthropic']:
                save_setting(provider + '_api_key', 'secret-factice-jamais-renvoye')
    response = admin_client.get('/gestion_cles_api')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'secret-factice-jamais-renvoye' not in html
    fields = Fields(html)
    assert not any(a.get('type') == 'password' for a, _ in fields.fields)
    owners = []
    for provider in ['openai', 'groq', 'anthropic']:
        matching = [(a, form) for a, form in fields.fields if a.get('id') == 'akInput_' + provider]
        assert len(matching) == 1
        attrs, owner = matching[0]
        assert attrs['type'] == 'text'
        assert attrs['name'] == provider + '_api_token'
        assert attrs['autocomplete'] == 'off'
        assert 'ak-secret-input' in attrs['class']
        assert not attrs.get('value')
        assert owner is not None and owner['autocomplete'] == 'off'
        owners.append(owner)
    assert len({id(owner) for owner in owners}) == 3
    if flux:
        attrs, owner = next((a, form) for a, form in fields.fields if a.get('id') == 'flxChamp')
        assert attrs['type'] == 'search'
        assert attrs['name'] == 'cspilot_navigation_query'
        assert owner['role'] == 'search'
        assert all(owner is not x for x in owners)


def test_recherche_classique_isolee(app, admin_client):
    from utils import save_setting
    with app.app_context():
        save_setting('interface_sans_menu_active', '0')
    html = admin_client.get('/dashboard_direction', follow_redirects=True).get_data(as_text=True)
    attrs, owner = next((a, f) for a, f in Fields(html).fields if a.get('id') == 'dsSearchInput')
    assert attrs['type'] == 'search'
    assert owner['role'] == 'search'
    assert attrs['autocomplete'] == 'off'


def test_connexion_conserve_champ_mot_de_passe(client, sample_users):
    html = client.get('/login').get_data(as_text=True)
    assert any(a.get('type') == 'password' for a, _ in Fields(html).fields)


def test_enregistrement_cle_garde_api_existante(app, admin_client):
    with patch('blueprints.api_keys.TEST_FUNCTIONS', {'groq': lambda key: (True, None)}):
        response = admin_client.post('/api/api_keys/save', json={'provider': 'groq', 'api_key': 'token-factice'})
    assert response.status_code == 200
    from utils import get_setting
    with app.app_context():
        assert get_setting('groq_api_key') == 'token-factice'
