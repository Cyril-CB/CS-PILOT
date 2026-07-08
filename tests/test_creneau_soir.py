"""
Tests du 3e créneau optionnel « soir ».

Le personnel d'entretien travaille parfois en trois créneaux (matin / après-midi
/ soir), notamment en période de vacances. Le créneau soir est optionnel, proposé
en contexte vacances, et doit compter dans tous les totaux d'heures.
"""
from datetime import date

from utils import (calculer_heures_reelles_jour, get_heures_theoriques_jour,
                   calculer_recup_partielle)
from blueprints.worktime_metrics import (day_segments_from_row,
                                          compute_segments_metrics)


class TestCalculSoir:
    def test_heures_reelles_jour_additionne_les_trois_creneaux(self):
        row = {
            'heure_debut_matin': '08:00', 'heure_fin_matin': '12:00',   # 4h
            'heure_debut_aprem': '13:00', 'heure_fin_aprem': '16:00',   # 3h
            'heure_debut_soir': '18:00', 'heure_fin_soir': '20:00',     # 2h
        }
        assert calculer_heures_reelles_jour(row) == 9.0

    def test_heures_reelles_jour_tolere_soir_absent(self):
        # Ancienne ligne / SELECT sans colonne soir : le soir vaut 0, pas d'erreur.
        row = {
            'heure_debut_matin': '08:00', 'heure_fin_matin': '12:00',
            'heure_debut_aprem': '13:00', 'heure_fin_aprem': '16:00',
        }
        assert calculer_heures_reelles_jour(row) == 7.0

    def test_heures_theoriques_jour_inclut_le_soir(self):
        planning = {
            'lundi_matin_debut': '09:00', 'lundi_matin_fin': '12:00',   # 3h
            'lundi_aprem_debut': '13:00', 'lundi_aprem_fin': '16:00',   # 3h
            'lundi_soir_debut': '17:00', 'lundi_soir_fin': '19:00',     # 2h
        }
        assert get_heures_theoriques_jour(planning, 0) == 8.0

    def test_recup_partielle_conserve_le_soir(self):
        planning = {
            'lundi_matin_debut': '09:00', 'lundi_matin_fin': '12:00',
            'lundi_aprem_debut': '13:00', 'lundi_aprem_fin': '16:00',
            'lundi_soir_debut': '18:00', 'lundi_soir_fin': '20:00',
        }
        # Absence toute l'après-midi : le matin et le soir restent travaillés.
        res = calculer_recup_partielle(planning, 0, '13:00', '16:00')
        assert res is not None
        assert res['heures_theoriques'] == 8.0      # 3 + 3 + 2
        assert res['heures_recup'] == 3.0           # l'après-midi retirée
        assert res['soir_debut'] == '18:00' and res['soir_fin'] == '20:00'


class TestMetriquesTempsSoir:
    """Le soir doit compter dans les métriques temps de travail (alerte surcharge)."""

    def test_day_segments_inclut_le_soir(self):
        row = {
            'heure_debut_matin': '08:00', 'heure_fin_matin': '12:00',
            'heure_debut_aprem': '13:00', 'heure_fin_aprem': '16:00',
            'heure_debut_soir': '18:00', 'heure_fin_soir': '20:00',
        }
        segments = day_segments_from_row(row)
        assert segments == [('08:00', '12:00'), ('13:00', '16:00'), ('18:00', '20:00')]
        metrics = compute_segments_metrics(date(2025, 1, 13), segments)
        assert metrics['worked_hours'] == 9.0

    def test_day_segments_tolere_soir_absent(self):
        # Ligne issue d'un SELECT sans colonne soir : pas d'erreur, soir ignoré.
        row = {
            'heure_debut_matin': '08:00', 'heure_fin_matin': '12:00',
            'heure_debut_aprem': '13:00', 'heure_fin_aprem': '16:00',
        }
        segments = day_segments_from_row(row)
        assert segments == [('08:00', '12:00'), ('13:00', '16:00')]
        assert compute_segments_metrics(date(2025, 1, 13), segments)['worked_hours'] == 7.0


class TestSaisieSoir:
    def test_saisie_enregistre_le_creneau_soir(self, auth_client, app, db, sample_users):
        date_test = '2025-01-13'  # lundi
        with app.app_context():
            auth_client.post('/saisie_heures', data={
                'date': date_test,
                'heure_debut_matin': '08:00', 'heure_fin_matin': '12:00',
                'heure_debut_aprem': '13:00', 'heure_fin_aprem': '16:00',
                'heure_debut_soir': '18:00', 'heure_fin_soir': '20:00',
            }, follow_redirects=True)
            row = db.execute("SELECT * FROM heures_reelles WHERE user_id = ? AND date = ?",
                             (sample_users['salarie_id'], date_test)).fetchone()
        assert row['heure_debut_soir'] == '18:00'
        assert row['heure_fin_soir'] == '20:00'

    def test_toggle_soir_reserve_aux_vacances(self, auth_client, app, db, sample_users):
        # Sans période de vacances : date scolaire → pas de champ soir proposé
        # (la fonction JS toggleSoir existe toujours, mais pas la case ni la section).
        html_scol = auth_client.get('/saisie_heures?date=2025-01-13').get_data(as_text=True)
        assert 'id="toggle_soir"' not in html_scol
        assert 'id="soir-section"' not in html_scol
        # On déclare une période de vacances couvrant la date → champ soir proposé.
        with app.app_context():
            db.execute("INSERT INTO periodes_vacances (nom, date_debut, date_fin) "
                       "VALUES ('Vac test', '2025-01-01', '2025-01-31')")
            db.commit()
        html_vac = auth_client.get('/saisie_heures?date=2025-01-13').get_data(as_text=True)
        assert 'id="toggle_soir"' in html_vac
        assert 'id="soir-section"' in html_vac
        assert 'créneau du soir' in html_vac


class TestPlanningSoir:
    def test_planning_enregistre_le_soir_et_le_total_hebdo(self, resp_client, app, db, sample_users):
        with app.app_context():
            resp_client.post('/planning_theorique', data={
                'user_id': sample_users['salarie_id'],
                'type_periode': 'vacances',
                'type_alternance': 'fixe',
                'date_debut_validite': '2025-01-01',
                'lundi_matin_debut': '09:00', 'lundi_matin_fin': '12:00',   # 3h
                'lundi_aprem_debut': '13:00', 'lundi_aprem_fin': '16:00',   # 3h
                'lundi_soir_debut': '17:00', 'lundi_soir_fin': '19:00',     # 2h
            }, follow_redirects=True)
            row = db.execute("SELECT * FROM planning_theorique WHERE user_id = ? "
                             "ORDER BY id DESC LIMIT 1", (sample_users['salarie_id'],)).fetchone()
        assert row['lundi_soir_debut'] == '17:00'
        assert row['lundi_soir_fin'] == '19:00'
        assert row['total_hebdo'] == 8.0
