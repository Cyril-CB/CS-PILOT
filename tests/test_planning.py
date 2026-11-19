"""
Tests pour le module planning.py :
- Saisie du planning théorique (pour soi-même)
- Saisie du planning d'un autre salarié par la direction, le comptable
  et les responsables (équipe uniquement)
- Contrôles d'accès
- Suppression d'un planning
"""
from datetime import datetime, timedelta, timezone
import importlib
import sqlite3

import pytest
from blueprints import planning as routes


HORLOGE_TEST = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)


@pytest.fixture
def horloge_planning(monkeypatch):
    monkeypatch.setattr(routes, '_maintenant_utc', lambda: HORLOGE_TEST)
    return HORLOGE_TEST


def _planning_data(user_id, date_debut='2025-01-06'):
    """Construit un jeu de données POST minimal et valide pour un planning fixe."""
    return {
        'user_id': user_id,
        'type_periode': 'periode_scolaire',
        'date_debut_validite': date_debut,
        'type_alternance': 'fixe',
        'lundi_matin_debut': '09:00',
        'lundi_matin_fin': '12:00',
        'lundi_aprem_debut': '14:00',
        'lundi_aprem_fin': '17:00',
    }


def _creer_salarie_autre_secteur(db):
    """Crée un secteur et un salarié distincts (hors équipe du responsable de test)."""
    from werkzeug.security import generate_password_hash

    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO secteurs (nom, description) VALUES (?, ?)",
        ('Autre Secteur', 'Secteur distinct pour les tests')
    )
    autre_secteur_id = cursor.lastrowid
    cursor.execute(
        "INSERT INTO users (nom, prenom, login, password, profil, secteur_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ('Petit', 'Luc', 'autre_salarie', generate_password_hash('autre123'),
         'salarie', autre_secteur_id)
    )
    autre_salarie_id = cursor.lastrowid
    db.commit()
    return autre_salarie_id


class TestPlanningAcces:
    """Tests d'accès à la page de planning."""

    def test_acces_planning_salarie(self, auth_client):
        """Un salarié peut accéder à son propre planning."""
        response = auth_client.get('/planning_theorique')
        assert response.status_code == 200

    def test_acces_planning_non_connecte(self, client):
        """Non connecté => redirigé vers login."""
        response = client.get('/planning_theorique', follow_redirects=False)
        assert response.status_code == 302
        assert '/login' in response.headers['Location']

    def test_salarie_pas_de_selecteur(self, auth_client):
        """Un salarié ne voit pas le sélecteur de salarié."""
        response = auth_client.get('/planning_theorique')
        assert b'select-salarie' not in response.data

    def test_directeur_voit_selecteur_et_nom(self, admin_client, sample_users):
        """Le directeur voit le sélecteur et le nom du salarié ciblé."""
        response = admin_client.get(
            f"/planning_theorique?user_id={sample_users['salarie_id']}"
        )
        assert response.status_code == 200
        assert b'select-salarie' in response.data
        assert b'Martin' in response.data  # nom du salarié de test


class TestPlanningCreation:
    """Tests de création de planning pour soi-même."""

    def test_salarie_cree_son_planning(self, auth_client, app, db, sample_users):
        """Un salarié peut créer son propre planning théorique."""
        with app.app_context():
            response = auth_client.post(
                '/planning_theorique',
                data=_planning_data(sample_users['salarie_id']),
                follow_redirects=True,
            )
            assert response.status_code == 200

            row = db.execute(
                "SELECT * FROM planning_theorique WHERE user_id = ? AND date_debut_validite = ?",
                (sample_users['salarie_id'], '2025-01-06')
            ).fetchone()
            assert row is not None
            assert row['lundi_matin_debut'] == '09:00'


