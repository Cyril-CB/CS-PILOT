import os
import zipfile


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
