"""
Tests du libellé du valideur de second niveau des demandes (direction / comptable).

Le nom du valideur était affiché avec un libellé « (direction) » codé en dur :
quand un(e) comptable validait une demande (en l'absence de la direction), son
nom apparaissait à tort comme « direction ». Le profil du valideur est
désormais stocké à la validation (profil_validation_direction) et le libellé
s'y adapte partout (pages, PDF).
"""


def _creer_demande_conge(db, user_id, statut='en_attente_direction'):
    cur = db.execute('''
        INSERT INTO demandes_conges
        (user_id, type_conge, date_debut, date_fin, nb_jours, statut)
        VALUES (?, 'Congé payé', '2025-08-04', '2025-08-08', 5, ?)
    ''', (user_id, statut))
    db.commit()
    return cur.lastrowid


def _valider(client, demande_id):
    return client.post('/validation_demandes_recup', data={
        'demande_id': demande_id,
        'action': 'valider',
        'demande_type': 'conge',
    }, follow_redirects=True)


def test_validation_par_comptable_stocke_son_profil(comptable_client, app, db,
                                                    sample_users, sample_planning):
    with app.app_context():
        demande_id = _creer_demande_conge(db, sample_users['salarie_id'])
    response = _valider(comptable_client, demande_id)
    assert response.status_code == 200

    with app.app_context():
        dem = db.execute('SELECT * FROM demandes_conges WHERE id = ?', (demande_id,)).fetchone()
    assert dem['statut'] == 'validee'
    assert dem['validation_direction'] == 'Sophie Durand'
    assert dem['profil_validation_direction'] == 'comptable'


def test_validation_par_directeur_stocke_son_profil(admin_client, app, db,
                                                    sample_users, sample_planning):
    with app.app_context():
        demande_id = _creer_demande_conge(db, sample_users['salarie_id'])
    _valider(admin_client, demande_id)

    with app.app_context():
        dem = db.execute('SELECT * FROM demandes_conges WHERE id = ?', (demande_id,)).fetchone()
    assert dem['statut'] == 'validee'
    assert dem['profil_validation_direction'] == 'directeur'


def test_auto_validation_directeur_stocke_son_profil(admin_client, app, db):
    # Un directeur qui pose son propre congé est auto-validé « direction ».
    admin_client.post('/demande_conge', data={
        'type_conge': 'Congé payé', 'date_debut': '2026-06-02', 'date_fin': '2026-06-02',
    }, follow_redirects=True)
    with app.app_context():
        dem = db.execute('SELECT * FROM demandes_conges ORDER BY id DESC LIMIT 1').fetchone()
    assert dem['statut'] == 'validee'
    assert dem['profil_validation_direction'] == 'directeur'


def test_libelle_comptable_sur_mes_demandes_conges(client, app, db,
                                                   sample_users, sample_planning):
    """Le salarié doit voir « (comptable) » — pas « (direction) » — quand
    c'est la comptabilité qui a validé sa demande."""
    with app.app_context():
        demande_id = _creer_demande_conge(db, sample_users['salarie_id'])

    # La comptable valide la demande…
    client.post('/login', data={'login': 'compta_test', 'password': 'compta123'},
                follow_redirects=True)
    _valider(client, demande_id)
    client.get('/logout', follow_redirects=True)

    # … puis le salarié consulte ses demandes.
    client.post('/login', data={'login': 'salarie_test', 'password': 'sal123'},
                follow_redirects=True)
    html = client.get('/mes_demandes_conges').get_data(as_text=True)
    assert 'Sophie Durand' in html
    assert '(comptable)' in html
    assert '(direction)' not in html


def test_libelle_direction_conserve_pour_un_directeur(client, app, db,
                                                      sample_users, sample_planning):
    with app.app_context():
        demande_id = _creer_demande_conge(db, sample_users['salarie_id'])

    client.post('/login', data={'login': 'admin', 'password': 'Admin1234'},
                follow_redirects=True)
    _valider(client, demande_id)
    client.get('/logout', follow_redirects=True)

    client.post('/login', data={'login': 'salarie_test', 'password': 'sal123'},
                follow_redirects=True)
    html = client.get('/mes_demandes_conges').get_data(as_text=True)
    assert '(direction)' in html
    assert '(comptable)' not in html


def test_pdf_conge_valide_par_comptable(comptable_client, app, db,
                                        sample_users, sample_planning):
    """Le PDF d'une demande validée par la comptabilité doit s'éditer sans
    erreur (colonne de signature « Comptable »)."""
    with app.app_context():
        demande_id = _creer_demande_conge(db, sample_users['salarie_id'])
    _valider(comptable_client, demande_id)

    r = comptable_client.get(f'/demande_conge/{demande_id}/pdf')
    assert r.status_code == 200
    assert r.headers['Content-Type'] == 'application/pdf'
    assert r.get_data()[:4] == b'%PDF'


def test_backfill_migration_retrouve_le_profil(app, db, sample_users):
    """La migration 0058 renseigne le profil des demandes déjà validées en
    retrouvant le valideur par « Prénom Nom » (NULL si inconnu)."""
    with app.app_context():
        cur = db.execute('''
            INSERT INTO demandes_conges
            (user_id, type_conge, date_debut, date_fin, nb_jours, statut,
             validation_direction, profil_validation_direction)
            VALUES (?, 'Congé payé', '2025-03-03', '2025-03-04', 2, 'validee',
                    'Sophie Durand', NULL)
        ''', (sample_users['salarie_id'],))
        connue_id = cur.lastrowid
        cur = db.execute('''
            INSERT INTO demandes_conges
            (user_id, type_conge, date_debut, date_fin, nb_jours, statut,
             validation_direction, profil_validation_direction)
            VALUES (?, 'Congé payé', '2025-03-05', '2025-03-06', 2, 'validee',
                    'Personne Partie', NULL)
        ''', (sample_users['salarie_id'],))
        inconnue_id = cur.lastrowid
        db.commit()

        import importlib.util
        import os
        chemin = os.path.join(os.path.dirname(__file__), '..', 'migrations',
                              '0058_profil_validation_direction.py')
        spec = importlib.util.spec_from_file_location('migration_0058_test', chemin)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        migration.upgrade(db)

        connue = db.execute('SELECT profil_validation_direction FROM demandes_conges WHERE id = ?',
                            (connue_id,)).fetchone()
        inconnue = db.execute('SELECT profil_validation_direction FROM demandes_conges WHERE id = ?',
                              (inconnue_id,)).fetchone()
    assert connue['profil_validation_direction'] == 'comptable'
    assert inconnue['profil_validation_direction'] is None
