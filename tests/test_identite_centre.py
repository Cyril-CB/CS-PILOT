"""Fiche commune : routes réelles et stockage isolé, aucun document du centre."""
from contextlib import closing
import hashlib
import importlib
import io
import re
import sqlite3

import pytest
from werkzeug.security import generate_password_hash

import database
import identite_centre as service
from tests.test_fiches_versions import client_role

URL = '/centre/identite'
VALEURS = {'nom': 'Association de démonstration', 'siren': '000 000 000',
           'siret': '00000000000000', 'ape': '00.00z', 'convention_collective_code': 'TEST'}


@pytest.fixture
def environnement(app, db, sample_users, monkeypatch, tmp_path):
    monkeypatch.setattr(database, 'DATA_DIR', str(tmp_path))
    return sample_users


def revision(db):
    return db.execute('SELECT revision FROM identite_centre WHERE id=1').fetchone()[0]


def modifier(client, db, action='enregistrer', **champs):
    return client.post(URL, data={'action': action, 'revision': revision(db), **champs})


def ajouter_document(client, db, contenu=b'Document synthetique', nom='statuts.txt', **kw):
    return modifier(client, db, 'ajouter_document', libelle_document='Statuts fictifs',
                    document=(io.BytesIO(contenu), nom), **kw)


def document(db):
    return db.execute('SELECT * FROM identite_centre_documents').fetchone()


@pytest.mark.parametrize('role', ['directeur', 'comptable'])
def test_saisie_champs_documents_et_suppression(app, db, environnement, role):
    client = client_role(app, environnement, role)
    assert client.get(URL).status_code == 200
    assert modifier(client, db, **VALEURS).status_code == 302
    fiche = db.execute('SELECT * FROM identite_centre').fetchone()
    assert (fiche['siren'], fiche['siret'], fiche['ape'], fiche['convention_collective_code']) == (
        '000000000', '00000000000000', '0000Z', 'TEST')
    assert modifier(client, db, 'ajouter_champ', libelle='RNA', valeur='W000000000').status_code == 302
    champ = db.execute('SELECT id FROM identite_centre_champs').fetchone()[0]
    assert modifier(client, db, 'modifier_champ', champ_id=champ, libelle='Référence', valeur='=1+1').status_code == 302
    assert db.execute('SELECT valeur FROM identite_centre_champs').fetchone()[0] == '=1+1'
    assert ajouter_document(client, db).status_code == 302
    piece = document(db)
    path = service.chemin_document(piece)
    assert path.read_bytes() == b'Document synthetique'
    assert path.stat().st_mode & 0o777 == 0o600
    lecteur = client_role(app, environnement, 'responsable')
    page = lecteur.get(URL)
    assert '00000000000000' in page.text and '=1+1' in page.text
    assert 'name="action" value="enregistrer"' not in page.text
    telechargement = lecteur.get(f'{URL}/documents/{piece["id"]}')
    assert telechargement.data == b'Document synthetique'
    assert telechargement.headers['Cache-Control'] == 'no-store'
    assert telechargement.headers['X-Content-Type-Options'] == 'nosniff'
    assert 'attachment' in telechargement.headers['Content-Disposition']
    assert modifier(client, db, 'supprimer_champ', champ_id=champ).status_code == 302
    assert modifier(client, db, 'supprimer_document', document_id=piece['id']).status_code == 302
    assert not path.exists() and document(db) is None
    assert not db.execute('SELECT * FROM identite_centre_champs').fetchall()
    assert lecteur.get(f'{URL}/documents/{piece["id"]}').status_code == 404
    assert db.execute('SELECT COUNT(*) FROM identite_centre').fetchone()[0] == 1


