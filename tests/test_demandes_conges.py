"""Tests pour les demandes de conges."""
import json


def test_demande_conge_page_accessible(auth_client):
    """Verifie que la page de demande de conge est accessible."""
    response = auth_client.get('/demande_conge')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Demande de cong' in html
    assert 'type_conge' in html


def test_demande_conge_creation(auth_client, app, db, sample_users, sample_planning):
    """Verifie la creation d'une demande de conge."""
    response = auth_client.post('/demande_conge', data={
        'type_conge': 'Congé payé',
        'date_debut': '2025-07-07',
        'date_fin': '2025-07-11',
        'motif_demande': 'Vacances',
    }, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        row = db.execute(
            "SELECT * FROM demandes_conges WHERE user_id = ?",
            (sample_users['salarie_id'],)
        ).fetchone()
        assert row is not None
        assert row['type_conge'] == 'Congé payé'
        assert row['nb_jours'] == 5
        assert row['statut'] == 'en_attente_responsable'


def test_demande_conge_type_invalide(auth_client):
    """Un type de conge invalide est rejete."""
    response = auth_client.post('/demande_conge', data={
        'type_conge': 'Sans solde',
        'date_debut': '2025-07-07',
        'date_fin': '2025-07-11',
    }, follow_redirects=True)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'invalide' in html.lower()


def test_demande_conge_dates_manquantes(auth_client):
    """Les dates manquantes sont rejetees."""
    response = auth_client.post('/demande_conge', data={
        'type_conge': 'Congé payé',
        'date_debut': '',
        'date_fin': '',
    }, follow_redirects=True)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'obligatoire' in html.lower()


def test_mes_demandes_conges_page(auth_client):
    """Verifie l'acces a la page mes demandes de conges."""
    response = auth_client.get('/mes_demandes_conges')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Mes demandes de cong' in html


def test_validation_demandes_page_accessible_directeur(admin_client):
    """Le directeur accede a la page de validation."""
    response = admin_client.get('/validation_demandes_recup')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Validation des demandes' in html


def test_validation_demandes_page_accessible_responsable(resp_client):
    """Le responsable accede a la page de validation."""
    response = resp_client.get('/validation_demandes_recup')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Validation des demandes' in html


def test_validation_demandes_interdit_salarie(auth_client):
    """Un salarie ne peut pas acceder a la validation."""
    response = auth_client.get('/validation_demandes_recup', follow_redirects=False)
    assert response.status_code == 302


def test_validation_conge_par_direction(admin_client, app, db, sample_users, sample_planning):
    """Verifie la validation d'un conge par la direction cree une absence."""
    with app.app_context():
        # Creer une demande de conge en attente direction
        db.execute('''
            INSERT INTO demandes_conges
            (user_id, type_conge, date_debut, date_fin, nb_jours, statut)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (sample_users['salarie_id'], 'Congé payé',
              '2025-08-04', '2025-08-08', 5, 'en_attente_direction'))
        db.commit()

        demande = db.execute('SELECT id FROM demandes_conges ORDER BY id DESC LIMIT 1').fetchone()
        demande_id = demande['id']

    response = admin_client.post('/validation_demandes_recup', data={
        'demande_id': demande_id,
        'action': 'valider',
        'demande_type': 'conge',
    }, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        # Verifier que la demande est validee
        dem = db.execute('SELECT statut FROM demandes_conges WHERE id = ?', (demande_id,)).fetchone()
        assert dem['statut'] == 'validee'

        # Verifier qu'une absence a ete creee
        absence = db.execute(
            "SELECT * FROM absences WHERE user_id = ? AND motif = 'Congé payé'",
            (sample_users['salarie_id'],)
        ).fetchone()
        assert absence is not None
        assert absence['jours_ouvres'] == 5


def test_refus_conge(admin_client, app, db, sample_users):
    """Verifie le refus d'un conge."""
    with app.app_context():
        db.execute('''
            INSERT INTO demandes_conges
            (user_id, type_conge, date_debut, date_fin, nb_jours, statut)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (sample_users['salarie_id'], 'Congé conventionnel',
              '2025-09-01', '2025-09-05', 5, 'en_attente_direction'))
        db.commit()
        demande = db.execute('SELECT id FROM demandes_conges ORDER BY id DESC LIMIT 1').fetchone()
        demande_id = demande['id']

    response = admin_client.post('/validation_demandes_recup', data={
        'demande_id': demande_id,
        'action': 'refuser',
        'demande_type': 'conge',
        'motif_refus': 'Periode non disponible',
    }, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        dem = db.execute('SELECT statut, motif_refus FROM demandes_conges WHERE id = ?', (demande_id,)).fetchone()
        assert dem['statut'] == 'refusee'
        assert dem['motif_refus'] == 'Periode non disponible'


def test_validation_responsable_conge(resp_client, app, db, sample_users):
    """Un responsable valide un conge vers en_attente_direction."""
    with app.app_context():
        db.execute('''
            INSERT INTO demandes_conges
            (user_id, type_conge, date_debut, date_fin, nb_jours, statut)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (sample_users['salarie_id'], 'Congé payé',
              '2025-10-06', '2025-10-10', 5, 'en_attente_responsable'))
        db.commit()
        demande = db.execute('SELECT id FROM demandes_conges ORDER BY id DESC LIMIT 1').fetchone()
        demande_id = demande['id']

    response = resp_client.post('/validation_demandes_recup', data={
        'demande_id': demande_id,
        'action': 'valider',
        'demande_type': 'conge',
    }, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        dem = db.execute('SELECT statut FROM demandes_conges WHERE id = ?', (demande_id,)).fetchone()
        assert dem['statut'] == 'en_attente_direction'


def test_historique_inclut_conges(admin_client, app, db, sample_users):
    """L'historique affiche les conges valides."""
    with app.app_context():
        db.execute('''
            INSERT INTO demandes_conges
            (user_id, type_conge, date_debut, date_fin, nb_jours, statut,
             validation_direction, date_validation_direction)
            VALUES (?, ?, ?, ?, ?, 'validee', 'Admin Test', '2025-07-01 10:00:00')
        ''', (sample_users['salarie_id'], 'Congé payé',
              '2025-07-07', '2025-07-11', 5))
        db.commit()

    response = admin_client.get('/historique_demandes_recup')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'CP' in html


def test_pending_count_includes_conges(admin_client, app, db, sample_users):
    """Le compteur de demandes en attente inclut les conges."""
    with app.app_context():
        db.execute('''
            INSERT INTO demandes_conges
            (user_id, type_conge, date_debut, date_fin, nb_jours, statut)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (sample_users['salarie_id'], 'Congé payé',
              '2025-11-03', '2025-11-07', 5, 'en_attente_direction'))
        db.commit()

    response = admin_client.get('/validation_demandes_recup')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'nav-badge' in html


def test_responsable_demande_conge_saute_responsable(resp_client, app, db, sample_users, sample_planning):
    """Un responsable qui fait une demande passe directement en attente direction."""
    response = resp_client.post('/demande_conge', data={
        'type_conge': 'Congé conventionnel',
        'date_debut': '2025-12-15',
        'date_fin': '2025-12-19',
        'motif_demande': '',
    }, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        row = db.execute(
            "SELECT statut FROM demandes_conges WHERE user_id = ?",
            (sample_users['responsable_id'],)
        ).fetchone()
        assert row is not None
        assert row['statut'] == 'en_attente_direction'
