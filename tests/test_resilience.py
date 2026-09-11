"""B4 : restauration sur données fictives, preuves exactes et cas hostiles."""
from contextlib import closing
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import time
import zipfile

import pytest

import database
import resilience as r
from tests.test_fiches_versions import fiche_complete, client_role, signer, validation
from tests.test_exports_comptables import piece, exporter

PHRASE = 'phrase fictive de sauvegarde 2026'
CLE = 'test-secret-key-for-pytest'


def contenu_base(chemin):
    with closing(r.ouvrir_lecture(chemin)) as conn:
        tables = [n for n, in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {n: conn.execute(f'SELECT * FROM "{n}" ORDER BY rowid').fetchall() for n in tables}


@pytest.fixture
def installation(app, db, sample_users, fiche_complete, piece, tmp_path):
    """Un dossier autonome, toutes les catégories et de vrais circuits HTTP."""
    source = tmp_path / 'source'
    source.mkdir()
    for dossier in r.REPERTOIRES:
        (source / dossier).mkdir()
    (source / 'documents/subventions').mkdir()
    fichiers = {
        'documents/identite.pdf': b'Piece identite fictive',
        'documents/contrat.pdf': b'Contrat signe fictif',
        'documents/absence.pdf': b'Justificatif fictif',
        'documents/subventions/dossier.pdf': b'Dossier fictif',
        'documents/subventions/element.pdf': b'Annexe fictive',
        'modeles_contrats/modele.docx': b'Modele fictif',
        'contrats_generes/contrat.docx': b'Contrat genere fictif',
        'exports/ancien.txt': b'Export historique exact',
        'documents/orphelin.txt': b'A conserver sans suppression automatique',
    }
    from reportlab.pdfgen.canvas import Canvas
    buffer = io.BytesIO()
    canvas = Canvas(buffer)
    canvas.drawString(40, 750, 'Facture fictive B4')
    canvas.save()
    fichiers['factures/facture.pdf'] = buffer.getvalue()
    for nom, contenu in fichiers.items():
        (source / nom).write_bytes(contenu)
    uid, did = fiche_complete, sample_users['directeur_id']
    doc = db.execute("INSERT INTO documents_salaries(user_id,type_document,fichier_path,fichier_nom) "
                     "VALUES (?, 'identite', 'identite.pdf', 'identite.pdf')", (uid,)).lastrowid
    db.execute("UPDATE contrats SET fichier_path='contrat.pdf', fichier_nom='contrat.pdf' WHERE user_id=?", (uid,))
    aid = db.execute("INSERT INTO absences(user_id,motif,date_debut,date_fin,jours_ouvres,justificatif_path,justificatif_nom,saisi_par) "
                     "VALUES (?, 'Maladie', '2026-09-10','2026-09-10',1,'absence.pdf','absence.pdf',?)", (uid,did)).lastrowid
    db.execute("INSERT INTO demandes_recup(user_id,date_debut,date_fin,nb_jours,nb_heures) "
               "VALUES (?, '2026-09-18','2026-09-18',1,7)", (uid,))
    sid = db.execute("INSERT INTO subventions(nom,justificatif_path) VALUES ('Test','dossier.pdf')").lastrowid
    db.execute("INSERT INTO subventions_sous_elements(subvention_id,nom,document_path) VALUES (?,'Test','element.pdf')", (sid,))
    db.execute("INSERT INTO modeles_contrats(nom,fichier_path,fichier_nom) VALUES ('Test','modele.docx','modele.docx')")
    db.execute("INSERT INTO contrats_generes(user_id,fichier_path,fichier_nom) VALUES (?,'contrat.docx','contrat.docx')", (uid,))
    db.execute("INSERT INTO archives_export(nom_fichier,fichier_path,created_by) VALUES ('ancien.txt',?,?)",
               (str(source / 'exports/ancien.txt'), did))
    fid, ids = piece
    db.execute("UPDATE factures SET fichier_path=?,fichier_nom='facture.pdf' WHERE id=?", (str(source / 'factures/facture.pdf'), fid))
    db.commit()
    with app.app_context():
        from utils import save_setting
        save_setting('smtp_password', 'smtp-SECRET-FICTIF')
        save_setting('smtp_enabled', '0')
        save_setting('openai_api_key', 'api-SECRET-FICTIF')
        save_setting('nom_structure', 'Centre de test B4')
    direction = client_role(app, sample_users, 'directeur')
    from tests.test_coherence_rh import traiter
    assert traiter(direction, uid).status_code == 200
    assert db.execute('SELECT traite FROM prepa_paie_statut WHERE user_id=?', (uid,)).fetchone()[0] == 1
    for role in ('salarie', 'responsable', 'directeur'):
        signer(client_role(app, sample_users, role), uid)
    assert validation(uid)['bloque']
    fichier_export = exporter(direction, ids)
    assert fichier_export.status_code == 200
    archive_id = db.execute('SELECT id FROM archives_export WHERE preuve_version=1').fetchone()[0]
    pdf = direction.get(f'/export_pdf_mensuel?user_id={uid}&annee=2026&mois=8')
    assert pdf.status_code == 200
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf.data)) as lecture:
        texte_pdf = '\n'.join(p.extract_text() for p in lecture.pages)
    r.copier_sqlite(database.DATABASE, source / 'cspilot.db')
    (source / '.env').write_text("SECRET_KEY='cle_fichier_differente_du_processus'\nAPP_TIMEZONE='UTC'\n")
    return {'source': source, 'fichiers': fichiers, 'uid': uid, 'doc': doc, 'absence': aid, 'facture': fid,
            'archive': archive_id, 'export': fichier_export.data, 'pdf': texte_pdf}


