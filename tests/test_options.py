"""
Tests des options applicatives et des personnalisations associées.
"""
from app_options import get_option_bool, set_option_bool


def _creer_contrats_equipe(db, sample_users):
    cursor = db.cursor()
    for user_id in (sample_users['responsable_id'], sample_users['salarie_id']):
        cursor.execute(
            "INSERT INTO contrats (user_id, type_contrat, date_debut, temps_hebdo, saisi_par) VALUES (?,?,?,?,?)",
            (user_id, 'CDI', '2024-01-01', 35.0, sample_users['directeur_id'])
        )
    db.commit()


class TestOptionsAdministration:
    """Tests de la page Options d'administration."""

    def test_directeur_peut_acceder_a_la_page_options(self, admin_client):
        response = admin_client.get('/administration/options')
        assert response.status_code == 200
        assert 'Options' in response.get_data(as_text=True)

    def test_comptable_peut_acceder_a_la_page_options(self, comptable_client):
        response = comptable_client.get('/administration/options')
        assert response.status_code == 200

    def test_salarie_ne_peut_pas_acceder_a_la_page_options(self, auth_client):
        response = auth_client.get('/administration/options', follow_redirects=True)
        assert response.status_code == 200
        assert 'non autorisé' in response.get_data(as_text=True).lower()

    def test_enregistrement_des_options(self, admin_client, app):
        with app.app_context():
            assert get_option_bool('saisie_afficher_declaration_conforme') is True
            assert get_option_bool('vue_mensuelle_afficher_horaires') is False

        response = admin_client.post('/administration/options', data={
            'vue_mensuelle_afficher_horaires': '1',
        }, follow_redirects=True)

        assert response.status_code == 200
        assert 'Options enregistrées avec succès' in response.get_data(as_text=True)

        with app.app_context():
            assert get_option_bool('saisie_afficher_declaration_conforme') is False
            assert get_option_bool('vue_mensuelle_afficher_horaires') is True


class TestOptionsSaisie:
    """Tests de l'option de déclaration conforme."""

    def test_saisie_cache_declaration_conforme_si_option_desactivee(self, auth_client, app):
        with app.app_context():
            set_option_bool('saisie_afficher_declaration_conforme', False)

        response = auth_client.get('/saisie_heures')
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert 'Je certifie avoir travaillé mes heures habituelles ce jour' not in html

    def test_saisie_ignore_declaration_conforme_si_option_desactivee(self, auth_client, app, db, sample_users):
        with app.app_context():
            set_option_bool('saisie_afficher_declaration_conforme', False)

            response = auth_client.post('/saisie_heures', data={
                'date': '2025-01-06',
                'declaration_conforme': '1',
                'heure_debut_matin': '08:30',
                'heure_fin_matin': '12:00',
                'heure_debut_aprem': '13:30',
                'heure_fin_aprem': '17:00',
            }, follow_redirects=True)

            assert response.status_code == 200

            row = db.execute(
                "SELECT declaration_conforme, type_saisie FROM heures_reelles WHERE user_id = ? AND date = ?",
                (sample_users['salarie_id'], '2025-01-06')
            ).fetchone()
            assert row is not None
            assert row['declaration_conforme'] == 0
            assert row['type_saisie'] == 'heures_modifiees'


class TestOptionsVueMensuelle:
    """Tests de l'affichage des horaires dans la vue mensuelle."""

    def test_vue_mensuelle_affiche_les_horaires_si_option_activee(self, auth_client, app, db, sample_users, sample_planning):
        with app.app_context():
            set_option_bool('vue_mensuelle_afficher_horaires', True)
            db.execute(
                """INSERT INTO heures_reelles
                   (user_id, date, heure_debut_matin, heure_fin_matin,
                    heure_debut_aprem, heure_fin_aprem, type_saisie, declaration_conforme)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
                (sample_users['salarie_id'], '2025-01-06', '08:45', '12:15', '13:15', '17:30', 'heures_modifiees')
            )
            db.commit()

        response = auth_client.get('/vue_mensuelle?mois=1&annee=2025')
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert 'Horaires théo.' in html
        assert 'Horaires réels' in html
        assert '08:30 - 12:00 / 13:30 - 17:00' in html
        assert '08:45 - 12:15 / 13:15 - 17:30' in html


class TestMonEquipeVisibilitePresences:
    """Tests de visibilité des présences par tranche horaire."""

    def test_salarie_ne_voit_pas_les_presences_par_tranche_horaire(self, auth_client, db, sample_users):
        _creer_contrats_equipe(db, sample_users)

        response = auth_client.get('/mon_equipe')
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert 'class="presences-horaires-titre">Présences par tranche horaire' not in html

    def test_responsable_voit_les_presences_par_tranche_horaire(self, resp_client, db, sample_users):
        _creer_contrats_equipe(db, sample_users)

        response = resp_client.get('/mon_equipe')
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert 'class="presences-horaires-titre">Présences par tranche horaire' in html
