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

    def test_saisie_heures_standard(self, auth_client, app, db, sample_users, sample_contrat):
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

    def test_saisie_declaration_conforme(self, auth_client, app, db, sample_users, sample_contrat):
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

    def test_saisie_recup_journee(self, auth_client, app, db, sample_users, sample_contrat):
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

    def test_historique_creation(self, auth_client, app, db, sample_users, sample_contrat):
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

    def test_creation_declenche_anomalie_si_ecart_superieur_a_3h(self, auth_client, app, db, sample_users, sample_planning, sample_contrat):
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


class TestSaisieExigeUnContrat:
    """Saisir des heures suppose un contrat couvrant la date.

    Les heures alimentent la paie : elles doivent se rattacher à un contrat.
    Le planning théorique, lui, n'est pas exigé — il peut arriver plus tard,
    les heures supplémentaires se recalculent alors d'elles-mêmes.
    """

    DATE = '2025-01-06'  # un lundi

    def _saisir(self, client, date=None, **extra):
        donnees = {
            'date': date or self.DATE,
            'heure_debut_matin': '08:30',
            'heure_fin_matin': '12:00',
            'heure_debut_aprem': '13:30',
            'heure_fin_aprem': '17:00',
        }
        donnees.update(extra)
        return client.post('/saisie_heures', data=donnees, follow_redirects=True)

    def _saisie_en_base(self, db, user_id, date=None):
        return db.execute(
            "SELECT * FROM heures_reelles WHERE user_id = ? AND date = ?",
            (user_id, date or self.DATE)
        ).fetchone()

    def test_refus_sans_aucun_contrat(self, auth_client, app, db, sample_users):
        """Sans contrat au dossier, la saisie est fermée."""
        with app.app_context():
            reponse = self._saisir(auth_client)
            assert reponse.status_code == 200
            assert 'Aucun contrat enregistré' in reponse.get_data(as_text=True)
            assert self._saisie_en_base(db, sample_users['salarie_id']) is None

    def test_refus_hors_periode_du_contrat(self, auth_client, app, db, sample_users):
        """Un CDD ne peut pas saisir avant son début ni après son terme."""
        with app.app_context():
            db.execute(
                """INSERT INTO contrats (user_id, type_contrat, date_debut, date_fin)
                   VALUES (?, 'CDD', '2025-02-01', '2025-02-28')""",
                (sample_users['salarie_id'],)
            )
            db.commit()

            self._saisir(auth_client)  # janvier : avant le contrat
            assert self._saisie_en_base(db, sample_users['salarie_id']) is None

            self._saisir(auth_client, date='2025-03-03')  # après le terme
            assert self._saisie_en_base(db, sample_users['salarie_id'], '2025-03-03') is None

    def test_saisie_acceptee_dans_la_periode(self, auth_client, app, db, sample_users):
        with app.app_context():
            db.execute(
                """INSERT INTO contrats (user_id, type_contrat, date_debut, date_fin)
                   VALUES (?, 'CDD', '2025-02-01', '2025-02-28')""",
                (sample_users['salarie_id'],)
            )
            db.commit()

            self._saisir(auth_client, date='2025-02-03')
            assert self._saisie_en_base(db, sample_users['salarie_id'], '2025-02-03') is not None

    def test_le_dernier_jour_du_contrat_est_saisissable(self, auth_client, app, db, sample_users):
        """`date_fin` est le dernier jour travaillé, pas le premier jour exclu."""
        with app.app_context():
            db.execute(
                """INSERT INTO contrats (user_id, type_contrat, date_debut, date_fin)
                   VALUES (?, 'CDD', '2025-02-01', '2025-02-28')""",
                (sample_users['salarie_id'],)
            )
            db.commit()

            self._saisir(auth_client, date='2025-02-28')
            assert self._saisie_en_base(db, sample_users['salarie_id'], '2025-02-28') is not None

    def test_une_saisie_anterieure_reste_modifiable(self, auth_client, app, db, sample_users):
        """Les heures posées avant la règle ne sont pas figées par elle.

        Leur auteur peut encore les corriger : on refuse la création, pas la
        rectification de ce qui existe déjà.
        """
        with app.app_context():
            db.execute(
                """INSERT INTO heures_reelles
                   (user_id, date, heure_debut_matin, heure_fin_matin,
                    heure_debut_aprem, heure_fin_aprem, type_saisie, declaration_conforme)
                   VALUES (?, ?, '09:00', '12:00', '14:00', '17:00',
                           'heures_modifiees', 0)""",
                (sample_users['salarie_id'], self.DATE)
            )
            db.commit()

            self._saisir(auth_client, heure_debut_matin='08:00')
            row = self._saisie_en_base(db, sample_users['salarie_id'])
            assert row['heure_debut_matin'] == '08:00'

    def test_une_ligne_d_absence_ne_sert_pas_de_laissez_passer(
            self, auth_client, app, db, sample_users):
        """Les circuits absences et récup écrivent librement hors contrat.

        Leur ligne ne doit pas rouvrir la saisie pour autant : sans ce
        garde-fou, il suffirait d'ouvrir le jour d'une absence pour y
        substituer des heures travaillées sur une période sans contrat.
        """
        with app.app_context():
            db.execute(
                """INSERT INTO heures_reelles
                   (user_id, date, type_saisie, declaration_conforme, commentaire)
                   VALUES (?, ?, 'absence', 1, 'Arrêt maladie')""",
                (sample_users['salarie_id'], self.DATE)
            )
            db.commit()

            self._saisir(auth_client)
            row = self._saisie_en_base(db, sample_users['salarie_id'])

        assert row['type_saisie'] == 'absence'          # rien n'a été remplacé
        assert row['heure_debut_matin'] is None

    def test_une_recup_ne_sert_pas_davantage_de_laissez_passer(
            self, auth_client, app, db, sample_users):
        with app.app_context():
            db.execute(
                """INSERT INTO heures_reelles
                   (user_id, date, type_saisie, declaration_conforme, commentaire)
                   VALUES (?, ?, 'recup_journee', 0, 'Récupération')""",
                (sample_users['salarie_id'], self.DATE)
            )
            db.commit()

            self._saisir(auth_client)
            row = self._saisie_en_base(db, sample_users['salarie_id'])

        assert row['type_saisie'] == 'recup_journee'

    def test_une_absence_sous_contrat_reste_modifiable(
            self, auth_client, app, db, sample_users, sample_contrat):
        """Le garde-fou ne vaut que hors contrat : sous contrat, rien ne change."""
        with app.app_context():
            db.execute(
                """INSERT INTO heures_reelles
                   (user_id, date, type_saisie, declaration_conforme, commentaire)
                   VALUES (?, ?, 'absence', 1, 'Arrêt maladie')""",
                (sample_users['salarie_id'], self.DATE)
            )
            db.commit()

            self._saisir(auth_client)
            row = self._saisie_en_base(db, sample_users['salarie_id'])

        assert row['heure_debut_matin'] == '08:30'

    def test_le_planning_n_est_pas_exige(self, auth_client, app, db, sample_users, sample_contrat):
        """Un contrat suffit : le planning peut arriver plus tard."""
        with app.app_context():
            # Volontairement pas de fixture sample_planning.
            self._saisir(auth_client)
            assert self._saisie_en_base(db, sample_users['salarie_id']) is not None

    def test_le_formulaire_annonce_le_refus(self, auth_client, app, db, sample_users):
        """Le bouton est désactivé et la raison affichée, avant tout envoi."""
        html = auth_client.get(f'/saisie_heures?date={self.DATE}').get_data(as_text=True)
        assert 'Aucun contrat enregistré' in html

    def test_le_message_dit_quoi_faire_selon_le_lecteur(self, auth_client, resp_client,
                                                        app, db, sample_users):
        """Un salarié ne peut pas créer son contrat ; un responsable, si."""
        pour_soi = auth_client.get(f'/saisie_heures?date={self.DATE}').get_data(as_text=True)
        assert 'Signalez-le à la direction' in pour_soi

        pour_autrui = resp_client.get(
            f"/saisie_heures?date={self.DATE}&user_id={sample_users['salarie_id']}"
        ).get_data(as_text=True)
        assert 'Infos Salariés' in pour_autrui


