"""
Tests pour le module auth.py :
- Login avec identifiants valides / invalides
- Logout et nettoyage de session
- Redirection selon le profil
- Protection des routes non authentifiées
- Setup initial (création du premier compte admin)
"""


class TestLogin:
    """Tests de la route /login."""

    def test_page_login_accessible(self, client, sample_users):
        """La page de login doit répondre en 200."""
        response = client.get('/login')
        assert response.status_code == 200

    def test_login_admin_valide(self, client, sample_users):
        """Login admin avec bons identifiants => redirection vers dashboard."""
        response = client.post('/login', data={
            'login': 'admin',
            'password': 'Admin1234',
        }, follow_redirects=False)
        # Doit rediriger (302) vers le dashboard forfait jour (profil directeur)
        assert response.status_code == 302

    def test_login_salarie_valide(self, client, sample_users):
        """Login salarié => redirection vers dashboard."""
        response = client.post('/login', data={
            'login': 'salarie_test',
            'password': 'sal123',
        }, follow_redirects=False)
        assert response.status_code == 302

    def test_login_mauvais_password(self, client, sample_users):
        """Mauvais mot de passe => reste sur la page login."""
        response = client.post('/login', data={
            'login': 'admin',
            'password': 'mauvais_mdp',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert 'Identifiants incorrects' in response.data.decode('utf-8')

    def test_login_utilisateur_inexistant(self, client, sample_users):
        """Utilisateur inexistant => message d'erreur."""
        response = client.post('/login', data={
            'login': 'inconnu',
            'password': 'test',
        }, follow_redirects=True)
        assert 'Identifiants incorrects' in response.data.decode('utf-8')

    def test_login_session_creee(self, client, sample_users):
        """Après login, la session doit contenir user_id, nom, profil."""
        with client:
            client.post('/login', data={
                'login': 'salarie_test',
                'password': 'sal123',
            })
            from flask import session
            assert 'user_id' in session
            assert session['nom'] == 'Martin'
            assert session['prenom'] == 'Jean'
            assert session['profil'] == 'salarie'


class TestLogout:
    """Tests de la route /logout."""

    def test_logout_nettoie_session(self, auth_client):
        """Après logout, la session doit être vidée."""
        with auth_client:
            response = auth_client.get('/logout', follow_redirects=True)
            assert response.status_code == 200
            from flask import session
            assert 'user_id' not in session

    def test_logout_redirige_vers_login(self, auth_client):
        """Logout doit rediriger vers la page de connexion."""
        response = auth_client.get('/logout', follow_redirects=False)
        assert response.status_code == 302
        assert '/login' in response.headers['Location']


class TestIndexRedirection:
    """Tests de la redirection depuis /."""

    def test_index_non_connecte_sans_users(self, client):
        """Sans utilisateurs => redirigé vers /setup."""
        response = client.get('/', follow_redirects=False)
        assert response.status_code == 302
        assert '/setup' in response.headers['Location']

    def test_index_non_connecte_avec_users(self, client, sample_users):
        """Non connecté mais des utilisateurs existent => redirigé vers /login."""
        response = client.get('/', follow_redirects=False)
        assert response.status_code == 302
        assert '/login' in response.headers['Location']

    def test_index_salarie_connecte(self, auth_client):
        """Salarié connecté => redirigé vers /dashboard."""
        response = auth_client.get('/', follow_redirects=False)
        assert response.status_code == 302
        assert '/dashboard' in response.headers['Location']


class TestProtectionRoutes:
    """Vérifie que les routes protégées redirigent vers login."""

    def test_dashboard_protege(self, client, sample_users):
        """Dashboard inaccessible sans login."""
        response = client.get('/dashboard', follow_redirects=False)
        assert response.status_code == 302
        assert '/login' in response.headers['Location']

    def test_saisie_protegee(self, client, sample_users):
        """Saisie d'heures inaccessible sans login."""
        response = client.get('/saisie_heures', follow_redirects=False)
        assert response.status_code == 302
        assert '/login' in response.headers['Location']


class TestSetup:
    """Tests de la route /setup (configuration initiale)."""

    def test_setup_accessible_sans_users(self, client):
        """La page de setup doit être accessible quand aucun utilisateur n'existe."""
        response = client.get('/setup')
        assert response.status_code == 200
        assert 'Configuration initiale' in response.data.decode('utf-8')

    def test_setup_redirige_si_users_existent(self, client, sample_users):
        """Si des utilisateurs existent, /setup redirige vers /login."""
        response = client.get('/setup', follow_redirects=False)
        assert response.status_code == 302
        assert '/login' in response.headers['Location']

    def test_login_redirige_vers_setup_sans_users(self, client):
        """Si aucun utilisateur, /login redirige vers /setup."""
        response = client.get('/login', follow_redirects=False)
        assert response.status_code == 302
        assert '/setup' in response.headers['Location']

    def test_setup_creation_admin(self, client):
        """Créer un admin via le setup => redirige vers login avec message de succès."""
        response = client.post('/setup', data={
            'nom': 'Dupont',
            'prenom': 'Jean',
            'login': 'jdupont',
            'password': 'Motdepasse1',
            'password_confirm': 'Motdepasse1',
        }, follow_redirects=True)
        assert response.status_code == 200
        content = response.data.decode('utf-8')
        assert 'Compte administrateur' in content

    def test_setup_password_faible_refuse(self, client):
        """Un mot de passe trop faible doit être refusé."""
        response = client.post('/setup', data={
            'nom': 'Dupont',
            'prenom': 'Jean',
            'login': 'jdupont',
            'password': 'abc',
            'password_confirm': 'abc',
        }, follow_redirects=True)
        content = response.data.decode('utf-8')
        assert '8 caract' in content

    def test_setup_passwords_differents_refuse(self, client):
        """Des mots de passe différents doivent être refusés."""
        response = client.post('/setup', data={
            'nom': 'Dupont',
            'prenom': 'Jean',
            'login': 'jdupont',
            'password': 'Motdepasse1',
            'password_confirm': 'Motdepasse2',
        }, follow_redirects=True)
        content = response.data.decode('utf-8')
        assert 'ne correspondent pas' in content

    def test_setup_profil_directeur(self, client, db):
        """Le compte créé via setup doit avoir le profil directeur."""
        client.post('/setup', data={
            'nom': 'Dupont',
            'prenom': 'Jean',
            'login': 'jdupont',
            'password': 'Motdepasse1',
            'password_confirm': 'Motdepasse1',
        })
        user = db.execute("SELECT profil FROM users WHERE login = 'jdupont'").fetchone()
        assert user is not None
        assert user['profil'] == 'directeur'
