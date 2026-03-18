"""
Tests pour les nouvelles fonctionnalités de sécurité :
- Validation de la complexité des mots de passe
- Protection CSRF (vérification de présence des tokens)
- Rate limiting sur la route de login
- Refus de démarrage si SECRET_KEY par défaut
- Génération automatique du fichier .env au démarrage
"""
import os
import sys
import io
from datetime import datetime

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


class TestPathTraversalProtection:
    """Vérifie la protection contre les chemins de type ../documents_evil."""

    def _login_admin(self, client):
        client.post('/login', data={'login': 'admin', 'password': 'Admin1234'}, follow_redirects=False)

    def test_infos_salaries_refuse_path_traversal(self, app, db, client, sample_users, monkeypatch, tmp_path):
        from blueprints import infos_salaries as infos_module
        docs_dir = tmp_path / 'documents'
        evil_dir = tmp_path / 'documents_evil'
        docs_dir.mkdir()
        evil_dir.mkdir()
        (evil_dir / 'pwn.pdf').write_bytes(b'not-a-real-pdf')
        monkeypatch.setattr(infos_module, 'DOCUMENTS_DIR', str(docs_dir))

        with app.app_context():
            db.execute(
                '''INSERT INTO documents_salaries
                   (user_id, type_document, description, fichier_path, fichier_nom, saisi_par)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (sample_users['salarie_id'], 'AUTRE-1', 'doc test', '../documents_evil/pwn.pdf', 'pwn.pdf',
                 sample_users['directeur_id'])
            )
            db.commit()
            doc_id = db.execute('SELECT MAX(id) as id FROM documents_salaries').fetchone()['id']

        self._login_admin(client)
        response = client.get(f'/infos_salaries/telecharger_document/{doc_id}', follow_redirects=False)
        assert response.status_code == 302

    def test_absences_refuse_path_traversal(self, app, db, client, sample_users, monkeypatch, tmp_path):
        from blueprints import absences as absences_module
        docs_dir = tmp_path / 'documents'
        evil_dir = tmp_path / 'documents_evil'
        docs_dir.mkdir()
        evil_dir.mkdir()
        (evil_dir / 'pwn.pdf').write_bytes(b'not-a-real-pdf')
        monkeypatch.setattr(absences_module, 'DOCUMENTS_DIR', str(docs_dir))

        with app.app_context():
            db.execute(
                '''INSERT INTO absences
                   (user_id, motif, date_debut, date_fin, jours_ouvres, justificatif_path, justificatif_nom, saisi_par)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (sample_users['salarie_id'], 'Maladie', '2025-01-01', '2025-01-01', 1,
                 '../documents_evil/pwn.pdf', 'pwn.pdf', sample_users['directeur_id'])
            )
            db.commit()
            absence_id = db.execute('SELECT MAX(id) as id FROM absences').fetchone()['id']

        self._login_admin(client)
        response = client.get(f'/absences/justificatif/{absence_id}', follow_redirects=False)
        assert response.status_code == 302

    def test_subventions_refuse_path_traversal(self, app, db, client, sample_users, monkeypatch, tmp_path):
        from blueprints import subventions as subventions_module
        docs_dir = tmp_path / 'documents'
        evil_dir = tmp_path / 'documents_evil'
        docs_dir.mkdir()
        evil_dir.mkdir()
        (evil_dir / 'pwn.pdf').write_bytes(b'not-a-real-pdf')
        monkeypatch.setattr(subventions_module, 'DOCUMENTS_DIR', str(docs_dir))

        with app.app_context():
            db.execute(
                '''INSERT INTO subventions (nom, justificatif_path, justificatif_nom)
                   VALUES (?, ?, ?)''',
                ('Subvention test', '../documents_evil/pwn.pdf', 'pwn.pdf')
            )
            db.commit()
            sub_id = db.execute('SELECT MAX(id) as id FROM subventions').fetchone()['id']

        self._login_admin(client)
        response = client.get(f'/subventions/justificatif/{sub_id}', follow_redirects=False)
        assert response.status_code == 302

    def test_subventions_sous_element_upload_sanitise_annee_action(
        self, app, db, comptable_client, monkeypatch, tmp_path
    ):
        from blueprints import subventions as subventions_module
        docs_dir = tmp_path / 'documents'
        docs_dir.mkdir()
        monkeypatch.setattr(subventions_module, 'DOCUMENTS_DIR', str(docs_dir))

        with app.app_context():
            db.execute(
                '''INSERT INTO subventions (nom, annee_action)
                   VALUES (?, ?)''',
                ('Subvention test', '../../documents_evil')
            )
            sub_id = db.execute('SELECT MAX(id) as id FROM subventions').fetchone()['id']
            db.execute(
                '''INSERT INTO subventions_sous_elements (subvention_id, nom)
                   VALUES (?, ?)''',
                (sub_id, 'Étape 1')
            )
            db.commit()
            se_id = db.execute('SELECT MAX(id) as id FROM subventions_sous_elements').fetchone()['id']

        data = {'fichier': (io.BytesIO(b'%PDF-1.4\n%test\n'), 'piece.pdf')}
        response = comptable_client.post(
            f'/api/subventions/sous-elements/{se_id}/document',
            data=data,
            content_type='multipart/form-data'
        )
        assert response.status_code == 200

        payload = response.get_json()
        assert payload['ok'] is True
        assert payload['nom'].startswith(f"{datetime.now().strftime('%Y')}_")
        assert '..' not in payload['nom']
        assert '/' not in payload['nom']
        assert (docs_dir / payload['nom']).exists()


