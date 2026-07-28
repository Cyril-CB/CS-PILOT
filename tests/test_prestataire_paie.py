"""
Profil « prestataire paie » (cabinet externe) : périmètre d'accès volontaire.

Le prestataire n'est pas un salarié de l'association : il est exclu de presque
toutes les vues (il est même filtré des listes de salariés par les requêtes
`profil != 'prestataire'`). Deux téléchargements font exception et
court-circuitent explicitement les contrôles habituels :

- `blueprints/absences.py` (route `/absences/justificatif/<id>`) ignore
  `_peut_gerer_absences()` quand le profil est `prestataire` ;
- `blueprints/infos_salaries.py` (route
  `/infos_salaries/telecharger_contrat/<id>`) ignore `_peut_gerer()` **et**
  `_est_salarie_visible()` dans le même cas.

Cet élargissement est VOULU et confirmé par l'utilisateur : pour établir la
paie, le cabinet doit disposer des pièces justificatives d'absence (arrêt
maladie, attestation d'accident du travail…) et du contrat de travail (quotité,
échéance, forfait). Il n'a en revanche accès ni aux pages qui les hébergent, ni
à aucun autre module.

Ces tests documentent ce contrat pour qu'un durcissement futur des accès ne le
casse pas par inadvertance — et pour que l'élargissement reste limité au seul
profil prestataire.
"""
import os


# Modules interdits au prestataire : chaque route renvoie vers le tableau de
# bord avec un message de refus (aucune page servie).
ROUTES_INTERDITES = [
    '/gestion_budgets',            # budgets par secteur
    '/budget-previsionnel',        # budget prévisionnel
    '/planificateur',              # planificateur de tâches
    '/administration',             # administration système
    '/administration/options',     # options applicatives
    '/tresorerie',                 # trésorerie
    '/tresorerie/comptes',         # comptes de trésorerie
    '/variables_paie',             # variables de paie (saisie interne)
    '/mon_equipe',                 # RH équipe
    '/dashboard_direction',        # tableau de bord direction
    '/dashboard_comptable',        # tableau de bord comptable
    '/soldes_conges',              # soldes de congés de tout l'effectif
]


def _creer_absence_avec_justificatif(db, user_id, saisi_par, docs_dir):
    """Crée une absence dont le justificatif existe réellement sur le disque."""
    nom_fichier = 'ARRET-MALADIE_Martin_Jean.pdf'
    with open(os.path.join(docs_dir, nom_fichier), 'wb') as f:
        f.write(b'%PDF-1.4\njustificatif de test\n')
    cur = db.execute(
        "INSERT INTO absences (user_id, motif, date_debut, date_fin, jours_ouvres, "
        "justificatif_path, justificatif_nom, saisi_par) "
        "VALUES (?, 'Arrêt maladie', '2026-03-02', '2026-03-06', 5, ?, ?, ?)",
        (user_id, nom_fichier, 'arret_maladie.pdf', saisi_par))
    db.commit()
    return cur.lastrowid


def _creer_contrat_avec_pdf(db, user_id, saisi_par, docs_dir):
    """Crée un contrat dont le PDF existe réellement sur le disque."""
    nom_fichier = '01-01-2026_CONTRAT_Martin_Jean_CDI.pdf'
    with open(os.path.join(docs_dir, nom_fichier), 'wb') as f:
        f.write(b'%PDF-1.4\ncontrat de test\n')
    cur = db.execute(
        "INSERT INTO contrats (user_id, type_contrat, date_debut, date_fin, "
        "fichier_path, fichier_nom, saisi_par) "
        "VALUES (?, 'CDI', '2026-01-01', NULL, ?, ?, ?)",
        (user_id, nom_fichier, 'contrat_martin.pdf', saisi_par))
    db.commit()
    return cur.lastrowid


# ── Accès élargis VOULUS ───────────────────────────────────────────────────

def test_prestataire_peut_telecharger_un_justificatif_absence(
        prestataire_client, app, db, sample_users, monkeypatch, tmp_path):
    """Accès voulu : le cabinet a besoin de l'arrêt de travail pour établir la
    paie (maintien de salaire, subrogation), alors qu'il ne gère pas les
    absences."""
    from blueprints import absences as absences_module
    docs_dir = tmp_path / 'documents'
    docs_dir.mkdir()
    monkeypatch.setattr(absences_module, 'DOCUMENTS_DIR', str(docs_dir))

    with app.app_context():
        absence_id = _creer_absence_avec_justificatif(
            db, sample_users['salarie_id'], sample_users['directeur_id'], str(docs_dir))

    response = prestataire_client.get(f'/absences/justificatif/{absence_id}')
    assert response.status_code == 200
    assert response.data.startswith(b'%PDF-1.4')


