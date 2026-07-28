"""
Tests de la limite de taille des envois de fichiers (MAX_CONTENT_LENGTH).

L'application compte une dizaine de points d'entrée de fichiers (justificatifs
d'absence, contrats, modèles DOCX, imports comptables, lots de factures PDF).
Sans borne, un envoi de taille arbitraire peut saturer la mémoire ou le disque
du serveur. La limite est volontairement très large (256 Mo par défaut) pour ne
pénaliser aucun usage réel ; ces tests vérifient qu'elle est bien appliquée et
que le dépassement produit une réponse française exploitable (JSON 413 pour les
routes d'API, message flash + redirection pour les formulaires classiques).

Pour rester rapides et déterministes, les tests de dépassement abaissent
temporairement `app.config['MAX_CONTENT_LENGTH']` au lieu de fabriquer un
fichier de 256 Mo.
"""
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


# Limite basse utilisée pour provoquer le dépassement sans gros fichier.
LIMITE_TEST_OCTETS = 2 * 1024          # 2 Ko
PDF_TROP_GROS = b'%PDF-1.4\n' + b'x' * (8 * 1024)   # ~8 Ko : au-dessus
PDF_NORMAL = b'%PDF-1.4\n%justificatif de test\n'   # quelques octets


def _creer_sous_element(app, db, nom_subvention='Subvention test'):
    """Crée une subvention et son sous-élément, retourne l'id du sous-élément."""
    with app.app_context():
        db.execute(
            'INSERT INTO subventions (nom, annee_action) VALUES (?, ?)',
            (nom_subvention, '2026'),
        )
        sub_id = db.execute('SELECT MAX(id) AS id FROM subventions').fetchone()['id']
        db.execute(
            'INSERT INTO subventions_sous_elements (subvention_id, nom) VALUES (?, ?)',
            (sub_id, 'Étape 1'),
        )
        db.commit()
        return db.execute(
            'SELECT MAX(id) AS id FROM subventions_sous_elements'
        ).fetchone()['id']


def _limite_configuree_octets():
    """Limite attendue en octets, d'après la configuration de l'exécution.

    La valeur dépend de `MAX_UPLOAD_MO` : on la relit au lieu de coder 256 Mo
    en dur, afin que les tests restent valides quand un déploiement (ou la CI)
    surcharge la variable d'environnement.
    """
    import app as app_module
    return app_module.lire_max_upload_mo() * 1024 * 1024


class TestConfigurationLimite:
    """La limite doit être définie, large et surchargeable."""

    def test_max_content_length_correspond_a_la_configuration(self, app):
        """La configuration expose la limite issue de `lire_max_upload_mo()`."""
        limite = app.config.get('MAX_CONTENT_LENGTH')
        assert limite is not None, "MAX_CONTENT_LENGTH doit être défini"
        assert limite == _limite_configuree_octets()

    def test_valeur_par_defaut_large_sans_surcharge(self, monkeypatch):
        """Sans `MAX_UPLOAD_MO`, la limite par défaut vaut 256 Mo."""
        import app as app_module

        monkeypatch.delenv('MAX_UPLOAD_MO', raising=False)
        assert app_module.MAX_UPLOAD_MO_DEFAUT == 256
        # Garde-fou : la valeur par défaut ne doit brider aucun envoi légitime.
        assert app_module.lire_max_upload_mo() * 1024 * 1024 >= 100 * 1024 * 1024

    def test_lecture_variable_environnement(self, monkeypatch):
        """MAX_UPLOAD_MO surcharge la valeur par défaut, avec repli sûr."""
        import app as app_module

        monkeypatch.setenv('MAX_UPLOAD_MO', '512')
        assert app_module.lire_max_upload_mo() == 512

        # Valeurs invalides : on retombe sur la valeur par défaut.
        for valeur_invalide in ('abc', '', '0', '-10', '12,5'):
            monkeypatch.setenv('MAX_UPLOAD_MO', valeur_invalide)
            assert app_module.lire_max_upload_mo() == app_module.MAX_UPLOAD_MO_DEFAUT

        monkeypatch.delenv('MAX_UPLOAD_MO', raising=False)
        assert app_module.lire_max_upload_mo() == app_module.MAX_UPLOAD_MO_DEFAUT


