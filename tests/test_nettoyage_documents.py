"""Le nettoyage disque ne doit ni sortir du dossier ni masquer l'état SQL."""
from io import BytesIO
import os

import pytest

from tests.test_fiches_versions import fiche_complete, verrouiller, etat_metier


@pytest.mark.parametrize('type_document', ['absence', 'contrat'])
def test_suppression_validee_reste_un_succes_si_fichier_bloque(
        app, db, admin_client, sample_users, fiche_complete, tmp_path,
        monkeypatch, caplog, type_document):
    import blueprints.absences as absences
    import blueprints.infos_salaries as infos
    dossier = tmp_path / 'documents'
    dossier.mkdir()
    monkeypatch.setattr(absences, 'DOCUMENTS_DIR', str(dossier))
    monkeypatch.setattr(infos, 'DOCUMENTS_DIR', str(dossier))
    uid = fiche_complete
    if type_document == 'absence':
        admin_client.post('/absences', data={
            'user_id': uid, 'motif': 'Congé payé',
            'date_debut': '2026-08-03', 'date_fin': '2026-08-03',
            'justificatif': (BytesIO(b'%PDF-fictif'), 'piece.pdf'),
        })
        row = db.execute('SELECT id, justificatif_path FROM absences').fetchone()
        identifiant, nom = row['id'], row['justificatif_path']
        url = f'/absences/supprimer/{identifiant}'
        table, message = 'absences', 'Absence supprimée et calendrier mis à jour.'
        pris_avant = db.execute('SELECT cp_pris FROM users WHERE id=?', (uid,)).fetchone()[0]
    else:
        nom = 'contrat-fictif.pdf'
        (dossier / nom).write_bytes(b'%PDF-fictif')
        identifiant = db.execute('SELECT id FROM contrats WHERE user_id=?', (uid,)).fetchone()[0]
        db.execute('UPDATE contrats SET fichier_path=? WHERE id=?', (nom, identifiant))
        db.commit()
        url = f'/infos_salaries/supprimer_contrat/{identifiant}'
        table, message = 'contrats', 'Contrat supprime.'

    def fichier_bloque(chemin):
        assert os.fspath(chemin) == str(dossier / nom)
        raise PermissionError('Verrou Windows simulé')

    monkeypatch.setattr(os, 'remove', fichier_bloque)
    response = admin_client.post(url, follow_redirects=True)
    assert response.status_code == 200
    assert message in response.get_data(as_text=True)
    assert db.execute(f'SELECT id FROM {table} WHERE id=?', (identifiant,)).fetchone() is None
    assert (dossier / nom).read_bytes() == b'%PDF-fictif'
    assert 'PermissionError' in caplog.text and nom in caplog.text
    if type_document == 'absence':
        assert db.execute('SELECT cp_pris FROM users WHERE id=?', (uid,)).fetchone()[0] == pris_avant - 1
        assert db.execute("SELECT id FROM heures_reelles WHERE user_id=? AND date='2026-08-03'",
                          (uid,)).fetchone() is None


@pytest.mark.parametrize('nettoyage_bloque', [False, True])
def test_nettoyage_upload_ne_masque_pas_le_refus_de_fiche_verrouillee(
        app, db, admin_client, sample_users, fiche_complete, tmp_path, monkeypatch, caplog,
        nettoyage_bloque):
    import blueprints.absences as absences
    dossier = tmp_path / 'documents'
    dossier.mkdir()
    monkeypatch.setattr(absences, 'DOCUMENTS_DIR', str(dossier))
    uid = fiche_complete
    verrouiller(app, sample_users, uid)
    avant = etat_metier(uid)

    def fichier_bloque(chemin):
        raise PermissionError('Verrou Windows simulé')

    if nettoyage_bloque:
        monkeypatch.setattr(os, 'remove', fichier_bloque)
    response = admin_client.post('/absences', data={
        'user_id': uid, 'motif': 'Arrêt maladie',
        'date_debut': '2026-08-03', 'date_fin': '2026-08-03',
        'justificatif': (BytesIO(b'%PDF-fictif'), 'piece.pdf'),
    }, follow_redirects=True)
    assert response.status_code == 200
    assert 'verrouillée' in response.get_data(as_text=True)
    assert 'Verrou Windows simulé' not in response.get_data(as_text=True)
    assert etat_metier(uid) == avant
    assert len(list(dossier.iterdir())) == int(nettoyage_bloque)
    assert ('PermissionError' in caplog.text) == nettoyage_bloque


@pytest.mark.parametrize('chemin', ['parent', 'absolu', 'prefixe_voisin', 'windows', 'lien_externe'])
def test_nettoyage_refuse_un_document_exterieur(tmp_path, chemin):
    from document_files import nettoyer_document
    dossier = tmp_path / 'documents'
    dossier.mkdir()
    voisin = tmp_path / 'documents-prives'
    voisin.mkdir()
    piece = (tmp_path if chemin == 'lien_externe' else voisin) / 'confidentiel.pdf'
    piece.write_bytes(b'Contenu fictif a conserver')
    noms = {'parent': '../documents-prives/confidentiel.pdf',
            'absolu': str(piece),
            'windows': '..\\documents-prives\\confidentiel.pdf'}
    if chemin in ('lien_externe', 'prefixe_voisin'):
        lien = dossier / 'lien.pdf'
        lien.symlink_to(piece)
        nom = lien.name
    else:
        nom = noms[chemin]
    assert not nettoyer_document(str(dossier), nom)
    assert piece.read_bytes() == b'Contenu fictif a conserver'


def test_nettoyage_piece_interne_et_relance_sans_fichier(tmp_path, caplog):
    from document_files import nettoyer_document
    piece = tmp_path / 'pièce-fictive.pdf'
    piece.write_bytes(b'%PDF-fictif')
    assert nettoyer_document(str(tmp_path), piece.name)
    assert not piece.exists()
    assert nettoyer_document(str(tmp_path), piece.name)
    assert not caplog.records