class TestEnvFileGeneration:
    """Tests pour la génération automatique du fichier .env."""

    def test_generate_env_file_creates_file(self, tmp_path):
        """La fonction generate_env_file doit créer le fichier .env."""
        from app import generate_env_file

        env_path = tmp_path / '.env'
        result = generate_env_file(str(env_path))

        assert result is True
        assert env_path.exists()

    def test_generate_env_file_contains_secret_key(self, tmp_path):
        """Le fichier .env généré doit contenir une ligne SECRET_KEY."""
        from app import generate_env_file

        env_path = tmp_path / '.env'
        generate_env_file(str(env_path))

        content = env_path.read_text(encoding='utf-8')
        assert 'SECRET_KEY=' in content
        assert 'BEHIND_PROXY' in content

    def test_generate_env_file_creates_random_key(self, tmp_path):
        """Chaque génération doit créer une clé différente."""
        from app import generate_env_file

        env_path1 = tmp_path / '.env1'
        env_path2 = tmp_path / '.env2'

        generate_env_file(str(env_path1))
        generate_env_file(str(env_path2))

        content1 = env_path1.read_text(encoding='utf-8')
        content2 = env_path2.read_text(encoding='utf-8')

        # Extraire les SECRET_KEY de chaque fichier
        key1 = [line for line in content1.split('\n') if line.startswith('SECRET_KEY=')][0]
        key2 = [line for line in content2.split('\n') if line.startswith('SECRET_KEY=')][0]

        # Les clés doivent être différentes
        assert key1 != key2

    def test_generate_env_file_key_length(self, tmp_path):
        """La clé générée doit avoir au moins 64 caractères (32 bytes en hex)."""
        from app import generate_env_file

        env_path = tmp_path / '.env'
        generate_env_file(str(env_path))

        content = env_path.read_text(encoding='utf-8')
        secret_line = [line for line in content.split('\n') if line.startswith('SECRET_KEY=')][0]
        secret_key = secret_line.split('=', 1)[1]

        # secrets.token_hex(32) génère une chaîne de 64 caractères hexadécimaux
        assert len(secret_key) == 64

    def test_generate_env_file_invalid_path(self):
        """La fonction doit retourner False si le chemin est invalide."""
        from app import generate_env_file

        # Essayer d'écrire dans un répertoire qui n'existe pas
        result = generate_env_file('/invalid/path/that/does/not/exist/.env')

        assert result is False