def _creer_salarie_meme_secteur(db, sample_users, login='collegue_test'):
    """Crée un second salarié dans le secteur du salarié de test."""
    from werkzeug.security import generate_password_hash

    cur = db.execute(
        "INSERT INTO users (nom, prenom, login, password, profil, secteur_id, responsable_id) "
        "VALUES (?, ?, ?, ?, 'salarie', ?, ?)",
        ('Bernard', 'Paul', login, generate_password_hash('col123'),
         sample_users['secteur_id'], sample_users['responsable_id']))
    db.commit()
    return cur.lastrowid


def _creer_salarie_autre_secteur(db, login='hors_secteur_test'):
    """Crée un salarié dans un autre secteur, hors équipe du responsable de test."""
    from werkzeug.security import generate_password_hash

    cur = db.execute("INSERT INTO secteurs (nom, description) VALUES (?, ?)",
                     ('Autre Secteur Saisie', 'Secteur distinct pour les tests'))
    autre_secteur_id = cur.lastrowid
    cur = db.execute(
        "INSERT INTO users (nom, prenom, login, password, profil, secteur_id) "
        "VALUES (?, ?, ?, ?, 'salarie', ?)",
        ('Petit', 'Luc', login, generate_password_hash('hors123'), autre_secteur_id))
    db.commit()
    return cur.lastrowid


