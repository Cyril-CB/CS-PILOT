import re


def test_dashboard_responsable_accessible(resp_client):
    """Verifie que le responsable accede a son dashboard."""
    response = resp_client.get('/dashboard_responsable')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Mon equipe' in html
    assert 'Absences en cours' in html
    assert 'Validations mensuelles' in html


def test_dashboard_responsable_affiche_sections(resp_client):
    """Verifie que les sections specifiques responsable sont presentes."""
    response = resp_client.get('/dashboard_responsable')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Mon solde récupération' in html
    assert 'Mes congés payés' in html
    assert 'Mes congés conventionnels' in html
    assert 'ETP Secteur' in html
    assert 'Factures en attente' in html
    assert 'Factures a approuver' in html
    assert 'cup &' in html  # "Demandes récup & congés"
    assert 'Subventions' in html
    assert 'Budget' in html
    assert 'Conges de l&#39;equipe' in html or "Conges de l'equipe" in html


def test_dashboard_responsable_affiche_les_soldes_en_cartes(resp_client, app, db, sample_users):
    with app.app_context():
        db.execute(
            '''
            UPDATE users
            SET solde_initial = ?, cp_a_prendre = ?, cp_pris = ?, cc_solde = ?
            WHERE id = ?
            ''',
            (3.5, 12, 2, -1, sample_users['responsable_id'])
        )
        db.commit()

    response = resp_client.get('/dashboard_responsable')
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert re.search(r'<div class="stat-card">.*?Mon solde récupération', html, re.S)
    assert re.search(r'<div class="stat-card">.*?Mes congés payés', html, re.S)
    assert re.search(r'<div class="stat-card">.*?Mes congés conventionnels', html, re.S)
    assert '+3.5h' in html
    assert '10.0 j' in html
    assert '-1.0 j' in html


def test_dashboard_responsable_pas_tresorerie_anomalies(resp_client):
    """Verifie que Tresorerie et Anomalies ne sont PAS affiches."""
    response = resp_client.get('/dashboard_responsable')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Tresorerie' not in html
    assert 'Anomalies' not in html


def test_dashboard_responsable_acces_rapides(resp_client):
    """Verifie que les acces rapides sont presents et adaptes."""
    response = resp_client.get('/dashboard_responsable')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Vue ensemble validation' in html
    assert 'Approbation factures' in html
    assert 'Mon budget' in html
    assert 'Budget previsionnel' in html


def test_dashboard_responsable_refuse_salarie(client, sample_users):
    """Verifie qu'un salarie ne peut pas acceder au dashboard responsable."""
    from tests.conftest import _login
    _login(client, 'salarie_test', 'sal123')
    response = client.get('/dashboard_responsable', follow_redirects=False)
    assert response.status_code == 302


def test_dashboard_responsable_refuse_directeur(admin_client):
    """Verifie qu'un directeur ne peut pas acceder au dashboard responsable."""
    response = admin_client.get('/dashboard_responsable', follow_redirects=False)
    assert response.status_code == 302


def test_dashboard_redirect_responsable(resp_client):
    """Verifie que /dashboard redirige vers dashboard_responsable pour un responsable."""
    response = resp_client.get('/dashboard', follow_redirects=False)
    assert response.status_code == 302
    assert 'dashboard_responsable' in response.headers.get('Location', '')


def test_dashboard_responsable_sans_secteur_ne_boucle_pas(resp_client, app, db, sample_users):
    """Pas de boucle de redirection pour un responsable sans secteur.

    - avec des rattachés directs : /dashboard renvoie vers le tableau
      responsable, qui s'affiche (une seule redirection) ;
    - sans secteur NI rattaché : /dashboard s'affiche directement (le tableau
      responsable renverrait vers /dashboard : c'est le vrai risque de boucle).
    """
    with app.app_context():
        db.execute(
            "UPDATE users SET secteur_id = NULL WHERE id = ?",
            (sample_users['responsable_id'],)
        )
        db.commit()

    # Avec rattaché (Martin) : redirection unique vers le tableau responsable.
    response = resp_client.get('/dashboard', follow_redirects=True)
    assert response.status_code == 200
    assert len(response.history) == 1
    assert response.request.path == '/dashboard_responsable'

    # Sans rattaché : /dashboard se rend directement, sans redirection.
    with app.app_context():
        db.execute("UPDATE users SET responsable_id = NULL WHERE responsable_id = ?",
                   (sample_users['responsable_id'],))
        db.commit()
    response = resp_client.get('/dashboard', follow_redirects=False)
    assert response.status_code == 200


def test_dashboard_responsable_sans_secteur_ni_rattache_redirige(resp_client, app, db, sample_users):
    """Sans secteur NI rattaché direct : redirection vers /dashboard."""
    with app.app_context():
        db.execute("UPDATE users SET secteur_id = NULL WHERE id = ?",
                   (sample_users['responsable_id'],))
        # Détacher aussi le salarié rattaché (responsable_id) du jeu de données.
        db.execute("UPDATE users SET responsable_id = NULL WHERE responsable_id = ?",
                   (sample_users['responsable_id'],))
        db.commit()

    response = resp_client.get('/dashboard_responsable', follow_redirects=False)
    assert response.status_code == 302
    assert response.headers.get('Location', '').endswith('/dashboard')


def test_dashboard_responsable_sans_secteur_mais_avec_rattache(resp_client, app, db, sample_users):
    """Sans secteur mais avec un rattaché direct (responsable_id), le tableau
    reste accessible et montre l'équipe rattachée."""
    with app.app_context():
        db.execute("UPDATE users SET secteur_id = NULL WHERE id = ?",
                   (sample_users['responsable_id'],))
        db.commit()

    html = resp_client.get('/dashboard_responsable').get_data(as_text=True)
    assert 'Martin' in html    # le rattaché reste visible
