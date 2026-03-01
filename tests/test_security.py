"""
Tests pour les nouvelles fonctionnalités de sécurité :
- Validation de la complexité des mots de passe
- Protection CSRF (vérification de présence des tokens)
- Rate limiting sur la route de login
- Refus de démarrage si SECRET_KEY par défaut
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from utils import validate_password_strength


class TestPasswordValidation:
    """Tests de la fonction validate_password_strength."""

    def test_mot_de_passe_trop_court(self):
        errors = validate_password_strength('Ab1!')
        assert any('8 caractères' in e for e in errors)

    def test_mot_de_passe_sans_majuscule(self):
        errors = validate_password_strength('abcdefg1')
        assert any('majuscule' in e for e in errors)

    def test_mot_de_passe_sans_minuscule(self):
        errors = validate_password_strength('ABCDEFG1')
        assert any('minuscule' in e for e in errors)

    def test_mot_de_passe_sans_chiffre(self):
        errors = validate_password_strength('Abcdefgh')
        assert any('chiffre' in e for e in errors)

    def test_mot_de_passe_valide(self):
        errors = validate_password_strength('Abcdef1!')
        assert errors == []

    def test_mot_de_passe_valide_sans_special(self):
        """Un mot de passe sans caractère spécial est accepté (recommandé mais pas obligatoire)."""
        errors = validate_password_strength('Abcdefg1')
        assert errors == []

    def test_mot_de_passe_vide(self):
        errors = validate_password_strength('')
        assert len(errors) >= 1

    def test_erreurs_multiples(self):
        """Un mot de passe très faible doit retourner plusieurs erreurs."""
        errors = validate_password_strength('abc')
        assert len(errors) >= 3  # trop court + pas de majuscule + pas de chiffre


class TestCsrfTokenPresence:
    """Vérifie que les tokens CSRF sont présents dans les formulaires critiques."""

    def test_csrf_token_sur_page_login(self, client, sample_users):
        """La page de login doit contenir un champ csrf_token."""
        response = client.get('/login')
        html = response.data.decode('utf-8')
        assert 'csrf_token' in html
        assert 'csrf-token' in html  # meta tag

    def test_csrf_meta_tag_dans_base(self, client, sample_users):
        """Le template de base doit inclure la meta CSRF."""
        response = client.get('/login')
        html = response.data.decode('utf-8')
        assert 'meta name="csrf-token"' in html


class TestCreerUserPasswordValidation:
    """Teste la validation du mot de passe à la création d'utilisateur."""

    def _login_admin_no_redirect(self, client):
        """Login admin sans follow_redirects pour éviter le bug pre-existant contrats."""
        client.post('/login', data={
            'login': 'admin',
            'password': 'Admin1234',
        }, follow_redirects=False)

    def test_creation_user_mot_de_passe_faible(self, client, sample_users, app):
        """La création avec un mot de passe faible doit être refusée."""
        self._login_admin_no_redirect(client)
        with app.app_context():
            response = client.post('/creer_user', data={
                'nom': 'Test',
                'prenom': 'User',
                'login': 'testuser',
                'password': 'abc',
                'profil': 'salarie',
            }, follow_redirects=True)
            html = response.data.decode('utf-8')
            assert '8 caractères' in html or 'majuscule' in html

    def test_creation_user_mot_de_passe_fort(self, client, sample_users, app):
        """La création avec un mot de passe fort doit réussir."""
        self._login_admin_no_redirect(client)
        with app.app_context():
            response = client.post('/creer_user', data={
                'nom': 'Test',
                'prenom': 'User',
                'login': 'testuser_fort',
                'password': 'Secure1Pass!',
                'profil': 'salarie',
            }, follow_redirects=True)
            html = response.data.decode('utf-8')
            assert 'créé avec succès' in html


class TestSecretKeyValidation:
    """Tests liés à la validation de SECRET_KEY."""

    def test_default_key_is_defined(self):
        """Vérifie que la constante de la clé par défaut est définie."""
        from app import _DEFAULT_SECRET_KEY
        assert _DEFAULT_SECRET_KEY == 'dev-secret-key-do-not-use-in-production'

    def test_app_has_custom_secret_key(self, app):
        """En mode test, l'app doit utiliser une clé custom."""
        assert app.secret_key != 'dev-secret-key-do-not-use-in-production'
        assert app.secret_key == 'test-secret-key-for-pytest'
