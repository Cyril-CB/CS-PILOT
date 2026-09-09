"""B3 : migration honnête de l'historique et propositions IA sans autorité."""
import importlib
import json
import sqlite3

import pytest

from tests.test_exports_comptables import piece, etat, exporter, selection
from tests.test_ecritures import _seed_facture, _two_lines

MIGRATION = importlib.import_module('migrations.0069_preuves_exports_comptables')


def retirer_schema(db):
    prefixes = ('preuve_', 'ecriture_exportee_', 'ecriture_export_preuve', 'ecriture_revision',
                'facture_exportee_conserver', 'historique_facture_exportee_')
    for row in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall():
        if row[0].startswith(prefixes):
            db.execute('DROP TRIGGER "' + row[0].replace('"', '""') + '"')
    for table in ('export_lignes', 'comptabilite_evenements'):
        db.execute(f'DROP TABLE {table}')
    colonnes = {'archives_export': ('preuve_version', 'contenu', 'empreinte', 'format', 'total_debit_centimes', 'total_credit_centimes', 'auteur_nom'),
                'ecritures_comptables': ('revision', 'export_historique'), 'factures': ('archivee',)}
    for table, champs in colonnes.items():
        for champ in champs:
            db.execute(f'ALTER TABLE {table} DROP COLUMN {champ}')
    db.commit()


def test_migration_neuve_idempotente(db):
    from database import ALL_MIGRATION_VERSIONS
    for _ in range(2):
        MIGRATION.upgrade(db); db.commit()
    assert ('0069', MIGRATION.NOM) in ALL_MIGRATION_VERSIONS
    assert 'contenu' in {r[1] for r in db.execute('PRAGMA table_info(archives_export)')}
    assert db.execute('SELECT COUNT(*) FROM export_lignes').fetchone()[0] == 0


@pytest.mark.parametrize('partielle', [False, True])
def test_historique_preserve_sans_fausse_preuve(piece, db, comptable_client, tmp_path, partielle):
    fid, ids = piece
    retirer_schema(db)
    db.execute("UPDATE ecritures_comptables SET statut='exportee', updated_at='2025-01-01 12:00:00' WHERE id=?", (ids[0],))
    if not partielle:
        db.execute("UPDATE ecritures_comptables SET statut='exportee' WHERE id=?", (ids[1],))
    fichier = tmp_path / 'ancien-export.txt'; fichier.write_bytes(b'CONTENU HISTORIQUE DIFFERENT')
    db.execute("INSERT INTO archives_export (nom_fichier, fichier_path, nb_ecritures, created_at) VALUES (?, ?, 1, '2025-01-01 12:00:00')", (fichier.name, str(fichier)))
    db.commit()
    anciennes = [dict(r) for r in db.execute('SELECT * FROM ecritures_comptables')]
    ancien_lot = dict(db.execute('SELECT * FROM archives_export').fetchone())
    for _ in range(2):
        MIGRATION.upgrade(db); db.commit()
    for avant, row in zip(anciennes, db.execute('SELECT * FROM ecritures_comptables')):
        assert all(row[k] == v for k, v in avant.items())
        assert row['export_historique'] == int(avant['statut'] == 'exportee')
    lot = db.execute('SELECT * FROM archives_export').fetchone()
    assert all(lot[k] == v for k, v in ancien_lot.items())
    assert lot['preuve_version'] == 0 and lot['contenu'] is None and lot['empreinte'] is None
    assert not db.execute('SELECT 1 FROM export_lignes').fetchone()
    assert not db.execute('SELECT 1 FROM comptabilite_evenements').fetchone()
    assert comptable_client.get(f'/exportation/archives/{lot["id"]}/telecharger').data == fichier.read_bytes()
    html = comptable_client.get(f'/exportation/archives/{lot["id"]}').get_data(as_text=True)
    assert 'contenu exact non garanti' in html
    assert 'Export historique' in comptable_client.get('/ecritures').get_data(as_text=True)
    comptable_client.post(f'/factures/{fid}/supprimer')
    assert db.execute('SELECT 1 FROM factures WHERE id=?', (fid,)).fetchone()
    if partielle:
        assert exporter(comptable_client, ids[1:]).status_code == 302
        assert db.execute('SELECT COUNT(*) FROM archives_export').fetchone()[0] == 1


def test_migration_via_init_db_restauration_ancienne_base(piece, db):
    from database import init_db
    retirer_schema(db)
    db.execute("UPDATE ecritures_comptables SET statut='exportee'"); db.commit()
    init_db()
    assert db.execute('SELECT SUM(export_historique) FROM ecritures_comptables').fetchone()[0] == 2
    assert not db.execute('SELECT 1 FROM export_lignes').fetchone()


def test_migration_echec_rollback(db):
    retirer_schema(db)
    class ConnexionDefaillante:
        @property
        def in_transaction(self): return db.in_transaction
        def execute(self, sql, *args):
            if 'CREATE TABLE IF NOT EXISTS export_lignes' in sql:
                raise sqlite3.OperationalError('Panne synthétique')
            return db.execute(sql, *args)
    with pytest.raises(sqlite3.OperationalError):
        with db: MIGRATION.upgrade(ConnexionDefaillante())
    assert 'revision' not in {r[1] for r in db.execute('PRAGMA table_info(ecritures_comptables)')}
    assert 'contenu' not in {r[1] for r in db.execute('PRAGMA table_info(archives_export)')}


