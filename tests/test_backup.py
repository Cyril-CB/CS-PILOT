import os
import sqlite3
import zipfile

import pytest
from markupsafe import escape


def _configurer_documents_test(tmp_path, monkeypatch):
    import backup_db
    import database

    monkeypatch.setattr(backup_db, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(backup_db, 'DATABASE', database.DATABASE)


def test_page_sauvegardes_affiche_archives_documents(app, admin_client, monkeypatch, tmp_path):
    _configurer_documents_test(tmp_path, monkeypatch)

    response = admin_client.get('/sauvegardes')
    contenu = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Archives des documents (0)' in contenu
    assert 'Sauvegardes BDD' not in contenu


def test_creation_sauvegarde_genere_zip_documents_avec_sous_repertoires(
    app, admin_client, monkeypatch, tmp_path
):
    _configurer_documents_test(tmp_path, monkeypatch)

    documents_dir = tmp_path / 'documents'
    (documents_dir / 'contrats').mkdir(parents=True)
    (documents_dir / 'contrats' / 'contrat_jean.txt').write_text('contrat', encoding='utf-8')
    (documents_dir / 'subventions' / '2026').mkdir(parents=True)
    (documents_dir / 'subventions' / '2026' / 'piece.pdf').write_text('piece', encoding='utf-8')

    response = admin_client.post('/sauvegardes/creer', data={'label': 'avant_test'}, follow_redirects=True)
    contenu = response.get_data(as_text=True)

    backup_dir = tmp_path / 'backups'
    db_backups = list(backup_dir.glob('backup_*_avant_test.db'))
    documents_archives = list(backup_dir.glob('documents_*_avant_test.zip'))

    assert response.status_code == 200
    assert 'Sauvegarde de la base creee avec succes' in contenu
    assert 'Archive des documents creee avec succes' in contenu
    assert len(db_backups) == 1
    assert len(documents_archives) == 1

    with zipfile.ZipFile(documents_archives[0]) as archive:
        noms = set(archive.namelist())

    assert 'contrats/contrat_jean.txt' in noms
    assert 'subventions/2026/piece.pdf' in noms


def test_creation_sauvegarde_sans_documents_n_genere_pas_de_zip(
    app, admin_client, monkeypatch, tmp_path
):
    _configurer_documents_test(tmp_path, monkeypatch)

    response = admin_client.post('/sauvegardes/creer', data={'label': 'sans_docs'}, follow_redirects=True)
    contenu = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Sauvegarde de la base creee avec succes' in contenu
    assert 'Archive des documents : Aucun document uploadé à archiver' in contenu
    assert not list((tmp_path / 'backups').glob('documents_*_sans_docs.zip'))


def test_telechargement_archive_documents_zip(app, admin_client, monkeypatch, tmp_path):
    _configurer_documents_test(tmp_path, monkeypatch)

    documents_dir = tmp_path / 'documents'
    documents_dir.mkdir(parents=True)
    (documents_dir / 'justificatif.txt').write_text('ok', encoding='utf-8')

    admin_client.post('/sauvegardes/creer', data={'label': 'telechargement'})

    archive_path = next((tmp_path / 'backups').glob('documents_*_telechargement.zip'))
    response = admin_client.get(f"/sauvegardes/telecharger/{archive_path.name}")

    assert response.status_code == 200
    assert archive_path.name in response.headers['Content-Disposition']
    assert response.data


def test_suppression_archive_documents_affiche_message_specifique(
    app, admin_client, monkeypatch, tmp_path
):
    _configurer_documents_test(tmp_path, monkeypatch)

    documents_dir = tmp_path / 'documents'
    documents_dir.mkdir(parents=True)
    (documents_dir / 'a_supprimer.txt').write_text('ok', encoding='utf-8')

    admin_client.post('/sauvegardes/creer', data={'label': 'suppression'})
    archive_path = next((tmp_path / 'backups').glob('documents_*_suppression.zip'))

    response = admin_client.post(
        '/sauvegardes/supprimer',
        data={'filename': archive_path.name},
        follow_redirects=True,
    )
    contenu = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Archive des documents supprimée' in contenu
    assert not archive_path.exists()


# ---------------------------------------------------------------------------
# Outils communs aux tests negatifs
# ---------------------------------------------------------------------------

# Nom de sauvegarde temoin : conforme a la whitelist backup_*.db, il permet de
# verifier qu'un acces refuse ne supprime, ne sert et ne restaure rien.
SAUVEGARDE_TEMOIN = 'backup_20260101_000000_temoin.db'
MARQUEUR_TEMOIN = 'contenu de la sauvegarde temoin'

# Les cinq routes du blueprint backup_bp, avec un formulaire plausible.
ROUTES_SAUVEGARDES = [
    ('get', '/sauvegardes', None),
    ('post', '/sauvegardes/creer', {'label': 'intrusion'}),
    ('get', f'/sauvegardes/telecharger/{SAUVEGARDE_TEMOIN}', None),
    ('post', '/sauvegardes/restaurer', {'filename': SAUVEGARDE_TEMOIN}),
    ('post', '/sauvegardes/supprimer', {'filename': SAUVEGARDE_TEMOIN}),
]


def _dossier_sauvegardes(tmp_path):
    """Retourne le dossier de sauvegardes utilise par les tests."""
    return tmp_path / 'backups'


def _fichiers_sauvegardes(tmp_path):
    """Retourne l'ensemble des noms de fichiers presents dans le dossier de sauvegardes."""
    backup_dir = _dossier_sauvegardes(tmp_path)
    if not backup_dir.exists():
        return set()
    return {fichier.name for fichier in backup_dir.iterdir()}


def _creer_sauvegarde_temoin(tmp_path, nom=SAUVEGARDE_TEMOIN):
    """Depose une base SQLite valide mais reconnaissable dans le dossier de sauvegardes."""
    backup_dir = _dossier_sauvegardes(tmp_path)
    backup_dir.mkdir(parents=True, exist_ok=True)
    chemin = backup_dir / nom
    conn = sqlite3.connect(str(chemin))
    conn.execute('CREATE TABLE marqueur (valeur TEXT)')
    conn.execute('INSERT INTO marqueur (valeur) VALUES (?)', (MARQUEUR_TEMOIN,))
    conn.commit()
    conn.close()
    return chemin


def _nb_utilisateurs():
    """Compte les utilisateurs de la base en place.

    La sauvegarde temoin ne contient pas de table `users` : ce compteur detecte
    donc toute restauration qui aurait ete executee a tort.
    """
    import database

    conn = sqlite3.connect(database.DATABASE)
    nombre = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    conn.close()
    return nombre


def _connexion(client, login, mot_de_passe):
    """Connecte explicitement le client de test (les fixtures partagent le meme client)."""
    return client.post(
        '/login',
        data={'login': login, 'password': mot_de_passe},
        follow_redirects=True,
    )


# ---------------------------------------------------------------------------
# Controle d'acces : les cinq routes exigent une session directeur/comptable
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('methode, url, donnees', ROUTES_SAUVEGARDES)
def test_routes_sauvegardes_refusees_sans_connexion(
    app, client, sample_users, monkeypatch, tmp_path, methode, url, donnees
):
    """Un visiteur anonyme est redirige vers /login, sans aucun effet sur les sauvegardes."""
    _configurer_documents_test(tmp_path, monkeypatch)
    temoin = _creer_sauvegarde_temoin(tmp_path)
    fichiers_avant = _fichiers_sauvegardes(tmp_path)
    utilisateurs_avant = _nb_utilisateurs()

    response = getattr(client, methode)(url, data=donnees)

    assert response.status_code == 302
    assert '/login' in response.headers['Location']
    assert 'Content-Disposition' not in response.headers
    assert MARQUEUR_TEMOIN.encode() not in response.data
    assert _fichiers_sauvegardes(tmp_path) == fichiers_avant
    assert temoin.exists()
    assert _nb_utilisateurs() == utilisateurs_avant


@pytest.mark.parametrize('login, mot_de_passe', [
    ('salarie_test', 'sal123'),
    ('resp_test', 'resp123'),
])
@pytest.mark.parametrize('methode, url, donnees', ROUTES_SAUVEGARDES)
def test_routes_sauvegardes_refusees_profils_non_autorises(
    app, client, sample_users, monkeypatch, tmp_path, methode, url, donnees, login, mot_de_passe
):
    """Un salarie ou un responsable est renvoye vers son tableau de bord, sans effet."""
    _configurer_documents_test(tmp_path, monkeypatch)
    temoin = _creer_sauvegarde_temoin(tmp_path)
    fichiers_avant = _fichiers_sauvegardes(tmp_path)
    utilisateurs_avant = _nb_utilisateurs()

    _connexion(client, login, mot_de_passe)
    response = getattr(client, methode)(url, data=donnees)

    assert response.status_code == 302
    assert '/dashboard' in response.headers['Location']
    assert '/login' not in response.headers['Location']
    assert 'Content-Disposition' not in response.headers
    assert MARQUEUR_TEMOIN.encode() not in response.data

    suivi = getattr(client, methode)(url, data=donnees, follow_redirects=True)
    assert 'Acces non autorise' in suivi.get_data(as_text=True)

    assert _fichiers_sauvegardes(tmp_path) == fichiers_avant
    assert temoin.exists()
    assert _nb_utilisateurs() == utilisateurs_avant

    client.get('/logout', follow_redirects=True)


@pytest.mark.parametrize('methode, url, donnees', ROUTES_SAUVEGARDES)
def test_routes_sauvegardes_refusees_au_prestataire_paie(
    app, prestataire_client, monkeypatch, tmp_path, methode, url, donnees
):
    """Le prestataire paie n'accede pas aux sauvegardes de la base complete."""
    _configurer_documents_test(tmp_path, monkeypatch)
    temoin = _creer_sauvegarde_temoin(tmp_path)
    fichiers_avant = _fichiers_sauvegardes(tmp_path)
    utilisateurs_avant = _nb_utilisateurs()

    response = getattr(prestataire_client, methode)(url, data=donnees)

    assert response.status_code == 302
    assert '/dashboard' in response.headers['Location']
    assert 'Content-Disposition' not in response.headers
    assert MARQUEUR_TEMOIN.encode() not in response.data
    assert _fichiers_sauvegardes(tmp_path) == fichiers_avant
    assert temoin.exists()
    assert _nb_utilisateurs() == utilisateurs_avant


def test_comptable_accede_aux_sauvegardes(app, comptable_client, monkeypatch, tmp_path):
    """Temoin positif : le comptable fait bien partie des profils autorises."""
    _configurer_documents_test(tmp_path, monkeypatch)

    response = comptable_client.get('/sauvegardes')

    assert response.status_code == 200
    assert 'Archives des documents (0)' in response.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Path traversal : telechargement
# ---------------------------------------------------------------------------

NOMS_HOSTILES_URL = [
    '../backup_20260101_000000_cible.db',
    '../../etc/passwd',
    '/etc/passwd',
    'backup_../backup_20260101_000000_cible.db',
    '..%2f..%2fetc%2fpasswd',
    '%2e%2e%2fbackup_20260101_000000_cible.db',
]


@pytest.mark.parametrize('nom_hostile', NOMS_HOSTILES_URL)
def test_telechargement_refuse_path_traversal(
    app, admin_client, monkeypatch, tmp_path, nom_hostile
):
    """Aucun fichier situe hors du dossier de sauvegardes n'est servi."""
    _configurer_documents_test(tmp_path, monkeypatch)
    _dossier_sauvegardes(tmp_path).mkdir(parents=True, exist_ok=True)
    hors_perimetre = tmp_path / 'backup_20260101_000000_cible.db'
    hors_perimetre.write_text('contenu confidentiel hors perimetre', encoding='utf-8')

    response = admin_client.get(f'/sauvegardes/telecharger/{nom_hostile}')

    assert response.status_code != 200
    assert 'Content-Disposition' not in response.headers
    assert b'contenu confidentiel hors perimetre' not in response.data
    assert hors_perimetre.exists()


def test_telechargement_refuse_lien_symbolique_vers_l_exterieur(
    app, admin_client, monkeypatch, tmp_path
):
    """Un nom conforme a la whitelist ne suffit pas : le chemin reel doit rester dans backups."""
    _configurer_documents_test(tmp_path, monkeypatch)
    backup_dir = _dossier_sauvegardes(tmp_path)
    backup_dir.mkdir(parents=True, exist_ok=True)
    secret = tmp_path / 'hors_backups.db'
    secret.write_text('contenu confidentiel hors perimetre', encoding='utf-8')
    (backup_dir / 'backup_20260101_000000_lien.db').symlink_to(secret)

    response = admin_client.get(
        '/sauvegardes/telecharger/backup_20260101_000000_lien.db',
        follow_redirects=True,
    )
    contenu = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Fichier introuvable ou nom invalide' in contenu
    assert 'contenu confidentiel hors perimetre' not in contenu
    assert secret.exists()


def test_telechargement_refuse_fichier_inexistant(app, admin_client, monkeypatch, tmp_path):
    """Un nom valide mais inconnu renvoie un message francais, sans 404 technique."""
    _configurer_documents_test(tmp_path, monkeypatch)
    _dossier_sauvegardes(tmp_path).mkdir(parents=True, exist_ok=True)

    response = admin_client.get(
        '/sauvegardes/telecharger/backup_20260101_000000_absent.db',
        follow_redirects=True,
    )
    contenu = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Fichier introuvable ou nom invalide' in contenu
    assert str(tmp_path) not in contenu


# ---------------------------------------------------------------------------
# Path traversal et whitelist : suppression
# ---------------------------------------------------------------------------

NOMS_HOSTILES_SUPPRESSION = [
    '../hors_backups/backup_cible.db',
    '../../etc/passwd',
    '/etc/passwd',
    '..\\backup_cible.db',
    'backup_cible.db/../../hors_backups/backup_cible.db',
    'backup cible.db',
]


@pytest.mark.parametrize('nom_hostile', NOMS_HOSTILES_SUPPRESSION)
def test_suppression_refuse_path_traversal(
    app, admin_client, monkeypatch, tmp_path, nom_hostile
):
    """Aucun fichier hors du dossier de sauvegardes ne peut etre supprime."""
    _configurer_documents_test(tmp_path, monkeypatch)
    temoin = _creer_sauvegarde_temoin(tmp_path)
    hors_perimetre = tmp_path / 'hors_backups'
    hors_perimetre.mkdir()
    cible = hors_perimetre / 'backup_cible.db'
    cible.write_text('fichier hors perimetre', encoding='utf-8')

    response = admin_client.post(
        '/sauvegardes/supprimer',
        data={'filename': nom_hostile},
        follow_redirects=True,
    )
    contenu = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Erreur : Operation non autorisee' in contenu
    assert str(tmp_path) not in contenu
    assert cible.exists()
    assert temoin.exists()


@pytest.mark.parametrize('nom_refuse', [
    'cspilot.db',
    'backup_20260101_000000_temoin.txt',
    'documents_20260101_000000.db',
    'notes.zip',
])
def test_suppression_refuse_hors_whitelist(
    app, admin_client, monkeypatch, tmp_path, nom_refuse
):
    """Seuls les fichiers backup_*.db et documents_*.zip sont supprimables."""
    _configurer_documents_test(tmp_path, monkeypatch)
    backup_dir = _dossier_sauvegardes(tmp_path)
    backup_dir.mkdir(parents=True, exist_ok=True)
    fichier = backup_dir / nom_refuse
    fichier.write_text('fichier non supprimable', encoding='utf-8')

    response = admin_client.post(
        '/sauvegardes/supprimer',
        data={'filename': nom_refuse},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert 'Erreur : Operation non autorisee' in response.get_data(as_text=True)
    assert fichier.exists()


def test_suppression_refuse_lien_symbolique_vers_l_exterieur(
    app, admin_client, monkeypatch, tmp_path
):
    """Un lien symbolique nomme backup_*.db ne permet pas de supprimer hors du dossier."""
    _configurer_documents_test(tmp_path, monkeypatch)
    backup_dir = _dossier_sauvegardes(tmp_path)
    backup_dir.mkdir(parents=True, exist_ok=True)
    cible = tmp_path / 'hors_backups.db'
    cible.write_text('fichier hors perimetre', encoding='utf-8')
    lien = backup_dir / 'backup_20260101_000000_lien.db'
    lien.symlink_to(cible)

    response = admin_client.post(
        '/sauvegardes/supprimer',
        data={'filename': lien.name},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert 'Erreur : Operation non autorisee' in response.get_data(as_text=True)
    assert cible.exists()


def test_suppression_sans_nom_de_fichier(app, admin_client, monkeypatch, tmp_path):
    """Un formulaire vide est refuse avec un message francais."""
    _configurer_documents_test(tmp_path, monkeypatch)
    temoin = _creer_sauvegarde_temoin(tmp_path)

    response = admin_client.post('/sauvegardes/supprimer', data={'filename': ''}, follow_redirects=True)

    assert response.status_code == 200
    assert 'Aucun fichier specifie' in response.get_data(as_text=True)
    assert temoin.exists()


# ---------------------------------------------------------------------------
# Restauration : la route qui ecrase toute la base
# ---------------------------------------------------------------------------

def test_restauration_sans_nom_de_fichier(app, admin_client, monkeypatch, tmp_path):
    """Sans nom de fichier, aucune restauration ni sauvegarde de securite."""
    _configurer_documents_test(tmp_path, monkeypatch)
    _dossier_sauvegardes(tmp_path).mkdir(parents=True, exist_ok=True)
    utilisateurs_avant = _nb_utilisateurs()

    response = admin_client.post('/sauvegardes/restaurer', data={'filename': ''}, follow_redirects=True)

    assert response.status_code == 200
    assert 'Aucun fichier specifie' in response.get_data(as_text=True)
    assert _fichiers_sauvegardes(tmp_path) == set()
    assert _nb_utilisateurs() == utilisateurs_avant


@pytest.mark.parametrize('nom_invalide', NOMS_HOSTILES_SUPPRESSION)
def test_restauration_refuse_nom_invalide(
    app, admin_client, monkeypatch, tmp_path, nom_invalide
):
    """Un nom hors whitelist est rejete avant toute lecture de fichier."""
    _configurer_documents_test(tmp_path, monkeypatch)
    _dossier_sauvegardes(tmp_path).mkdir(parents=True, exist_ok=True)
    utilisateurs_avant = _nb_utilisateurs()

    response = admin_client.post(
        '/sauvegardes/restaurer',
        data={'filename': nom_invalide},
        follow_redirects=True,
    )
    contenu = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Erreur lors de la restauration : Nom de fichier invalide' in contenu
    assert str(tmp_path) not in contenu
    # Aucune sauvegarde de securite : le refus intervient avant toute ecriture.
    assert _fichiers_sauvegardes(tmp_path) == set()
    assert _nb_utilisateurs() == utilisateurs_avant


def test_restauration_refuse_fichier_inexistant(app, admin_client, monkeypatch, tmp_path):
    """Un nom valide mais absent du dossier ne declenche aucune restauration."""
    _configurer_documents_test(tmp_path, monkeypatch)
    _dossier_sauvegardes(tmp_path).mkdir(parents=True, exist_ok=True)
    utilisateurs_avant = _nb_utilisateurs()

    response = admin_client.post(
        '/sauvegardes/restaurer',
        data={'filename': 'backup_20260101_000000_absent.db'},
        follow_redirects=True,
    )
    contenu = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Erreur lors de la restauration : Fichier de sauvegarde introuvable' in contenu
    assert str(tmp_path) not in contenu
    assert _fichiers_sauvegardes(tmp_path) == set()
    assert _nb_utilisateurs() == utilisateurs_avant


def test_restauration_refuse_fichier_non_sqlite(app, admin_client, monkeypatch, tmp_path):
    """Un fichier qui n'est pas une base SQLite est refuse proprement, base intacte."""
    _configurer_documents_test(tmp_path, monkeypatch)
    backup_dir = _dossier_sauvegardes(tmp_path)
    backup_dir.mkdir(parents=True, exist_ok=True)
    faux = backup_dir / 'backup_20260101_000000_corrompu.db'
    faux.write_bytes(b'ceci n\'est pas une base de donnees SQLite' * 32)
    utilisateurs_avant = _nb_utilisateurs()

    response = admin_client.post(
        '/sauvegardes/restaurer',
        data={'filename': faux.name},
        follow_redirects=True,
    )
    contenu = response.get_data(as_text=True)

    assert response.status_code == 200
    # Jinja echappe l'apostrophe du message : on compare avec le texte echappe.
    assert str(escape(
        "Erreur lors de la restauration : Le fichier n'est pas une base de donnees SQLite valide"
    )) in contenu
    # Pas de fuite technique : ni trace d'exception, ni chemin local.
    assert 'Traceback' not in contenu
    assert 'sqlite3' not in contenu
    assert str(tmp_path) not in contenu
    # Base inchangee et aucune sauvegarde de securite creee.
    assert _nb_utilisateurs() == utilisateurs_avant
    assert _fichiers_sauvegardes(tmp_path) == {faux.name}


def test_restauration_sauvegarde_valide_par_directeur(
    app, db, admin_client, sample_users, monkeypatch, tmp_path
):
    """Cas legitime : un directeur restaure une sauvegarde valide et la base revient a son etat."""
    _configurer_documents_test(tmp_path, monkeypatch)

    admin_client.post('/sauvegardes/creer', data={'label': 'avantmodif'})
    sauvegarde = next(_dossier_sauvegardes(tmp_path).glob('backup_*_avantmodif.db'))
    utilisateurs_avant = _nb_utilisateurs()

    # Modification volontaire de la base apres la sauvegarde
    with app.app_context():
        db.execute(
            "INSERT INTO users (nom, prenom, login, password, profil) VALUES (?, ?, ?, ?, ?)",
            ('Intrus', 'Test', 'intrus_test', 'x', 'salarie')
        )
        db.commit()
    assert _nb_utilisateurs() == utilisateurs_avant + 1

    response = admin_client.post(
        '/sauvegardes/restaurer',
        data={'filename': sauvegarde.name},
        follow_redirects=True,
    )
    contenu = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Restauration reussie' in contenu
    assert _nb_utilisateurs() == utilisateurs_avant
    # Une sauvegarde de securite a bien ete creee avant l'ecrasement.
    assert list(_dossier_sauvegardes(tmp_path).glob('backup_*_avant_restauration.db'))
