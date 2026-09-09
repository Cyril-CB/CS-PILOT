"""B3 : preuve d'export et protection du contenu comptable (données fictives)."""
import re

import pytest


@pytest.fixture
def piece(db, comptable_client, monkeypatch, tmp_path):
    from blueprints import exportation
    monkeypatch.setattr(exportation, 'ARCHIVES_DIR', str(tmp_path / 'exports'))
    fid = db.execute("INSERT INTO factures (numero_facture, date_facture, montant_ttc, statut) "
                     "VALUES ('TEST-B3', '2026-09-09', 120, 'traitee')").lastrowid
    ids = []
    for compte, debit, credit in [('606100', 120, 0), ('FTEST', 0, 120)]:
        ids.append(db.execute(
            "INSERT INTO ecritures_comptables (facture_id, date_ecriture, compte, libelle, "
            "numero_facture, debit, credit, statut) VALUES (?, '2026-09-09', ?, 'TEST B3', "
            "'TEST-B3', ?, ?, 'validee')", (fid, compte, debit, credit)).lastrowid)
    db.execute("INSERT INTO facture_historique (facture_id, action) VALUES (?, 'Création test')", (fid,))
    db.commit()
    return fid, ids


def selection(client, ids):
    """Lire les références du formulaire, aussi utilisable pour reproduire sur main."""
    html = client.get('/exportation').get_data(as_text=True)
    data = {'ecriture_ids': [str(i) for i in ids]}
    for name, value in re.findall(r'name="(reference_\d+)" value="([^"]+)"', html):
        data[name] = value
    return data


def exporter(client, ids):
    return client.post('/exportation/exporter', data=selection(client, ids))


def test_b3_a_refus_export_partiel(piece, db, comptable_client):
    _, ids = piece
    response = exporter(comptable_client, ids[:1])
    assert response.status_code == 302
    assert db.execute('SELECT COUNT(*) FROM archives_export').fetchone()[0] == 0
    assert all(r[0] == 'validee' for r in db.execute('SELECT statut FROM ecritures_comptables'))


def test_b3_b_export_non_modifiable(piece, db, comptable_client):
    _, ids = piece
    response = exporter(comptable_client, ids)
    assert response.status_code == 200
    comptable_client.post(f'/ecritures/{ids[0]}/modifier', data={
        'compte': '607000', 'libelle': 'CHANGEMENT', 'debit': '999',
        'credit': '0', 'code_analytique': 'AUTRE'})
    row = db.execute('SELECT * FROM ecritures_comptables WHERE id=?', (ids[0],)).fetchone()
    assert row['debit'] == 120
    assert row['statut'] == 'exportee'


def test_b3_c_source_et_historique_conserves(piece, db, comptable_client):
    fid, ids = piece
    assert exporter(comptable_client, ids).status_code == 200
    comptable_client.post(f'/factures/{fid}/supprimer')
    assert db.execute('SELECT COUNT(*) FROM factures WHERE id=?', (fid,)).fetchone()[0] == 1
    assert db.execute('SELECT COUNT(*) FROM ecritures_comptables WHERE facture_id=?', (fid,)).fetchone()[0] == 2
    assert db.execute('SELECT COUNT(*) FROM facture_historique WHERE facture_id=?', (fid,)).fetchone()[0] > 0


def references(client, url='/ecritures'):
    return dict(re.findall(r'name="(reference_\d+)" value="([^"]+)"', client.get(url).get_data(as_text=True)))


def modifier(client, eid, **champs):
    data = {'compte': '606100', 'libelle': 'TEST B3', 'debit': '120', 'credit': '0',
            'code_analytique': '', 'reference': references(client)[f'reference_{eid}']}
    data.update(champs)
    return client.post(f'/ecritures/{eid}/modifier', data=data, follow_redirects=True)


