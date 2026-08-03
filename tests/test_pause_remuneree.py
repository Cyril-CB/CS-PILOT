"""
Tests de la pause méridienne rémunérée (case à cocher de la saisie des heures).

Certains salariés (accueil de loisirs, crèche…) prennent leur pause sur place
en restant à la disposition de l'employeur : ce temps est du travail effectif
(art. L3121-2). Quand la case est cochée, l'écart entre la fin du matin et le
début de l'après-midi est compté dans les heures travaillées et ne déclenche
pas d'alerte « pause manquante » — la pause a bien eu lieu.
"""
from datetime import date

from utils import calculer_heures_reelles_jour, duree_pause_meridienne
from blueprints.prevention_sante import compute_prevention_messages
from blueprints.worktime_metrics import compute_segments_metrics


class TestCalculPauseRemuneree:
    ROW = {
        'heure_debut_matin': '09:00', 'heure_fin_matin': '12:40',   # 3h40
        'heure_debut_aprem': '13:00', 'heure_fin_aprem': '17:00',   # 4h, pause 20 min
    }

    def test_duree_pause_meridienne(self):
        assert duree_pause_meridienne(self.ROW) == 0.33

    def test_total_sans_flag_exclut_la_pause(self):
        assert calculer_heures_reelles_jour(self.ROW) == 7.67

    def test_total_avec_flag_inclut_la_pause(self):
        row = dict(self.ROW, pause_remuneree=1)
        assert calculer_heures_reelles_jour(row) == 8.0

    def test_flag_sans_apres_midi_sans_effet(self):
        # Pas de créneau après-midi : aucune pause méridienne à rémunérer.
        row = {'heure_debut_matin': '09:00', 'heure_fin_matin': '12:40',
               'pause_remuneree': 1}
        assert calculer_heures_reelles_jour(row) == 3.67

    def test_horaires_incoherents_ignores(self):
        # Début d'après-midi antérieur à la fin du matin : la « pause » négative
        # ne doit ni compter ni basculer sur le lendemain (+24h).
        row = {'heure_debut_matin': '09:00', 'heure_fin_matin': '13:00',
               'heure_debut_aprem': '12:30', 'heure_fin_aprem': '17:00',
               'pause_remuneree': 1}
        assert duree_pause_meridienne(row) == 0
        assert calculer_heures_reelles_jour(row) == 8.5  # 4h + 4h30, sans pause


class TestMetriquesPauseRemuneree:
    """La pause rémunérée compte dans les heures ET vaut pause prise
    (pas d'alerte « plus de 6h consécutives »)."""

    def test_flag_compte_la_pause_et_coupe_le_travail_consecutif(self):
        segments = [('08:00', '12:00'), ('12:15', '16:45')]  # pause 15 min
        sans = compute_segments_metrics(date(2025, 6, 16), segments)
        assert sans['worked_hours'] == 8.5
        assert sans['break_minutes'] == 15.0
        # Pause < 20 min : le travail est considéré comme continu (8h45).
        assert sans['longest_consecutive_hours'] == 8.75

        avec = compute_segments_metrics(date(2025, 6, 16), segments, pause_remuneree=True)
        assert avec['worked_hours'] == 8.75          # la pause est payée
        assert avec['break_minutes'] == 15.0
        assert avec['longest_consecutive_hours'] == 4.5  # la pause prise coupe

    def test_flag_ne_paye_que_la_pause_meridienne(self):
        # L'écart après-midi → soir reste exclu des heures travaillées.
        segments = [('08:00', '12:00'), ('12:15', '16:00'), ('18:00', '20:00')]
        m = compute_segments_metrics(date(2025, 6, 16), segments, pause_remuneree=True)
        assert m['worked_hours'] == 10.0             # 4 + 3.75 + 2 + 0.25
        assert m['longest_consecutive_hours'] == 4.0


class TestPreventionPauseRemuneree:
    """Journée > 6h avec pause courte : alerte sans le flag, silence avec."""

    DATE = '2025-06-16'   # lundi
    TODAY = date(2025, 6, 17)

    def _inserer_jour(self, db, user_id, pause_remuneree):
        db.execute(
            "INSERT INTO heures_reelles (user_id, date, heure_debut_matin, heure_fin_matin, "
            "heure_debut_aprem, heure_fin_aprem, type_saisie, declaration_conforme, pause_remuneree) "
            "VALUES (?, ?, '08:00', '12:00', '12:15', '16:45', 'heures_modifiees', 0, ?)",
            (user_id, self.DATE, pause_remuneree))
        db.commit()

    def test_pause_courte_alerte_sans_flag(self, app, db, sample_users):
        with app.app_context():
            self._inserer_jour(db, sample_users['salarie_id'], 0)
            messages = compute_prevention_messages(db, sample_users['salarie_id'], today=self.TODAY)
        assert any('s2_pause_courte' in m.key for m in messages)

    def test_pause_remuneree_supprime_l_alerte(self, app, db, sample_users):
        with app.app_context():
            self._inserer_jour(db, sample_users['salarie_id'], 1)
            messages = compute_prevention_messages(db, sample_users['salarie_id'], today=self.TODAY)
        assert not any('s1_no_pause' in m.key or 's2_pause_courte' in m.key for m in messages)


