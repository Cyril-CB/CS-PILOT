"""
Tests de la délégation de la gestion des bénévoles.

Par défaut, le répertoire des bénévoles est tenu par la direction, la
comptabilité et — pour leurs seuls bénévoles — les responsables ; le suivi des
heures est réservé à la direction et à la comptabilité. La direction (ou la
comptabilité) peut confier l'intégralité de la page à un ou plusieurs salariés
depuis la page Délégation.
"""
from database import get_db


def _login(c, login, password):
    return c.post('/login', data={'login': login, 'password': password},
                  follow_redirects=True)


def _deleguer(client, user_ids):
    return client.post('/delegations', data={
        'form_type': 'benevoles',
        'benevoles_users': user_ids,
    }, follow_redirects=True)


def _creer_benevole(app, nom='Bernard Bénévole', responsable_id=None):
    with app.app_context():
        conn = get_db()
        cur = conn.execute(
            "INSERT INTO benevoles (nom, groupe, responsable_id) VALUES (?, 'actif', ?)",
            (nom, responsable_id)
        )
        conn.commit()
        ben_id = cur.lastrowid
        conn.close()
        return ben_id


def _delegations(app):
    with app.app_context():
        conn = get_db()
        ids = [r['user_id'] for r in
               conn.execute('SELECT user_id FROM delegations_benevoles').fetchall()]
        conn.close()
        return ids


# ── Sans délégation ──

def test_salarie_sans_delegation_n_accede_pas_a_la_page(app, sample_users):
    sal = app.test_client()
    _login(sal, 'salarie_test', 'sal123')
    r = sal.get('/benevoles', follow_redirects=False)
    assert r.status_code == 302
    assert '/dashboard' in r.headers['Location']


def test_salarie_sans_delegation_ne_peut_pas_modifier(app, sample_users):
    ben_id = _creer_benevole(app)
    sal = app.test_client()
    _login(sal, 'salarie_test', 'sal123')
    r = sal.post(f'/api/benevoles/{ben_id}/modifier',
                 json={'field': 'nom', 'value': 'Piraté'})
    assert r.status_code == 403
    with app.app_context():
        conn = get_db()
        nom = conn.execute('SELECT nom FROM benevoles WHERE id = ?', (ben_id,)).fetchone()['nom']
        conn.close()
    assert nom == 'Bernard Bénévole'


def test_salarie_sans_delegation_n_accede_pas_au_suivi_des_heures(app, sample_users):
    sal = app.test_client()
    _login(sal, 'salarie_test', 'sal123')
    r = sal.get('/benevoles/heures', follow_redirects=False)
    assert r.status_code == 302


# ── Attribution de la délégation ──

def test_directeur_delegue_puis_salarie_gere_la_page(app, sample_users):
    ben_id = _creer_benevole(app)
    admin = app.test_client()
    _login(admin, 'admin', 'Admin1234')
    r = _deleguer(admin, [sample_users['salarie_id']])
    assert 'ont été enregistrées' in r.get_data(as_text=True)
    assert _delegations(app) == [sample_users['salarie_id']]

    sal = app.test_client()
    _login(sal, 'salarie_test', 'sal123')
    # Répertoire : consultation, modification, ajout et suppression.
    assert sal.get('/benevoles').status_code == 200
    assert sal.post(f'/api/benevoles/{ben_id}/modifier',
                    json={'field': 'nom', 'value': 'Bernard B.'}).status_code == 200
    assert sal.post('/api/benevoles/ajouter',
                    json={'nom': 'Nouvelle recrue', 'groupe': 'nouveau'}).status_code == 200
    assert sal.post(f'/api/benevoles/{ben_id}/supprimer', json={}).status_code == 200
    with app.app_context():
        conn = get_db()
        noms = [r['nom'] for r in conn.execute('SELECT nom FROM benevoles').fetchall()]
        conn.close()
    assert noms == ['Nouvelle recrue']


def test_salarie_delegue_accede_au_suivi_des_heures(app, sample_users):
    admin = app.test_client()
    _login(admin, 'admin', 'Admin1234')
    _deleguer(admin, [sample_users['salarie_id']])

    sal = app.test_client()
    _login(sal, 'salarie_test', 'sal123')
    assert sal.get('/benevoles/heures').status_code == 200
    r = sal.post('/api/benevoles/activites/ajouter',
                 json={'nom': 'Conseil d\'administration', 'mode': 'seance'})
    assert r.status_code == 200
    with app.app_context():
        conn = get_db()
        n = conn.execute('SELECT COUNT(*) AS n FROM benevoles_activites').fetchone()['n']
        conn.close()
    assert n == 1


def test_plusieurs_salaries_delegues(app, sample_users):
    admin = app.test_client()
    _login(admin, 'admin', 'Admin1234')
    _deleguer(admin, [sample_users['salarie_id'], sample_users['responsable_id']])
    assert sorted(_delegations(app)) == sorted(
        [sample_users['salarie_id'], sample_users['responsable_id']])


