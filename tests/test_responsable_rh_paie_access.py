from werkzeug.security import generate_password_hash


def test_responsable_menu_rh_paie_contient_liens_et_deplace_temps_annualise(resp_client):
    response = resp_client.get('/dashboard_responsable')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '💼 RH &amp; Paie' in html or '💼 RH & Paie' in html
    assert 'Infos Salariés' in html
    assert 'Génération contrats' in html
    assert '<a href="/planning_enfance" class="sidebar-link">🕐 Temps annualisé</a>' not in html
    assert '<a href="/planning_enfance">🕐 Temps annualisé</a>' in html


def test_responsable_infos_salaries_limite_aux_salaries_de_son_equipe(resp_client, app, db, sample_users):
    with app.app_context():
        db.execute("INSERT INTO secteurs (nom, description) VALUES (?, ?)", ('Secteur Externe', 'Hors équipe'))
        secteur_externe_id = db.execute("SELECT id FROM secteurs WHERE nom = ?", ('Secteur Externe',)).fetchone()['id']
        db.execute(
            "INSERT INTO users (nom, prenom, login, password, profil, secteur_id, actif) VALUES (?, ?, ?, ?, ?, ?, 1)",
            ('Externe', 'Alice', 'ext_sal', generate_password_hash('Ext1234'), 'salarie', secteur_externe_id)
        )
        db.commit()

    response = resp_client.get('/infos_salaries')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Martin Jean (salarie) - Secteur Test' in html
    assert 'Dupont Marie (responsable) - Secteur Test' in html
    assert 'Externe Alice (salarie) - Secteur Externe' not in html


def test_responsable_infos_salaries_refuse_fiche_hors_equipe(resp_client, app, db):
    with app.app_context():
        db.execute("INSERT INTO secteurs (nom, description) VALUES (?, ?)", ('Secteur Externe 2', 'Hors équipe'))
        secteur_externe_id = db.execute("SELECT id FROM secteurs WHERE nom = ?", ('Secteur Externe 2',)).fetchone()['id']
        db.execute(
            "INSERT INTO users (nom, prenom, login, password, profil, secteur_id, actif) VALUES (?, ?, ?, ?, ?, ?, 1)",
            ('Externe', 'Bob', 'ext_sal2', generate_password_hash('Ext1234'), 'salarie', secteur_externe_id)
        )
        externe_id = db.execute("SELECT id FROM users WHERE login = ?", ('ext_sal2',)).fetchone()['id']
        db.commit()

    response = resp_client.get(f'/infos_salaries?user_id={externe_id}', follow_redirects=True)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Acces non autorise.' in html


def test_responsable_generation_contrats_limite_aux_salaries_de_son_equipe(resp_client, app, db):
    with app.app_context():
        db.execute("INSERT INTO secteurs (nom, description) VALUES (?, ?)", ('Secteur Externe 3', 'Hors équipe'))
        secteur_externe_id = db.execute("SELECT id FROM secteurs WHERE nom = ?", ('Secteur Externe 3',)).fetchone()['id']
        db.execute(
            "INSERT INTO users (nom, prenom, login, password, profil, secteur_id, actif) VALUES (?, ?, ?, ?, ?, ?, 1)",
            ('Externe', 'Claire', 'ext_sal3', generate_password_hash('Ext1234'), 'salarie', secteur_externe_id)
        )
        db.commit()

    response = resp_client.get('/generation_contrats')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Martin Jean' in html
    assert 'Dupont Marie' in html
    assert 'Externe Claire' not in html