@pytest.fixture
def sauvegarde(installation, tmp_path):
    archive = tmp_path / 'test.cspbackup'
    resultat = r.sauvegarder(installation['source'], archive, PHRASE, arret_confirme=True, secret_key=CLE)
    assert resultat['ok'] and resultat['diagnostic']['ok'], resultat
    assert resultat['diagnostic']['orphelins'] == ['documents/orphelin.txt']
    assert resultat['diagnostic']['exports_verifies'] == 1
    return archive


def test_t1_t2_t5_restauration_vierge_et_application(installation, sauvegarde, tmp_path):
    source, dest = installation['source'], tmp_path / 'restauree'
    avant = contenu_base(source / 'cspilot.db')
    resultat = r.restaurer(sauvegarde, dest, PHRASE)
    assert resultat['ok'], resultat
    assert contenu_base(dest / 'cspilot.db') == avant
    for nom, contenu in installation['fichiers'].items():
        assert (dest / nom).read_bytes() == contenu
    assert stat.S_IMODE(sauvegarde.stat().st_mode) == 0o600
    assert stat.S_IMODE((dest / '.env').stat().st_mode) == 0o600
    assert CLE.encode() not in sauvegarde.read_bytes()
    # Supprimer l'accès à la source : aucun téléchargement ne doit en dépendre.
    source.rename(tmp_path / 'source-indisponible')
    urls = [f"/infos_salaries/telecharger_document/{installation['doc']}",
            f"/absences/justificatif/{installation['absence']}",
            f"/factures/{installation['facture']}/telecharger", '/exportation/archives/1/telecharger']
    programme = '''import sys, json, re, hashlib, io
def sans_reseau(event, args):
    if event == 'socket.connect': raise RuntimeError('Réseau interdit en restauration de test')
sys.addaudithook(sans_reseau)
import database
database.preparer_demarrage()
from app import app
from resilience import verifier_parametres
with app.app_context():
    conn=database.get_db(); verifier_parametres(conn, app.secret_key); conn.close()
client=app.test_client()
page=client.get('/login')
csrf=re.search(r'name="csrf_token" value="([^"]+)"',page.text).group(1)
login=client.post('/login',data={'login':'admin','password':'Admin1234','csrf_token':csrf})
assert login.status_code == 302 and '/login' not in login.location
urls=json.loads(sys.argv[1]); sorties=[]
for url in urls:
    resp=client.get(url); assert resp.status_code == 200, (url, resp.status_code)
    sorties.append(hashlib.sha256(resp.data).hexdigest())
page=client.get('/exportation'); csrf=re.search(r'name="csrf_token" value="([^"]+)"',page.text).group(1)
resp=client.post('/exportation/archives/'+sys.argv[2]+'/telecharger',data={'confirmer':'1','csrf_token':csrf})
assert resp.status_code==200
pdf=client.get('/export_pdf_mensuel?annee=2026&mois=8&user_id='+sys.argv[3]); assert pdf.status_code==200
import pdfplumber
with pdfplumber.open(io.BytesIO(pdf.data)) as lecture: texte='\\n'.join(p.extract_text() for p in lecture.pages)
print(json.dumps({'fichiers':sorties,'export':hashlib.sha256(resp.data).hexdigest(),'pdf':texte}))
'''
    env = {k: v for k, v in os.environ.items() if k != 'SECRET_KEY'}
    env.update(CSPILOT_DATA_DIR=str(dest), APP_TIMEZONE='UTC')
    debut_controles = time.monotonic()
    demarrage = subprocess.run([sys.executable, '-c', programme, json.dumps(urls), str(installation['archive']), str(installation['uid'])],
                               env=env, capture_output=True, text=True, timeout=40)
    assert demarrage.returncode == 0, demarrage.stderr
    preuves = json.loads(demarrage.stdout.strip().splitlines()[-1])
    assert preuves['export'] == hashlib.sha256(installation['export']).hexdigest()
    assert preuves['pdf'] == installation['pdf']
    assert preuves['fichiers'] == [hashlib.sha256(installation['fichiers'][p]).hexdigest() for p in
                                   ('documents/identite.pdf', 'documents/absence.pdf', 'factures/facture.pdf', 'exports/ancien.txt')]
    print(f"Restauration fictive : {resultat['secondes']} s ; "
          f"démarrage/auth/documents/PDF/export : {time.monotonic() - debut_controles:.3f} s ; "
          f"archive {sauvegarde.stat().st_size} octets ; DB { (dest / 'cspilot.db').stat().st_size} octets")