class TestSaisieDroits:
    """Tests des contrôles d'accès pour la saisie."""

    def test_directeur_ne_peut_pas_saisir_pour_lui(self, admin_client, app, db, sample_users):
        """Le directeur ne peut PAS modifier sa propre fiche via saisie.

        Le refus doit être visible (message français) ET sans effet en base :
        un simple `status_code == 200` après redirection passerait même si la
        saisie interdite avait été acceptée.
        """
        date_test = '2025-01-06'

        with app.app_context():
            response = admin_client.post('/saisie_heures', data={
                'date': date_test,
                'heure_debut_matin': '09:00',
                'heure_fin_matin': '12:00',
            }, follow_redirects=True)
            assert response.status_code == 200
            assert 'pas le droit de modifier cette fiche' in response.get_data(as_text=True)

            row = db.execute(
                "SELECT * FROM heures_reelles WHERE user_id = ? AND date = ?",
                (sample_users['directeur_id'], date_test)
            ).fetchone()
            assert row is None    # rien écrit

    def test_salarie_ne_peut_pas_saisir_pour_autrui(self, auth_client, app, db, sample_users):
        """Un salarié ne peut PAS saisir les heures d'un collègue, même de son
        propre secteur : seul le profil (responsable/directeur) ouvre ce droit."""
        date_test = '2025-01-13'

        with app.app_context():
            collegue_id = _creer_salarie_meme_secteur(db, sample_users)

            response = auth_client.post('/saisie_heures', data={
                'user_id': collegue_id,
                'date': date_test,
                'heure_debut_matin': '08:00',
                'heure_fin_matin': '12:00',
            }, follow_redirects=True)
            assert response.status_code == 200
            assert 'pas le droit de modifier cette fiche' in response.get_data(as_text=True)

            row = db.execute(
                "SELECT * FROM heures_reelles WHERE user_id = ?", (collegue_id,)
            ).fetchone()
            assert row is None    # rien écrit

    def test_responsable_ne_peut_pas_saisir_hors_secteur(self, resp_client, app, db, sample_users):
        """Le responsable ne peut PAS saisir pour un salarié d'un autre secteur
        qui ne lui est pas non plus rattaché directement."""
        date_test = '2025-01-14'

        with app.app_context():
            hors_equipe_id = _creer_salarie_autre_secteur(db)

            response = resp_client.post('/saisie_heures', data={
                'user_id': hors_equipe_id,
                'date': date_test,
                'heure_debut_matin': '08:00',
                'heure_fin_matin': '12:00',
            }, follow_redirects=True)
            assert response.status_code == 200
            assert 'pas le droit de modifier cette fiche' in response.get_data(as_text=True)

            row = db.execute(
                "SELECT * FROM heures_reelles WHERE user_id = ?", (hors_equipe_id,)
            ).fetchone()
            assert row is None    # rien écrit

    def test_mois_verrouille_refuse_la_modification(self, auth_client, app, db, sample_users):
        """Une fiche verrouillée (validée par le responsable ET le directeur)
        refuse toute nouvelle saisie sur le mois concerné."""
        date_test = '2025-02-03'    # lundi de février 2025

        with app.app_context():
            db.execute(
                "INSERT INTO validations (user_id, mois, annee, validation_responsable, "
                "validation_directeur, bloque) VALUES (?, 2, 2025, ?, ?, 1)",
                (sample_users['salarie_id'], 'Dupont Marie', 'Admin Systeme'))
            db.commit()

            response = auth_client.post('/saisie_heures', data={
                'date': date_test,
                'heure_debut_matin': '08:00',
                'heure_fin_matin': '12:00',
            }, follow_redirects=True)
            assert response.status_code == 200
            assert 'la fiche est verrouillée' in response.get_data(as_text=True)

            row = db.execute(
                "SELECT * FROM heures_reelles WHERE user_id = ? AND date = ?",
                (sample_users['salarie_id'], date_test)
            ).fetchone()
            assert row is None    # rien écrit

    def test_responsable_peut_saisir_pour_son_secteur(self, resp_client, app, db, sample_users, sample_contrat):
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
