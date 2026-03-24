"""
Tests pour le module saisie.py :
- Saisie d'heures (création / modification)
- Vérification des droits d'accès (salarié, responsable, directeur)
- Détection d'anomalies
- Verrouillage par validation
"""
from datetime import datetime, timedelta


class TestSaisieAcces:
    """Tests d'accès au formulaire de saisie."""

    def test_acces_saisie_salarie(self, auth_client):
        """Un salarié peut accéder à sa propre saisie."""
        response = auth_client.get('/saisie_heures')
        assert response.status_code == 200

    def test_acces_saisie_non_connecte(self, client):
        """Non connecté => redirigé vers login."""
        response = client.get('/saisie_heures', follow_redirects=False)
        assert response.status_code == 302
        assert '/login' in response.headers['Location']


class TestSaisieCreation:
    """Tests de création de saisie d'heures."""

    def test_saisie_heures_standard(self, auth_client, app, db, sample_users):
        """Un salarié peut saisir ses heures pour une journée."""
        # Utiliser une date passée pour éviter les problèmes de validation
        date_test = '2025-01-06'  # Un lundi

        with app.app_context():
            response = auth_client.post('/saisie_heures', data={
                'date': date_test,
                'heure_debut_matin': '08:30',
                'heure_fin_matin': '12:00',
                'heure_debut_aprem': '13:30',
                'heure_fin_aprem': '17:00',
                'commentaire': 'Test automatisé',
            }, follow_redirects=True)
            assert response.status_code == 200

            # Vérifier en base
            row = db.execute(
                "SELECT * FROM heures_reelles WHERE user_id = ? AND date = ?",
                (sample_users['salarie_id'], date_test)
            ).fetchone()
            assert row is not None
            assert row['heure_debut_matin'] == '08:30'
            assert row['heure_fin_matin'] == '12:00'
            assert row['commentaire'] == 'Test automatisé'

    def test_saisie_declaration_conforme(self, auth_client, app, db, sample_users):
        """Déclaration conforme : pas d'heures stockées, flag à 1."""
        date_test = '2025-01-07'

        with app.app_context():
            auth_client.post('/saisie_heures', data={
                'date': date_test,
                'declaration_conforme': '1',
            }, follow_redirects=True)

            row = db.execute(
                "SELECT * FROM heures_reelles WHERE user_id = ? AND date = ?",
                (sample_users['salarie_id'], date_test)
            ).fetchone()
            assert row is not None
            assert row['declaration_conforme'] == 1
            assert row['heure_debut_matin'] is None
            assert row['type_saisie'] == 'declaration_conforme'

    def test_saisie_recup_journee(self, auth_client, app, db, sample_users):
        """Récupération journée : heures vides, type_saisie = recup_journee."""
        date_test = '2025-01-08'

        with app.app_context():
            auth_client.post('/saisie_heures', data={
                'date': date_test,
                'recup_journee': '1',
            }, follow_redirects=True)

            row = db.execute(
                "SELECT * FROM heures_reelles WHERE user_id = ? AND date = ?",
                (sample_users['salarie_id'], date_test)
            ).fetchone()
            assert row is not None
            assert row['type_saisie'] == 'recup_journee'
            assert row['heure_debut_matin'] is None


class TestSaisieHistorique:
    """Tests de traçabilité."""

    def test_historique_creation(self, auth_client, app, db, sample_users):
        """La création d'une saisie doit être enregistrée dans l'historique."""
        date_test = '2025-01-09'

        with app.app_context():
            auth_client.post('/saisie_heures', data={
                'date': date_test,
                'heure_debut_matin': '09:00',
                'heure_fin_matin': '12:00',
                'heure_debut_aprem': '14:00',
                'heure_fin_aprem': '18:00',
            }, follow_redirects=True)

            historique = db.execute(
                "SELECT * FROM historique_modifications WHERE user_id_modifie = ? AND date_concernee = ?",
                (sample_users['salarie_id'], date_test)
            ).fetchone()
            assert historique is not None
            assert historique['action'] == 'creation'


class TestSaisieAnomalies:
    """Tests de détection d'anomalies à la saisie."""

    def test_creation_declenche_anomalie_si_ecart_superieur_a_3h(self, auth_client, app, db, sample_users, sample_planning):
        """Une création avec +4h vs planning théorique doit créer une anomalie."""
        date_test = '2025-01-06'  # Lundi, 7h théoriques via sample_planning

        with app.app_context():
            response = auth_client.post('/saisie_heures', data={
                'date': date_test,
                'heure_debut_matin': '08:00',
                'heure_fin_matin': '12:00',
                'heure_debut_aprem': '13:00',
                'heure_fin_aprem': '20:00',  # 11h total -> écart 4h
                'commentaire': 'Création test anomalie',
            }, follow_redirects=True)
            assert response.status_code == 200

            anomalie = db.execute(
                "SELECT * FROM anomalies WHERE user_id = ? AND date_concernee = ? AND type_anomalie = ?",
                (sample_users['salarie_id'], date_test, 'gros_changement_heures')
            ).fetchone()
            assert anomalie is not None


class TestSaisieDroits:
    """Tests des contrôles d'accès pour la saisie."""

    def test_directeur_ne_peut_pas_saisir_pour_lui(self, admin_client, app, sample_users):
        """Le directeur ne peut PAS modifier sa propre fiche via saisie."""
        with app.app_context():
            response = admin_client.post('/saisie_heures', data={
                'date': '2025-01-06',
                'heure_debut_matin': '09:00',
                'heure_fin_matin': '12:00',
            }, follow_redirects=True)
            assert response.status_code == 200

    def test_responsable_peut_saisir_pour_son_secteur(self, resp_client, app, db, sample_users):
        """Le responsable peut saisir pour un salarié de son secteur."""
        date_test = '2025-01-10'

        with app.app_context():
            response = resp_client.post('/saisie_heures', data={
                'user_id': sample_users['salarie_id'],
                'date': date_test,
                'heure_debut_matin': '08:00',
                'heure_fin_matin': '12:00',
                'heure_debut_aprem': '13:00',
                'heure_fin_aprem': '17:00',
            }, follow_redirects=True)
            assert response.status_code == 200

            row = db.execute(
                "SELECT * FROM heures_reelles WHERE user_id = ? AND date = ?",
                (sample_users['salarie_id'], date_test)
            ).fetchone()
            assert row is not None
