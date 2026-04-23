"""
Tests des options applicatives et des personnalisations associées.
"""
from datetime import datetime, timedelta

from blueprints import mon_equipe as mon_equipe_module
from app_options import get_option_bool, set_option_bool

DATE_REFERENCE_MON_EQUIPE = datetime(2025, 1, 6, 12, 0, 0)


def _creer_contrats_equipe(db, sample_users):
    cursor = db.cursor()
    for user_id in (sample_users['responsable_id'], sample_users['salarie_id']):
        cursor.execute(
            "INSERT INTO contrats (user_id, type_contrat, date_debut, temps_hebdo, saisi_par) VALUES (?,?,?,?,?)",
            (user_id, 'CDI', '2024-01-01', 35.0, sample_users['directeur_id'])
        )
    db.commit()


def _figer_semaine_mon_equipe(monkeypatch):
    class DateTimeFigee(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(
                DATE_REFERENCE_MON_EQUIPE.year,
                DATE_REFERENCE_MON_EQUIPE.month,
                DATE_REFERENCE_MON_EQUIPE.day,
                DATE_REFERENCE_MON_EQUIPE.hour,
                DATE_REFERENCE_MON_EQUIPE.minute,
                DATE_REFERENCE_MON_EQUIPE.second,
                tzinfo=tz
            )

    monkeypatch.setattr(mon_equipe_module, 'datetime', DateTimeFigee)
    return DATE_REFERENCE_MON_EQUIPE.date()


def _ajouter_absence_semaine(db, user_id, motif, saisi_par, date_reference):
    lundi = date_reference - timedelta(days=date_reference.weekday())
    date_str = lundi.strftime('%Y-%m-%d')
    db.execute(
        """INSERT INTO absences
           (user_id, motif, date_debut, date_fin, jours_ouvres, commentaire, saisi_par)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (user_id, motif, date_str, date_str, 1, 'Absence de test', saisi_par)
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
            assert get_option_bool('mon_equipe_masquer_motifs_absence_salaries') is False

        response = admin_client.post('/administration/options', data={
            'vue_mensuelle_afficher_horaires': '1',
            'mon_equipe_masquer_motifs_absence_salaries': '1',
        }, follow_redirects=True)

        assert response.status_code == 200
        assert 'Options enregistrées avec succès' in response.get_data(as_text=True)

        with app.app_context():
            assert get_option_bool('saisie_afficher_declaration_conforme') is False
            assert get_option_bool('vue_mensuelle_afficher_horaires') is True
            assert get_option_bool('mon_equipe_masquer_motifs_absence_salaries') is True


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

    def test_saisie_preserve_declaration_conforme_existante_si_option_desactivee(self, auth_client, app, db, sample_users):
        date_test = '2025-01-07'
        with app.app_context():
            db.execute(
                """INSERT INTO heures_reelles
                   (user_id, date, commentaire, type_saisie, declaration_conforme)
                   VALUES (?, ?, ?, ?, 1)""",
                (
                    sample_users['salarie_id'],
                    date_test,
                    'Déclaration conforme au planning',
                    'declaration_conforme',
                )
            )
            db.commit()
            set_option_bool('saisie_afficher_declaration_conforme', False)

        response = auth_client.post('/saisie_heures', data={
            'date': date_test,
            'commentaire': 'Déclaration conforme au planning',
        }, follow_redirects=True)

        assert response.status_code == 200

        with app.app_context():
            row = db.execute(
                """SELECT declaration_conforme, type_saisie, heure_debut_matin, heure_fin_matin,
                          heure_debut_aprem, heure_fin_aprem
                   FROM heures_reelles WHERE user_id = ? AND date = ?""",
                (sample_users['salarie_id'], date_test)
            ).fetchone()
            assert row is not None
            assert row['declaration_conforme'] == 1
            assert row['type_saisie'] == 'declaration_conforme'
            assert row['heure_debut_matin'] is None
            assert row['heure_fin_matin'] is None
            assert row['heure_debut_aprem'] is None
            assert row['heure_fin_aprem'] is None


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
        assert 'month-mobile-hours-real month-mobile-hours-real-schedule' in html


class TestMonEquipeVisibilitePresences:
    """Tests de visibilité des présences par tranche horaire."""

    def test_salarie_ne_voit_pas_les_presences_par_tranche_horaire(self, auth_client, db, sample_users):
        _creer_contrats_equipe(db, sample_users)

        response = auth_client.get('/mon_equipe')
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert "Planning hebdomadaire de l'equipe" in html
        assert 'class="presences-horaires-titre">Présences par tranche horaire' not in html

    def test_responsable_voit_les_presences_par_tranche_horaire(self, resp_client, db, sample_users):
        _creer_contrats_equipe(db, sample_users)

        response = resp_client.get('/mon_equipe')
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert 'class="presences-horaires-titre">Présences par tranche horaire' in html

    def test_comptable_voit_les_presences_par_tranche_horaire(self, comptable_client, db, sample_users):
        db.execute(
            "INSERT INTO contrats (user_id, type_contrat, date_debut, temps_hebdo, saisi_par) VALUES (?,?,?,?,?)",
            (sample_users['comptable_id'], 'CDI', '2024-01-01', 35.0, sample_users['directeur_id'])
        )
        db.commit()

        response = comptable_client.get('/mon_equipe')
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert 'class="presences-horaires-titre">Présences par tranche horaire' in html


class TestOptionMonEquipeMotifsAbsence:
    """Tests de l'option de masquage des motifs d'absence."""

    def test_salarie_voit_le_motif_si_option_desactivee(self, auth_client, app, db, sample_users, monkeypatch):
        date_reference = _figer_semaine_mon_equipe(monkeypatch)
        _creer_contrats_equipe(db, sample_users)
        _ajouter_absence_semaine(db, sample_users['responsable_id'], 'Arrêt maladie', sample_users['directeur_id'], date_reference)

        with app.app_context():
            set_option_bool('mon_equipe_masquer_motifs_absence_salaries', False)

        response = auth_client.get('/mon_equipe')
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert 'Arrêt maladie' in html
        assert '<span class="card-label">Absent</span>' not in html

    def test_salarie_ne_voit_pas_le_motif_si_option_activee(self, auth_client, app, db, sample_users, monkeypatch):
        date_reference = _figer_semaine_mon_equipe(monkeypatch)
        _creer_contrats_equipe(db, sample_users)
        _ajouter_absence_semaine(db, sample_users['responsable_id'], 'Arrêt maladie', sample_users['directeur_id'], date_reference)

        with app.app_context():
            set_option_bool('mon_equipe_masquer_motifs_absence_salaries', True)

        response = auth_client.get('/mon_equipe')
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert '<span class="card-label">Absent</span>' in html
        assert 'Arrêt maladie' not in html

    def test_responsable_continue_de_voir_le_motif_si_option_activee(self, resp_client, app, db, sample_users, monkeypatch):
        date_reference = _figer_semaine_mon_equipe(monkeypatch)
        _creer_contrats_equipe(db, sample_users)
        _ajouter_absence_semaine(db, sample_users['salarie_id'], 'Congé payé', sample_users['directeur_id'], date_reference)

        with app.app_context():
            set_option_bool('mon_equipe_masquer_motifs_absence_salaries', True)

        response = resp_client.get('/mon_equipe')
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert 'Congé payé' in html

    def test_comptable_continue_de_voir_le_motif_si_option_activee(self, comptable_client, app, db, sample_users, monkeypatch):
        date_reference = _figer_semaine_mon_equipe(monkeypatch)
        db.execute(
            "UPDATE users SET secteur_id = ? WHERE id = ?",
            (sample_users['secteur_id'], sample_users['comptable_id'])
        )
        db.execute(
            "INSERT INTO contrats (user_id, type_contrat, date_debut, temps_hebdo, saisi_par) VALUES (?,?,?,?,?)",
            (sample_users['comptable_id'], 'CDI', '2024-01-01', 35.0, sample_users['directeur_id'])
        )
        _creer_contrats_equipe(db, sample_users)
        _ajouter_absence_semaine(db, sample_users['salarie_id'], 'Congé sans solde', sample_users['directeur_id'], date_reference)

        with app.app_context():
            set_option_bool('mon_equipe_masquer_motifs_absence_salaries', True)

        response = comptable_client.get('/mon_equipe')
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert 'Congé sans solde' in html


class TestOptionsAccesResponsables:
    """Tests des options d'accès responsables."""

    def test_generation_contrats_refuse_responsable_si_option_desactivee(self, resp_client, app):
        with app.app_context():
            set_option_bool('generation_contrats_responsable_autorise', False)

        response = resp_client.get('/generation_contrats', follow_redirects=True)
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert 'Génération de contrats' not in html
        assert 'non autorisé' in html.lower()

    def test_budget_previsionnel_refuse_responsable_si_option_desactivee(self, resp_client, app):
        with app.app_context():
            set_option_bool('budget_previsionnel_responsable_autorise', False)

        response = resp_client.get('/budget-previsionnel', follow_redirects=True)
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert 'Budget prévisionnel' not in html
        assert 'non autorisé' in html.lower()

    def test_menu_responsable_masque_les_liens_desactives(self, resp_client, app):
        with app.app_context():
            set_option_bool('generation_contrats_responsable_autorise', False)
            set_option_bool('budget_previsionnel_responsable_autorise', False)

        response = resp_client.get('/dashboard_responsable')
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert '📄 Générer le contrat' not in html
        assert '📝 Génération contrats' not in html
        assert 'Budget prévisionnel' not in html
        assert 'Budget previsionnel' not in html

    def test_infos_salaries_masque_bouton_generation_si_option_desactivee(self, resp_client, app, sample_users):
        with app.app_context():
            set_option_bool('generation_contrats_responsable_autorise', False)

        response = resp_client.get(f"/infos_salaries?user_id={sample_users['salarie_id']}")
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert '📄 Générer le contrat' not in html
