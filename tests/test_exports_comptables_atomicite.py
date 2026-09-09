"""B3 : échecs, transactions concurrentes et contrôles de droits actuels."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
import sqlite3

import pytest

from tests.test_exports_comptables import piece, etat, exporter, selection, references


@pytest.mark.parametrize('phase', ['permission', 'disque', 'ecriture', 'lecture', 'fermeture', 'apres_temporaire', 'apres_sql', 'commit'])
def test_panne_stockage_annule_tout(piece, db, comptable_client, monkeypatch, tmp_path, phase):
    from blueprints import exportation as module
    from fiches_db import ConnexionFiches
    avant = etat(db)
    donnees = selection(comptable_client, piece[1])
    if phase in ('permission', 'disque'):
        def echouer(*a, **kw):
            raise PermissionError('Interdit') if phase == 'permission' else OSError('Disque indisponible')
        monkeypatch.setattr(module.tempfile, 'TemporaryFile', echouer)
    elif phase in ('ecriture', 'lecture', 'fermeture'):
        original = module.tempfile.TemporaryFile
        class FichierDefaillant:
            def __init__(self, *a, **kw): self.f = original(*a, **kw)
            def __enter__(self): return self
            def __exit__(self, *args):
                self.f.close()
                if phase == 'fermeture': raise OSError('Fermeture impossible')
            def write(self, contenu):
                self.f.write(contenu[:4])
                if phase == 'ecriture': raise OSError('Écriture interrompue')
                self.f.seek(0); return self.f.write(contenu)
            def flush(self): self.f.flush()
            def seek(self, pos): self.f.seek(pos)
            def read(self): return b'incomplet' if phase == 'lecture' else self.f.read()
        monkeypatch.setattr(module.tempfile, 'TemporaryFile', FichierDefaillant)
    elif phase == 'apres_temporaire':
        original = module._produire_fichier
        def echouer(lignes):
            original(lignes)
            raise OSError('Panne après fermeture du temporaire')
        monkeypatch.setattr(module, '_produire_fichier', echouer)
    elif phase == 'apres_sql':
        def echouer(conn, *a, **kw):
            assert conn.execute("SELECT COUNT(*) FROM ecritures_comptables WHERE statut='exportee'").fetchone()[0] == 2
            raise sqlite3.OperationalError('Panne SQL')
        monkeypatch.setattr(module, 'evenement', echouer)
    else:
        original = ConnexionFiches.commit
        def echouer(conn):
            if conn.execute('SELECT 1 FROM archives_export').fetchone():
                raise sqlite3.OperationalError('Commit impossible')
            return original(conn)
        monkeypatch.setattr(ConnexionFiches, 'commit', echouer)
    response = comptable_client.post('/exportation/exporter', data=donnees, follow_redirects=True)
    assert 'Export non réalisé' in response.get_data(as_text=True)
    assert etat(db) == avant
    dossier = tmp_path / 'exports'
    assert not dossier.exists() or not list(dossier.iterdir())


def client_comptable(app):
    client = app.test_client()
    assert client.post('/login', data={'login': 'compta_test', 'password': 'compta123'}).status_code == 302
    return client


def test_t6_deux_exports_simultanes_un_seul_lot(piece, db, app, comptable_client):
    clients = [client_comptable(app), client_comptable(app)]
    forms = [selection(c, piece[1]) for c in clients]
    barriere = Barrier(2)
    def envoyer(i):
        barriere.wait(timeout=5)
        return clients[i].post('/exportation/exporter', data=forms[i])
    with ThreadPoolExecutor(max_workers=2) as pool:
        resultats = list(pool.map(envoyer, (0, 1)))
    assert sorted(r.status_code for r in resultats) == [200, 302]
    assert db.execute('SELECT COUNT(*) FROM archives_export').fetchone()[0] == 1
    assert db.execute('SELECT COUNT(*) FROM export_lignes').fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM comptabilite_evenements WHERE action='export'").fetchone()[0] == 1


def test_deux_pieces_simultanees_noms_uniques(piece, db, app):
    fid = db.execute("INSERT INTO factures (numero_facture, statut) VALUES ('SECONDE', 'traitee')").lastrowid
    ids = []
    for debit, credit in [(5, 0), (0, 5)]:
        ids.append(db.execute("INSERT INTO ecritures_comptables (facture_id, date_ecriture, compte, libelle, debit, credit, statut) VALUES (?, '2026-09-09', 'TEST', 'AUTRE', ?, ?, 'validee')", (fid, debit, credit)).lastrowid)
    db.commit()
    clients = [client_comptable(app), client_comptable(app)]
    forms = [selection(clients[0], piece[1]), selection(clients[1], ids)]
    barriere = Barrier(2)
    def envoyer(i):
        barriere.wait(timeout=5)
        return clients[i].post('/exportation/exporter', data=forms[i])
    with ThreadPoolExecutor(max_workers=2) as pool:
        resultats = list(pool.map(envoyer, (0, 1)))
    assert all(r.status_code == 200 for r in resultats)
    lots = db.execute('SELECT * FROM archives_export').fetchall()
    assert len(lots) == 2 and lots[0]['nom_fichier'] != lots[1]['nom_fichier']
    assert {l['contenu'] for l in lots} == {r.data for r in resultats}


@pytest.mark.parametrize('action', ['modification', 'suppression'])
def test_export_attend_ecriture_concurrente_puis_refuse_page_perimee(piece, db, app, action):
    from database import get_db
    client = client_comptable(app)
    data = selection(client, piece[1])
    verrou = Event(); terminer = Event(); pret = Event()
    def modifier():
        with app.app_context():
            conn = get_db()
            try:
                conn.execute('BEGIN IMMEDIATE')
                if action == 'modification':
                    conn.execute("UPDATE ecritures_comptables SET libelle='CONCURRENT' WHERE id=?", (piece[1][0],))
                else:
                    conn.execute('DELETE FROM ecritures_comptables WHERE id=?', (piece[1][0],))
                verrou.set()
                assert terminer.wait(5)
                conn.commit()
            finally: conn.close()
    def envoyer():
        assert verrou.wait(5)
        pret.set()
        return client.post('/exportation/exporter', data=data)
    with ThreadPoolExecutor(max_workers=2) as pool:
        modification = pool.submit(modifier)
        export = pool.submit(envoyer)
        assert pret.wait(5)
        terminer.set()
        modification.result(timeout=10)
        response = export.result(timeout=10)
    assert response.status_code == 302
    assert db.execute('SELECT COUNT(*) FROM archives_export').fetchone()[0] == 0


def test_export_puis_modification_concurrente_refusee(piece, db, app, monkeypatch):
    from blueprints import exportation
    export_client, edit_client = client_comptable(app), client_comptable(app)
    data = selection(export_client, piece[1])
    eid = piece[1][0]
    edition = {'reference': references(edit_client)[f'reference_{eid}'], 'compte': 'AUTRE', 'libelle': 'AUTRE', 'debit': '999', 'credit': '0'}
    verrou = Event(); terminer = Event(); pret = Event()
    original = exportation._produire_fichier
    def produire(lignes):
        verrou.set()
        assert terminer.wait(5)
        return original(lignes)
    monkeypatch.setattr(exportation, '_produire_fichier', produire)
    def modifier():
        assert verrou.wait(5)
        pret.set()
        return edit_client.post(f'/ecritures/{eid}/modifier', data=edition)
    with ThreadPoolExecutor(max_workers=2) as pool:
        export = pool.submit(export_client.post, '/exportation/exporter', data=data)
        edit = pool.submit(modifier)
        assert pret.wait(5)
        terminer.set()
        assert export.result(timeout=10).status_code == 200
        assert edit.result(timeout=10).status_code == 302
    assert db.execute('SELECT debit FROM ecritures_comptables WHERE id=?', (eid,)).fetchone()[0] == 120
    assert db.execute("SELECT 1 FROM comptabilite_evenements WHERE action='modification_refusee'").fetchone()


@pytest.mark.parametrize('profil', ['salarie', 'responsable', 'prestataire', 'anonyme'])
def test_post_direct_non_autorise_aucun_effet(piece, db, app, request, profil):
    client = app.test_client() if profil == 'anonyme' else request.getfixturevalue(
        {'salarie': 'auth_client', 'responsable': 'resp_client', 'prestataire': 'prestataire_client'}[profil])
    fid, ids = piece
    avant = etat(db)
    for url in ('/exportation/exporter', '/ecritures/valider', f'/ecritures/{ids[0]}/modifier',
                f'/factures/{fid}/supprimer', f'/factures/{fid}/archiver',
                f'/factures/{fid}/signaler-correction', '/exportation/archives/1/telecharger'):
        r = client.post(url, data={'ecriture_ids': ids, 'motif': 'Faux', 'confirmer': '1'})
        assert r.status_code in (302, 403)
        assert etat(db) == avant
    assert not db.execute('SELECT 1 FROM comptabilite_evenements').fetchone()


@pytest.mark.parametrize('changement', ['profil', 'desactive', 'session'])
def test_droits_relus_sous_verrou(piece, db, comptable_client, monkeypatch, sample_users, changement):
    from blueprints import exportation
    original = exportation.get_db
    data = selection(comptable_client, piece[1])
    def ouvrir():
        # Après le gate avant-requête, avant BEGIN IMMEDIATE dans la route.
        if changement == 'profil':
            db.execute("UPDATE users SET profil='salarie' WHERE id=?", (sample_users['comptable_id'],))
        elif changement == 'desactive':
            db.execute('UPDATE users SET actif=0 WHERE id=?', (sample_users['comptable_id'],))
        else:
            db.execute('UPDATE users SET session_version=session_version+1 WHERE id=?', (sample_users['comptable_id'],))
        db.commit()
        return original()
    monkeypatch.setattr(exportation, 'get_db', ouvrir)
    avant = etat(db)
    r = comptable_client.post('/exportation/exporter', data=data)
    assert r.status_code == 302
    assert etat(db) == avant


def test_ia_deux_generations_simultanees_une_seule_proposition(app, db, comptable_client, monkeypatch):
    import json
    from tests.test_ecritures import _seed_facture, _two_lines
    fid = _seed_facture(app, db)
    clients = [client_comptable(app), client_comptable(app)]
    barriere = Barrier(2)
    def ia(*args):
        barriere.wait(timeout=5)
        return json.dumps({'facture_id': fid, 'lignes': _two_lines(fid)})
    monkeypatch.setattr('blueprints.ecritures.call_ai', ia)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reponses = list(pool.map(lambda c: c.post('/ecritures/generer', data={'model': 'fictif'}), clients))
    assert all(r.status_code == 302 for r in reponses)
    assert db.execute('SELECT COUNT(*) FROM ecritures_comptables').fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM facture_historique WHERE action='Écritures générées'").fetchone()[0] == 1


def test_export_mille_lignes(piece, db, comptable_client):
    from time import perf_counter
    fid, ids = piece
    for _ in range(499):
        for debit, credit in ((1, 0), (0, 1)):
            ids.append(db.execute("INSERT INTO ecritures_comptables (facture_id, date_ecriture, compte, libelle, debit, credit, statut) VALUES (?, '2026-09-09', 'TEST', 'VOLUME SYNTHETIQUE', ?, ?, 'validee')", (fid, debit, credit)).lastrowid)
    db.commit()
    donnees = selection(comptable_client, ids)
    debut = perf_counter()
    r = comptable_client.post('/exportation/exporter', data=donnees)
    duree = perf_counter() - debut
    assert r.status_code == 200
    assert len(r.data.splitlines()) == 1000
    lot = db.execute('SELECT * FROM archives_export').fetchone()
    assert lot['nb_ecritures'] == 1000 and lot['total_debit_centimes'] == lot['total_credit_centimes'] == 61900
    print(f'Export HTTP de 1000 lignes : {duree:.3f} s ; fichier {len(r.data)} octets ; commit inclus.')