class TestPlanningDroits:
    """Contrôles d'accès pour la saisie du planning d'un autre salarié."""

    def test_directeur_cree_planning_salarie(self, admin_client, app, db, sample_users):
        """Le directeur peut saisir le planning de n'importe quel salarié."""
        with app.app_context():
            response = admin_client.post(
                '/planning_theorique',
                data=_planning_data(sample_users['salarie_id']),
                follow_redirects=True,
            )
            assert response.status_code == 200

            row = db.execute(
                "SELECT * FROM planning_theorique WHERE user_id = ? AND date_debut_validite = ?",
                (sample_users['salarie_id'], '2025-01-06')
            ).fetchone()
            assert row is not None

    def test_comptable_cree_planning_salarie(self, comptable_client, app, db, sample_users):
        """Le comptable peut saisir le planning de n'importe quel salarié."""
        with app.app_context():
            response = comptable_client.post(
                '/planning_theorique',
                data=_planning_data(sample_users['salarie_id']),
                follow_redirects=True,
            )
            assert response.status_code == 200

            row = db.execute(
                "SELECT * FROM planning_theorique WHERE user_id = ? AND date_debut_validite = ?",
                (sample_users['salarie_id'], '2025-01-06')
            ).fetchone()
            assert row is not None

    def test_responsable_cree_planning_de_son_equipe(self, resp_client, app, db, sample_users):
        """Le responsable peut saisir le planning d'un salarié de son secteur."""
        with app.app_context():
            response = resp_client.post(
                '/planning_theorique',
                data=_planning_data(sample_users['salarie_id']),
                follow_redirects=True,
            )
            assert response.status_code == 200

            row = db.execute(
                "SELECT * FROM planning_theorique WHERE user_id = ? AND date_debut_validite = ?",
                (sample_users['salarie_id'], '2025-01-06')
            ).fetchone()
            assert row is not None

    def test_responsable_ne_peut_pas_saisir_hors_equipe(self, resp_client, app, db, sample_users):
        """Le responsable ne peut PAS saisir le planning d'un salarié d'un autre secteur."""
        with app.app_context():
            autre_salarie_id = _creer_salarie_autre_secteur(db)

            response = resp_client.post(
                '/planning_theorique',
                data=_planning_data(autre_salarie_id),
                follow_redirects=True,
            )
            assert response.status_code == 200

            row = db.execute(
                "SELECT * FROM planning_theorique WHERE user_id = ?",
                (autre_salarie_id,)
            ).fetchone()
            assert row is None

    def test_salarie_ne_peut_pas_saisir_pour_autrui(self, auth_client, app, db, sample_users):
        """Un salarié ne peut PAS saisir le planning d'un autre salarié."""
        with app.app_context():
            response = auth_client.post(
                '/planning_theorique',
                data=_planning_data(sample_users['responsable_id']),
                follow_redirects=True,
            )
            assert response.status_code == 200

            row = db.execute(
                "SELECT * FROM planning_theorique WHERE user_id = ?",
                (sample_users['responsable_id'],)
            ).fetchone()
            assert row is None


class TestPlanningSuppression:
    """Tests de suppression de planning."""

    def test_directeur_supprime_planning_salarie(self, admin_client, app, db, sample_users, sample_planning):
        """Le directeur peut supprimer le planning d'un salarié."""
        planning_id = sample_planning['planning_id']

        with app.app_context():
            # La fixture est un planning synthétique ancien, sans horodatage.
            # Pour tester une suppression permise, le marquer comme récent.
            db.execute('UPDATE planning_theorique SET created_at=? WHERE id=?',
                       (datetime.now(timezone.utc).isoformat(), planning_id))
            db.commit()
            response = admin_client.post(
                f'/planning_theorique/supprimer/{planning_id}',
                follow_redirects=True,
            )
            assert response.status_code == 200

            row = db.execute(
                "SELECT * FROM planning_theorique WHERE id = ?", (planning_id,)
            ).fetchone()
            assert row is None

    def test_salarie_ne_peut_pas_supprimer_planning_autrui(self, auth_client, app, db, sample_users):
        """Un salarié ne peut PAS supprimer le planning d'un autre salarié."""
        with app.app_context():
            # Créer un planning appartenant au responsable
            cursor = db.cursor()
            cursor.execute(
                "INSERT INTO planning_theorique (user_id, type_periode, date_debut_validite, type_alternance, total_hebdo) "
                "VALUES (?, ?, ?, ?, ?)",
                (sample_users['responsable_id'], 'periode_scolaire', '2025-01-06', 'fixe', 35.0)
            )
            planning_id = cursor.lastrowid
            db.commit()

            response = auth_client.post(
                f'/planning_theorique/supprimer/{planning_id}',
                follow_redirects=True,
            )
            assert response.status_code == 200

            # Le planning ne doit PAS avoir été supprimé
            row = db.execute(
                "SELECT * FROM planning_theorique WHERE id = ?", (planning_id,)
            ).fetchone()
            assert row is not None


