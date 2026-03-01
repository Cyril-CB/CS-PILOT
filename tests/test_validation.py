"""
Tests pour le module validation.py :
- Validation par salarié, responsable, directeur
- Verrouillage après double validation (responsable + directeur)
- Déverrouillage par directeur
- Contrôles d'accès sur la vue d'ensemble
"""
from datetime import datetime


def _creer_saisie_mois(db, user_id, mois, annee):
    """Helper : crée une saisie par jour ouvré du mois pour permettre la validation."""
    from datetime import timedelta
    premier_jour = datetime(annee, mois, 1)
    if mois == 12:
        dernier_jour = datetime(annee + 1, 1, 1) - timedelta(days=1)
    else:
        dernier_jour = datetime(annee, mois + 1, 1) - timedelta(days=1)

    jour = premier_jour
    while jour <= dernier_jour:
        if jour.weekday() < 5:  # Lundi à vendredi
            db.execute(
                """INSERT OR IGNORE INTO heures_reelles
                   (user_id, date, heure_debut_matin, heure_fin_matin,
                    heure_debut_aprem, heure_fin_aprem, type_saisie, declaration_conforme)
                   VALUES (?, ?, '08:30', '12:00', '13:30', '17:00', 'heures_modifiees', 0)""",
                (user_id, jour.strftime('%Y-%m-%d'))
            )
        jour += timedelta(days=1)
    db.commit()


class TestValidationMois:
    """Tests de la validation mensuelle."""

    def test_salarie_valide_sa_fiche(self, auth_client, app, db, sample_users):
        """Un salarié peut valider sa propre fiche pour un mois terminé."""
        # Utiliser un mois passé (décembre 2024)
        mois, annee = 12, 2024
        with app.app_context():
            _creer_saisie_mois(db, sample_users['salarie_id'], mois, annee)

            response = auth_client.post('/valider_mois', data={
                'user_id': sample_users['salarie_id'],
                'mois': mois,
                'annee': annee,
            }, follow_redirects=True)
            assert response.status_code == 200

            validation = db.execute(
                "SELECT * FROM validations WHERE user_id = ? AND mois = ? AND annee = ?",
                (sample_users['salarie_id'], mois, annee)
            ).fetchone()
            assert validation is not None
            assert validation['validation_salarie'] is not None
            assert validation['bloque'] == 0  # Pas encore verrouillé

    def test_responsable_valide_fiche_secteur(self, resp_client, app, db, sample_users):
        """Un responsable peut valider la fiche d'un salarié de son secteur."""
        mois, annee = 11, 2024
        with app.app_context():
            _creer_saisie_mois(db, sample_users['salarie_id'], mois, annee)

            response = resp_client.post('/valider_mois', data={
                'user_id': sample_users['salarie_id'],
                'mois': mois,
                'annee': annee,
            }, follow_redirects=True)
            assert response.status_code == 200

            validation = db.execute(
                "SELECT * FROM validations WHERE user_id = ? AND mois = ? AND annee = ?",
                (sample_users['salarie_id'], mois, annee)
            ).fetchone()
            assert validation is not None
            assert validation['validation_responsable'] is not None

    def test_verrouillage_double_validation(self, app, db, sample_users):
        """La fiche est verrouillée quand responsable ET directeur ont validé."""
        mois, annee = 10, 2024
        with app.app_context():
            _creer_saisie_mois(db, sample_users['salarie_id'], mois, annee)

            # Client 1 : responsable
            client_resp = app.test_client()
            client_resp.post('/login', data={'login': 'resp_test', 'password': 'resp123'})
            client_resp.post('/valider_mois', data={
                'user_id': sample_users['salarie_id'],
                'mois': mois,
                'annee': annee,
            }, follow_redirects=True)

            # Client 2 : directeur (session séparée)
            client_dir = app.test_client()
            client_dir.post('/login', data={'login': 'admin', 'password': 'Admin1234'})
            client_dir.post('/valider_mois', data={
                'user_id': sample_users['salarie_id'],
                'mois': mois,
                'annee': annee,
            }, follow_redirects=True)

            validation = db.execute(
                "SELECT * FROM validations WHERE user_id = ? AND mois = ? AND annee = ?",
                (sample_users['salarie_id'], mois, annee)
            ).fetchone()
            assert validation is not None
            assert validation['bloque'] == 1  # Verrouillé !

    def test_refus_validation_mois_en_cours(self, auth_client, app, db, sample_users):
        """On ne peut pas valider le mois en cours."""
        now = datetime.now()
        with app.app_context():
            response = auth_client.post('/valider_mois', data={
                'user_id': sample_users['salarie_id'],
                'mois': now.month,
                'annee': now.year,
            }, follow_redirects=True)
            assert response.status_code == 200
            assert 'Impossible de valider un mois en cours' in response.data.decode('utf-8')