def etat(db):
    return {t: [tuple(r) for r in db.execute(f'SELECT * FROM {t} ORDER BY id')]
            for t in ('factures', 'ecritures_comptables', 'archives_export', 'export_lignes', 'facture_historique')}


def test_t2_preuve_exacte_et_autonome(piece, db, comptable_client):
    import hashlib
    import json
    fid, ids = piece
    resultat = exporter(comptable_client, ids)
    attendu = (b'AC\t09092026\t606100\tTEST B3\tTEST-B3\t120.00\t\t\t\n'
               b'AC\t09092026\tFTEST\tTEST B3\tTEST-B3\t\t120.00\t\t\n')
    assert resultat.data == attendu
    lot = db.execute('SELECT * FROM archives_export').fetchone()
    assert lot['contenu'] == attendu
    assert lot['empreinte'] == hashlib.sha256(attendu).hexdigest()
    assert lot['preuve_version'] == 1 and lot['format'] == 'aiga-txt-v1'
    assert lot['nb_ecritures'] == 2
    assert lot['total_debit_centimes'] == lot['total_credit_centimes'] == 12000
    assert lot['auteur_nom'] == 'Sophie Durand'
    lignes = [json.loads(r['contenu']) for r in db.execute('SELECT * FROM export_lignes ORDER BY position')]
    assert [l['ecriture']['id'] for l in lignes] == ids
    assert all(l['ecriture']['revision'] == 1 for l in lignes)
    assert b''.join(('\t'.join(l['colonnes']) + '\n').encode() for l in lignes) == attendu
    # Les valeurs courantes de la source et du nom d'utilisateur n'altèrent pas la preuve.
    db.execute("UPDATE factures SET numero_facture='COURANTE', montant_ttc=999 WHERE id=?", (fid,))
    db.execute("UPDATE users SET prenom='Autre' WHERE id=?", (lot['created_by'],))
    db.commit()
    html = comptable_client.get(f'/exportation/archives/{lot["id"]}').get_data(as_text=True)
    assert 'TEST-B3' in html and 'Sophie Durand' in html and 'COURANTE' not in html
    assert db.execute('SELECT contenu FROM archives_export').fetchone()[0] == attendu


@pytest.mark.parametrize('champs', [
    {'debit': '999'}, {'compte': 'AUTRE'}, {'code_analytique': 'ANA99'}, {'libelle': 'AUTRE'}])
def test_t3_modifications_refusees_et_tracees(piece, db, comptable_client, champs):
    _, ids = piece
    assert exporter(comptable_client, ids).status_code == 200
    avant = etat(db)
    response = modifier(comptable_client, ids[0], **champs)
    assert 'déjà été exportée' in response.get_data(as_text=True)
    assert etat(db) == avant
    event = db.execute("SELECT * FROM comptabilite_evenements WHERE action='modification_refusee'").fetchone()
    assert event['archive_id'] and event['ecriture_id'] == ids[0]


def test_correction_signalee_sans_recriture_et_archivage(piece, db, comptable_client, tmp_path):
    fid, ids = piece
    pdf = tmp_path / 'facture-fictive.pdf'
    pdf.write_bytes(b'Fichier fictif de test')
    db.execute('UPDATE factures SET fichier_path=? WHERE id=?', (str(pdf), fid)); db.commit()
    assert exporter(comptable_client, ids).status_code == 200
    avant = etat(db)
    r = comptable_client.post(f'/factures/{fid}/signaler-correction', data={'motif': 'Compte à examiner'}, follow_redirects=True)
    assert 'Correction signalée' in r.get_data(as_text=True)
    apres = etat(db)
    for table in ('ecritures_comptables', 'archives_export', 'export_lignes', 'factures'):
        assert apres[table] == avant[table]
    comptable_client.post(f'/factures/{fid}/archiver', data={'motif': 'Dossier classé'})
    assert db.execute('SELECT archivee FROM factures WHERE id=?', (fid,)).fetchone()[0] == 1
    assert pdf.exists()
    assert 'TEST-B3' not in comptable_client.get('/factures').get_data(as_text=True)
    assert 'TEST-B3' in comptable_client.get('/factures?archives=1').get_data(as_text=True)
    assert db.execute("SELECT COUNT(*) FROM comptabilite_evenements WHERE action='correction_signalee'").fetchone()[0] == 1
    assert db.execute('SELECT contenu FROM archives_export').fetchone()[0] == avant['archives_export'][0][7]


