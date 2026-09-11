"""B10 : transactions réelles, reprise et convergence (bases fictives)."""
import sqlite3
import types

import pytest

import database
import migration_manager as migrations


@pytest.fixture
def catalogue_fictif(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DATABASE', str(tmp_path / 'migration.db'))
    dossier = tmp_path / 'migrations'
    dossier.mkdir()
    (dossier / '9000_test.py').write_text('# Migration fictive\n')
    monkeypatch.setattr(migrations, 'MIGRATIONS_DIR', str(dossier))
    return dossier


def test_echec_commit_interne_et_reprise(catalogue_fictif, monkeypatch):
    cause = {'echec': True}

    def upgrade(conn):
        conn.execute('CREATE TABLE exemple (id INTEGER PRIMARY KEY, valeur INTEGER)')
        conn.execute('INSERT INTO exemple VALUES (1, 42)')
        conn.commit()  # Les anciennes migrations livrées font réellement ceci.
        if cause['echec']:
            raise RuntimeError('un-secret-qui-ne-doit-pas-sortir')

    monkeypatch.setattr(migrations, '_load_migration_module', lambda _: types.SimpleNamespace(
        NOM='Exemple', DESCRIPTION='Test', upgrade=upgrade))
    ok, message = migrations.appliquer_migration('9000')
    assert not ok
    assert 'un-secret' not in message
    statut = migrations.get_statut_complet()
    assert not statut['a_jour']
    assert statut['nb_appliquees'] == 0
    assert statut['nb_en_attente'] == 1
    with sqlite3.connect(database.DATABASE) as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='exemple'").fetchone()
    cause['echec'] = False
    assert migrations.appliquer_migration('9000')[0]
    assert migrations.get_statut_complet()['a_jour']
    with sqlite3.connect(database.DATABASE) as conn:
        assert conn.execute('SELECT * FROM exemple').fetchall() == [(1, 42)]
        assert conn.execute('SELECT statut FROM schema_migrations').fetchall() == [('ok',)]
        assert conn.execute('SELECT statut FROM schema_migrations_tentatives ORDER BY id').fetchall() == [
            ('erreur',), ('ok',)]


def test_erreur_sans_fichier_jamais_a_jour(catalogue_fictif):
    migrations._ensure_migration_table()
    with sqlite3.connect(database.DATABASE) as conn:
        conn.execute("INSERT INTO schema_migrations(version, nom, statut) VALUES ('8999', 'Ancienne', 'erreur')")
    (catalogue_fictif / '9000_test.py').unlink()
    assert not migrations.get_statut_complet()['a_jour']


def test_fichier_migration_invalide_visible_et_non_applique(catalogue_fictif):
    (catalogue_fictif / '9000_test.py').write_text('def upgrade(\n')
    assert not migrations.get_statut_complet()['a_jour']
    assert 'illisible' in migrations.get_migrations_en_attente()[0]['description']
    assert not migrations.appliquer_migration('9000')[0]
    assert migrations.get_statut_complet()['erreurs'][0]['version'] == '9000'


def test_init_repetee_ne_masque_pas_erreur(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DATABASE', str(tmp_path / 'fresh.db'))
    database.init_db()
    with sqlite3.connect(database.DATABASE) as conn:
        conn.execute("UPDATE schema_migrations SET statut='erreur' WHERE version='0070'")
    database.init_db()
    assert not migrations.get_statut_complet()['a_jour']


def test_interruption_processus_reprise(catalogue_fictif):
    """os._exit ne laisse aucun finally Python s'exécuter : test du vrai WAL."""
    import os
    import subprocess
    import sys
    fichier = catalogue_fictif / '9000_test.py'
    fichier.write_text("import os\nNOM='Interruption'\ndef upgrade(conn):\n"
                       "    conn.execute('CREATE TABLE exemple(id INTEGER PRIMARY KEY)')\n"
                       "    conn.execute('INSERT INTO exemple VALUES (1)')\n"
                       "    conn.commit()\n    os._exit(73)\n")
    programme = ("import sys, database, migration_manager as m; "
                 "database.DATABASE=sys.argv[1]; m.MIGRATIONS_DIR=sys.argv[2]; "
                 "m.appliquer_migration('9000')")
    result = subprocess.run([sys.executable, '-c', programme, database.DATABASE, str(catalogue_fictif)],
                            env={**os.environ, 'CSPILOT_DATA_DIR': str(catalogue_fictif.parent)},
                            capture_output=True, timeout=30)
    assert result.returncode == 73
    assert not migrations.get_statut_complet()['a_jour']
    with sqlite3.connect(database.DATABASE) as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='exemple'").fetchone()
        assert not conn.execute('SELECT 1 FROM schema_migrations').fetchone()
    fichier.write_text("NOM='Reprise'\ndef upgrade(conn):\n"
                       "    conn.execute('CREATE TABLE exemple(id INTEGER PRIMARY KEY)')\n"
                       "    conn.execute('INSERT INTO exemple VALUES (1)')\n")
    assert migrations.appliquer_migration('9000')[0]


def test_ancien_echec_partiel_exige_diagnostic(catalogue_fictif, monkeypatch):
    migrations._ensure_migration_table()
    with sqlite3.connect(database.DATABASE) as conn:
        conn.execute("INSERT INTO schema_migrations(version, nom, statut) VALUES ('9000', 'Ancienne', 'erreur')")
        conn.execute('CREATE TABLE exemple(id INTEGER PRIMARY KEY)')
    def upgrade(conn):
        conn.execute('CREATE TABLE IF NOT EXISTS exemple(id INTEGER PRIMARY KEY)')
        conn.execute('INSERT OR IGNORE INTO exemple VALUES (1)')
    monkeypatch.setattr(migrations, '_load_migration_module', lambda _: types.SimpleNamespace(NOM='Reprise', upgrade=upgrade))
    assert not migrations.appliquer_migration('9000')[0]
    assert migrations.appliquer_migration('9000', reprise_historique=True)[0]
    with sqlite3.connect(database.DATABASE) as conn:
        assert conn.execute('SELECT statut FROM schema_migrations_tentatives ORDER BY id').fetchall() == [('erreur',), ('ok',)]


def test_migrations_concurrentes_une_seule_execution(catalogue_fictif, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    def upgrade(conn):
        conn.execute('CREATE TABLE exemple(id INTEGER PRIMARY KEY)')
        conn.execute('INSERT INTO exemple VALUES (1)')
    monkeypatch.setattr(migrations, '_load_migration_module', lambda _: types.SimpleNamespace(NOM='Concurrente', upgrade=upgrade))
    migrations._ensure_migration_table()
    with ThreadPoolExecutor(max_workers=2) as pool:
        resultats = list(pool.map(lambda _: migrations.appliquer_migration('9000'), range(2)))
    assert sum(ok for ok, _ in resultats) == 1
    with sqlite3.connect(database.DATABASE) as conn:
        assert conn.execute('SELECT COUNT(*) FROM exemple').fetchone()[0] == 1
        assert conn.execute('SELECT COUNT(*) FROM schema_migrations_tentatives').fetchone()[0] == 1


def test_demarrage_ne_repare_pas_echec(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DATABASE', str(tmp_path / 'start.db'))
    database.init_db()
    with sqlite3.connect(database.DATABASE) as conn:
        conn.execute("UPDATE schema_migrations SET statut='erreur' WHERE version='0071'")
        conn.execute('DROP TABLE plan_comptable_general')
    with pytest.raises(RuntimeError, match='arrêtée'):
        database.preparer_demarrage()
    with sqlite3.connect(database.DATABASE) as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='plan_comptable_general'").fetchone()


@pytest.mark.parametrize('version', ['0000', '9999'])
def test_version_inconnue_empeche_statut_et_demarrage(tmp_path, monkeypatch, version):
    monkeypatch.setattr(database, 'DATABASE', str(tmp_path / 'future.db'))
    database.init_db()
    with sqlite3.connect(database.DATABASE) as conn:
        conn.execute("INSERT INTO schema_migrations(version, nom, statut) VALUES (?, 'Autre code', 'ok')", (version,))
        conn.commit()
        avant = list(conn.iterdump())
    statut = migrations.get_statut_complet()
    assert statut['nb_en_attente'] == 0 and not statut['erreurs']
    assert not statut['a_jour']
    assert [m['version'] for m in statut['inconnues']] == [version]
    with pytest.raises(RuntimeError, match='inconnues'):
        database.preparer_demarrage()
    with sqlite3.connect(database.DATABASE) as conn:
        assert list(conn.iterdump()) == avant


def test_migration_refuse_base_autre_code_meme_reprise_historique(catalogue_fictif, monkeypatch):
    migrations._ensure_migration_table()
    with sqlite3.connect(database.DATABASE) as conn:
        conn.execute("INSERT INTO schema_migrations(version, nom, statut) VALUES ('9999', 'Autre code', 'ok')")
    def upgrade(conn):
        conn.execute('CREATE TABLE modification_interdite(id INTEGER)')
    monkeypatch.setattr(migrations, '_load_migration_module', lambda _: types.SimpleNamespace(NOM='Test', upgrade=upgrade))
    for reprise in (False, True):
        ok, message = migrations.appliquer_migration('9000', reprise_historique=reprise)
        assert not ok and 'inconnues' in message
    with sqlite3.connect(database.DATABASE) as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='modification_interdite'").fetchone()
        assert conn.execute('SELECT version, statut FROM schema_migrations').fetchall() == [('9999', 'ok')]
        assert not conn.execute('SELECT 1 FROM schema_migrations_tentatives').fetchone()


def test_admin_affiche_versions_inconnues(app, admin_client, db):
    db.execute("INSERT INTO schema_migrations(version, nom, statut) VALUES ('9999', 'Autre code', 'ok')")
    db.commit()
    reponse = admin_client.get('/administration')
    assert reponse.status_code == 200
    assert 'Migration 9999 : inconnue de ce code.' in reponse.text
    assert 'La base de donnees est a jour.' not in reponse.text
    assert '0 mise(s) a jour disponible(s).' not in reponse.text


@pytest.mark.parametrize('fin_transaction', ['COMMIT', 'ROLLBACK'])
def test_transaction_sql_ne_contourne_pas_atomicite(catalogue_fictif, monkeypatch, fin_transaction):
    def upgrade(conn):
        conn.execute('CREATE TABLE exemple(id INTEGER)')
        conn.execute(fin_transaction)
    monkeypatch.setattr(migrations, '_load_migration_module', lambda _: types.SimpleNamespace(NOM='Test', upgrade=upgrade))
    assert not migrations.appliquer_migration('9000')[0]
    with sqlite3.connect(database.DATABASE) as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='exemple'").fetchone()


def test_0071_preserve_base_issue_init_0070_et_triggers(db, sample_users):
    """Prépa paie de l'ancien init_db : traite nullable, triggers dépendants."""
    from schema_resilience import creer_schema
    uid = sample_users['salarie_id']
    db.execute("INSERT INTO prepa_paie_statut(user_id,mois,annee,traite,revision) VALUES (?,9,2026,0,7)", (uid,))
    db.commit()
    # Reproduire exactement la divergence historique de nullabilité.
    ddl = db.execute("SELECT sql FROM sqlite_master WHERE name='prepa_paie_statut'").fetchone()[0]
    colonnes = ','.join(r[1] for r in db.execute('PRAGMA table_info(prepa_paie_statut)'))
    triggers = db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'").fetchall()
    for nom, _ in triggers:
        db.execute(f'DROP TRIGGER "{nom}"')
    db.execute('ALTER TABLE prepa_paie_statut RENAME TO ancien_statut')
    db.execute(ddl.replace('traite INTEGER NOT NULL DEFAULT 0', 'traite INTEGER DEFAULT 0'))
    db.execute(f'INSERT INTO prepa_paie_statut({colonnes}) SELECT {colonnes} FROM ancien_statut')
    db.execute('DROP TABLE ancien_statut')
    for _, sql in triggers:
        db.execute(sql)
    db.commit()
    avant = [tuple(r) for r in db.execute('SELECT * FROM prepa_paie_statut')]
    with db.migration_atomique():
        creer_schema(db)
    assert [tuple(r) for r in db.execute('SELECT * FROM prepa_paie_statut')] == avant
    assert sorted(tuple(r) for r in db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'")) == sorted(tuple(r) for r in triggers)
    assert next(r for r in db.execute('PRAGMA table_info(prepa_paie_statut)') if r[1] == 'traite')[3] == 1


def test_0071_conserve_subvention_et_annexe(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DATABASE', str(tmp_path / 'old.db'))
    for fichier in migrations.lister_fichiers_migrations():
        if fichier['version'] == '0071':
            break
        assert migrations.appliquer_migration(fichier['version'])[0]
    with sqlite3.connect(database.DATABASE) as conn:
        conn.row_factory = sqlite3.Row
        sid = conn.execute("INSERT INTO subventions(nom,action_budget_id) VALUES ('Fictive',NULL)").lastrowid
        conn.execute("INSERT INTO subventions_sous_elements(subvention_id,nom) VALUES (?,'Annexe')", (sid,))
        avant = [dict(r) for r in conn.execute('SELECT * FROM subventions')], [dict(r) for r in conn.execute('SELECT * FROM subventions_sous_elements')]
    assert migrations.appliquer_migration('0071')[0]
    with sqlite3.connect(database.DATABASE) as conn:
        conn.row_factory = sqlite3.Row
        assert ([dict(r) for r in conn.execute('SELECT * FROM subventions')], [dict(r) for r in conn.execute('SELECT * FROM subventions_sous_elements')]) == avant


def test_admin_affiche_echec_visible(app, admin_client, db):
    db.execute("UPDATE schema_migrations SET statut='erreur' WHERE version='0071'")
    db.commit()
    reponse = admin_client.get('/administration')
    assert reponse.status_code == 200
    assert 'Migration 0071 : échec.' in reponse.text
    assert 'La base de donnees est a jour.' not in reponse.text


def schema(conn):
    """Compare types, défauts, nullabilité, PK/FK, index et triggers.

    L'ordre physique des colonnes et les noms autoindex SQLite sont sans effet
    métier ; les contraintes UNIQUE/CHECK sont comparées séparément.
    """
    import re
    resultat = {}
    for typ, nom, sql in conn.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name"):
        if typ != 'table':
            resultat[(typ, nom)] = ' '.join(sql.lower().split())
            continue
        colonnes = sorted(tuple(r[1:]) for r in conn.execute(f'PRAGMA table_info("{nom}")'))
        fk = sorted(tuple(r[2:]) for r in conn.execute(f'PRAGMA foreign_key_list("{nom}")'))
        index = []
        for row in conn.execute(f'PRAGMA index_list("{nom}")'):
            index.append((row[2], row[3], row[4], tuple(
                tuple(x[2:]) for x in conn.execute(f'PRAGMA index_xinfo("{row[1]}")'))))
        # Les CHECK du catalogue sont de profondeur simple (IN peut être imbriqué).
        checks = sorted(re.findall(r'CHECK\s*(\((?:[^()]|\([^()]*\))*\))', sql, re.I))
        resultat[(typ, nom)] = (colonnes, fk, sorted(index), checks)
    return resultat


def test_schema_neuf_identique_ancien_migre(tmp_path, monkeypatch):
    from resilience import TABLES_REQUISES
    monkeypatch.setattr(database, 'DATABASE', str(tmp_path / 'fresh.db'))
    database.init_db()
    assert migrations.get_statut_complet()['a_jour']
    assert {v for v, _ in database.ALL_MIGRATION_VERSIONS} == {
        m['version'] for m in migrations.lister_fichiers_migrations()}
    with sqlite3.connect(database.DATABASE) as conn:
        neuf = schema(conn)
    assert {nom for typ, nom in neuf if typ == 'table'} == {
        table for tables in TABLES_REQUISES.values() for table in tables} | {'schema_migrations'}
    monkeypatch.setattr(database, 'DATABASE', str(tmp_path / 'old.db'))
    # Le schéma 0001 constitue la base historique ; toutes les migrations sont
    # exécutées, sans appeler init_db pour masquer d'éventuelles omissions.
    for fichier in migrations.lister_fichiers_migrations():
        version = fichier['version']
        ok, message = migrations.appliquer_migration(version, 'test')
        assert ok, message
        with sqlite3.connect(database.DATABASE) as conn:
            presentes = {n for n, in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        # Vérifier l'exhaustivité ET la date d'introduction : une ancienne
        # sauvegarde ne doit pas être obligée d'avoir les futurs modules.
        requises = {table for v, tables in TABLES_REQUISES.items() if v <= version for table in tables}
        # Le gestionnaire crée ses journaux avant la première migration.
        assert presentes == requises | {'schema_migrations', 'schema_migrations_tentatives'}, version
    with sqlite3.connect(database.DATABASE) as conn:
        assert schema(conn) == neuf
