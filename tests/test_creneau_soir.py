"""
Tests du 3e créneau optionnel « soir ».

Le personnel d'entretien travaille parfois en trois créneaux (matin / après-midi
/ soir), notamment en période de vacances. Le créneau soir est optionnel, proposé
toute l’année, et doit compter dans tous les totaux d'heures.
"""
from datetime import date
from html.parser import HTMLParser

import pytest

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
    @pytest.mark.parametrize('vacances', [False, True])
    def test_saisie_enregistre_le_creneau_soir(
            self, auth_client, app, db, sample_users, sample_contrat, vacances):
        date_test = '2025-01-13'  # lundi
        if vacances:
            db.execute("INSERT INTO periodes_vacances (nom, date_debut, date_fin) "
                       "VALUES ('Vac test', '2025-01-01', '2025-01-31')")
            db.commit()
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

    @pytest.mark.parametrize('vacances', [False, True])
    @pytest.mark.parametrize('client_fixture', ['auth_client', 'resp_client', 'admin_client'])
    def test_toggle_soir_disponible_toute_annee(
            self, request, client_fixture, db, sample_users, sample_contrat, vacances):
        client = request.getfixturevalue(client_fixture)
        if vacances:
            db.execute("INSERT INTO periodes_vacances (nom, date_debut, date_fin) "
                       "VALUES ('Vac test', '2025-01-01', '2025-01-31')")
            db.commit()
        url = f"/saisie_heures?date=2025-01-13&user_id={sample_users['salarie_id']}"
        response = client.get(url)
        assert response.status_code == 200
        fields = _form_fields(response.get_data(as_text=True))
        assert 'checked' not in fields['toggle_soir']
        assert 'disabled' not in fields['toggle_soir']
        assert fields['soir-section']['style'] == 'display:none;'
        for name in ('heure_debut_soir', 'heure_fin_soir'):
            assert 'disabled' in fields[name]
            assert fields[name]['value'] == ''

    @pytest.mark.parametrize('vacances', [False, True])
    @pytest.mark.parametrize('debut,fin', [('18:00', '20:00'), ('18:00', None),
                                         (None, '20:00'), (None, None)])
    def test_saisie_existante_preservee(
            self, auth_client, db, sample_users, vacances, debut, fin):
        # Ancienne saisie manuelle, même sans contrat : aucune réécriture au GET.
        if vacances:
            db.execute("INSERT INTO periodes_vacances (nom, date_debut, date_fin) "
                       "VALUES ('Vac test', '2025-01-01', '2025-01-31')")
        db.execute("""INSERT INTO heures_reelles
            (user_id, date, heure_debut_matin, heure_fin_matin,
             heure_debut_soir, heure_fin_soir, type_saisie)
            VALUES (?, '2025-01-13', '08:00', '12:00', ?, ?, 'heures')""",
            (sample_users['salarie_id'], debut, fin))
        db.commit()
        before = dict(db.execute('SELECT * FROM heures_reelles').fetchone())
        response = auth_client.get('/saisie_heures?date=2025-01-13')
        assert response.status_code == 200
        fields = _form_fields(response.get_data(as_text=True))
        rempli = bool(debut or fin)
        assert ('checked' in fields['toggle_soir']) == rempli
        assert ('style' not in fields['soir-section']) == rempli
        for name, value in [('heure_debut_soir', debut), ('heure_fin_soir', fin)]:
            assert fields[name]['value'] == (value or '')
            assert ('disabled' not in fields[name]) == rempli
        assert fields['heure_debut_matin']['value'] == '08:00'
        assert fields['heure_fin_matin']['value'] == '12:00'
        assert dict(db.execute('SELECT * FROM heures_reelles').fetchone()) == before


class _FieldsParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields = {}
        self.scripts = []
        self._script = None

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self._script = []
        attrs = dict(attrs)
        if 'id' in attrs:
            self.fields[attrs['id']] = attrs

    def handle_data(self, data):
        if self._script is not None:
            self._script.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self._script is not None:
            self.scripts.append(''.join(self._script))
            self._script = None


def _form_fields(html):
    parser = _FieldsParser()
    parser.feed(html)
    return parser.fields


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


@pytest.mark.parametrize('mode', ['vide', 'soir', 'recup_journee', 'declaration_conforme'])
@pytest.mark.parametrize('option_conforme', [False, True])
def test_transitions_modes_journee(
        auth_client, db, sample_users, sample_contrat, mode, option_conforme):
    import json
    from pathlib import Path
    import shutil
    import subprocess

    if not shutil.which('node'):
        pytest.skip('Node requis pour exécuter le JavaScript livré')
    db.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
               ('saisie_afficher_declaration_conforme', '1' if option_conforme else '0'))
    if mode != 'vide':
        db.execute("""INSERT INTO heures_reelles
            (user_id, date, type_saisie, declaration_conforme, heure_debut_soir, heure_fin_soir)
            VALUES (?, '2025-01-13', ?, ?, ?, ?)""",
            (sample_users['salarie_id'], 'heures_modifiees' if mode == 'soir' else mode,
             int(mode == 'declaration_conforme'),
             '18:00' if mode == 'soir' else None, '20:00' if mode == 'soir' else None))
    db.commit()
    response = auth_client.get('/saisie_heures?date=2025-01-13')
    assert response.status_code == 200
    parser = _FieldsParser()
    parser.feed(response.get_data(as_text=True))
    result = subprocess.run(
        ['node', str(Path(__file__).with_name('saisie_modes_frontend.cjs'))],
        input=json.dumps({'scripts': parser.scripts, 'fields': parser.fields}),
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
