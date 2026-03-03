from io import BytesIO
from blueprints.generation_contrat import _build_replacements


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


def test_aliases_naissance_et_securitesociale_sont_inclus():
    salarie = {
        'nom': 'Martin',
        'prenom': 'Jean',
        'adresse_postale': '10 rue des Tests',
        'email': 'jean@example.org',
        'date_naissance': '1999-01-01',
        'numero_securite_sociale': '1 99 01 75 123 456 78',
    }
    form = {
        'date_debut': '2026-03-01',
        'date_fin': '',
        'remplace': '',
        'hebdo': '35h',
        'essai': '2 mois',
        'anciennete': '0',
        'forfait': '',
        'jours': '',
        'lundi': '',
        'mardi': '',
        'mercredi': '',
        'jeudi': '',
        'vendredi': '',
    }
    repl = _build_replacements(
        salarie=salarie,
        type_contrat='CDI',
        poste=None,
        responsable=None,
        lieux_rows=[],
        socle=23000.0,
        brutm=2500.0,
        form=form
    )
    assert repl['NAISSANCE'] == '1999-01-01'
    assert repl['SECURITESOCIALE'] == '1 99 01 75 123 456 78'