@pytest.mark.parametrize('role', ['responsable', 'salarie', 'prestataire', 'anonyme'])
def test_refus_serveur_de_toutes_les_mutations(app, db, environnement, role):
    direction = client_role(app, environnement, 'directeur')
    assert ajouter_document(direction, db).status_code == 302
    assert modifier(direction, db, 'ajouter_champ', libelle='RNA', valeur='fictif').status_code == 302
    piece = document(db)
    if role == 'prestataire':
        db.execute('INSERT INTO users(nom,prenom,login,password,profil) VALUES (?,?,?,?,?)',
                   ('Test', 'Prestataire', 'presta_identite', generate_password_hash('Fictif123'), role))
        db.commit()
        client = app.test_client()
        assert client.post('/login', data={'login':'presta_identite','password':'Fictif123'}).status_code == 302
    elif role == 'anonyme':
        client = app.test_client()
    else:
        client = client_role(app, environnement, role)
    avant = revision(db)
    for action in ('enregistrer', 'ajouter_champ', 'modifier_champ', 'supprimer_champ',
                   'ajouter_document', 'supprimer_document'):
        rep = modifier(client, db, action, nom='Interdit', champ_id=1,
                       document_id=piece['id'], libelle='Interdit', valeur='Interdit')
        assert rep.status_code == (302 if role == 'anonyme' else 403)
    assert revision(db) == avant
    assert db.execute('SELECT libelle FROM identite_centre_champs').fetchone()[0] == 'RNA'
    assert service.chemin_document(piece).read_bytes() == b'Document synthetique'
    attendu = 200 if role == 'responsable' else 302 if role == 'anonyme' else 403
    assert client.get(URL).status_code == attendu
    assert client.get(f'{URL}/documents/{piece["id"]}').status_code == attendu


def test_version_obsolete_et_retrait_du_droit(app, db, environnement):
    client = client_role(app, environnement, 'directeur')
    ancienne = revision(db)
    assert modifier(client, db, **VALEURS).status_code == 302
    rep = client.post(URL, data={'action':'enregistrer', 'revision':ancienne, 'nom':'Écrasement'})
    assert rep.status_code == 409
    # Le refus ne réarme pas silencieusement un formulaire obsolète.
    assert f'name="revision" value="{ancienne}"' in rep.text
    assert db.execute('SELECT nom FROM identite_centre').fetchone()[0] == VALEURS['nom']
    db.execute('UPDATE users SET profil=? WHERE id=?', ('responsable', environnement['directeur_id']))
    db.commit()
    assert modifier(client, db, **VALEURS).status_code == 403
    assert revision(db) == ancienne + 1


@pytest.mark.parametrize('champs', [
    {'siren':'123'}, {'siret':'x'*14}, {'siren':'000000000','siret':'11111111100000'},
    {'ape':'pas-un-code'}, {'nom':'x'*161}, {'convention_collective_code':'x'*51},
    {'nom':'a\x00b'}])
def test_identite_invalide_ne_modifie_rien(app, db, environnement, champs):
    client = client_role(app, environnement, 'directeur')
    rep = modifier(client, db, **{**VALEURS, **champs})
    assert rep.status_code == 400 and revision(db) == 0
    assert db.execute('SELECT nom FROM identite_centre').fetchone()[0] == ''


def test_bornes_champs_et_echappement(app, db, environnement):
    client = client_role(app, environnement, 'directeur')
    assert modifier(client, db, 'ajouter_champ', libelle='x'*81, valeur='v').status_code == 400
    assert modifier(client, db, 'ajouter_champ', libelle='x', valeur='v'*2001).status_code == 400
    assert modifier(client, db, 'ajouter_champ', libelle='RNA', valeur='<script>secret()</script>').status_code == 302
    assert modifier(client, db, 'ajouter_champ', libelle='rna', valeur='doublon').status_code == 400
    assert modifier(client, db, 'ajouter_champ', libelle='Échéance', valeur='premier').status_code == 302
    assert modifier(client, db, 'ajouter_champ', libelle='échéance', valeur='doublon accentué').status_code == 400
    page = client.get(URL)
    assert '<script>secret()' not in page.text and '&lt;script&gt;' in page.text
    db.executemany('''INSERT INTO identite_centre_champs(libelle,libelle_cle,valeur)
                      VALUES (?,?,?)''',
                   [(f'Champ {n}', service.cle_libelle(f'Champ {n}'), '')
                    for n in range(service.MAX_CHAMPS-2)])
    db.commit()
    assert modifier(client, db, 'ajouter_champ', libelle='En trop', valeur='').status_code == 400
    assert db.execute('SELECT COUNT(*) FROM identite_centre_champs').fetchone()[0] == 30


@pytest.mark.parametrize('nom,contenu', [('fichier.exe', b'MZ'), ('faux.pdf', b'pas un PDF'),
    ('../statuts.txt', b'texte'), ('vide.txt', b''), ('grand.txt', b'x'*(5*1024**2+1))])
