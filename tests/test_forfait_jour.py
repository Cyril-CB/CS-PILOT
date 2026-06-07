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


# --- Suivi facultatif des heures travaillées (horaires matin / après-midi) ---

def _premier_jour_ouvre(annee, mois, decalage=0):
    """Retourne le (1 + decalage)-ième jour ouvré du mois, format YYYY-MM-DD."""
    jour = datetime(annee, mois, 1)
    trouves = 0
    while True:
        if jour.weekday() < 5:
            if trouves == decalage:
                return jour.strftime('%Y-%m-%d')
            trouves += 1
        jour += timedelta(days=1)


def test_saisie_horaires_enregistree(app, admin_client, sample_users):
    """Les horaires matin / après-midi saisis sont enregistrés en base."""
    annee = 2026
    date = _premier_jour_ouvre(annee, 4)

    resp = admin_client.post('/calendrier_forfait_jour', data={
        'date': date,
        'type_journee': 'travaille',
        'matin_debut': '08:30', 'matin_fin': '12:00',
        'aprem_debut': '13:30', 'aprem_fin': '17:00',
    }, follow_redirects=True)
    assert resp.status_code == 200

    import database
    with app.app_context():
        conn = database.get_db()
        row = conn.execute(
            "SELECT matin_debut, matin_fin, aprem_debut, aprem_fin "
            "FROM presence_forfait_jour WHERE user_id = ? AND date = ?",
            (sample_users['directeur_id'], date)
        ).fetchone()
        conn.close()

    assert row['matin_debut'] == '08:30'
    assert row['matin_fin'] == '12:00'
    assert row['aprem_debut'] == '13:30'
    assert row['aprem_fin'] == '17:00'


def test_horaires_affiches_sur_calendrier(admin_client):
    """Les horaires et le total d'heures apparaissent sur le calendrier."""
    annee = 2026
    date = _premier_jour_ouvre(annee, 4)

    admin_client.post('/calendrier_forfait_jour', data={
        'date': date,
        'type_journee': 'travaille',
        'matin_debut': '08:30', 'matin_fin': '12:00',
        'aprem_debut': '13:30', 'aprem_fin': '17:00',
    }, follow_redirects=True)

    resp = admin_client.get(f'/calendrier_forfait_jour?mois=4&annee={annee}')
    html = resp.data.decode('utf-8')
    assert '08:30-12:00' in html
    assert '13:30-17:00' in html
    assert '7h' in html  # total d'heures de la journée (3,5 + 3,5)


def test_horaires_vides_par_defaut(admin_client):
    """Sans saisie d'horaire, aucune plage horaire n'est affichée."""
    import re
    annee = 2026
    resp = admin_client.get(f'/calendrier_forfait_jour?mois=1&annee={annee}')
    html = resp.data.decode('utf-8')
    # aucune plage HH:MM-HH:MM ne doit apparaître tant qu'aucun horaire n'est saisi
    assert not re.search(r'\d{2}:\d{2}-\d{2}:\d{2}', html)


def test_pdf_bilan_total_heures(admin_client):
    """Le bilan du PDF mensuel affiche le total d'heures et le nb de jours."""
    import pdfplumber
    from io import BytesIO

    annee, mois = 2026, 4
    j1 = _premier_jour_ouvre(annee, mois, 0)
    j2 = _premier_jour_ouvre(annee, mois, 1)

    # 08:30-12:00 + 13:30-17:00 = 7h
    admin_client.post('/calendrier_forfait_jour', data={
        'date': j1, 'type_journee': 'travaille',
        'matin_debut': '08:30', 'matin_fin': '12:00',
        'aprem_debut': '13:30', 'aprem_fin': '17:00',
    }, follow_redirects=True)
    # 09:00-12:00 + 14:00-17:00 = 6h
    admin_client.post('/calendrier_forfait_jour', data={
        'date': j2, 'type_journee': 'travaille',
        'matin_debut': '09:00', 'matin_fin': '12:00',
        'aprem_debut': '14:00', 'aprem_fin': '17:00',
    }, follow_redirects=True)

    resp = admin_client.get(f'/rapport_forfait_jour_pdf/{mois}/{annee}')
    assert resp.status_code == 200
    assert resp.headers['Content-Type'] == 'application/pdf'

    with pdfplumber.open(BytesIO(resp.data)) as pdf:
        texte = '\n'.join(page.extract_text() or '' for page in pdf.pages)
    norm = ' '.join(texte.split())

    # 7h + 6h = 13h réparties sur 2 jours
    assert '13 heures' in norm
    assert '2 jours avec horaires saisies' in norm