def test_downgrade_refuse_destruction_preuves(db):
    with pytest.raises(RuntimeError, match='sauvegarde'): MIGRATION.downgrade(db)


@pytest.mark.parametrize('changement', ['montant', 'suppression', 'traitement', 'ecriture', 'fournisseur', 'role'])
def test_ia_tardive_refuse_facture_changee(app, db, comptable_client, sample_users, monkeypatch, changement):
    fid = _seed_facture(app, db)
    def ia(*args):
        if changement == 'montant':
            db.execute('UPDATE factures SET montant_ttc=999 WHERE id=?', (fid,))
        elif changement == 'suppression':
            db.execute('DELETE FROM factures WHERE id=?', (fid,))
        elif changement == 'traitement':
            db.execute("UPDATE factures SET statut='traitee' WHERE id=?", (fid,))
        elif changement == 'ecriture':
            db.execute("INSERT INTO ecritures_comptables (facture_id, date_ecriture, compte, libelle, debit) VALUES (?, '2026-09-09', '606000', 'AUTRE', 12)", (fid,))
        elif changement == 'fournisseur':
            db.execute("UPDATE fournisseurs SET code_comptable='AUTRE'")
        else:
            db.execute("UPDATE users SET profil='salarie' WHERE id=?", (sample_users['comptable_id'],))
        db.commit()
        return json.dumps({'ecritures': [{'facture_id': fid, 'lignes': _two_lines(fid)}]})
    monkeypatch.setattr('blueprints.ecritures.call_ai', ia)
    r = comptable_client.post('/ecritures/generer', data={'model': 'modele-fictif'})
    assert r.status_code == 302
    assert db.execute('SELECT COUNT(*) FROM ecritures_comptables').fetchone()[0] == (1 if changement == 'ecriture' else 0)
    assert not db.execute("SELECT 1 FROM facture_historique WHERE action='Écritures générées'").fetchone()


@pytest.mark.parametrize('cas', ['id_inconnu', 'autre_facture_traitee', 'doublon', 'ligne_invalide'])
def test_reponse_ia_n_impose_pas_sa_selection(app, db, comptable_client, monkeypatch, cas):
    fid = _seed_facture(app, db)
    autre = _seed_facture(app, db, statut='traitee')
    entree = {'facture_id': fid, 'lignes': _two_lines(fid)}
    if cas == 'id_inconnu': entree['facture_id'] = 999999
    elif cas == 'autre_facture_traitee': entree['facture_id'] = autre
    elif cas == 'ligne_invalide': entree['lignes'][1]['credit'] = 'nan'
    entries = [entree, entree] if cas == 'doublon' else [entree]
    monkeypatch.setattr('blueprints.ecritures.call_ai', lambda *args: json.dumps({'ecritures': entries}))
    avant = etat(db)
    comptable_client.post('/ecritures/generer', data={'model': 'modele-fictif'})
    assert etat(db) == avant


def test_approbation_facture_independante_et_ia_soumise_aux_memes_invariants(app, db, comptable_client, monkeypatch, tmp_path):
    from blueprints import exportation
    monkeypatch.setattr(exportation, 'ARCHIVES_DIR', str(tmp_path / 'exports'))
    from tests.test_exports_comptables import references
    fid = _seed_facture(app, db)
    monkeypatch.setattr('blueprints.ecritures.call_ai', lambda *args: json.dumps({'facture_id': fid, 'lignes': _two_lines(fid)}))
    comptable_client.post('/ecritures/generer', data={'model': 'modele-fictif'})
    ids = [r[0] for r in db.execute('SELECT id FROM ecritures_comptables')]
    assert len(ids) == 2
    assert exporter(comptable_client, ids).status_code == 302
    comptable_client.post('/ecritures/valider', data={'ecriture_ids': ids, **references(comptable_client)})
    assert exporter(comptable_client, ids).status_code == 200
    assert db.execute('SELECT approbation FROM factures WHERE id=?', (fid,)).fetchone()[0] == 'en_attente'


def test_reliquat_historique_archive_exclu_du_dashboard(piece, db, comptable_client, app):
    from flask import template_rendered
    fid, ids = piece
    retirer_schema(db)
    db.execute("UPDATE ecritures_comptables SET statut='exportee' WHERE id=?", (ids[0],)); db.commit()
    MIGRATION.upgrade(db); db.commit()
    comptable_client.post(f'/factures/{fid}/archiver', data={'motif': 'Classement historique'})
    rendus = []
    def capturer(sender, template, context, **extra):
        rendus.append(context)
    with template_rendered.connected_to(capturer, app):
        assert comptable_client.get('/dashboard_comptable').status_code == 200
    assert rendus[-1]['nb_ecritures_brouillon'] == 0
    assert rendus[-1]['nb_ecritures_a_exporter'] == 0
