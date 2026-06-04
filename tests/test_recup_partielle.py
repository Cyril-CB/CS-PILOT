"""Tests pour les demandes de récupération partielles (créneau d'absence)."""
from utils import calculer_recup_partielle, calculer_solde_recup


# Planning du fixture sample_planning : 08:30-12:00 / 13:30-17:00 = 7h/jour
# 2025-09-08 est un lundi en période scolaire.
JOUR_TEST = '2025-09-08'


def _planning_dict():
    """Reconstitue un planning lundi identique au fixture sample_planning."""
    p = {}
    for jour in ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi']:
        p[f'{jour}_matin_debut'] = '08:30'
        p[f'{jour}_matin_fin'] = '12:00'
        p[f'{jour}_aprem_debut'] = '13:30'
        p[f'{jour}_aprem_fin'] = '17:00'
    return p


def test_calcul_recup_partielle_apres_midi():
    """Absence 14:00-17:00 sur un après-midi 13:30-17:00 = 3h de récup."""
    calcul = calculer_recup_partielle(_planning_dict(), 0, '14:00', '17:00')
    assert calcul is not None
    assert calcul['heures_recup'] == 3.0
    # Matin intact, après-midi réduit à 13:30-14:00
    assert calcul['matin_debut'] == '08:30'
    assert calcul['matin_fin'] == '12:00'
    assert calcul['aprem_debut'] == '13:30'
    assert calcul['aprem_fin'] == '14:00'


def test_calcul_recup_partielle_matin_complet():
    """Absence couvrant tout le matin = 3.5h, après-midi conservé."""
    calcul = calculer_recup_partielle(_planning_dict(), 0, '08:30', '12:00')
    assert calcul['heures_recup'] == 3.5
    assert calcul['matin_debut'] is None
    assert calcul['matin_fin'] is None
    assert calcul['aprem_debut'] == '13:30'
    assert calcul['aprem_fin'] == '17:00'


def test_calcul_recup_partielle_hors_horaires():
    """Un créneau hors des horaires prévus ne consomme aucune heure."""
    calcul = calculer_recup_partielle(_planning_dict(), 0, '18:00', '19:00')
    assert calcul['heures_recup'] == 0.0


def test_creation_demande_partielle(auth_client, app, db, sample_users, sample_planning):
    """Création d'une demande de récup partielle via le formulaire."""
    response = auth_client.post('/demande_recup', data={
        'type_demande': 'partielle',
        'date_debut': JOUR_TEST,
        'heure_debut': '14:00',
        'heure_fin': '17:00',
        'motif_demande': 'Rendez-vous',
    }, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        row = db.execute(
            "SELECT * FROM demandes_recup WHERE user_id = ?",
            (sample_users['salarie_id'],)
        ).fetchone()
        assert row is not None
        assert row['type_demande'] == 'partielle'
        assert row['nb_heures'] == 3.0
        assert row['date_debut'] == JOUR_TEST
        assert row['date_fin'] == JOUR_TEST
        assert row['heure_debut'] == '14:00'
        assert row['heure_fin'] == '17:00'
        assert row['statut'] == 'en_attente_responsable'


def test_creation_demande_partielle_hors_horaires_rejetee(auth_client, app, db, sample_users, sample_planning):
    """Un créneau ne chevauchant pas le planning est refusé."""
    response = auth_client.post('/demande_recup', data={
        'type_demande': 'partielle',
        'date_debut': JOUR_TEST,
        'heure_debut': '18:00',
        'heure_fin': '19:00',
    }, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        row = db.execute(
            "SELECT * FROM demandes_recup WHERE user_id = ?",
            (sample_users['salarie_id'],)
        ).fetchone()
        assert row is None


def test_validation_partielle_reporte_journee(admin_client, app, db, sample_users, sample_planning):
    """La validation direction reporte la journée travaillée et diminue le solde."""
    # Demande partielle en attente (créée directement en base)
    with app.app_context():
        cur = db.execute('''
            INSERT INTO demandes_recup
            (user_id, date_debut, date_fin, nb_jours, nb_heures,
             type_demande, heure_debut, heure_fin, motif_demande, statut)
            VALUES (?, ?, ?, ?, ?, 'partielle', ?, ?, ?, 'en_attente_responsable')
        ''', (sample_users['salarie_id'], JOUR_TEST, JOUR_TEST, 0.43, 3.0,
              '14:00', '17:00', 'Rendez-vous'))
        db.commit()
        demande_id = cur.lastrowid

    # Le directeur valide
    response = admin_client.post('/validation_demandes_recup', data={
        'demande_id': demande_id,
        'action': 'valider',
        'demande_type': 'recup',
    }, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        demande = db.execute(
            "SELECT statut FROM demandes_recup WHERE id = ?", (demande_id,)
        ).fetchone()
        assert demande['statut'] == 'validee'

        hr = db.execute(
            "SELECT * FROM heures_reelles WHERE user_id = ? AND date = ?",
            (sample_users['salarie_id'], JOUR_TEST)
        ).fetchone()
        assert hr is not None
        assert hr['type_saisie'] == 'recup_partielle'
        # Horaires travaillés : matin intact + après-midi réduit
        assert hr['heure_debut_matin'] == '08:30'
        assert hr['heure_fin_matin'] == '12:00'
        assert hr['heure_debut_aprem'] == '13:30'
        assert hr['heure_fin_aprem'] == '14:00'

        # Le solde de récup a baissé de 3h
        solde = calculer_solde_recup(sample_users['salarie_id'])
        assert solde == -3.0


def _creer_demande_recup(db, user_id, statut='en_attente_responsable'):
    cur = db.execute('''
        INSERT INTO demandes_recup
        (user_id, date_debut, date_fin, nb_jours, nb_heures, motif_demande, statut)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, JOUR_TEST, JOUR_TEST, 1, 7.0, 'Test', statut))
    db.commit()
    return cur.lastrowid


def test_suppression_demande_recup_non_validee(auth_client, app, db, sample_users):
    """Le salarié peut supprimer sa demande de récup non validée."""
    with app.app_context():
        demande_id = _creer_demande_recup(db, sample_users['salarie_id'])

    response = auth_client.post('/supprimer_demande_recup', data={
        'demande_id': demande_id,
    }, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        row = db.execute("SELECT * FROM demandes_recup WHERE id = ?", (demande_id,)).fetchone()
        assert row is None


def test_suppression_demande_recup_validee_interdite(auth_client, app, db, sample_users):
    """Une demande déjà validée ne peut pas être supprimée."""
    with app.app_context():
        demande_id = _creer_demande_recup(db, sample_users['salarie_id'], statut='validee')

    auth_client.post('/supprimer_demande_recup', data={
        'demande_id': demande_id,
    }, follow_redirects=True)

    with app.app_context():
        row = db.execute("SELECT * FROM demandes_recup WHERE id = ?", (demande_id,)).fetchone()
        assert row is not None


def test_suppression_demande_recup_autre_salarie_interdite(auth_client, app, db, sample_users):
    """Un salarié ne peut pas supprimer la demande d'un autre utilisateur."""
    with app.app_context():
        demande_id = _creer_demande_recup(db, sample_users['responsable_id'])

    auth_client.post('/supprimer_demande_recup', data={
        'demande_id': demande_id,
    }, follow_redirects=True)

    with app.app_context():
        row = db.execute("SELECT * FROM demandes_recup WHERE id = ?", (demande_id,)).fetchone()
        assert row is not None
