from io import BytesIO


def test_infos_salaries_met_a_jour_coordonnees(admin_client, db, sample_users):
    user_id = sample_users['salarie_id']
    response = admin_client.post('/infos_salaries/email', data={
        'user_id': user_id,
        'adresse_postale': '10 rue des Tests',
        'numero_securite_sociale': '1 99 01 75 123 456 78',
        'date_naissance': '1999-01-01',
        'email': 'jean.martin@example.org',
    }, follow_redirects=True)
    assert response.status_code == 200

    row = db.execute(
        "SELECT adresse_postale, numero_securite_sociale, date_naissance, email FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()
    assert row['adresse_postale'] == '10 rue des Tests'
    assert row['numero_securite_sociale'] == '1 99 01 75 123 456 78'
    assert row['date_naissance'] == '1999-01-01'
    assert row['email'] == 'jean.martin@example.org'


def test_page_generation_contrat_accessible_admin(admin_client):
    response = admin_client.get('/generation_contrat')
    content = response.data.decode('utf-8')
    assert response.status_code == 200
    assert 'Generation contrat' in content
    assert 'Generer un contrat' in content
    assert 'Modeles DOCX' in content
    assert 'Brut mensuel (BRUTM)' in content


def test_upload_modele_refuse_si_pas_docx(admin_client):
    response = admin_client.post('/generation_contrat/modeles', data={
        'nom_modele': 'Modele test',
        'fichier_modele': (BytesIO(b'test'), 'modele.txt'),
    }, content_type='multipart/form-data', follow_redirects=True)
    assert response.status_code == 200
    assert 'DOCX' in response.data.decode('utf-8')