def test_t3_nouvelle_cle_rechiffrement_atomique(installation, sauvegarde, tmp_path):
    dest = tmp_path / 'nouvelle-cle'
    nouvelle = 'nouvelle-cle-fictive-pour-test'
    resultat = r.restaurer(sauvegarde, dest, PHRASE, nouvelle_cle=nouvelle)
    assert resultat['ok'] and resultat['rechiffrement']
    assert not r.diagnostiquer(dest, CLE)['ok']
    assert r.diagnostiquer(dest, nouvelle)['ok']
    with closing(r.ouvrir_lecture(dest / 'cspilot.db')) as conn:
        valeur = conn.execute("SELECT value FROM app_settings WHERE key='smtp_password'").fetchone()[0]
        assert r.fernet_pour(nouvelle).decrypt(valeur.encode()) == b'smtp-SECRET-FICTIF'
    avant, apres = contenu_base(installation['source'] / 'cspilot.db'), contenu_base(dest / 'cspilot.db')
    assert avant.pop('app_settings') != apres.pop('app_settings')
    assert avant == apres
    # Un service gardant une autre clé dans son environnement doit refuser de
    # démarrer, pas masquer les paramètres indéchiffrables.
    resultat = subprocess.run([sys.executable, 'app.py'], env={**os.environ,
        'CSPILOT_DATA_DIR': str(dest), 'SECRET_KEY': 'cle-fictive-incorrecte-du-service'},
        capture_output=True, text=True, timeout=30)
    assert resultat.returncode != 0
    assert 'indéchiffrables' in resultat.stderr
    assert 'cle-fictive-incorrecte-du-service' not in resultat.stderr


def test_t4_diagnostic_manquant_et_export_altere(installation):
    source = installation['source']
    (source / 'documents/identite.pdf').unlink()
    diagnostic = r.diagnostiquer(source, CLE)
    assert not diagnostic['ok']
    assert {'table': 'documents_salaries', 'id': installation['doc'], 'colonne': 'fichier_path'} in diagnostic['references_absentes']
    # Simulation d'une corruption physique/logique hors application.
    with sqlite3.connect(source / 'cspilot.db') as conn:
        for nom, in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='archives_export'").fetchall():
            conn.execute(f'DROP TRIGGER "{nom}"')
        conn.execute("UPDATE archives_export SET contenu=X'00' WHERE preuve_version=1")
    diagnostic = r.diagnostiquer(source, CLE)
    assert any('archives_export' in e for e in diagnostic['erreurs'])


