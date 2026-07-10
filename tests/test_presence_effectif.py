"""
Tests de la page « Présence effectif » (direction / comptable).

Tableau mensuel des salariés en contrat sur la période : un statut par jour
(présent, arrêt maladie, congés, récupération, autre absence), week-ends et
fériés neutralisés, jours hors contrat distincts.
"""
from blueprints.presence_effectif import _construire_matrice


def _contrat(db, user_id, debut='2025-01-01', fin=None):
    db.execute("INSERT INTO contrats (user_id, type_contrat, date_debut, date_fin) "
               "VALUES (?, 'CDI', ?, ?)", (user_id, debut, fin))
    db.commit()


def _absence(db, user_id, motif, debut, fin, saisi_par):
    db.execute("INSERT INTO absences (user_id, motif, date_debut, date_fin, jours_ouvres, saisi_par) "
               "VALUES (?, ?, ?, ?, 1, ?)", (user_id, motif, debut, fin, saisi_par))
    db.commit()


def _ligne(salaries, nom):
    return next(s for s in salaries if s['nom'] == nom)


def _cat(ligne, jour):
    return ligne['cells'][jour - 1]['cat']


# ──────────────────────────────────────────────────────────────────────────
#  Accès
# ──────────────────────────────────────────────────────────────────────────

def test_salarie_refuse(auth_client):
    resp = auth_client.get('/presence-effectif', follow_redirects=True)
    assert 'Accès non autorisé' in resp.get_data(as_text=True)


def test_responsable_refuse(resp_client):
    resp = resp_client.get('/presence-effectif', follow_redirects=True)
    assert 'Accès non autorisé' in resp.get_data(as_text=True)


def test_directeur_accede(admin_client):
    resp = admin_client.get('/presence-effectif')
    assert resp.status_code == 200
    assert 'Présence effectif' in resp.get_data(as_text=True)


def test_comptable_accede(comptable_client):
    resp = comptable_client.get('/presence-effectif')
    assert resp.status_code == 200


# ──────────────────────────────────────────────────────────────────────────
#  Liste des salariés en contrat sur la période
# ──────────────────────────────────────────────────────────────────────────

def test_seuls_les_salaries_en_contrat_apparaissent(app, db, sample_users):
    # Martin : contrat couvrant mars 2026 ; Dupont (responsable) : aucun contrat ;
    # contrat terminé avant le mois → invisible.
    _contrat(db, sample_users['salarie_id'])
    db.execute("INSERT INTO users (nom, prenom, login, password, profil, actif) "
               "VALUES ('Parti', 'Depuis', 'parti', 'x', 'salarie', 0)")
    parti_id = db.execute("SELECT id FROM users WHERE login='parti'").fetchone()['id']
    _contrat(db, parti_id, debut='2024-01-01', fin='2025-12-31')
    db.commit()

    with app.app_context():
        _, salaries, _ = _construire_matrice(db, 2026, 3, 31)
    noms = [s['nom'] for s in salaries]
    assert 'Martin' in noms
    assert 'Dupont' not in noms          # pas de contrat
    assert 'Parti' not in noms           # contrat clos avant la période


def test_salaries_classes_par_secteur(app, db, sample_users):
    """Les salariés sont regroupés par secteur (alphabétique), les comptes
    sans secteur en dernier."""
    _contrat(db, sample_users['salarie_id'])        # Martin — Secteur Test
    _contrat(db, sample_users['directeur_id'])      # Admin — sans secteur
    db.execute("INSERT INTO secteurs (nom) VALUES ('Autre Secteur')")
    autre_id = db.execute("SELECT id FROM secteurs WHERE nom='Autre Secteur'").fetchone()['id']
    db.execute("INSERT INTO users (nom, prenom, login, password, profil, actif, secteur_id) "
               "VALUES ('Zola', 'Emile', 'zola', 'x', 'salarie', 1, ?)", (autre_id,))
    zola_id = db.execute("SELECT id FROM users WHERE login='zola'").fetchone()['id']
    _contrat(db, zola_id)

    with app.app_context():
        _, salaries, _ = _construire_matrice(db, 2026, 3, 31)
    ordre = [(s['secteur'], s['nom']) for s in salaries]
    assert ordre == [
        ('Autre Secteur', 'Zola'),
        ('Secteur Test', 'Martin'),
        ('Sans secteur', 'Admin'),
    ]


def test_contrat_clos_reste_visible_le_mois_du_depart(app, db, sample_users):
    db.execute("INSERT INTO users (nom, prenom, login, password, profil, actif) "
               "VALUES ('Sortant', 'Mimois', 'sortant', 'x', 'salarie', 0)")
    uid = db.execute("SELECT id FROM users WHERE login='sortant'").fetchone()['id']
    _contrat(db, uid, debut='2024-01-01', fin='2026-03-15')

    with app.app_context():
        _, salaries, _ = _construire_matrice(db, 2026, 3, 31)
    ligne = _ligne(salaries, 'Sortant')
    assert _cat(ligne, 13) == 'present'   # vendredi 13 mars : sous contrat
    assert _cat(ligne, 17) == 'hors'      # mardi 17 mars : contrat terminé


