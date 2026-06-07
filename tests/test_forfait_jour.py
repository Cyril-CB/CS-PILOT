"""
Tests du calendrier forfait jour (direction).

Couvre :
- l'initialisation automatique d'une année : jours ouvrés (lun-ven) = travaillé ;
- l'exclusion des jours fériés et des week-ends ;
- la préservation des saisies existantes (aucun écrasement) ;
- l'affichage prioritaire des jours fériés sur la valeur « travaillé » par défaut ;
- la possibilité de saisir des journées futures (prévisionnel).
"""
from datetime import datetime, timedelta


def _jours_ouvres_attendus(annee, feries=None):
    """Nombre de jours lun-ven de l'année, hors jours fériés fournis."""
    feries = set(feries or [])
    n = 0
    jour = datetime(annee, 1, 1)
    fin = datetime(annee, 12, 31)
    while jour <= fin:
        d = jour.strftime('%Y-%m-%d')
        if jour.weekday() < 5 and d not in feries:
            n += 1
        jour += timedelta(days=1)
    return n


def _presences(app, user_id, annee):
    """Retourne {date: type_journee} pour l'utilisateur et l'année donnés."""
    import database
    with app.app_context():
        conn = database.get_db()
        rows = conn.execute(
            "SELECT date, type_journee FROM presence_forfait_jour "
            "WHERE user_id = ? AND strftime('%Y', date) = ?",
            (user_id, str(annee))
        ).fetchall()
        conn.close()
    return {r['date']: r['type_journee'] for r in rows}


def _ajouter_ferie(app, annee, date, libelle):
    import database
    with app.app_context():
        conn = database.get_db()
        conn.execute(
            "INSERT INTO jours_feries (annee, date, libelle) VALUES (?, ?, ?)",
            (annee, date, libelle)
        )
        conn.commit()
        conn.close()


def test_calendrier_initialise_jours_ouvres_en_travaille(app, admin_client, sample_users):
    """À la 1re ouverture, chaque jour ouvré non férié est marqué 'travaille'."""
    annee = 2026
    resp = admin_client.get(f'/calendrier_forfait_jour?mois=1&annee={annee}')
    assert resp.status_code == 200

    presences = _presences(app, sample_users['directeur_id'], annee)

    assert len(presences) == _jours_ouvres_attendus(annee)
    # tous les jours initialisés sont des jours travaillés
    assert set(presences.values()) == {'travaille'}
    # aucun week-end n'a été inséré
    for d in presences:
        assert datetime.strptime(d, '%Y-%m-%d').weekday() < 5


def test_initialisation_exclut_jours_feries(app, admin_client, sample_users):
    """Un jour férié (jour ouvré) n'est pas marqué travaillé."""
    annee = 2026
    ferie_dt = datetime(annee, 7, 14)  # Fête nationale
    while ferie_dt.weekday() >= 5:  # garantir un jour ouvré pour la pertinence
        ferie_dt += timedelta(days=1)
    ferie = ferie_dt.strftime('%Y-%m-%d')
    _ajouter_ferie(app, annee, ferie, 'Fête nationale')

    admin_client.get(f'/calendrier_forfait_jour?mois=7&annee={annee}')
    presences = _presences(app, sample_users['directeur_id'], annee)

    assert ferie not in presences
    assert len(presences) == _jours_ouvres_attendus(annee, feries=[ferie])


def test_initialisation_preserve_saisies_existantes(app, admin_client, sample_users):
    """Une réouverture ne réécrase pas une absence déjà posée."""
    annee = 2026
    admin_client.get(f'/calendrier_forfait_jour?mois=3&annee={annee}')

    # La direction pose un congé payé sur un lundi de mars
    jour = datetime(annee, 3, 1)
    while jour.weekday() != 0:
        jour += timedelta(days=1)
    jour_cp = jour.strftime('%Y-%m-%d')

    resp = admin_client.post('/calendrier_forfait_jour', data={
        'date': jour_cp,
        'type_journee': 'conge_paye',
        'commentaire': 'Congé test',
    }, follow_redirects=True)
    assert resp.status_code == 200

    # Nouvelle ouverture : le congé ne doit pas redevenir 'travaille'
    admin_client.get(f'/calendrier_forfait_jour?mois=3&annee={annee}')
    presences = _presences(app, sample_users['directeur_id'], annee)
    assert presences[jour_cp] == 'conge_paye'


def test_jour_ferie_affiche_meme_si_travaille_par_defaut(app, admin_client, sample_users):
    """Un férié ajouté après l'init reste affiché comme férié, pas 'travaillé'."""
    annee = 2026
    ferie_dt = datetime(annee, 11, 11)  # Armistice
    while ferie_dt.weekday() >= 5:
        ferie_dt += timedelta(days=1)
    ferie = ferie_dt.strftime('%Y-%m-%d')

    # Init AVANT l'ajout du férié : la date reçoit 'travaille' par défaut
    admin_client.get(f'/calendrier_forfait_jour?mois=11&annee={annee}')
    _ajouter_ferie(app, annee, ferie, 'Armistice 1918')

    resp = admin_client.get(f'/calendrier_forfait_jour?mois=11&annee={annee}')
    html = resp.data.decode('utf-8')
    # le libellé du férié l'emporte sur l'affichage « travaillé »
    assert 'Armistice 1918' in html


def test_saisie_jour_futur_autorisee(app, admin_client, sample_users):
    """La direction peut poser une absence sur une date future (prévisionnel)."""
    futur = datetime.now() + timedelta(days=120)
    while futur.weekday() >= 5:
        futur += timedelta(days=1)
    date_futur = futur.strftime('%Y-%m-%d')

    resp = admin_client.post('/calendrier_forfait_jour', data={
        'date': date_futur,
        'type_journee': 'repos_forfait',
        'commentaire': 'RTT prévisionnel',
    }, follow_redirects=True)
    assert resp.status_code == 200

    presences = _presences(app, sample_users['directeur_id'], futur.year)
    assert presences.get(date_futur) == 'repos_forfait'


def test_dashboard_initialise_aussi(app, admin_client, sample_users):
    """Le dashboard pré-remplit également l'année consultée."""
    annee = 2027
    resp = admin_client.get(f'/dashboard_forfait_jour?annee={annee}')
    assert resp.status_code == 200

    presences = _presences(app, sample_users['directeur_id'], annee)
    travailles = [t for t in presences.values() if t == 'travaille']
    assert len(travailles) == _jours_ouvres_attendus(annee)


def test_acces_refuse_non_directeur(auth_client):
    """Un salarié ne peut pas accéder au calendrier forfait jour."""
    resp = auth_client.get('/calendrier_forfait_jour', follow_redirects=True)
    assert resp.status_code == 200
    assert b'Calendrier Forfait Jour' not in resp.data
