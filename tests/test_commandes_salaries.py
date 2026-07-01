from datetime import date

from tests.conftest import _login


def test_page_commandes_salaries_accessible_aux_salaries(auth_client):
    response = auth_client.get('/commandes-salaries')

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Commandes salariés' in html
    assert 'Description de la demande' in html
    assert 'Quantité' in html


def test_creation_demande_fournitures(auth_client, app, db, sample_users):
    response = auth_client.post(
        '/commandes-salaries',
        data={
            'description': 'Cahier grand format',
            'reference': 'REF-42',
            'quantite': '3',
            'prix': '12,50',
            'urgence': 'urgent',
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    row = db.execute(
        '''
        SELECT * FROM commandes_salaries
        WHERE user_id = ? AND description = ?
        ''',
        (sample_users['salarie_id'], 'Cahier grand format')
    ).fetchone()

    assert row is not None
    assert row['date_demande'] == date.today().isoformat()
    assert row['reference'] == 'REF-42'
    assert row['quantite'] == 3
    assert row['urgence'] == 'urgent'
    assert row['groupe'] == 'en_cours'
    assert row['prix'] == 12.5


def test_quantite_par_defaut_vaut_un(auth_client, db, sample_users):
    """Quantité omise : la demande est enregistrée avec 1 unité."""
    auth_client.post(
        '/commandes-salaries',
        data={'description': 'Ramette papier', 'urgence': 'normal'},
        follow_redirects=True,
    )
    row = db.execute(
        'SELECT quantite FROM commandes_salaries WHERE description = ?',
        ('Ramette papier',)
    ).fetchone()
    assert row is not None
    assert row['quantite'] == 1


def test_quantite_invalide_rejetee(auth_client, db, sample_users):
    """Quantité non entière/positive : la demande est refusée."""
    for valeur in ('0', '-2', 'abc', '1.5'):
        auth_client.post(
            '/commandes-salaries',
            data={'description': f'Article {valeur}', 'quantite': valeur, 'urgence': 'normal'},
            follow_redirects=True,
        )
        row = db.execute(
            'SELECT id FROM commandes_salaries WHERE description = ?',
            (f'Article {valeur}',)
        ).fetchone()
        assert row is None, f"la quantité invalide '{valeur}' n'aurait pas dû être enregistrée"


def test_quantite_affichee_dans_le_tableau(auth_client, db, sample_users):
    """La quantité saisie apparaît dans le tableau des demandes."""
    auth_client.post(
        '/commandes-salaries',
        data={'description': 'Boîte de trombones', 'quantite': '7', 'urgence': 'normal'},
        follow_redirects=True,
    )
    html = auth_client.get('/commandes-salaries').get_data(as_text=True)
    assert 'Boîte de trombones' in html
    assert '>7<' in html or '> 7 <' in html


def test_direction_peut_mettre_a_jour_le_statut(admin_client, db, sample_users):
    cursor = db.execute(
        '''
        INSERT INTO commandes_salaries (user_id, date_demande, description, urgence, groupe)
        VALUES (?, ?, ?, ?, ?)
        ''',
        (sample_users['salarie_id'], date.today().isoformat(), 'Stylos bleus', 'normal', 'en_cours')
    )
    db.commit()

    response = admin_client.post(
        f'/commandes-salaries/{cursor.lastrowid}/statut',
        data={'groupe': 'commandee'},
        follow_redirects=True,
    )

    assert response.status_code == 200
    row = db.execute(
        'SELECT groupe, traite_par FROM commandes_salaries WHERE id = ?',
        (cursor.lastrowid,)
    ).fetchone()
    assert row['groupe'] == 'commandee'
    assert row['traite_par'] == sample_users['directeur_id']


def test_delegation_ouvre_le_suivi_global_au_salarie(app, db, sample_users):
    db.execute(
        '''
        INSERT INTO commandes_salaries (user_id, date_demande, description, urgence, groupe)
        VALUES (?, ?, ?, ?, ?)
        ''',
        (sample_users['responsable_id'], date.today().isoformat(), 'Ramette papier A4', 'normal', 'en_cours')
    )
    db.commit()

    directeur_client = app.test_client()
    salarie_client = app.test_client()
    _login(directeur_client, 'admin', 'Admin1234')
    _login(salarie_client, 'salarie_test', 'sal123')

    before = salarie_client.get('/commandes-salaries')
    assert 'Marie Dupont' not in before.get_data(as_text=True)

    response = directeur_client.post(
        '/delegations',
        data={
            'mission_key': 'suivi_commandes_fournitures',
            'delegated_user_id': str(sample_users['salarie_id']),
        },
        follow_redirects=True,
    )

    assert response.status_code == 200

    after = salarie_client.get('/commandes-salaries')
    html = after.get_data(as_text=True)
    assert 'Marie Dupont' in html
    assert 'Ramette papier A4' in html


def test_menus_affichent_les_liens_commandes_et_delegation(app, sample_users):
    salarie_client = app.test_client()
    admin_client = app.test_client()
    _login(salarie_client, 'salarie_test', 'sal123')
    _login(admin_client, 'admin', 'Admin1234')

    salarie_html = salarie_client.get('/', follow_redirects=True).get_data(as_text=True)
    assert 'Commandes salariés' in salarie_html

    admin_html = admin_client.get('/', follow_redirects=True).get_data(as_text=True)
    assert 'Commandes salariés' in admin_html
    assert 'Délégation' in admin_html