# ──────────────────────────────────────────────────────────────────────────
#  Statuts jour par jour
# ──────────────────────────────────────────────────────────────────────────

def test_categories_par_motif(app, db, sample_users):
    uid = sample_users['salarie_id']
    saisi_par = sample_users['directeur_id']
    _contrat(db, uid)
    _absence(db, uid, 'Arrêt maladie', '2026-03-03', '2026-03-04', saisi_par)
    _absence(db, uid, 'Congé payé', '2026-03-10', '2026-03-10', saisi_par)
    _absence(db, uid, 'Evènement familial', '2026-03-12', '2026-03-12', saisi_par)
    db.execute("INSERT INTO heures_reelles (user_id, date, type_saisie) "
               "VALUES (?, '2026-03-17', 'recup_journee')", (uid,))
    db.execute("INSERT INTO jours_feries (annee, date, libelle) "
               "VALUES (2026, '2026-03-16', 'Férié test')")
    db.commit()

    with app.app_context():
        jours, salaries, absents = _construire_matrice(db, 2026, 3, 31)
    ligne = _ligne(salaries, 'Martin')

    assert _cat(ligne, 2) == 'present'    # lundi 2 mars, rien de saisi
    assert _cat(ligne, 3) == 'maladie'
    assert _cat(ligne, 4) == 'maladie'
    assert _cat(ligne, 10) == 'conges'
    assert _cat(ligne, 12) == 'autre'     # motif non regroupé → autre
    assert _cat(ligne, 17) == 'recup'
    assert _cat(ligne, 16) == 'ferie'     # férié prioritaire
    assert _cat(ligne, 1) == 'weekend'    # dimanche 1er mars
    assert _cat(ligne, 7) == 'weekend'    # samedi 7 mars

    # Compteurs mensuels par catégorie (jours ouvrés uniquement).
    assert ligne['compteurs'] == {'maladie': 2, 'conges': 1, 'recup': 1, 'autre': 1}
    # Ligne « Absents » : 1 absent le 3 mars (index 2), 0 le 2 mars (index 1).
    assert absents[2] == 1
    assert absents[1] == 0


def test_absence_sur_weekend_reste_weekend(app, db, sample_users):
    uid = sample_users['salarie_id']
    _contrat(db, uid)
    # Arrêt couvrant du vendredi 6 au lundi 9 : le week-end reste neutre.
    _absence(db, uid, 'Arrêt maladie', '2026-03-06', '2026-03-09', sample_users['directeur_id'])

    with app.app_context():
        _, salaries, _ = _construire_matrice(db, 2026, 3, 31)
    ligne = _ligne(salaries, 'Martin')
    assert _cat(ligne, 6) == 'maladie'
    assert _cat(ligne, 7) == 'weekend'
    assert _cat(ligne, 8) == 'weekend'
    assert _cat(ligne, 9) == 'maladie'
    assert ligne['compteurs']['maladie'] == 2


def test_forfait_jour_direction(app, db, sample_users):
    """Une journée posée directement dans le calendrier forfait jour (sans fiche
    d'absence) est classée : forfait_jour → congés ; travaille → présent."""
    uid = sample_users['directeur_id']
    _contrat(db, uid)
    db.execute("INSERT INTO presence_forfait_jour (user_id, date, type_journee) "
               "VALUES (?, '2026-03-05', 'forfait_jour')", (uid,))
    db.execute("INSERT INTO presence_forfait_jour (user_id, date, type_journee) "
               "VALUES (?, '2026-03-06', 'travaille')", (uid,))
    db.commit()

    with app.app_context():
        _, salaries, _ = _construire_matrice(db, 2026, 3, 31)
    ligne = _ligne(salaries, 'Admin')
    assert _cat(ligne, 5) == 'conges'
    assert _cat(ligne, 6) == 'present'


# ──────────────────────────────────────────────────────────────────────────
#  Rendu de la page
# ──────────────────────────────────────────────────────────────────────────

def test_rendu_page_avec_donnees(admin_client, db, sample_users):
    uid = sample_users['salarie_id']
    _contrat(db, uid)
    _absence(db, uid, 'Arrêt maladie', '2026-03-03', '2026-03-04', sample_users['directeur_id'])

    resp = admin_client.get('/presence-effectif?mois=3&annee=2026')
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert 'Martin' in html
    assert 'pe-maladie' in html
    assert '2026-03-03 — Arrêt maladie' in html    # motif exact en info-bulle
    assert 'M / C / R / A' in html                  # colonne des compteurs
    assert 'Mars 2026' in html or 'mars 2026' in html