@pytest.mark.parametrize('action', ['archiver', 'signaler-correction'])
def test_action_apres_export_motif_obligatoire(piece, db, comptable_client, action):
    fid, ids = piece
    exporter(comptable_client, ids)
    avant = etat(db)
    r = comptable_client.post(f'/factures/{fid}/{action}', data={'motif': '   '}, follow_redirects=True)
    assert 'Indiquez un motif' in r.get_data(as_text=True)
    assert etat(db) == avant


def test_t5_doublon_et_retelechargement_explicite(piece, db, comptable_client):
    _, ids = piece
    formulaire = selection(comptable_client, ids)
    initial = comptable_client.post('/exportation/exporter', data=formulaire)
    avant = etat(db)
    assert comptable_client.post('/exportation/exporter', data=formulaire).status_code == 302
    assert etat(db) == avant
    lot = db.execute('SELECT id FROM archives_export').fetchone()[0]
    url = f'/exportation/archives/{lot}/telecharger'
    assert comptable_client.get(url).status_code == 302
    assert comptable_client.post(url).status_code == 302
    assert not db.execute("SELECT 1 FROM comptabilite_evenements WHERE action='retelechargement'").fetchone()
    assert comptable_client.post(url, data={'confirmer': '1'}).data == initial.data
    assert etat(db) == avant
    assert db.execute("SELECT COUNT(*) FROM comptabilite_evenements WHERE action='retelechargement'").fetchone()[0] == 1


@pytest.mark.parametrize('changement', ['montant', 'compte', 'analytique', 'libelle', 'source', 'suppression', 'ajout_ligne'])
def test_t7_page_export_perimee(piece, db, comptable_client, changement):
    fid, ids = piece
    data = selection(comptable_client, ids)
    if changement == 'montant':
        db.execute('UPDATE ecritures_comptables SET debit=121 WHERE id=?', (ids[0],))
    elif changement == 'compte':
        db.execute("UPDATE ecritures_comptables SET compte='607000' WHERE id=?", (ids[0],))
    elif changement == 'analytique':
        db.execute("UPDATE ecritures_comptables SET code_analytique='A' WHERE id=?", (ids[0],))
    elif changement == 'libelle':
        db.execute("UPDATE ecritures_comptables SET libelle='NOUVEAU' WHERE id=?", (ids[0],))
    elif changement == 'source':
        db.execute("UPDATE factures SET numero_facture='NOUVEAU' WHERE id=?", (fid,))
    elif changement == 'suppression':
        db.execute('DELETE FROM ecritures_comptables WHERE id=?', (ids[0],))
    else:
        db.execute("INSERT INTO ecritures_comptables (facture_id, date_ecriture, compte, libelle) VALUES (?, '2026-09-09', '606000', 'AJOUT')", (fid,))
    db.commit()
    avant = etat(db)
    assert comptable_client.post('/exportation/exporter', data=data).status_code == 302
    assert etat(db) == avant