class TestDeverrouillage:
    """Tests du déverrouillage par le directeur."""

    def test_directeur_deverrouille_avec_motif(self, admin_client, app, db, sample_users):
        """Le directeur peut déverrouiller une fiche avec un motif."""
        mois, annee = 9, 2024
        with app.app_context():
            # Créer une validation verrouillée manuellement
            db.execute(
                """INSERT INTO validations (user_id, mois, annee, validation_responsable,
                   validation_directeur, bloque) VALUES (?, ?, ?, 'Resp', 'Dir', 1)""",
                (sample_users['salarie_id'], mois, annee)
            )
            db.commit()

            response = admin_client.post('/deverrouiller_mois', data={
                'user_id': sample_users['salarie_id'],
                'mois': mois,
                'annee': annee,
                'motif': 'Correction demandée par le salarié',
            }, follow_redirects=True)
            assert response.status_code == 200

            # Vérifier que la validation a été supprimée
            validation = db.execute(
                "SELECT * FROM validations WHERE user_id = ? AND mois = ? AND annee = ?",
                (sample_users['salarie_id'], mois, annee)
            ).fetchone()
            assert validation is None

    def test_deverrouillage_sans_motif_refuse(self, admin_client, app, db, sample_users):
        """Le déverrouillage sans motif est refusé."""
        mois, annee = 8, 2024
        with app.app_context():
            db.execute(
                """INSERT INTO validations (user_id, mois, annee, validation_responsable,
                   validation_directeur, bloque) VALUES (?, ?, ?, 'Resp', 'Dir', 1)""",
                (sample_users['salarie_id'], mois, annee)
            )
            db.commit()

            response = admin_client.post('/deverrouiller_mois', data={
                'user_id': sample_users['salarie_id'],
                'mois': mois,
                'annee': annee,
                'motif': '',
            }, follow_redirects=True)
            assert response.status_code == 200
            assert 'Le motif est obligatoire' in response.data.decode('utf-8')

    def test_salarie_ne_peut_pas_deverrouiller(self, auth_client, app, db, sample_users):
        """Un salarié ne peut PAS déverrouiller une fiche."""
        mois, annee = 7, 2024
        with app.app_context():
            db.execute(
                """INSERT INTO validations (user_id, mois, annee, validation_responsable,
                   validation_directeur, bloque) VALUES (?, ?, ?, 'Resp', 'Dir', 1)""",
                (sample_users['salarie_id'], mois, annee)
            )
            db.commit()

            response = auth_client.post('/deverrouiller_mois', data={
                'user_id': sample_users['salarie_id'],
                'mois': mois,
                'annee': annee,
                'motif': 'Je veux modifier',
            }, follow_redirects=True)
            assert response.status_code == 200
            # Doit rester verrouillé
            validation = db.execute(
                "SELECT * FROM validations WHERE user_id = ? AND mois = ? AND annee = ?",
                (sample_users['salarie_id'], mois, annee)
            ).fetchone()
            assert validation is not None
            assert validation['bloque'] == 1


class TestVueEnsembleAcces:
    """Tests d'accès à la vue d'ensemble des validations."""

    def test_directeur_acces(self, admin_client):
        """Le directeur a accès à la vue d'ensemble."""
        response = admin_client.get('/vue_ensemble_validation')
        assert response.status_code == 200

    def test_salarie_refuse(self, auth_client):
        """Un salarié n'a PAS accès à la vue d'ensemble."""
        response = auth_client.get('/vue_ensemble_validation', follow_redirects=True)
        assert response.status_code == 200
        assert 'non autoris' in response.data.decode('utf-8').lower()