class TestSaisiePauseRemuneree:
    DATE = '2025-06-16'

    def test_saisie_enregistre_la_pause_remuneree(self, auth_client, app, db, sample_users, sample_contrat):
        with app.app_context():
            auth_client.post('/saisie_heures', data={
                'date': self.DATE,
                'heure_debut_matin': '09:00', 'heure_fin_matin': '12:40',
                'heure_debut_aprem': '13:00', 'heure_fin_aprem': '17:00',
                'pause_remuneree': '1',
            }, follow_redirects=True)
            row = db.execute("SELECT * FROM heures_reelles WHERE user_id = ? AND date = ?",
                             (sample_users['salarie_id'], self.DATE)).fetchone()
        assert row['pause_remuneree'] == 1
        assert calculer_heures_reelles_jour(row) == 8.0

    def test_saisie_sans_case_reste_a_zero(self, auth_client, app, db, sample_users, sample_contrat):
        with app.app_context():
            auth_client.post('/saisie_heures', data={
                'date': self.DATE,
                'heure_debut_matin': '09:00', 'heure_fin_matin': '12:40',
                'heure_debut_aprem': '13:00', 'heure_fin_aprem': '17:00',
            }, follow_redirects=True)
            row = db.execute("SELECT * FROM heures_reelles WHERE user_id = ? AND date = ?",
                             (sample_users['salarie_id'], self.DATE)).fetchone()
        assert row['pause_remuneree'] == 0

    def test_recup_journee_ignore_la_pause(self, auth_client, app, db, sample_users, sample_contrat):
        # Une récup journée n'a pas d'heures : le flag est remis à zéro même si envoyé.
        with app.app_context():
            auth_client.post('/saisie_heures', data={
                'date': self.DATE,
                'recup_journee': '1',
                'pause_remuneree': '1',
            }, follow_redirects=True)
            row = db.execute("SELECT * FROM heures_reelles WHERE user_id = ? AND date = ?",
                             (sample_users['salarie_id'], self.DATE)).fetchone()
        assert row['type_saisie'] == 'recup_journee'
        assert row['pause_remuneree'] == 0

    def test_formulaire_affiche_case_et_avertissement(self, auth_client):
        html = auth_client.get(f'/saisie_heures?date={self.DATE}').get_data(as_text=True)
        assert 'id="pause_remuneree"' in html
        assert 'id="pauseRemunereeModal"' in html
        # Le message d'avertissement : sincérité, cadre légal et risques santé.
        assert 'pause fictive' in html
        assert 'L. 3121-16' in html
        assert 'vingt minutes consécutives' in html
        assert 'troubles musculosquelettiques' in html

    def test_vue_mensuelle_signale_la_pause_remuneree(self, auth_client, app, db, sample_users):
        with app.app_context():
            db.execute(
                "INSERT INTO heures_reelles (user_id, date, heure_debut_matin, heure_fin_matin, "
                "heure_debut_aprem, heure_fin_aprem, type_saisie, declaration_conforme, pause_remuneree) "
                "VALUES (?, ?, '09:00', '12:40', '13:00', '17:00', 'heures_modifiees', 0, 1)",
                (sample_users['salarie_id'], self.DATE))
            db.commit()
        html = auth_client.get('/vue_mensuelle?mois=6&annee=2025').get_data(as_text=True)
        assert 'Pause méridienne rémunérée' in html
        assert '☕' in html


def _texte_pdf(data):
    """Concatène les flux décompressés du PDF (le texte y est en clair).

    ReportLab encode ses flux en ASCII85 puis Flate ; on tente les deux
    décodages (a85 -> zlib, puis zlib direct) et on ignore le reste (polices…).
    """
    import base64
    import re
    import zlib
    morceaux = []
    for m in re.findall(rb'stream\r?\n(.*?)endstream', data, re.S):
        m = m.strip()
        for decode in (lambda b: zlib.decompress(base64.a85decode(b, adobe=True)),
                       zlib.decompress):
            try:
                morceaux.append(decode(m))
                break
            except Exception:
                continue
    return b''.join(morceaux)


class TestExportPdfPauseRemuneree:
    """Le PDF mensuel signé doit inclure la pause rémunérée dans les totaux,
    comme la vue mensuelle (revue Codex sur la PR #215)."""

    DATE = '2025-06-16'

    def test_pdf_mensuel_compte_la_pause_remuneree(self, auth_client, app, db, sample_users):
        uid = sample_users['salarie_id']
        with app.app_context():
            db.execute(
                "INSERT INTO heures_reelles (user_id, date, heure_debut_matin, heure_fin_matin, "
                "heure_debut_aprem, heure_fin_aprem, type_saisie, declaration_conforme, pause_remuneree) "
                "VALUES (?, ?, '09:00', '12:40', '13:00', '17:00', 'heures_modifiees', 0, 1)",
                (uid, self.DATE))
            # Le PDF n'est disponible que pour un mois validé/bloqué.
            db.execute('''INSERT INTO validations (user_id, mois, annee, validation_salarie,
                          validation_responsable, validation_directeur, bloque)
                          VALUES (?, 6, 2025, 'Jean M.', 'Marie D.', 'Dir', 1)''', (uid,))
            db.commit()

        r = auth_client.get(f'/export_pdf_mensuel?user_id={uid}&mois=6&annee=2025')
        assert r.status_code == 200
        assert r.data[:4] == b'%PDF'
        texte = _texte_pdf(r.data)
        assert b'8.00h' in texte        # 3h40 + 4h + pause 20 min, comme la vue mensuelle
        assert b'7.67' not in texte     # l'ancien total sans la pause ne doit plus apparaître
        # Marqueur sur la ligne du jour (les parenthèses sont échappées dans le flux PDF).
        assert b'+ pause' in texte
