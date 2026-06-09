"""
Tests du module securite :
- Journalisation des evenements d'acces (connexion reussie/echouee,
  reinitialisation demandee, mot de passe modifie)
- Page de consultation du journal (reservee a la direction)
- Export CSV
- Presence du menu "Securite" dans l'administration du directeur
"""


def _derniere_entree(db, evenement):
    """Retourne la derniere entree du journal pour un evenement donne."""
    return db.execute(
        "SELECT * FROM journal_acces WHERE evenement = ? ORDER BY id DESC LIMIT 1",
        (evenement,)
    ).fetchone()


class TestJournalisationAcces:
    """Verifie que les evenements d'acces sont enregistres dans le journal."""

    def test_connexion_reussie_journalisee(self, client, app, db, sample_users):
        client.post('/login', data={'login': 'admin', 'password': 'Admin1234'})
        with app.app_context():
            entry = _derniere_entree(db, 'connexion_reussie')
        assert entry is not None
        assert entry['login_saisi'] == 'admin'
        assert entry['user_id'] == sample_users['directeur_id']

    def test_echec_connexion_journalise(self, client, app, db, sample_users):
        client.post('/login', data={'login': 'admin', 'password': 'mauvais_mdp'})
        with app.app_context():
            entry = _derniere_entree(db, 'echec_connexion')
        assert entry is not None
        assert entry['login_saisi'] == 'admin'
        assert entry['user_id'] is None

    def test_echec_connexion_utilisateur_inconnu_journalise(self, client, app, db, sample_users):
        client.post('/login', data={'login': 'inconnu', 'password': 'peu_importe'})
        with app.app_context():
            entry = _derniere_entree(db, 'echec_connexion')
        assert entry is not None
        assert entry['login_saisi'] == 'inconnu'

    def test_changement_mot_de_passe_journalise(self, client, app, db, sample_users):
        from werkzeug.security import generate_password_hash

        with app.app_context():
            db.execute(
                "INSERT INTO users (nom, prenom, login, password, profil, force_password_change) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ('Temp', 'User', 'temp_user', generate_password_hash('Temporaire!'), 'salarie', 1)
            )
            db.commit()

        client.post('/login', data={'login': 'temp_user', 'password': 'Temporaire!'})
        client.post('/changer_mot_de_passe', data={
            'current_password': 'Temporaire!',
            'new_password': 'Nouveau!Pass',
            'password_confirm': 'Nouveau!Pass',
        })

        with app.app_context():
            entry = _derniere_entree(db, 'mot_de_passe_modifie')
        assert entry is not None
        assert entry['login_saisi'] == 'temp_user'

    def test_reinitialisation_demandee_journalisee(self, client, app, db, sample_users, monkeypatch):
        with app.app_context():
            db.execute(
                "UPDATE users SET email = ? WHERE login = ?",
                ('salarie@example.com', 'salarie_test')
            )
            db.commit()

        monkeypatch.setattr('blueprints.auth.is_email_configured', lambda: True)
        monkeypatch.setattr('blueprints.auth.envoyer_email', lambda *a, **k: (True, 'ok'))

        client.post('/mot-de-passe-oublie', data={'login': 'salarie_test'})

        with app.app_context():
            entry = _derniere_entree(db, 'reinitialisation_demandee')
        assert entry is not None
        assert entry['login_saisi'] == 'salarie_test'


class TestPageJournalAcces:
    """Verifie le controle d'acces et l'affichage de la page du journal."""

    def test_acces_directeur_ok(self, admin_client):
        response = admin_client.get('/securite/journal-acces')
        assert response.status_code == 200
        assert 'Journal des accès' in response.get_data(as_text=True)

    def test_acces_refuse_salarie(self, auth_client):
        response = auth_client.get('/securite/journal-acces', follow_redirects=False)
        assert response.status_code == 302

    def test_acces_refuse_comptable(self, comptable_client):
        response = comptable_client.get('/securite/journal-acces', follow_redirects=False)
        assert response.status_code == 302

    def test_acces_refuse_non_connecte(self, client, sample_users):
        response = client.get('/securite/journal-acces', follow_redirects=False)
        assert response.status_code == 302
        assert '/login' in response.headers['Location']

    def test_affiche_connexion_reussie(self, admin_client):
        # admin_client s'est connecte : une entree "connexion reussie" existe
        response = admin_client.get('/securite/journal-acces')
        html = response.get_data(as_text=True)
        assert 'Connexion réussie' in html
        assert 'admin' in html

    def test_filtre_par_evenement(self, admin_client):
        response = admin_client.get('/securite/journal-acces?evenement=echec_connexion')
        assert response.status_code == 200


class TestExportJournalAcces:
    """Verifie l'export CSV du journal."""

    def test_export_directeur_ok(self, admin_client):
        response = admin_client.get('/securite/journal-acces/export')
        assert response.status_code == 200
        assert 'text/csv' in response.content_type
        disposition = response.headers.get('Content-Disposition', '')
        assert 'attachment' in disposition
        assert '.csv' in disposition
        body = response.get_data(as_text=True)
        assert 'Date et heure' in body

    def test_export_refuse_salarie(self, auth_client):
        response = auth_client.get('/securite/journal-acces/export', follow_redirects=False)
        assert response.status_code == 302


class TestMenuSecurite:
    """Verifie la presence du menu Securite selon le profil."""

    def test_lien_present_pour_directeur(self, admin_client):
        html = admin_client.get('/securite/journal-acces').get_data(as_text=True)
        assert '🔒 Sécurité' in html
        assert url_securite() in html

    def test_lien_absent_pour_comptable(self, comptable_client):
        html = comptable_client.get('/dashboard_comptable').get_data(as_text=True)
        assert '🔒 Sécurité' not in html


def url_securite():
    """URL de la page du journal des acces (pour les assertions de menu)."""
    return '/securite/journal-acces'
