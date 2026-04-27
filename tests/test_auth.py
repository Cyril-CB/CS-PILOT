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

    def test_login_avec_changement_mdp_obligatoire(self, client, app, db, sample_users):
        """Un utilisateur avec changement obligatoire est redirigé vers la page dédiée."""
        from werkzeug.security import generate_password_hash

        with app.app_context():
            db.execute(
                '''
                INSERT INTO users (nom, prenom, login, password, profil, force_password_change, email)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ''',
                ('Temp', 'User', 'temp_user', generate_password_hash('Temporaire!'), 'salarie', 1, 'temp@example.com')
            )
            db.commit()

        response = client.post('/login', data={
            'login': 'temp_user',
            'password': 'Temporaire!',
        }, follow_redirects=False)
        assert response.status_code == 302
        assert '/changer_mot_de_passe' in response.headers['Location']


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
            'password': 'Motdepasse!',
            'password_confirm': 'Motdepasse!',
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
            'password': 'Motdepasse!',
            'password_confirm': 'Motdepasse2!',
        }, follow_redirects=True)
        content = response.data.decode('utf-8')
        assert 'ne correspondent pas' in content

    def test_setup_profil_directeur(self, client, db):
        """Le compte créé via setup doit avoir le profil directeur."""
        client.post('/setup', data={
            'nom': 'Dupont',
            'prenom': 'Jean',
            'login': 'jdupont',
            'password': 'Motdepasse!',
            'password_confirm': 'Motdepasse!',
        })
        user = db.execute("SELECT profil FROM users WHERE login = 'jdupont'").fetchone()
        assert user is not None
        assert user['profil'] == 'directeur'


class TestChangementMotDePasse:
    """Tests du changement obligatoire de mot de passe."""

    def test_route_forcee_depuis_dashboard(self, client, app, db):
        from werkzeug.security import generate_password_hash

        with app.app_context():
            db.execute(
                '''
                INSERT INTO users (nom, prenom, login, password, profil, force_password_change)
                VALUES (?, ?, ?, ?, ?, ?)
                ''',
                ('Temp', 'User', 'temp_user', generate_password_hash('Temporaire!'), 'salarie', 1)
            )
            db.commit()

        client.post('/login', data={'login': 'temp_user', 'password': 'Temporaire!'}, follow_redirects=False)
        response = client.get('/dashboard', follow_redirects=False)
        assert response.status_code == 302
        assert '/changer_mot_de_passe' in response.headers['Location']

    def test_changement_mot_de_passe_reussi(self, client, app, db):
        from werkzeug.security import generate_password_hash

        with app.app_context():
            db.execute(
                '''
                INSERT INTO users (nom, prenom, login, password, profil, force_password_change)
                VALUES (?, ?, ?, ?, ?, ?)
                ''',
                ('Temp', 'User', 'temp_user', generate_password_hash('Temporaire!'), 'salarie', 1)
            )
            db.commit()

        client.post('/login', data={'login': 'temp_user', 'password': 'Temporaire!'}, follow_redirects=False)
        response = client.post('/changer_mot_de_passe', data={
            'current_password': 'Temporaire!',
            'new_password': 'Nouveau!Pass',
            'password_confirm': 'Nouveau!Pass',
        }, follow_redirects=False)
        assert response.status_code == 302
        assert '/dashboard' in response.headers['Location']

        user = db.execute(
            'SELECT force_password_change FROM users WHERE login = ?',
            ('temp_user',)
        ).fetchone()
        assert user['force_password_change'] == 0

        client.get('/logout')
        relogin = client.post('/login', data={'login': 'temp_user', 'password': 'Nouveau!Pass'}, follow_redirects=False)
        assert relogin.status_code == 302
        assert '/dashboard' in relogin.headers['Location']


class TestMotDePasseOublie:
    """Tests du parcours mot de passe oublié."""

    def test_page_mot_de_passe_oublie_accessible(self, client, sample_users):
        response = client.get('/mot-de-passe-oublie')
        assert response.status_code == 200
        assert 'Mot de passe oublié' in response.get_data(as_text=True)

    def test_reinitialisation_envoie_mot_de_passe_temporaire(self, client, app, db, sample_users, monkeypatch):
        sent = {}

        with app.app_context():
            db.execute(
                "UPDATE users SET email = ? WHERE login = ?",
                ('salarie@example.com', 'salarie_test')
            )
            db.commit()

        monkeypatch.setattr('blueprints.auth.is_email_configured', lambda: True)

        def fake_send_email(destinataire, sujet, contenu_html, destinataire_prenom=''):
            sent['destinataire'] = destinataire
            sent['contenu_html'] = contenu_html
            return True, 'ok'

        monkeypatch.setattr('blueprints.auth.envoyer_email', fake_send_email)

        response = client.post('/mot-de-passe-oublie', data={'login': 'salarie_test'}, follow_redirects=True)
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert 'mot de passe temporaire' in html
        assert sent['destinataire'] == 'salarie@example.com'

        user = db.execute(
            'SELECT force_password_change FROM users WHERE login = ?',
            ('salarie_test',)
        ).fetchone()
        assert user['force_password_change'] == 1

    def test_reinitialisation_inconnue_reste_generique(self, client, sample_users, monkeypatch):
        monkeypatch.setattr('blueprints.auth.is_email_configured', lambda: True)
        monkeypatch.setattr('blueprints.auth.envoyer_email', lambda *args, **kwargs: (True, 'ok'))

        response = client.post('/mot-de-passe-oublie', data={'login': 'inconnu'}, follow_redirects=True)
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert 'mot de passe temporaire' in html


class TestGestionVacances:
    """Tests de la page /gestion_vacances."""

    def test_duree_periode_vacances_calculee_sur_plage_complete(self, app, db, admin_client):
        """La durée doit être calculée avec les dates complètes, même en changeant de mois."""
        with app.app_context():
            db.execute(
                '''
                INSERT INTO periodes_vacances (nom, date_debut, date_fin, created_by)
                VALUES (?, ?, ?, ?)
                ''',
                ('Vacances d\'hiver 2024', '2024-02-19', '2024-03-01', 1)
            )
            db.commit()

        response = admin_client.get('/gestion_vacances')
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert 'Vacances d&#39;hiver 2024' in html
        assert '12 jours' in html
        assert '-17 jours' not in html