def test_j_moins_3_ne_depend_pas_des_nouvelles_donnees(installation, sauvegarde, tmp_path):
    source = installation['source']
    avant = contenu_base(source / 'cspilot.db')
    (source / 'documents/identite.pdf').unlink()
    (source / 'documents/nouveau.pdf').write_bytes(b'Post J-3')
    with sqlite3.connect(source / 'cspilot.db') as conn:
        conn.execute("UPDATE documents_salaries SET fichier_path='nouveau.pdf'")
    dest = tmp_path / 'j-3'
    assert r.restaurer(sauvegarde, dest, PHRASE)['ok']
    assert contenu_base(dest / 'cspilot.db') == avant
    assert (dest / 'documents/identite.pdf').is_file()
    assert not (dest / 'documents/nouveau.pdf').exists()


@pytest.mark.parametrize('cause', ['phrase', 'alteration', 'destination'])
def test_refus_sans_ecrasement(sauvegarde, tmp_path, cause):
    dest = tmp_path / 'destination'
    phrase = PHRASE
    if cause == 'phrase':
        phrase = 'mauvaise phrase de sauvegarde'
    if cause == 'alteration':
        contenu = bytearray(sauvegarde.read_bytes()); contenu[-30] ^= 1
        sauvegarde.write_bytes(contenu)
    if cause == 'destination':
        dest.mkdir(); (dest / 'temoin').write_text('Préexistant')
    with pytest.raises(r.ErreurResilience):
        r.restaurer(sauvegarde, dest, phrase)
    if cause == 'destination':
        assert (dest / 'temoin').read_text() == 'Préexistant'
    else:
        assert not dest.exists()
    assert not list(tmp_path.glob('.cspilot-restore-*'))


@pytest.mark.parametrize('cause', ['cle', 'arret', 'lien', 'manquant'])
def test_sauvegarde_incomplete_jamais_annoncee_reussie(installation, tmp_path, cause):
    source, dest = installation['source'], tmp_path / 'refuse.cspbackup'
    if cause == 'lien':
        (source / 'documents/lien').symlink_to(tmp_path / 'exterieur')
    if cause == 'manquant':
        (source / 'factures/facture.pdf').unlink()
    with pytest.raises(r.ErreurResilience):
        r.sauvegarder(source, dest, PHRASE, arret_confirme=cause != 'arret',
                      secret_key='cle-incorrecte' if cause == 'cle' else CLE)
    assert not dest.exists()


def test_backup_api_capture_wal(tmp_path):
    source, dest = tmp_path / 'wal.db', tmp_path / 'copie.db'
    with sqlite3.connect(source) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA wal_autocheckpoint=0')
        conn.execute('CREATE TABLE exemple(valeur TEXT)'); conn.commit()
        conn.execute("INSERT INTO exemple VALUES ('Dans le WAL')"); conn.commit()
        assert Path(str(source) + '-wal').stat().st_size > 0
        r.copier_sqlite(source, dest)
        with closing(r.ouvrir_lecture(dest)) as copie:
            assert copie.execute('SELECT valeur FROM exemple').fetchone()[0] == 'Dans le WAL'


def test_cli_erreur_ne_divulgue_pas_secret(tmp_path, capsys):
    from resilience_cli import main
    secret = tmp_path / 'phrase'
    secret.write_text('secret-ne-doit-pas-sortir'); secret.chmod(0o600)
    assert main(['restaurer','--archive',str(tmp_path / 'absente'), '--destination', str(tmp_path / 'neuf'),
                 '--phrase-fichier',str(secret)]) == 2
    sortie = capsys.readouterr().out
    assert 'secret-ne-doit-pas-sortir' not in sortie
    assert str(tmp_path) not in sortie