class TestDepassementLimite:
    """Un envoi trop volumineux doit produire une erreur 413 propre."""

    def test_api_retourne_413_json_en_francais(
        self, app, db, comptable_client, monkeypatch, tmp_path
    ):
        """Route d'API : JSON en 413 indiquant la taille maximale."""
        from blueprints import subventions as subventions_module
        docs_dir = tmp_path / 'documents'
        docs_dir.mkdir()
        monkeypatch.setattr(subventions_module, 'DOCUMENTS_DIR', str(docs_dir))

        se_id = _creer_sous_element(app, db)

        limite_initiale = app.config['MAX_CONTENT_LENGTH']
        app.config['MAX_CONTENT_LENGTH'] = LIMITE_TEST_OCTETS
        try:
            response = comptable_client.post(
                f'/api/subventions/sous-elements/{se_id}/document',
                data={'fichier': (io.BytesIO(PDF_TROP_GROS), 'volumineux.pdf')},
                content_type='multipart/form-data',
            )
        finally:
            app.config['MAX_CONTENT_LENGTH'] = limite_initiale

        assert response.status_code == 413
        payload = response.get_json()
        assert payload is not None, "La réponse d'API doit rester du JSON"
        assert payload['ok'] is False
        message = payload['error']
        assert 'volumineux' in message.lower()
        assert 'dépasser' in message
        assert '2 Ko' in message, f"Le message doit rappeler la limite : {message}"
        # Aucun fichier ne doit avoir été écrit sur le disque.
        assert list(docs_dir.iterdir()) == []

    def test_formulaire_classique_flash_et_redirection(
        self, app, db, comptable_client, sample_users, monkeypatch, tmp_path
    ):
        """Formulaire classique : message flash français puis redirection."""
        from blueprints import absences as absences_module
        docs_dir = tmp_path / 'documents_absences'
        docs_dir.mkdir()
        monkeypatch.setattr(absences_module, 'DOCUMENTS_DIR', str(docs_dir))

        donnees = {
            'user_id': str(sample_users['salarie_id']),
            'motif': 'Maladie',
            'date_debut': '2026-03-02',
            'date_fin': '2026-03-06',
            'justificatif': (io.BytesIO(PDF_TROP_GROS), 'arret.pdf'),
        }

        limite_initiale = app.config['MAX_CONTENT_LENGTH']
        app.config['MAX_CONTENT_LENGTH'] = LIMITE_TEST_OCTETS
        try:
            response = comptable_client.post(
                '/absences', data=donnees,
                content_type='multipart/form-data',
                headers={'Referer': 'http://localhost/absences'},
                follow_redirects=False,
            )
            assert response.status_code == 302, (
                "Un formulaire classique doit être redirigé (Post/Redirect/Get) "
                "et non recevoir une erreur brute"
            )
            # La redirection vise le tableau de bord : l'en-tête Referer,
            # contrôlé par le client, n'est jamais utilisé comme cible.
            assert response.headers['Location'].endswith('/dashboard')
            suite = comptable_client.get('/dashboard', follow_redirects=True)
        finally:
            app.config['MAX_CONTENT_LENGTH'] = limite_initiale

        contenu = suite.get_data(as_text=True)
        assert 'Envoi trop volumineux' in contenu
        assert '2 Ko' in contenu
        # Aucune absence ni aucun fichier ne doit avoir été enregistré.
        assert list(docs_dir.iterdir()) == []
        with app.app_context():
            nb = db.execute('SELECT COUNT(*) AS nb FROM absences').fetchone()['nb']
        assert nb == 0

    def test_aucune_trace_technique_dans_la_reponse(
        self, app, db, comptable_client, monkeypatch, tmp_path
    ):
        """La réponse ne doit révéler ni exception ni chemin local."""
        from blueprints import subventions as subventions_module
        docs_dir = tmp_path / 'documents'
        docs_dir.mkdir()
        monkeypatch.setattr(subventions_module, 'DOCUMENTS_DIR', str(docs_dir))

        se_id = _creer_sous_element(app, db)

        limite_initiale = app.config['MAX_CONTENT_LENGTH']
        app.config['MAX_CONTENT_LENGTH'] = LIMITE_TEST_OCTETS
        try:
            response = comptable_client.post(
                f'/api/subventions/sous-elements/{se_id}/document',
                data={'fichier': (io.BytesIO(PDF_TROP_GROS), 'volumineux.pdf')},
                content_type='multipart/form-data',
            )
        finally:
            app.config['MAX_CONTENT_LENGTH'] = limite_initiale

        contenu = response.get_data(as_text=True)
        assert 'Traceback' not in contenu
        assert 'RequestEntityTooLarge' not in contenu
        assert str(tmp_path) not in contenu


