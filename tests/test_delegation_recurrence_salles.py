"""
Tests de la délégation des réservations de salle récurrentes.

Par défaut, seuls la direction/comptable et les responsables peuvent créer des
récurrences. La direction peut déléguer ce droit à des salariés depuis la page
Délégation.
"""
from database import get_db


def _login(c, login, password):
    return c.post('/login', data={'login': login, 'password': password}, follow_redirects=True)


def _make_salle(app, nom='Salle Test'):
    with app.app_context():
        conn = get_db()
        cur = conn.execute("INSERT INTO salles (nom, active) VALUES (?, 1)", (nom,))
        conn.commit()
        sid = cur.lastrowid
        conn.close()
        return sid


def _recurrence_form(salle_id):
    return {
        'salle_id': salle_id,
        'titre_rec': 'Atelier hebdo',
        'description_rec': '',
        'jour_semaine': 0,            # Lundi
        'heure_debut_rec': '09:00',
        'heure_fin_rec': '10:00',
        'date_debut_rec': '2025-01-06',
        'date_fin_rec': '2025-01-27',
        'exclure_vacances': '',
        'exclure_feries': '',
    }


def _count_recurrences(app):
    with app.app_context():
        conn = get_db()
        n = conn.execute('SELECT COUNT(*) AS n FROM recurrences_salles').fetchone()['n']
        conn.close()
        return n


def test_salarie_sans_delegation_ne_peut_pas_creer_recurrence(app, sample_users):
    salle_id = _make_salle(app)
    sal = app.test_client()
    _login(sal, 'salarie_test', 'sal123')
    sal.post('/salles/recurrence', data=_recurrence_form(salle_id), follow_redirects=True)
    assert _count_recurrences(app) == 0


def test_directeur_delegue_puis_salarie_peut_creer(app, sample_users):
    salle_id = _make_salle(app)
    admin = app.test_client()
    _login(admin, 'admin', 'Admin1234')
    # Déléguer la récurrence au salarié.
    admin.post('/delegations', data={
        'form_type': 'salle_recurrence',
        'salle_recurrence_users': [sample_users['salarie_id']],
    }, follow_redirects=True)

    with app.app_context():
        conn = get_db()
        row = conn.execute(
            'SELECT user_id FROM delegations_salles_recurrence WHERE user_id = ?',
            (sample_users['salarie_id'],)
        ).fetchone()
        conn.close()
    assert row is not None

    # Le salarié délégué peut désormais créer une récurrence.
    sal = app.test_client()
    _login(sal, 'salarie_test', 'sal123')
    sal.post('/salles/recurrence', data=_recurrence_form(salle_id), follow_redirects=True)
    assert _count_recurrences(app) == 1


def test_retrait_delegation(app, sample_users):
    salle_id = _make_salle(app)
    admin = app.test_client()
    _login(admin, 'admin', 'Admin1234')
    admin.post('/delegations', data={
        'form_type': 'salle_recurrence',
        'salle_recurrence_users': [sample_users['salarie_id']],
    }, follow_redirects=True)
    # Retrait : aucune case cochée.
    admin.post('/delegations', data={'form_type': 'salle_recurrence'}, follow_redirects=True)

    with app.app_context():
        conn = get_db()
        n = conn.execute('SELECT COUNT(*) AS n FROM delegations_salles_recurrence').fetchone()['n']
        conn.close()
    assert n == 0

    sal = app.test_client()
    _login(sal, 'salarie_test', 'sal123')
    sal.post('/salles/recurrence', data=_recurrence_form(salle_id), follow_redirects=True)
    assert _count_recurrences(app) == 0


def test_comptable_peut_deleguer_les_salles(app, sample_users):
    """Le comptable (gestion des salles) peut définir les salariés autorisés
    aux réservations récurrentes — et le salarié peut ensuite en créer une."""
    salle_id = _make_salle(app)
    compta = app.test_client()
    _login(compta, 'compta_test', 'compta123')
    r = compta.post('/delegations', data={
        'form_type': 'salle_recurrence',
        'salle_recurrence_users': [sample_users['salarie_id']],
    }, follow_redirects=True)
    assert 'ont été enregistrées' in r.get_data(as_text=True)
    with app.app_context():
        conn = get_db()
        n = conn.execute('SELECT COUNT(*) AS n FROM delegations_salles_recurrence').fetchone()['n']
        conn.close()
    assert n == 1
    # Bout en bout : le salarié délégué crée une récurrence.
    sal = app.test_client()
    _login(sal, 'salarie_test', 'sal123')
    sal.post('/salles/recurrence', data=_recurrence_form(salle_id), follow_redirects=True)
    assert _count_recurrences(app) == 1


def test_comptable_peut_retirer_les_delegations_salles(app, sample_users):
    admin = app.test_client()
    _login(admin, 'admin', 'Admin1234')
    admin.post('/delegations', data={
        'form_type': 'salle_recurrence',
        'salle_recurrence_users': [sample_users['salarie_id']],
    }, follow_redirects=True)
    compta = app.test_client()
    _login(compta, 'compta_test', 'compta123')
    compta.post('/delegations', data={'form_type': 'salle_recurrence'},
                follow_redirects=True)
    with app.app_context():
        conn = get_db()
        n = conn.execute('SELECT COUNT(*) AS n FROM delegations_salles_recurrence').fetchone()['n']
        conn.close()
    assert n == 0


def test_comptable_ne_peut_pas_deleguer_les_missions(app, sample_users):
    """Les missions (fournitures, suivi validations…) restent réservées à la
    direction : seul le formulaire des salles est ouvert au comptable."""
    compta = app.test_client()
    _login(compta, 'compta_test', 'compta123')
    r = compta.post('/delegations', data={
        'mission_key': 'suivi_commandes_fournitures',
        'delegated_user_id': sample_users['salarie_id'],
    }, follow_redirects=True)
    assert 'Seule la direction peut modifier les délégations' in r.get_data(as_text=True)
    with app.app_context():
        conn = get_db()
        n = conn.execute('SELECT COUNT(*) AS n FROM delegations_missions').fetchone()['n']
        conn.close()
    assert n == 0


def test_page_comptable_formulaire_salles_actif(app, sample_users):
    """Côté page : cases cochables et bouton visible pour le comptable sur la
    section salles, missions toujours désactivées."""
    compta = app.test_client()
    _login(compta, 'compta_test', 'compta123')
    html = compta.get('/delegations').get_data(as_text=True)
    # La section salles est active : au moins une case non désactivée.
    section_salles = html.split('Réservation de salle récurrente')[1]
    assert 'Enregistrer les autorisations' in section_salles
    assert 'name="salle_recurrence_users"' in section_salles
    assert 'disabled' not in section_salles.split('form-actions')[0]
    # Les missions restent en lecture seule (selects désactivés).
    section_missions = html.split('Réservation de salle récurrente')[0]
    assert 'disabled' in section_missions


def test_page_delegations_affiche_section_recurrence(app, sample_users):
    admin = app.test_client()
    _login(admin, 'admin', 'Admin1234')
    r = admin.get('/delegations')
    assert r.status_code == 200
    assert 'Réservation de salle récurrente' in r.get_data(as_text=True)