def test_prestataire_peut_telecharger_un_contrat(
        prestataire_client, app, db, sample_users, monkeypatch, tmp_path):
    """Accès voulu : quotité, échéance et forfait du contrat conditionnent la
    paie. Le prestataire n'a pourtant aucun secteur, donc `_est_salarie_visible`
    lui répondrait « non » : la route l'ignore explicitement pour ce profil."""
    from blueprints import infos_salaries as infos_module
    docs_dir = tmp_path / 'documents'
    docs_dir.mkdir()
    monkeypatch.setattr(infos_module, 'DOCUMENTS_DIR', str(docs_dir))

    with app.app_context():
        contrat_id = _creer_contrat_avec_pdf(
            db, sample_users['salarie_id'], sample_users['directeur_id'], str(docs_dir))

    response = prestataire_client.get(f'/infos_salaries/telecharger_contrat/{contrat_id}')
    assert response.status_code == 200
    assert response.data.startswith(b'%PDF-1.4')


def test_prestataire_accede_a_la_preparation_de_paie(prestataire_client):
    """La prépa paie est le seul module métier ouvert au prestataire."""
    assert prestataire_client.get('/prepa_paie').status_code == 200
    assert prestataire_client.get('/prepa_paie/export_excel').status_code == 200


def test_connexion_prestataire_ouvre_directement_la_prepa_paie(prestataire_client):
    """Sa page d'accueil après connexion est la prépa paie, pas le tableau de
    bord : c'est bien le seul endroit où il a quelque chose à faire."""
    prestataire_client.get('/logout', follow_redirects=True)
    response = prestataire_client.post(
        '/login', data={'login': 'presta_test', 'password': 'presta123'},
        follow_redirects=False)
    assert response.status_code == 302
    assert '/prepa_paie' in response.headers['Location']


# ── Tout le reste lui reste fermé ──────────────────────────────────────────

def test_prestataire_refuse_sur_les_autres_modules(prestataire_client):
    """L'accès élargi se limite aux deux téléchargements : budget, trésorerie,
    planificateur, administration et RH restent inaccessibles."""
    for url in ROUTES_INTERDITES:
        response = prestataire_client.get(url, follow_redirects=False)
        assert response.status_code == 302, url
        assert response.headers['Location'].endswith('/dashboard'), url


def test_prestataire_refuse_sur_les_api_budget(prestataire_client):
    """Les API JSON du budget répondent 403 (et non une page HTML)."""
    from datetime import datetime

    annee = datetime.now().year
    response = prestataire_client.get(
        f'/api/budget-previsionnel/donnees?type_budget=actualise&annee={annee}')
    assert response.status_code == 403


def test_prestataire_ne_voit_pas_les_pages_qui_hebergent_les_pieces(prestataire_client):
    """Nuance importante du contrat : il télécharge la pièce s'il en connaît
    l'identifiant (fourni par la prépa paie), mais les pages de gestion des
    absences et des fiches salariés lui restent fermées — il ne peut donc pas
    parcourir librement les dossiers RH."""
    for url in ('/absences', '/infos_salaries'):
        response = prestataire_client.get(url, follow_redirects=False)
        assert response.status_code == 302, url
        assert response.headers['Location'].endswith('/dashboard'), url


def test_l_acces_elargi_est_reserve_au_prestataire(
        client, app, db, sample_users, monkeypatch, tmp_path):
    """Contrôle négatif : le court-circuit est bien conditionné au profil.
    Un salarié qui appelle les mêmes URL est refusé sur les deux routes.
    (Les fixtures de clients authentifiés partagent le même client de test :
    on se connecte explicitement.)"""
    from blueprints import absences as absences_module
    from blueprints import infos_salaries as infos_module
    docs_dir = tmp_path / 'documents'
    docs_dir.mkdir()
    monkeypatch.setattr(absences_module, 'DOCUMENTS_DIR', str(docs_dir))
    monkeypatch.setattr(infos_module, 'DOCUMENTS_DIR', str(docs_dir))

    with app.app_context():
        absence_id = _creer_absence_avec_justificatif(
            db, sample_users['salarie_id'], sample_users['directeur_id'], str(docs_dir))
        contrat_id = _creer_contrat_avec_pdf(
            db, sample_users['salarie_id'], sample_users['directeur_id'], str(docs_dir))

    urls = (f'/absences/justificatif/{absence_id}',
            f'/infos_salaries/telecharger_contrat/{contrat_id}')

    # Non connecté : redirigé vers la connexion, aucun fichier servi.
    for url in urls:
        response = client.get(url, follow_redirects=False)
        assert response.status_code == 302, url
        assert '/login' in response.headers['Location'], url

    # Salarié : refusé, le fichier n'est pas servi.
    client.post('/login', data={'login': 'salarie_test', 'password': 'sal123'},
                follow_redirects=True)
    for url in urls:
        response = client.get(url, follow_redirects=False)
        assert response.status_code == 302, url
        assert response.headers['Location'].endswith('/dashboard'), url
    client.get('/logout', follow_redirects=True)