def modifier_archive(sauvegarde, tmp_path, transformation):
    """Archive authentifiée mais incohérente : la clé seule ne vaut pas validation."""
    clair = tmp_path / 'test-clair.zip'
    r._dechiffrer(sauvegarde, clair, PHRASE)
    with zipfile.ZipFile(clair) as entree:
        fichiers = {n: entree.read(n) for n in entree.namelist()}
    manifeste = json.loads(fichiers.pop('manifest.json'))
    transformation(fichiers, manifeste)
    modifie = tmp_path / 'test-modifie.zip'
    with zipfile.ZipFile(modifie, 'w') as sortie:
        for nom, contenu in fichiers.items():
            sortie.writestr(nom, contenu)
        sortie.writestr('manifest.json', json.dumps(manifeste))
    final = tmp_path / 'modifie.cspbackup'
    r._chiffrer(modifie, final, PHRASE)
    return final


@pytest.mark.parametrize('cause', ['document_retire', 'hash', 'traversee', 'reference_exterieure'])
def test_archive_authentifiee_incoherente_refusee(sauvegarde, tmp_path, cause):
    def transformer(fichiers, manifeste):
        if cause == 'document_retire':
            del fichiers['documents/identite.pdf']
            del manifeste['fichiers']['documents/identite.pdf']
        elif cause == 'hash':
            fichiers['documents/identite.pdf'] = b'Contenu different'
        else:
            if cause == 'traversee':
                nom, contenu = '../sortie.txt', b'Hors repertoire'
            else:
                nom = r.FICHIER_CHEMINS
                correspondances = json.loads(fichiers[nom])
                correspondances[next(iter(correspondances))] = 'documents/../../sortie.txt'
                contenu = json.dumps(correspondances).encode()
            fichiers[nom] = contenu
            manifeste['fichiers'][nom] = {'sha256': hashlib.sha256(contenu).hexdigest(), 'taille': len(contenu)}
    archive = modifier_archive(sauvegarde, tmp_path, transformer)
    with pytest.raises(r.ErreurResilience):
        r.restaurer(archive, tmp_path / 'refuse', PHRASE)
    assert not (tmp_path / 'refuse').exists()
    assert not (tmp_path / 'sortie.txt').exists()


def test_config_priorite_environnement_et_cle_absente(installation, monkeypatch, tmp_path):
    monkeypatch.setenv('SECRET_KEY', CLE)
    source = installation['source']
    # Le .env fictif contient volontairement une autre clé ; comme Flask,
    # la sauvegarde doit employer l'environnement effectif.
    assert r._configuration(source, None)['SECRET_KEY'] == CLE
    monkeypatch.delenv('SECRET_KEY')
    (source / '.env').unlink()
    with pytest.raises(r.ErreurResilience, match='absente'):
        r.sauvegarder(source, tmp_path / 'sans-cle.cspbackup', PHRASE, arret_confirme=True)


def test_rechiffrement_refuse_partiel(installation):
    source = installation['source']
    with sqlite3.connect(source / 'cspilot.db') as conn:
        conn.execute("UPDATE app_settings SET value='illisible' WHERE key='openai_api_key'")
        conn.commit()
        avant = conn.execute('SELECT * FROM app_settings ORDER BY id').fetchall()
        with pytest.raises(r.ErreurResilience):
            r.rechiffrer_parametres(conn, CLE, 'nouvelle-cle-fictive')
        assert conn.execute('SELECT * FROM app_settings ORDER BY id').fetchall() == avant


def test_source_change_pendant_copie_refusee(installation, tmp_path, monkeypatch):
    original = r._inventaire
    appels = {'nb': 0}
    def inventaire(dossier):
        appels['nb'] += 1
        if appels['nb'] == 3:
            (dossier / 'documents/identite.pdf').write_bytes(b'Changement concurrent')
        return original(dossier)
    monkeypatch.setattr(r, '_inventaire', inventaire)
    with pytest.raises(r.ErreurResilience, match='changé'):
        r.sauvegarder(installation['source'], tmp_path / 'course.cspbackup', PHRASE,
                      arret_confirme=True, secret_key=CLE)
    assert not (tmp_path / 'course.cspbackup').exists()


