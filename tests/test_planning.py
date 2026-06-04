"""
Tests pour le module planning.py :
- Saisie du planning théorique (pour soi-même)
- Saisie du planning d'un autre salarié par la direction, le comptable
  et les responsables (équipe uniquement)
- Contrôles d'accès
- Suppression d'un planning
"""


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