def test_migration_0036_ajoute_colonnes_horaires(tmp_path):
    """La migration 0036 ajoute les colonnes d'horaires sur une base existante."""
    import os
    import sqlite3
    from migration_manager import _load_migration_module, MIGRATIONS_DIR

    db_path = str(tmp_path / 'old.db')
    conn = sqlite3.connect(db_path)
    # Ancienne table, sans les colonnes d'horaires
    conn.execute('''
        CREATE TABLE presence_forfait_jour (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            type_journee TEXT NOT NULL,
            commentaire TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, date)
        )
    ''')
    conn.commit()

    module = _load_migration_module(
        os.path.join(MIGRATIONS_DIR, '0036_horaires_forfait_jour.py')
    )
    module.upgrade(conn)
    module.upgrade(conn)  # idempotent : un second passage ne casse rien

    cols = [r[1] for r in conn.execute(
        'PRAGMA table_info(presence_forfait_jour)'
    ).fetchall()]
    conn.close()

    for col in ('matin_debut', 'matin_fin', 'aprem_debut', 'aprem_fin'):
        assert col in cols


# --- Réconciliation des fériés déclarés après le pré-remplissage ---

def test_ajout_ferie_retire_travaille_par_defaut(app, admin_client, sample_users):
    """Déclarer un férié après le pré-remplissage retire la journée « travaillé »
    générée par défaut et corrige les stats (pas de sur-comptage)."""
    import utils
    annee = 2026
    # pré-remplir l'année (jours ouvrés = travaillé)
    admin_client.get(f'/calendrier_forfait_jour?mois=5&annee={annee}')

    ferie = _premier_jour_ouvre(annee, 5)
    presences = _presences(app, sample_users['directeur_id'], annee)
    assert presences.get(ferie) == 'travaille'

    with app.app_context():
        travaille_avant = utils.calculer_stats_forfait_jour(
            sample_users['directeur_id'], annee)['travaille']

    # déclarer ce jour comme férié via la page de gestion
    resp = admin_client.post('/gestion_jours_feries', data={
        'action': 'ajouter', 'date': ferie, 'libelle': 'Jour de test',
    }, follow_redirects=True)
    assert resp.status_code == 200

    # la journée « travaillé » par défaut a été retirée
    presences = _presences(app, sample_users['directeur_id'], annee)
    assert ferie not in presences

    # les statistiques ne comptent plus ce jour comme travaillé
    with app.app_context():
        travaille_apres = utils.calculer_stats_forfait_jour(
            sample_users['directeur_id'], annee)['travaille']
    assert travaille_apres == travaille_avant - 1


def test_ajout_ferie_preserve_saisie_reelle(app, admin_client, sample_users):
    """Une journée avec horaires saisis n'est pas supprimée si elle devient férié."""
    annee = 2026
    date = _premier_jour_ouvre(annee, 6)

    # saisie réelle : journée travaillée avec horaires
    admin_client.post('/calendrier_forfait_jour', data={
        'date': date, 'type_journee': 'travaille',
        'matin_debut': '08:30', 'matin_fin': '12:00',
        'aprem_debut': '13:30', 'aprem_fin': '17:00',
    }, follow_redirects=True)

    # le jour est ensuite déclaré férié
    admin_client.post('/gestion_jours_feries', data={
        'action': 'ajouter', 'date': date, 'libelle': 'Férié test',
    }, follow_redirects=True)

    # la saisie réelle (avec horaires) est conservée
    presences = _presences(app, sample_users['directeur_id'], annee)
    assert presences.get(date) == 'travaille'
