"""Tests UI minimaux pour la page salles."""


def test_gestion_salles_utilise_toggle_dedie(admin_client, db):
    """Le formulaire admin des salles doit utiliser le toggle dédié à la page."""
    db.execute(
        "INSERT INTO salles (nom, capacite, description, couleur, active) VALUES (?, ?, ?, ?, ?)",
        ('Salle Polyvalente', 30, 'Test', '#2563eb', 1)
    )
    db.commit()

    resp = admin_client.get('/salles')
    html = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert "onclick=\"toggleSallesSection('section-salles')\"" in html
    assert "onclick=\"toggleSallesSection('section-resa')\"" in html
    assert "onclick=\"toggleSallesSection('section-rec')\"" in html
    assert "function toggleSallesSection(id)" in html


def test_responsable_peut_voir_formulaire_recurrence(resp_client, db):
    """Le responsable doit voir la section de creation de recurrences."""
    db.execute(
        "INSERT INTO salles (nom, capacite, description, couleur, active) VALUES (?, ?, ?, ?, ?)",
        ('Salle Reunion', 20, 'Test', '#2563eb', 1)
    )
    db.commit()

    resp = resp_client.get('/salles')
    html = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert 'Creer la recurrence' in html
    assert "onclick=\"toggleSallesSection('section-rec')\"" in html


def test_salarie_ne_peut_pas_creer_recurrence(auth_client, db):
    """Le salarie conserve l'interdiction de creer une recurrence."""
    cursor = db.execute(
        "INSERT INTO salles (nom, capacite, description, couleur, active) VALUES (?, ?, ?, ?, ?)",
        ('Salle Atelier', 15, 'Test', '#0ea5e9', 1)
    )
    salle_id = cursor.lastrowid
    db.commit()

    response = auth_client.post('/salles/recurrence', data={
        'salle_id': salle_id,
        'titre_rec': 'Atelier',
        'jour_semaine': 0,
        'heure_debut_rec': '09:00',
        'heure_fin_rec': '10:00',
        'date_debut_rec': '2026-04-20',
        'date_fin_rec': '2026-05-20',
    }, follow_redirects=True)

    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Seuls les administrateurs et responsables peuvent creer des recurrences.' in html
    assert 'Creer la recurrence' not in html
    assert db.execute('SELECT COUNT(*) FROM recurrences_salles').fetchone()[0] == 0


def test_responsable_peut_creer_recurrence(resp_client, db, sample_users):
    """Le responsable peut creer une recurrence de salle."""
    cursor = db.execute(
        "INSERT INTO salles (nom, capacite, description, couleur, active) VALUES (?, ?, ?, ?, ?)",
        ('Salle Formation', 12, 'Test', '#22c55e', 1)
    )
    salle_id = cursor.lastrowid
    db.commit()

    response = resp_client.post('/salles/recurrence', data={
        'salle_id': salle_id,
        'titre_rec': 'Formation equipe',
        'description_rec': 'Hebdomadaire',
        'jour_semaine': 0,
        'heure_debut_rec': '09:00',
        'heure_fin_rec': '10:00',
        'date_debut_rec': '2026-04-20',
        'date_fin_rec': '2026-05-18',
        'exclure_vacances': '1',
        'exclure_feries': '1',
    }, follow_redirects=True)

    recurrence = db.execute(
        'SELECT titre, created_by FROM recurrences_salles'
    ).fetchone()
    reservations = db.execute(
        'SELECT COUNT(*) FROM reservations_salles WHERE recurrence_id IS NOT NULL'
    ).fetchone()[0]

    assert response.status_code == 200
    assert 'Recurrence "Formation equipe" creee' in response.get_data(as_text=True)
    assert recurrence['titre'] == 'Formation equipe'
    assert recurrence['created_by'] == sample_users['responsable_id']
    assert reservations == 5
