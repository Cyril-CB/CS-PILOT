"""Tests UI minimaux pour la page salles."""

from flask import url_for


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


def test_salarie_voit_lien_salles_dans_menu(auth_client):
    """Le salarié doit pouvoir accéder au module Salles depuis le menu."""
    with auth_client.application.test_request_context():
        salles_url = url_for('salles_bp.salles')

    response = auth_client.get('/dashboard')

    assert response.status_code == 200
    assert f'<a href="{salles_url}" class="sidebar-link">🏠 Salles</a>' in response.get_data(as_text=True)


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
    assert 'Formation equipe' in response.get_data(as_text=True)
    assert recurrence['titre'] == 'Formation equipe'
    assert recurrence['created_by'] == sample_users['responsable_id']
    assert reservations == 5


# ── Vues jour / semaine / mois et navigation (retours utilisateurs) ──

def _salle(db, nom, couleur='#2563eb'):
    cur = db.execute("INSERT INTO salles (nom, couleur, active) VALUES (?, ?, 1)", (nom, couleur))
    db.commit()
    return cur.lastrowid


def _resa(db, salle_id, date, debut='09:00', fin='10:00', titre='Reunion'):
    db.execute("INSERT INTO reservations_salles (salle_id, titre, date, heure_debut, heure_fin) "
               "VALUES (?, ?, ?, ?, ?)", (salle_id, titre, date, debut, fin))
    db.commit()


def test_navigation_jour_precedent_suivant(auth_client, db, sample_users):
    _salle(db, 'Salle A')
    html = auth_client.get('/salles?date=2026-07-15').get_data(as_text=True)
    assert 'date=2026-07-14' in html    # flèche jour précédent
    assert 'date=2026-07-16' in html    # flèche jour suivant
    assert 'Semaine' in html and 'Mois' in html   # onglets de vue


def test_vue_jour_salles_reservees_en_tete(auth_client, db, sample_users):
    """La salle réservée passe devant dans la grille quotidienne, même si son
    nom la classe en dernier alphabétiquement."""
    _salle(db, 'Alpha')
    zid = _salle(db, 'Zebre')
    _resa(db, zid, '2026-07-15')
    html = auth_client.get('/salles?date=2026-07-15').get_data(as_text=True)
    assert html.index('Zebre') < html.index('Alpha')
    # Sans réservation : ordre alphabétique conservé.
    html = auth_client.get('/salles?date=2026-07-20').get_data(as_text=True)
    assert html.index('Alpha') < html.index('Zebre')


def test_vue_semaine_affiche_les_reservations(auth_client, db, sample_users):
    sid = _salle(db, 'Salle A')
    _resa(db, sid, '2026-07-14', titre='Atelier mardi')     # mardi
    # N'importe quel jour de la même semaine (jeudi 16) montre la semaine du 13 au 19.
    html = auth_client.get('/salles?date=2026-07-16&vue=semaine').get_data(as_text=True)
    assert 'Atelier mardi' in html
    assert 'Semaine du 13 au 19' in html
    assert 'date=2026-07-09' in html    # semaine précédente
    assert 'date=2026-07-23' in html    # semaine suivante
    # Chaque jour est cliquable vers la vue quotidienne.
    assert 'date=2026-07-14' in html and 'vue=jour' in html


def test_vue_mois_marque_les_jours_reserves(auth_client, db, sample_users):
    sid = _salle(db, 'Salle A')
    _resa(db, sid, '2026-07-14')
    _resa(db, sid, '2026-07-14', debut='14:00', fin='15:00')
    html = auth_client.get('/salles?date=2026-07-01&vue=mois').get_data(as_text=True)
    assert 'Juillet 2026' in html
    assert html.count('salles-mois-marque') == 1        # un seul jour marqué
    assert '2 reservation(s)' in html                    # avec le nombre
    assert 'date=2026-06-01' in html                     # mois précédent
    assert 'date=2026-08-01' in html                     # mois suivant
    # Mois sans réservation : aucune marque.
    html = auth_client.get('/salles?date=2026-09-01&vue=mois').get_data(as_text=True)
    assert 'salles-mois-marque' not in html


def test_date_ou_vue_invalide_retombe_proprement(auth_client, db, sample_users):
    _salle(db, 'Salle A')
    r = auth_client.get('/salles?date=zzz&vue=nimporte')
    assert r.status_code == 200
    assert 'salles-grid' in r.get_data(as_text=True)    # vue jour par défaut
    # Dates ISO valides mais aux bornes de Python : l'arithmétique de
    # navigation (±1 jour, ±7 jours) déborderait → retombée sur aujourd'hui
    # (revue Codex).
    for borne in ('0001-01-01', '9999-12-31', '1970-01-01'):
        r = auth_client.get(f'/salles?date={borne}&vue=semaine')
        assert r.status_code == 200, borne


def test_vue_semaine_salles_reservees_en_tete(auth_client, db, sample_users):
    """Même principe qu'en vue jour : la salle réservée dans la semaine passe
    en tête du tableau hebdomadaire."""
    _salle(db, 'Alpha')
    zid = _salle(db, 'Zebre')
    _resa(db, zid, '2026-07-14')
    html = auth_client.get('/salles?date=2026-07-16&vue=semaine').get_data(as_text=True)
    corps = html.split('salles-semaine-table')[1]
    assert corps.index('Zebre') < corps.index('Alpha')