def test_responsable_delegue_voit_tous_les_benevoles(app, sample_users):
    """Sans délégation le responsable ne voit que ses bénévoles ; avec la
    délégation il gère la page entière (liste complète et bouton d'ajout)."""
    _creer_benevole(app, 'Bénévole du responsable', sample_users['responsable_id'])
    _creer_benevole(app, 'Bénévole sans responsable')

    resp = app.test_client()
    _login(resp, 'resp_test', 'resp123')
    html = resp.get('/benevoles').get_data(as_text=True)
    assert 'Bénévole du responsable' in html
    assert 'Bénévole sans responsable' not in html
    assert '+ Ajouter' not in html

    admin = app.test_client()
    _login(admin, 'admin', 'Admin1234')
    _deleguer(admin, [sample_users['responsable_id']])

    html = resp.get('/benevoles').get_data(as_text=True)
    assert 'Bénévole sans responsable' in html
    assert '+ Ajouter' in html


def test_comptable_peut_deleguer(app, sample_users):
    """La comptabilité tient la page bénévoles : elle peut aussi la déléguer."""
    compta = app.test_client()
    _login(compta, 'compta_test', 'compta123')
    r = _deleguer(compta, [sample_users['salarie_id']])
    assert 'ont été enregistrées' in r.get_data(as_text=True)
    assert _delegations(app) == [sample_users['salarie_id']]


# ── Retrait de la délégation ──

def test_retrait_de_la_delegation(app, sample_users):
    ben_id = _creer_benevole(app)
    admin = app.test_client()
    _login(admin, 'admin', 'Admin1234')
    _deleguer(admin, [sample_users['salarie_id']])
    # Retrait : aucune case cochée.
    admin.post('/delegations', data={'form_type': 'benevoles'}, follow_redirects=True)
    assert _delegations(app) == []

    sal = app.test_client()
    _login(sal, 'salarie_test', 'sal123')
    assert sal.get('/benevoles', follow_redirects=False).status_code == 302
    assert sal.post(f'/api/benevoles/{ben_id}/modifier',
                    json={'field': 'nom', 'value': 'Piraté'}).status_code == 403


def test_delegation_sans_effet_si_le_compte_est_desactive(app, sample_users):
    """Une délégation ne doit pas survivre à la désactivation du compte."""
    admin = app.test_client()
    _login(admin, 'admin', 'Admin1234')
    _deleguer(admin, [sample_users['salarie_id']])

    sal = app.test_client()
    _login(sal, 'salarie_test', 'sal123')
    assert sal.get('/benevoles').status_code == 200

    with app.app_context():
        conn = get_db()
        conn.execute('UPDATE users SET actif = 0 WHERE id = ?', (sample_users['salarie_id'],))
        conn.commit()
        conn.close()
    assert sal.get('/benevoles', follow_redirects=False).status_code == 302


# ── Contrôles d'accès de la page Délégation ──

def test_salarie_ne_peut_pas_se_deleguer_lui_meme(app, sample_users):
    sal = app.test_client()
    _login(sal, 'salarie_test', 'sal123')
    r = sal.post('/delegations', data={
        'form_type': 'benevoles',
        'benevoles_users': [sample_users['salarie_id']],
    }, follow_redirects=False)
    assert r.status_code == 302
    assert _delegations(app) == []


def test_responsable_ne_peut_pas_deleguer(app, sample_users):
    resp = app.test_client()
    _login(resp, 'resp_test', 'resp123')
    resp.post('/delegations', data={
        'form_type': 'benevoles',
        'benevoles_users': [sample_users['salarie_id']],
    }, follow_redirects=True)
    assert _delegations(app) == []


def test_profil_non_delegable_ignore(app, sample_users, db):
    """Seuls les comptes actifs salarié/responsable sont délégables : un
    identifiant forgé (ici la comptabilité) est écarté côté serveur."""
    admin = app.test_client()
    _login(admin, 'admin', 'Admin1234')
    _deleguer(admin, [sample_users['comptable_id'], sample_users['salarie_id']])
    assert _delegations(app) == [sample_users['salarie_id']]


# ── Page Délégation et menu ──

def test_page_delegations_affiche_la_section(app, sample_users):
    admin = app.test_client()
    _login(admin, 'admin', 'Admin1234')
    html = admin.get('/delegations').get_data(as_text=True)
    assert 'Gestion des bénévoles' in html
    assert 'name="benevoles_users"' in html


def test_section_benevoles_active_pour_le_comptable(app, sample_users):
    compta = app.test_client()
    _login(compta, 'compta_test', 'compta123')
    html = compta.get('/delegations').get_data(as_text=True)
    section = html.split('Gestion des bénévoles')[1]
    assert 'Enregistrer les délégations' in section
    assert 'disabled' not in section.split('form-actions')[0]


def test_menu_benevoles_visible_pour_le_salarie_delegue(app, sample_users):
    sal = app.test_client()
    _login(sal, 'salarie_test', 'sal123')
    assert '🤝 Bénévoles' not in sal.get('/dashboard').get_data(as_text=True)

    admin = app.test_client()
    _login(admin, 'admin', 'Admin1234')
    _deleguer(admin, [sample_users['salarie_id']])

    assert '🤝 Bénévoles' in sal.get('/dashboard').get_data(as_text=True)


class TestBaseNeuve:
    """Une installation neuve ne doit pas réclamer une migration déjà incluse."""

    def test_migration_0063_marquee_appliquee(self, app, db):
        import database
        assert any(v == '0063' for v, _ in database.ALL_MIGRATION_VERSIONS), \
            "0063 doit figurer dans ALL_MIGRATION_VERSIONS"
        with app.app_context():
            ligne = db.execute(
                "SELECT statut FROM schema_migrations WHERE version = '0063'").fetchone()
        assert ligne and ligne['statut'] == 'ok'