def test_documents_invalides(app, db, environnement, nom, contenu):
    client = client_role(app, environnement, 'directeur')
    assert ajouter_document(client, db, contenu, nom).status_code == 400
    assert document(db) is None and revision(db) == 0


def test_document_borne_confinement_et_integrite(app, db, environnement, tmp_path):
    client = client_role(app, environnement, 'directeur')
    assert ajouter_document(client, db).status_code == 302
    piece = document(db)
    path = service.chemin_document(piece)
    path.write_bytes(b'altere')
    assert client.get(f'{URL}/documents/{piece["id"]}').status_code == 404
    path.unlink()
    cible = tmp_path / 'hors-module.txt'
    cible.write_bytes(b'Document synthetique')
    path.symlink_to(cible)
    assert client.get(f'{URL}/documents/{piece["id"]}').status_code == 404
    assert modifier(client, db, 'supprimer_document', document_id=piece['id']).status_code == 400
    assert cible.read_bytes() == b'Document synthetique'
    db.execute('UPDATE identite_centre_documents SET fichier_path=?', ('propositions/'+'a'*32+'.txt',))
    db.commit()
    assert client.get(f'{URL}/documents/{piece["id"]}').status_code == 404


def test_echec_apres_ecriture_nettoie_et_annule(app, db, environnement, monkeypatch, tmp_path):
    client = client_role(app, environnement, 'directeur')
    original = service.ajouter_document
    def interrompre(*args):
        original(*args)
        raise OSError('chemin-prive-a-ne-pas-afficher')
    monkeypatch.setattr(service, 'ajouter_document', interrompre)
    rep = ajouter_document(client, db)
    assert rep.status_code == 503 and 'chemin-prive' not in rep.text
    assert document(db) is None and revision(db) == 0
    assert not list((tmp_path / service.RACINE).iterdir())


@pytest.mark.parametrize('role', ['directeur', 'comptable', 'responsable', 'salarie'])
def test_recherche_dans_les_droits(app, environnement, role):
    client = client_role(app, environnement, role)
    for demande in ('SIRET asso', 'SIREN association', 'statuts association', 'code de convention collective'):
        reponse = client.post('/api/search/suggestions', json={'query': demande})
        assert reponse.status_code == 200
        suggestions = reponse.json['suggestions']
        if role == 'salarie':
            assert not any(s.get('url') == URL for s in suggestions)
        else:
            assert suggestions[0].get('url') == URL, (demande, suggestions)


@pytest.mark.parametrize('flux', [False, True])
def test_rendu_synthetique(app, db, environnement, tmp_path, flux):
    from app_options import set_option_bool
    with app.app_context():
        set_option_bool('interface_sans_menu_active', flux)
    client = client_role(app, environnement, 'directeur')
    pages = {'vide':client.get(URL)}
    assert modifier(client, db, **VALEURS).status_code == 302
    client.get(URL)
    assert modifier(client, db, 'ajouter_champ', libelle='Numéro RNA', valeur='W000000000').status_code == 302
    client.get(URL)
    assert ajouter_document(client, db).status_code == 302
    pages['gestionnaire'] = client.get(URL)
    pages['responsable'] = client_role(app, environnement, 'responsable').get(URL)
    pages['erreur'] = modifier(client, db, **{**VALEURS, 'siret':'invalide'})
    for nom, page in pages.items():
        assert page.status_code == (400 if nom == 'erreur' else 200)
        (tmp_path / f'{nom}.html').write_text(page.text)


@pytest.mark.parametrize('jeton_valide', [False, True])
def test_csrf_et_plafond_avant_lecture(app, db, environnement, monkeypatch, jeton_valide):
    client = client_role(app, environnement, 'directeur')
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    jeton = re.search(r'name="csrf_token" value="([^"]+)"', client.get(URL).text).group(1)
    rep = modifier(client, db, **VALEURS, **({'csrf_token':jeton} if jeton_valide else {}))
    assert rep.status_code == 302
    assert rep.location.endswith(URL if jeton_valide else '/login')
    assert revision(db) == (1 if jeton_valide else 0)
    assert client.post(URL, data=b'x'*(service.MAX_REQUETE+1),
                       content_type='multipart/form-data; boundary=test',
                       headers={'Accept':'application/json'}).status_code == 413