def test_restaurer_puis_sauvegarder_a_nouveau(installation, sauvegarde, tmp_path):
    dest = tmp_path / 'premiere'
    r.restaurer(sauvegarde, dest, PHRASE)
    deuxieme = tmp_path / 'deuxieme.cspbackup'
    r.sauvegarder(dest, deuxieme, PHRASE, arret_confirme=True, secret_key=CLE)
    final = tmp_path / 'final'
    assert r.restaurer(deuxieme, final, PHRASE)['ok']
    assert contenu_base(final / 'cspilot.db') == contenu_base(installation['source'] / 'cspilot.db')


def test_volume_non_restaurable_refuse_avant_publication(installation, tmp_path, monkeypatch):
    monkeypatch.setattr(r, 'MAX_ARCHIVE', 10)
    with pytest.raises(r.ErreurResilience, match='limite'):
        r.sauvegarder(installation['source'], tmp_path / 'volume.cspbackup', PHRASE,
                      arret_confirme=True, secret_key=CLE)
    assert not (tmp_path / 'volume.cspbackup').exists()


@pytest.mark.parametrize('table', ['fiches_evenements', 'cse_membres', 'budgets', 'tresorerie_comptes'])
def test_table_absente_empeche_faux_succes(installation, tmp_path, table):
    source = installation['source']
    with sqlite3.connect(source / 'cspilot.db') as conn:
        conn.execute(f'DROP TABLE "{table}"')
    diagnostic = r.diagnostiquer(source, CLE)
    assert not diagnostic['ok']
    assert diagnostic['tables_absentes'] == [table]
    with pytest.raises(r.ErreurResilience):
        r.sauvegarder(source, tmp_path / 'incomplete.cspbackup', PHRASE, arret_confirme=True, secret_key=CLE)
    assert not (tmp_path / 'incomplete.cspbackup').exists()


@pytest.mark.parametrize('table', ['cse_membres', 'budgets', 'tresorerie_comptes'])
def test_restauration_refuse_table_absente_meme_archive_authentifiee(sauvegarde, tmp_path, table):
    def retirer_table(fichiers, manifeste):
        # Représente une archive produite par l'ancien contrôle incomplet :
        # chiffrement et empreinte DB corrects, mais une table métier perdue.
        copie = tmp_path / 'incomplete.db'
        copie.write_bytes(fichiers['cspilot.db'])
        with closing(sqlite3.connect(copie)) as conn, conn:
            conn.execute(f'DROP TABLE "{table}"')
        contenu = copie.read_bytes()
        fichiers['cspilot.db'] = contenu
        manifeste['fichiers']['cspilot.db'] = {'sha256': hashlib.sha256(contenu).hexdigest(), 'taille': len(contenu)}
    archive = modifier_archive(sauvegarde, tmp_path, retirer_table)
    destination = tmp_path / 'incomplete'
    with pytest.raises(r.ErreurResilience, match='Restauration refusée'):
        r.restaurer(archive, destination, PHRASE)
    assert not destination.exists()


def test_ancienne_sauvegarde_ne_requiert_pas_futurs_modules(tmp_path, monkeypatch):
    import migration_manager as migrations
    source = tmp_path / 'ancienne'
    source.mkdir()
    monkeypatch.setattr(database, 'DATABASE', str(source / 'cspilot.db'))
    for fichier in migrations.lister_fichiers_migrations():
        if fichier['version'] > '0040':
            break
        assert migrations.appliquer_migration(fichier['version'])[0]
    with closing(sqlite3.connect(database.DATABASE)) as conn, conn:
        # Ce journal n'existait pas encore dans l'ancienne installation.
        conn.execute('DROP TABLE schema_migrations_tentatives')
    avant = contenu_base(source / 'cspilot.db')
    archive = tmp_path / 'ancienne.cspbackup'
    r.sauvegarder(source, archive, PHRASE, arret_confirme=True, secret_key=CLE)
    destination = tmp_path / 'restauree'
    resultat = r.restaurer(archive, destination, PHRASE)
    assert resultat['diagnostic']['donnees_valides']
    assert resultat['diagnostic']['tables_absentes'] == []
    assert resultat['diagnostic']['migrations']['en_attente']
    assert not resultat['ok']  # Mise à niveau explicite nécessaire avant service.
    assert contenu_base(destination / 'cspilot.db') == avant