@pytest.mark.parametrize('cas', ['sans_reference', 'reference_autre', 'reference_falsifiee', 'inconnu', 'double', 'vide', 'non_numerique', 'negatif', 'grand', 'brouillon', 'deja_exportee', 'autre_piece'])
def test_selection_invalide_atomique(piece, db, comptable_client, cas):
    fid, ids = piece
    data = selection(comptable_client, ids)
    if cas == 'sans_reference':
        data.pop(f'reference_{ids[0]}')
    elif cas == 'reference_autre':
        data[f'reference_{ids[0]}'] = data[f'reference_{ids[1]}']
    elif cas == 'reference_falsifiee':
        data[f'reference_{ids[0]}'] += 'faux'
    elif cas in ('inconnu', 'double', 'vide', 'non_numerique', 'negatif', 'grand'):
        data['ecriture_ids'] = {'inconnu': ids + [999999], 'double': ids + ids[:1], 'vide': [],
                                'non_numerique': ['abc'], 'negatif': [-1], 'grand': [2**80]}[cas]
    elif cas == 'brouillon':
        db.execute("UPDATE ecritures_comptables SET statut='brouillon' WHERE id=?", (ids[1],)); db.commit()
    elif cas == 'deja_exportee':
        exporter(comptable_client, ids)
    else:
        autre = db.execute("INSERT INTO factures (numero_facture) VALUES ('AUTRE')").lastrowid
        eid = db.execute("INSERT INTO ecritures_comptables (facture_id, date_ecriture, compte, libelle, debit, statut) VALUES (?, '2026-09-09', '606000', 'AUTRE', 10, 'validee')", (autre,)).lastrowid
        db.commit()
        data['ecriture_ids'].append(str(eid))
    avant = etat(db)
    r = comptable_client.post('/exportation/exporter', data=data)
    assert r.status_code == 302
    assert etat(db) == avant


def test_equilibre_lot_ne_compense_pas_pieces_desequilibrees(piece, db, comptable_client):
    fid, ids = piece
    autre = db.execute("INSERT INTO factures (numero_facture) VALUES ('AUTRE')").lastrowid
    db.execute('UPDATE ecritures_comptables SET facture_id=? WHERE id=?', (autre, ids[1]))
    db.execute("UPDATE ecritures_comptables SET statut='validee' WHERE id=?", (ids[1],)); db.commit()
    r = exporter(comptable_client, ids)
    assert r.status_code == 302
    assert db.execute('SELECT COUNT(*) FROM archives_export').fetchone()[0] == 0


@pytest.mark.parametrize('valeur', ['-1', 'nan', 'inf', 'abc', '1.001', '99999999999999999999'])
def test_montants_invalides_refuses(piece, db, comptable_client, valeur):
    _, ids = piece
    avant = etat(db)
    modifier(comptable_client, ids[0], debit=valeur)
    assert etat(db) == avant


def test_modification_validee_redevient_brouillon_revisionnee(piece, db, comptable_client):
    _, ids = piece
    ancienne = selection(comptable_client, ids)
    modifier(comptable_client, ids[0], libelle='NOUVEAU')
    row = db.execute('SELECT * FROM ecritures_comptables WHERE id=?', (ids[0],)).fetchone()
    assert row['statut'] == 'brouillon' and row['revision'] == 2
    data = {'ecriture_ids': [str(ids[0])], **references(comptable_client)}
    comptable_client.post('/ecritures/valider', data=data)
    assert db.execute('SELECT statut FROM ecritures_comptables WHERE id=?', (ids[0],)).fetchone()[0] == 'validee'
    assert comptable_client.post('/exportation/exporter', data=ancienne).status_code == 302
    assert exporter(comptable_client, ids).status_code == 200
    assert db.execute('SELECT revision FROM export_lignes WHERE ecriture_id=?', (ids[0],)).fetchone()[0] == 2