def test_plafond_documents_et_upload_obsolete(app, db, environnement, monkeypatch):
    client = client_role(app, environnement, 'directeur')
    ancienne = revision(db)
    assert ajouter_document(client, db).status_code == 302
    assert ajouter_document(client, db, revision=ancienne).status_code == 409
    monkeypatch.setattr(service, 'MAX_DOCUMENTS', 1)
    assert ajouter_document(client, db).status_code == 400
    assert db.execute('SELECT COUNT(*) FROM identite_centre_documents').fetchone()[0] == 1


@pytest.mark.parametrize('identifiant', ['invalide', '-1', str(2**80)])
def test_champ_inconnu_refuse_sans_mutation(app, db, environnement, identifiant):
    client = client_role(app, environnement, 'directeur')
    assert modifier(client, db, 'supprimer_champ', champ_id=identifiant).status_code == 404
    assert revision(db) == 0


def test_echec_suppression_conserve_la_piece(app, db, environnement, monkeypatch):
    import blueprints.identite_centre as routes
    client = client_role(app, environnement, 'directeur')
    assert ajouter_document(client, db).status_code == 302
    piece = document(db)
    original = routes._modifier
    def interrompre(*args):
        original(*args)
        raise OSError('incident fictif')
    monkeypatch.setattr(routes, '_modifier', interrompre)
    assert modifier(client, db, 'supprimer_document', document_id=piece['id']).status_code == 503
    assert document(db)['id'] == piece['id'] and revision(db) == 1
    assert service.chemin_document(piece).read_bytes() == b'Document synthetique'


def test_schema_neuf_et_migration_idempotente(app, db, environnement):
    migration = importlib.import_module('migrations.0073_identite_centre')
    tables = ['identite_centre_documents', 'identite_centre_champs', 'identite_centre']
    ddl = {t: db.execute('SELECT sql FROM sqlite_master WHERE name=?',(t,)).fetchone()[0] for t in tables}
    users = [tuple(r) for r in db.execute('SELECT * FROM users')]
    for t in tables:
        db.execute(f'DROP TABLE {t}')
    migration.upgrade(db)
    db.execute("UPDATE identite_centre SET nom='À conserver'")
    db.execute("""INSERT INTO identite_centre_champs(libelle,libelle_cle,valeur)
                  VALUES ('RNA','rna','fictif')""")
    migration.upgrade(db)
    assert db.execute('SELECT nom FROM identite_centre').fetchall()[0][0] == 'À conserver'
    assert db.execute('SELECT COUNT(*) FROM identite_centre').fetchone()[0] == 1
    assert db.execute('SELECT valeur FROM identite_centre_champs').fetchone()[0] == 'fictif'
    assert users == [tuple(r) for r in db.execute('SELECT * FROM users')]
    assert ddl == {t: db.execute('SELECT sql FROM sqlite_master WHERE name=?',(t,)).fetchone()[0] for t in tables}


def test_sauvegarde_restauration_fiche_champs_et_documents(app, db, environnement, tmp_path):
    from resilience import sauvegarder, restaurer, diagnostiquer
    client = client_role(app, environnement, 'directeur')
    assert modifier(client, db, **VALEURS).status_code == 302
    assert modifier(client, db, 'ajouter_champ', libelle='RNA', valeur='W000000000').status_code == 302
    assert ajouter_document(client, db).status_code == 302
    with closing(sqlite3.connect(tmp_path / 'cspilot.db')) as copie:
        db.backup(copie)
    archive = tmp_path.parent / (tmp_path.name+'.cspbackup')
    sauvegarder(tmp_path, archive, 'phrase-fictive-assez-longue',
                arret_confirme=True, secret_key='test-secret-key-for-pytest')
    destination = tmp_path.parent / (tmp_path.name+'-restauree')
    restaurer(archive, destination, 'phrase-fictive-assez-longue')
    with closing(sqlite3.connect(destination / 'cspilot.db')) as conn:
        assert conn.execute('SELECT nom FROM identite_centre').fetchone()[0] == VALEURS['nom']
        assert conn.execute('SELECT valeur FROM identite_centre_champs').fetchone()[0] == 'W000000000'
        relatif, empreinte = conn.execute('SELECT fichier_path,sha256 FROM identite_centre_documents').fetchone()
    contenu = (destination / 'documents' / relatif).read_bytes()
    assert contenu == b'Document synthetique' and hashlib.sha256(contenu).hexdigest() == empreinte
    assert diagnostiquer(destination, secret_key='test-secret-key-for-pytest')['ok']