class TestPlanningCorrectionSeptJours:
    """Une correction rectifie une erreur récente sans effacer les versions anciennes."""

    def _creer(self, client, db, uid):
        result = client.post('/planning_theorique',
                             data=_planning_data(uid, '2026-12-07'), follow_redirects=True)
        assert result.status_code == 200
        row = db.execute('SELECT * FROM planning_theorique WHERE user_id=? ORDER BY id DESC LIMIT 1',
                         (uid,)).fetchone()
        assert row['created_at'] == HORLOGE_TEST.isoformat(timespec='seconds')
        return row['id'], row['created_at']

    def test_creation_date_enregistree_et_correction_possible(self, auth_client, db, sample_users,
                                                               horloge_planning):
        uid = sample_users['salarie_id']
        identifiant, cree_le = self._creer(auth_client, db, uid)
        page = auth_client.get('/planning_theorique').get_data(as_text=True)
        assert 'Corriger' in page

        formulaire = _planning_data(uid, '2026-12-14')
        formulaire.update(planning_id=str(identifiant), lundi_matin_debut='10:00')
        resultat = auth_client.post('/planning_theorique', data=formulaire, follow_redirects=True)
        assert resultat.status_code == 200
        assert 'Planning corrigé' in resultat.get_data(as_text=True)
        row = db.execute('SELECT * FROM planning_theorique WHERE id=?', (identifiant,)).fetchone()
        assert row['date_debut_validite'] == '2026-12-14'
        assert row['lundi_matin_debut'] == '10:00'
        assert row['created_at'] == cree_le
        assert db.execute('SELECT COUNT(*) FROM planning_theorique WHERE user_id=?',
                          (uid,)).fetchone()[0] == 1

    @pytest.mark.parametrize('ecart,autorise', [
        (timedelta(days=7) - timedelta(seconds=1), True),
        (timedelta(days=7), False),
        (timedelta(days=8), False),
    ])
    def test_borne_exacte_sept_jours(self, auth_client, db, sample_users,
                                     horloge_planning, monkeypatch, ecart, autorise):
        uid = sample_users['salarie_id']
        identifiant, _ = self._creer(auth_client, db, uid)
        monkeypatch.setattr(routes, '_maintenant_utc', lambda: HORLOGE_TEST + ecart)
        formulaire = _planning_data(uid, '2026-12-21')
        formulaire['planning_id'] = str(identifiant)
        response = auth_client.post('/planning_theorique', data=formulaire, follow_redirects=True)
        assert response.status_code == 200
        row = db.execute('SELECT date_debut_validite FROM planning_theorique WHERE id=?',
                         (identifiant,)).fetchone()
        assert row['date_debut_validite'] == ('2026-12-21' if autorise else '2026-12-07')
        if not autorise:
            assert 'ne peut plus être modifié après 7 jours' in response.get_data(as_text=True)

    def test_planning_historique_sans_creation_verrouille(self, auth_client, db, sample_users,
                                                         horloge_planning):
        uid = sample_users['salarie_id']
        cur = db.execute('INSERT INTO planning_theorique '
                         '(user_id, type_periode, date_debut_validite, type_alternance) '
                         "VALUES (?, 'periode_scolaire', '2024-01-01', 'fixe')", (uid,))
        db.commit()
        identifiant = cur.lastrowid
        assert db.execute('SELECT created_at FROM planning_theorique WHERE id=?',
                          (identifiant,)).fetchone()[0] is None
        page = auth_client.get('/planning_theorique').get_data(as_text=True)
        assert 'Correction indisponible' in page
        formulaire = _planning_data(uid, '2026-12-21')
        formulaire['planning_id'] = str(identifiant)
        auth_client.post('/planning_theorique', data=formulaire)
        row = db.execute('SELECT date_debut_validite FROM planning_theorique WHERE id=?',
                         (identifiant,)).fetchone()
        assert row[0] == '2024-01-01'
        auth_client.post(f'/planning_theorique/supprimer/{identifiant}')
        assert db.execute('SELECT id FROM planning_theorique WHERE id=?',
                          (identifiant,)).fetchone() is not None

    def test_suppression_verrouillee_apres_sept_jours(self, auth_client, db, sample_users,
                                                       horloge_planning, monkeypatch):
        uid = sample_users['salarie_id']
        identifiant, _ = self._creer(auth_client, db, uid)
        monkeypatch.setattr(routes, '_maintenant_utc', lambda: HORLOGE_TEST + timedelta(days=7))
        response = auth_client.post(f'/planning_theorique/supprimer/{identifiant}',
                                    follow_redirects=True)
        assert 'Suppression impossible après 7 jours' in response.get_data(as_text=True)
        assert db.execute('SELECT id FROM planning_theorique WHERE id=?',
                          (identifiant,)).fetchone() is not None

    def test_pas_de_correction_chez_autrui(self, auth_client, admin_client, db, sample_users,
                                           horloge_planning):
        uid = sample_users['responsable_id']
        identifiant, _ = self._creer(admin_client, db, uid)
        formulaire = _planning_data(uid, '2026-12-21')
        formulaire['planning_id'] = str(identifiant)
        auth_client.post('/planning_theorique', data=formulaire)
        row = db.execute('SELECT date_debut_validite FROM planning_theorique WHERE id=?',
                         (identifiant,)).fetchone()
        assert row[0] == '2026-12-07'

    def test_pas_de_correction_du_type(self, auth_client, db, sample_users,
                                        horloge_planning):
        uid = sample_users['salarie_id']
        identifiant, _ = self._creer(auth_client, db, uid)
        formulaire = _planning_data(uid, '2026-12-21')
        formulaire['planning_id'] = str(identifiant)
        formulaire['type_periode'] = 'vacances'
        auth_client.post('/planning_theorique', data=formulaire)
        row = db.execute('SELECT type_periode, date_debut_validite FROM planning_theorique WHERE id=?',
                         (identifiant,)).fetchone()
        assert (row['type_periode'], row['date_debut_validite']) == ('periode_scolaire', '2026-12-07')

    def test_migration_preserve_les_plannings_historiques(self):
        conn = sqlite3.connect(':memory:')
        try:
            conn.execute('CREATE TABLE planning_theorique (id INTEGER PRIMARY KEY, user_id INTEGER)')
            conn.execute('INSERT INTO planning_theorique (id, user_id) VALUES (1, 42)')
            migration = importlib.import_module('migrations.0086_planning_creation')
            migration.upgrade(conn)
            migration.upgrade(conn)  # migration idempotente
            assert conn.execute('SELECT created_at FROM planning_theorique WHERE id=1').fetchone()[0] is None
        finally:
            conn.close()

    def test_references_alternance_partagees_ne_bougent_pas(self, auth_client, db, sample_users,
                                                            horloge_planning):
        uid = sample_users['salarie_id']
        ids = []
        for semaine in ('semaine_1', 'semaine_2'):
            data = _planning_data(uid, '2026-12-07')
            data.update(type_alternance=semaine, date_reference='2026-12-07')
            response = auth_client.post('/planning_theorique', data=data, follow_redirects=True)
            assert response.status_code == 200
            identifiant = db.execute('SELECT MAX(id) FROM planning_theorique').fetchone()[0]
            ids.append(identifiant)
        data = _planning_data(uid, '2026-12-14')
        data.update(type_alternance='semaine_1', date_reference='2026-12-07', planning_id=str(ids[0]))
        response = auth_client.post('/planning_theorique', data=data, follow_redirects=True)
        assert 'date d’alternance est partagée' in response.get_data(as_text=True)
        for identifiant in ids:
            assert db.execute('SELECT date_debut_validite FROM planning_theorique WHERE id=?',
                              (identifiant,)).fetchone()[0] == '2026-12-07'
        assert db.execute('SELECT date_debut_validite FROM alternance_reference '
                          'WHERE user_id=?', (uid,)).fetchone()[0] == '2026-12-07'

    def test_reference_unique_se_deplace_avec_date(self, auth_client, db, sample_users,
                                                    horloge_planning):
        uid = sample_users['salarie_id']
        data = _planning_data(uid, '2026-12-07')
        data.update(type_alternance='semaine_1', date_reference='2026-12-07')
        auth_client.post('/planning_theorique', data=data)
        identifiant = db.execute('SELECT MAX(id) FROM planning_theorique').fetchone()[0]
        data['planning_id'] = str(identifiant)
        data['date_debut_validite'] = '2026-12-14'
        response = auth_client.post('/planning_theorique', data=data, follow_redirects=True)
        assert 'Planning corrigé' in response.get_data(as_text=True)
        assert db.execute('SELECT date_debut_validite FROM alternance_reference WHERE user_id=?',
                          (uid,)).fetchone()[0] == '2026-12-14'
        assert db.execute('SELECT date_debut_validite FROM planning_theorique WHERE id=?',
                          (identifiant,)).fetchone()[0] == '2026-12-14'