def test_historique_validation_conserve_etat_valide_et_revision(piece, db, comptable_client):
    import json
    fid, ids = piece
    db.execute("UPDATE ecritures_comptables SET statut='brouillon' WHERE facture_id=?", (fid,))
    db.commit()
    response = comptable_client.post('/ecritures/valider', data={
        'ecriture_ids': ids, **references(comptable_client)}, follow_redirects=True)
    assert response.status_code == 200
    assert '2 écriture(s) validée(s).' in response.get_data(as_text=True)
    evenements = db.execute(
        "SELECT * FROM comptabilite_evenements WHERE action='validation' ORDER BY id").fetchall()
    assert len(evenements) == 2
    for evenement, eid in zip(evenements, ids):
        row = db.execute('SELECT * FROM ecritures_comptables WHERE id=?', (eid,)).fetchone()
        details = json.loads(evenement['details'])
        assert evenement['ecriture_id'] == eid and evenement['facture_id'] == fid
        assert details['source']['id'] == fid
        assert details['ecriture']['statut'] == row['statut'] == 'validee'
        assert details['ecriture']['revision'] == row['revision'] == 1
        assert details['ecriture']['id'] == eid
        assert details['ecriture']['debit'] == row['debit']
        assert details['ecriture']['credit'] == row['credit']

    # Une nouvelle révision n'altère pas l'état attesté par la validation précédente.
    premier = dict(evenements[0])
    modifier(comptable_client, ids[0], libelle='NOUVELLE REVISION')
    assert db.execute('SELECT statut FROM ecritures_comptables WHERE id=?', (ids[0],)).fetchone()[0] == 'brouillon'
    comptable_client.post('/ecritures/valider', data={
        'ecriture_ids': [ids[0]], **references(comptable_client)})
    assert dict(db.execute('SELECT * FROM comptabilite_evenements WHERE id=?', (premier['id'],)).fetchone()) == premier
    validations = db.execute(
        "SELECT details FROM comptabilite_evenements WHERE action='validation' AND ecriture_id=? ORDER BY id",
        (ids[0],)).fetchall()
    assert len(validations) == 2
    nouvelle = json.loads(validations[1]['details'])['ecriture']
    assert nouvelle['statut'] == 'validee'
    assert nouvelle['revision'] == 2 and nouvelle['libelle'] == 'NOUVELLE REVISION'


@pytest.mark.parametrize('champ,valeur', [('libelle', 'X\tINJECTION'), ('compte', 'X\nLIGNE'), ('code_analytique', 'A\rB'), ('debit', 120.001), ('date_ecriture', '2026-02-30'), ('echeance', '31022026')])
def test_colonnes_export_invalides(piece, db, comptable_client, champ, valeur):
    _, ids = piece
    # Liste fermée de colonnes des scénarios, jamais issue d'une requête.
    assert champ in ('libelle', 'compte', 'code_analytique', 'debit', 'date_ecriture', 'echeance')
    db.execute(f'UPDATE ecritures_comptables SET {champ}=? WHERE id=?', (valeur, ids[0]))
    db.execute("UPDATE ecritures_comptables SET statut='validee' WHERE id=?", (ids[0],)); db.commit()
    avant = etat(db)
    assert exporter(comptable_client, ids).status_code == 302
    assert etat(db) == avant


@pytest.mark.parametrize('operation', [
    "UPDATE archives_export SET nom_fichier='autre'", 'DELETE FROM archives_export',
    "UPDATE export_lignes SET contenu='{}'", 'DELETE FROM export_lignes',
    "UPDATE ecritures_comptables SET statut='brouillon'", 'DELETE FROM ecritures_comptables',
    'DELETE FROM factures', 'DELETE FROM facture_historique', 'DELETE FROM comptabilite_evenements'])