class TestControleAccesLimite:
    """Tests négatifs : la limite ne contourne aucun contrôle d'autorisation."""

    def test_non_connecte_redirige_sans_erreur_technique(
        self, app, db, client, sample_users
    ):
        """Non connecté : redirection vers la connexion, jamais de 500."""
        se_id = _creer_sous_element(app, db)

        limite_initiale = app.config['MAX_CONTENT_LENGTH']
        app.config['MAX_CONTENT_LENGTH'] = LIMITE_TEST_OCTETS
        try:
            response = client.post(
                f'/api/subventions/sous-elements/{se_id}/document',
                data={'fichier': (io.BytesIO(PDF_TROP_GROS), 'volumineux.pdf')},
                content_type='multipart/form-data',
                follow_redirects=False,
            )
        finally:
            app.config['MAX_CONTENT_LENGTH'] = limite_initiale

        assert response.status_code in (302, 401, 413)
        assert response.status_code != 500

    def test_mauvais_profil_refuse_avant_la_limite(
        self, app, db, auth_client, sample_users
    ):
        """Salarié : l'accès reste refusé (403), la limite ne l'ouvre pas."""
        se_id = _creer_sous_element(app, db)

        limite_initiale = app.config['MAX_CONTENT_LENGTH']
        app.config['MAX_CONTENT_LENGTH'] = LIMITE_TEST_OCTETS
        try:
            response = auth_client.post(
                f'/api/subventions/sous-elements/{se_id}/document',
                data={'fichier': (io.BytesIO(PDF_TROP_GROS), 'volumineux.pdf')},
                content_type='multipart/form-data',
            )
        finally:
            app.config['MAX_CONTENT_LENGTH'] = limite_initiale

        assert response.status_code == 403
        payload = response.get_json()
        assert payload['ok'] is False

    def test_referer_externe_ignore(self, app, comptable_client, sample_users):
        """Un Referer externe ne sert jamais de cible de redirection.

        L'en-tête Referer n'est pas exploité du tout : la redirection vise
        toujours le tableau de bord (protection contre la redirection ouverte,
        signalée par l'analyse de code).
        """
        limite_initiale = app.config['MAX_CONTENT_LENGTH']
        app.config['MAX_CONTENT_LENGTH'] = LIMITE_TEST_OCTETS
        try:
            response = comptable_client.post(
                '/absences',
                data={
                    'user_id': str(sample_users['salarie_id']),
                    'motif': 'Maladie',
                    'date_debut': '2026-03-02',
                    'date_fin': '2026-03-06',
                    'justificatif': (io.BytesIO(PDF_TROP_GROS), 'arret.pdf'),
                },
                content_type='multipart/form-data',
                headers={'Referer': 'https://site-externe.invalid/piege'},
                follow_redirects=False,
            )
        finally:
            app.config['MAX_CONTENT_LENGTH'] = limite_initiale

        assert response.status_code == 302
        assert 'site-externe.invalid' not in response.headers['Location']


class TestEnvoiNormalToujoursAccepte:
    """La limite très large ne doit gêner aucun envoi légitime."""

    def test_petit_fichier_accepte_par_l_api(
        self, app, db, comptable_client, monkeypatch, tmp_path
    ):
        """Un PDF de taille normale passe toujours avec la limite par défaut."""
        from blueprints import subventions as subventions_module
        docs_dir = tmp_path / 'documents'
        docs_dir.mkdir()
        monkeypatch.setattr(subventions_module, 'DOCUMENTS_DIR', str(docs_dir))

        se_id = _creer_sous_element(app, db)

        assert app.config['MAX_CONTENT_LENGTH'] == _limite_configuree_octets()
        response = comptable_client.post(
            f'/api/subventions/sous-elements/{se_id}/document',
            data={'fichier': (io.BytesIO(PDF_NORMAL), 'piece.pdf')},
            content_type='multipart/form-data',
        )

        assert response.status_code == 200
        payload = response.get_json()
        assert payload['ok'] is True
        assert (docs_dir / payload['nom']).exists()

    def test_fichier_volumineux_mais_legitime_accepte(
        self, app, db, comptable_client, monkeypatch, tmp_path
    ):
        """Un PDF de plusieurs Mo (cas réel : scan de contrat) reste accepté."""
        from blueprints import subventions as subventions_module
        docs_dir = tmp_path / 'documents'
        docs_dir.mkdir()
        monkeypatch.setattr(subventions_module, 'DOCUMENTS_DIR', str(docs_dir))

        se_id = _creer_sous_element(app, db)

        pdf_5_mo = b'%PDF-1.4\n' + b'a' * (5 * 1024 * 1024)
        response = comptable_client.post(
            f'/api/subventions/sous-elements/{se_id}/document',
            data={'fichier': (io.BytesIO(pdf_5_mo), 'scan.pdf')},
            content_type='multipart/form-data',
        )

        assert response.status_code == 200
        payload = response.get_json()
        assert payload['ok'] is True
        assert (docs_dir / payload['nom']).stat().st_size == len(pdf_5_mo)


class TestFormatageTailleMaximale:
    """Le message doit annoncer la limite dans une unité lisible."""

    @pytest.mark.parametrize('limite,attendu', [
        (256 * 1024 * 1024, '256 Mo'),
        (512 * 1024 * 1024, '512 Mo'),
        (1536 * 1024, '1.5 Mo'),
        (2 * 1024, '2 Ko'),
    ])
    def test_taille_max_lisible(self, app, limite, attendu):
        import app as app_module

        limite_initiale = app.config['MAX_CONTENT_LENGTH']
        app.config['MAX_CONTENT_LENGTH'] = limite
        try:
            assert app_module._taille_max_lisible() == attendu
        finally:
            app.config['MAX_CONTENT_LENGTH'] = limite_initiale