def test_preuve_protegee_contre_ecriture_directe(piece, db, comptable_client, operation):
    import sqlite3
    exporter(comptable_client, piece[1])
    avant = etat(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(operation)
    db.rollback()
    assert etat(db) == avant


def test_supprimer_archive_refuse_et_conserve_preuve(piece, db, comptable_client):
    exporter(comptable_client, piece[1])
    lot = db.execute('SELECT id FROM archives_export').fetchone()[0]
    avant = etat(db)
    r = comptable_client.post(f'/exportation/archives/{lot}/supprimer', follow_redirects=True)
    assert 'archives comptables sont conservées' in r.get_data(as_text=True)
    assert etat(db) == avant


@pytest.mark.parametrize('statut', ['brouillon', 'validee'])
def test_suppression_non_exportee_reste_possible(piece, db, comptable_client, statut):
    fid, _ = piece
    db.execute('UPDATE ecritures_comptables SET statut=? WHERE facture_id=?', (statut, fid)); db.commit()
    comptable_client.post(f'/factures/{fid}/supprimer')
    assert not db.execute('SELECT 1 FROM factures WHERE id=?', (fid,)).fetchone()
    assert not db.execute('SELECT 1 FROM ecritures_comptables').fetchone()
    assert db.execute("SELECT 1 FROM comptabilite_evenements WHERE action='suppression_facture'").fetchone()


def test_ancienne_validation_et_edition_perimees_refusees(piece, db, comptable_client):
    _, ids = piece
    db.execute("UPDATE ecritures_comptables SET statut='brouillon'"); db.commit()
    refs = references(comptable_client)
    db.execute("UPDATE ecritures_comptables SET libelle='AUTRE SESSION' WHERE id=?", (ids[0],)); db.commit()
    avant = etat(db)
    comptable_client.post('/ecritures/valider', data={'ecriture_ids': ids, **refs})
    comptable_client.post(f'/ecritures/{ids[0]}/modifier', data={'reference': refs[f'reference_{ids[0]}'], 'compte': '606100', 'libelle': 'ANCIEN', 'debit': 120, 'credit': 0})
    assert etat(db) == avant
    assert not db.execute('SELECT 1 FROM comptabilite_evenements').fetchone()


def test_archive_sort_des_actions_et_relances(piece, db, comptable_client, app, sample_users, monkeypatch):
    from flux_infos import _factures, _ecritures
    fid, ids = piece
    db.execute('UPDATE factures SET secteur_id=? WHERE id=?', (sample_users['secteur_id'], fid)); db.commit()
    exporter(comptable_client, ids)
    comptable_client.post(f'/factures/{fid}/archiver', data={'motif': 'Classement explicite'})
    with app.test_request_context('/'):
        assert _factures(db, {'profil': 'comptable'}) == []
        assert _ecritures(db, {'profil': 'comptable'}) == []
        # Même filtre que les actions et la page d'approbation.
    html = comptable_client.get('/factures/approbation').get_data(as_text=True)
    assert 'TEST-B3' not in html
    envois = []
    monkeypatch.setattr('blueprints.factures.envoyer_email', lambda *a, **k: envois.append(a))
    comptable_client.post('/factures/relancer')
    assert envois == []


def test_ecriture_historique_orpheline_reste_visible(db, comptable_client):
    db.execute("INSERT INTO ecritures_comptables (facture_id, date_ecriture, compte, libelle, debit, statut) VALUES (999, '2025-01-01', '606000', 'ORPHELINE HISTORIQUE', 10, 'exportee')")
    db.commit()
    assert 'ORPHELINE HISTORIQUE' in comptable_client.get('/ecritures').get_data(as_text=True)


def test_montant_non_fini_ancien_reste_consultable_et_corrigeable(piece, db, comptable_client):
    _, ids = piece
    db.execute('UPDATE ecritures_comptables SET debit=? WHERE id=?', (float('inf'), ids[0])); db.commit()
    assert comptable_client.get('/ecritures').status_code == 200
    db.execute("UPDATE ecritures_comptables SET statut='validee' WHERE id=?", (ids[0],)); db.commit()
    assert exporter(comptable_client, ids).status_code == 302
    modifier(comptable_client, ids[0], debit='120')
    assert db.execute('SELECT debit FROM ecritures_comptables WHERE id=?', (ids[0],)).fetchone()[0] == 120
    detail = db.execute("SELECT details FROM comptabilite_evenements WHERE action='modification'").fetchone()[0]
    assert 'nombre_non_fini' in detail
