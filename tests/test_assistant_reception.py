"""Réception documentaire : PDF synthétiques, fournisseurs simulés, droits réels."""
from copy import deepcopy
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import uuid

import pytest
from reportlab.pdfgen import canvas
from reportlab.lib.pdfencrypt import StandardEncryption

import assistant_documents_analyse as analyse_ia
from tests.test_fiches_versions import fiche_complete, verrouiller

TEXTE = '''FACTURE - Document original numerique
Atelier Test - Facture F001 - Date 2026-11-17 - Echeance 2026-12-17
Montant TTC 120.00 euros - Secteur Test mentionne sur le document
Financement du projet Action Enfance au titre de l'exercice 2027.
Signature 2026-11-17. Montant accorde 120.00 euros.
Bilan financier a produire le 2027-06-30 pour obtenir le solde.
Contrat CDI - Jean Martin - Debut 2027-01-01 - 35 heures hebdomadaires.
Cette piece est un document de demonstration entierement synthetique.
'''


def pdf(texte=TEXTE, **kwargs):
    out = BytesIO()
    c = canvas.Canvas(out, invariant=True, pageCompression=0, **kwargs)
    for i, line in enumerate(texte.splitlines()):
        c.drawString(40, 800 - i * 20, line)
    c.save()
    return out.getvalue()


def proposition(typ='facture'):
    champs = {
        'facture': {'fournisseur': 'Atelier Test', 'numero_facture': 'F001',
            'date_facture': '2026-11-17', 'date_echeance': '2026-12-17', 'montant_ttc': 120.00},
        'convention': {'nom': 'Action Enfance', 'annee_action': '2027', 'montant_accorde': 120.00},
        'notification': {'nom': 'Action Enfance', 'annee_action': '2027', 'montant_accorde': 120.00},
        'contrat': {'nom_salarie': 'Martin', 'prenom_salarie': 'Jean', 'type_contrat': 'CDI',
            'date_debut': '2027-01-01', 'temps_hebdo': 35},
    }.get(typ, {})
    preuves = {k: str(v) if v != 120 else '120.00' for k, v in champs.items()}
    if typ in ('convention', 'notification'):
        preuves['annee_action'] = "Financement du projet Action Enfance au titre de l'exercice 2027."
    return {'type': typ, 'confiance': 0.98, 'titre': 'Document de demonstration',
            'resume': 'Financement de 120 euros. Bilan a produire pour obtenir le solde.',
            'informations': ['Montant : 120 euros', 'Bilan financier a produire'], 'questions': [],
            'champs': champs, 'preuves': preuves,
            'etapes': [{'nom': 'Bilan financier', 'date_echeance': '2027-06-30',
                       'preuve': 'Bilan financier a produire le 2027-06-30 pour obtenir le solde.'}]
                      if typ in ('convention', 'notification') else [],
            'instructions': {'affectation': None, 'salaries': [], 'sans_salarie': False,
                             'sans_echeance': False, 'preuve_instruction': ''}}


@pytest.fixture(autouse=True)
def environnement_synthetique(app, tmp_path, monkeypatch):
    import database
    import assistant_pdf
    import assistant_documents_metier
    import factures_import
    import blueprints.factures as factures
    import blueprints.infos_salaries as infos
    import blueprints.subventions as subventions
    import requests
    import email_service
    root = tmp_path / 'donnees'
    root.mkdir()
    for module in (database, assistant_pdf, assistant_documents_metier, factures_import):
        monkeypatch.setattr(module, 'DATA_DIR', str(root))
    monkeypatch.setattr(factures, 'FACTURES_DIR', str(root / 'factures'))
    monkeypatch.setattr(infos, 'DOCUMENTS_DIR', str(root / 'documents'))
    monkeypatch.setattr(subventions, 'DOCUMENTS_DIR', str(root / 'documents' / 'subventions'))
    def interdit(*a, **k):
        raise AssertionError('Aucun appel externe réel autorisé dans ces tests')
    monkeypatch.setattr(requests, 'post', interdit)
    monkeypatch.setattr(email_service, 'envoyer_email', interdit)
    from utils import save_setting
    with app.app_context():
        save_setting('openai_api_key', 'cle-factice-documentaire')
    return root


@pytest.fixture
def modele(monkeypatch):
    appels = []
    valeur = {'analyse': proposition()}
    def fake(model, messages, **kwargs):
        appels.append((model, messages, kwargs))
        return deepcopy(valeur['analyse'])
    monkeypatch.setattr(analyse_ia, 'appel_json', fake)
    return valeur, appels


def depot(client, contenu=None, commentaire='', modele_id='gpt-5.5', nom='original.pdf', **extra):
    return client.post('/api/assistant/documents', data={
        'fichier': (BytesIO(contenu if contenu is not None else pdf()), nom),
        'commentaire': commentaire, 'model': modele_id, **extra}, content_type='multipart/form-data')


def autre_client(app, login='resp_test', password='resp123'):
    c = app.test_client()
    c.post('/login', data={'login': login, 'password': password}, follow_redirects=True)
    return c


def preciser(client, d, reponses):
    return client.post(f"/api/assistant/documents/{d['id']}/precisions", json={
        'revision': d['revision'], 'reponses': reponses})


def creer_subvention(db, **valeurs):
    nom = valeurs.pop('nom', 'Action Enfance')
    annee = valeurs.pop('annee_action', '2027')
    cur = db.execute('INSERT INTO subventions(nom,annee_action) VALUES (?,?)', (nom, annee))
    for k, v in valeurs.items():
        assert k in {'montant_accorde', 'justificatif_path', 'justificatif_nom', 'assignee_1_id', 'assignee_2_id'}
        db.execute(f'UPDATE subventions SET {k}=? WHERE id=?', (v, cur.lastrowid))
    db.commit()
    return cur.lastrowid


def test_anonyme_et_hors_profil_refuses(client, auth_client, sample_users):
    # Les fixtures partagent un client ; déconnexion explicite pour le cas anonyme.
    auth_client.get('/logout')
    assert depot(client).status_code == 302
    c = client.post('/login', data={'login': 'salarie_test', 'password': 'sal123'})
    assert c.status_code == 302
    assert depot(client).status_code == 403


def test_depot_prive_chiffre_sans_cle_et_telechargement(app, db, admin_client, environnement_synthetique):
    r = depot(admin_client, modele_id='', commentaire='Une note privee')
    assert r.status_code == 200, r.json
    d = r.json
    assert d['statut'] == 'recu' and d['analyse'] is None
    row = db.execute('SELECT * FROM assistant_documents').fetchone()
    assert 'Une note privee' not in row['contenu'] and 'Jean Martin' not in row['contenu']
    assert len(list(environnement_synthetique.rglob('*.pdf'))) == 1
    assert admin_client.get(d['pdf']).data == pdf()
    assert admin_client.get(d['pdf']).headers['Cache-Control'] == 'private, no-store'
    autre = autre_client(app)
    assert autre.get('/api/assistant/documents').json['documents'] == []
    assert autre.get('/api/assistant/documents/' + d['id']).status_code == 404
    assert autre.get(d['pdf']).status_code == 404
    assert autre.post('/api/assistant/documents/' + d['id'] + '/analyser', json={'model':'gpt-5.5'}).status_code == 404
    assert preciser(autre, d, {}).status_code == 404


@pytest.mark.parametrize('contenu,nom', [(b'pas un PDF', 'fake.pdf'), (b'%PDF-1.4\ncasse', 'casse.pdf'),
    (pdf(''), 'vide.pdf'), (pdf(), 'document.docx'),
    (pdf(encrypt=StandardEncryption('mot-de-passe-test', canCopy=0)), 'protege.pdf')])
def test_pdf_invalides_refuses_avant_ia(db, admin_client, modele, contenu, nom):
    r = depot(admin_client, contenu=contenu, nom=nom)
    assert r.status_code == 400, r.json
    assert db.execute('SELECT COUNT(*) FROM assistant_documents').fetchone()[0] == 0
    assert modele[1] == []


def test_scan_meme_avec_couche_texte_refuse(db, admin_client, modele):
    from PIL import Image
    from reportlab.lib.utils import ImageReader
    out = BytesIO()
    c = canvas.Canvas(out, pagesize=(600,800))
    c.drawImage(ImageReader(Image.new('RGB', (600,800), 'white')), 0,0, width=600,height=800)
    c.drawString(20,760,TEXTE.splitlines()[0] + ' couche OCR avec des caracteres')
    c.save()
    r = depot(admin_client, contenu=out.getvalue())
    assert r.status_code == 400 and 'scan' in r.json['error']
    assert modele[1] == []
    assert db.execute('SELECT COUNT(*) FROM assistant_documents').fetchone()[0] == 0


def test_facture_circuit_normal_sans_secteur_devine(db, admin_client, modele):
    d = depot(admin_client).json
    assert d['statut'] == 'traite', d
    f = db.execute('SELECT * FROM factures').fetchone()
    assert f['numero_facture'] == 'F001' and f['montant_ttc'] == 120
    assert f['statut'] == 'a_traiter' and f['approbation'] == 'en_attente'
    assert f['secteur_id'] is None and f['assigned_direction'] == 0
    assert db.execute('SELECT COUNT(*) FROM ecritures_comptables').fetchone()[0] == 0
    assert d['resultat']['lien'] == '/factures'


@pytest.mark.parametrize('cible', ['Secteur Test', 'direction'])
def test_affectation_uniquement_commentaire(db, admin_client, modele, sample_users, cible):
    commentaire = 'Cette facture est pour ' + cible
    modele[0]['analyse']['instructions'].update(affectation=cible, preuve_instruction=commentaire)
    d = depot(admin_client, commentaire=commentaire).json
    assert d['statut'] == 'traite', d
    f = db.execute('SELECT secteur_id,assigned_direction FROM factures').fetchone()
    assert f['assigned_direction'] == int(cible == 'direction')
    assert f['secteur_id'] == (sample_users['secteur_id'] if cible != 'direction' else None)


def test_affectation_inventee_depuis_pdf_ignoree(db, admin_client, modele):
    modele[0]['analyse']['instructions'].update(affectation='Secteur Test', preuve_instruction='Secteur Test')
    assert depot(admin_client).status_code == 200
    assert db.execute('SELECT secteur_id FROM factures').fetchone()[0] is None


def test_double_depot_et_rejeu_sans_double_appel_ni_creation(db, admin_client, modele):
    a, b = depot(admin_client).json, depot(admin_client).json
    assert a['id'] == b['id'] and a['resultat'] == b['resultat']
    assert len(modele[1]) == 1
    assert db.execute('SELECT COUNT(*) FROM factures').fetchone()[0] == 1
    assert admin_client.get('/api/assistant/etat').json['restant'] == 29
    assert preciser(admin_client, a, {}).json['resultat'] == a['resultat']


def test_facture_meme_reference_autre_pdf_ne_cree_pas_doublon(db, admin_client, modele):
    a = depot(admin_client).json
    b = depot(admin_client, contenu=pdf(TEXTE + '\nDeuxieme exemplaire')).json
    assert b['id'] != a['id']
    assert b['resultat']['facture_id'] == a['resultat']['facture_id']
    assert db.execute('SELECT COUNT(*) FROM factures').fetchone()[0] == 1


def test_champ_sans_preuve_demande_precision(db, admin_client, modele):
    modele[0]['analyse']['preuves']['date_facture'] = 'date inventee'
    d = depot(admin_client).json
    assert d['statut'] == 'precision'
    assert 'date_facture' in {q['champ'] for q in d['questions']}
    assert db.execute('SELECT COUNT(*) FROM factures').fetchone()[0] == 0
    r = preciser(admin_client, d, {'date_facture':'2026-11-17'})
    assert r.status_code == 200 and r.json['statut'] == 'traite', r.json


@pytest.mark.parametrize('typ', ['convention', 'notification'])
def test_nouvelle_subvention_bonne_annee_assignation_et_etapes(db, admin_client, modele, sample_users, typ):
    modele[0]['analyse'] = proposition(typ)
    d = depot(admin_client).json
    assert d['statut'] == 'precision', d
    assert db.execute('SELECT COUNT(*) FROM subventions').fetchone()[0] == 0
    r = preciser(admin_client, d, {'assignees':[sample_users['responsable_id'], sample_users['comptable_id']]})
    assert r.status_code == 200 and r.json['statut'] == 'traite', r.json
    s = db.execute('SELECT * FROM subventions').fetchone()
    assert s['annee_action'] == '2027' and s['montant_accorde'] == 120
    assert s['assignee_1_id'] == sample_users['responsable_id']
    assert s['assignee_2_id'] == sample_users['comptable_id']
    assert db.execute('SELECT nom FROM subventions_types WHERE id=?', (s['type_id'],)).fetchone()[0] == '_A classer'
    assert s['justificatif_path']
    etape = db.execute('SELECT * FROM subventions_sous_elements WHERE subvention_id=?', (s['id'],)).fetchone()
    assert etape['nom'] == 'Bilan financier' and etape['date_echeance'] == '2027-06-30'


def test_annee_signature_ne_devient_pas_annee_financement(db, admin_client, modele):
    a = proposition('notification')
    a['champs']['annee_action'] = '2026'
    a['preuves']['annee_action'] = 'Signature 2026-11-17.'
    modele[0]['analyse'] = a
    d = depot(admin_client).json
    assert 'annee_action' in {q['champ'] for q in d['questions']}
    assert db.execute('SELECT COUNT(*) FROM subventions').fetchone()[0] == 0
    r = preciser(admin_client, d, {'annee_action':'2027', 'assignees':[]})
    assert r.status_code == 200 and r.json['statut'] == 'traite', r.json


def test_rapprochement_existant_sans_modifier_montants_ni_assignation(db, admin_client, modele, sample_users):
    sid = creer_subvention(db, montant_accorde=999, assignee_1_id=sample_users['comptable_id'])
    modele[0]['analyse'] = proposition('convention')
    d = depot(admin_client).json
    assert d['statut'] == 'traite', d
    assert d['resultat']['subvention_id'] == sid
    s = db.execute('SELECT * FROM subventions WHERE id=?', (sid,)).fetchone()
    assert s['montant_accorde'] == 999 and s['assignee_1_id'] == sample_users['comptable_id']
    assert s['justificatif_path']
    assert db.execute('SELECT COUNT(*) FROM subventions').fetchone()[0] == 1


def test_piece_principale_preservee_nouveau_sous_element(db, admin_client, modele, environnement_synthetique):
    dossier = environnement_synthetique / 'documents' / 'subventions'
    dossier.mkdir(parents=True)
    ancien = dossier / 'convention_originale.pdf'
    ancien.write_bytes(b'ancienne piece a conserver')
    sid = creer_subvention(db, justificatif_path=ancien.name, justificatif_nom='Original')
    modele[0]['analyse'] = proposition('notification')
    d = depot(admin_client).json
    assert d['statut'] == 'traite', d
    s = db.execute('SELECT * FROM subventions WHERE id=?', (sid,)).fetchone()
    assert s['justificatif_path'] == ancien.name and s['justificatif_nom'] == 'Original'
    assert ancien.read_bytes() == b'ancienne piece a conserver'
    piece = db.execute('SELECT * FROM subventions_sous_elements WHERE document_path IS NOT NULL').fetchone()
    assert piece['subvention_id'] == sid and piece['document_path'] != ancien.name
    assert (dossier / piece['document_path']).is_file()


def test_rapprochement_ambigu_demande_choix_et_revision(db, admin_client, modele):
    sid = creer_subvention(db, nom='Action Enfance CAF')
    creer_subvention(db, nom='Action Enfance Ville')
    modele[0]['analyse'] = proposition('convention')
    d = depot(admin_client).json
    assert 'subvention_id' in {q['champ'] for q in d['questions']}
    assert db.execute('SELECT COUNT(*) FROM subventions').fetchone()[0] == 2
    r = preciser(admin_client, d, {'subvention_id':sid})
    assert r.status_code == 200 and r.json['statut'] == 'traite', r.json
    assert db.execute('SELECT COUNT(*) FROM subventions').fetchone()[0] == 2


def test_sans_echeance_demande_et_choix_aucune(db, admin_client, modele):
    a = proposition('notification'); a['etapes'] = []
    modele[0]['analyse'] = a
    d = depot(admin_client).json
    assert {'assignees','etapes'} <= {q['champ'] for q in d['questions']}
    r = preciser(admin_client, d, {'assignees':[], 'etapes':[]})
    assert r.status_code == 200 and r.json['statut'] == 'traite', r.json
    assert db.execute('SELECT COUNT(*) FROM subventions_sous_elements').fetchone()[0] == 0


def test_contrat_cree_sur_salarie_existant_sans_modifier_sa_fiche(db, admin_client, modele, sample_users):
    modele[0]['analyse'] = proposition('contrat')
    avant = dict(db.execute('SELECT * FROM users WHERE id=?', (sample_users['salarie_id'],)).fetchone())
    d = depot(admin_client).json
    assert d['statut'] == 'traite', d
    c = db.execute('SELECT * FROM contrats').fetchone()
    assert c['user_id'] == sample_users['salarie_id'] and c['type_contrat'] == 'CDI'
    assert c['temps_hebdo'] == 35 and c['date_debut'] == '2027-01-01'
    assert dict(db.execute('SELECT * FROM users WHERE id=?', (sample_users['salarie_id'],)).fetchone()) == avant
    assert 'infos_salaries' in d['resultat']['lien']
    assert db.execute('SELECT COUNT(*) FROM journal_actions WHERE action=\'ajout_contrat\'').fetchone()[0] == 1


def test_contrat_existant_jamais_ecrase(db, admin_client, modele, sample_users):
    db.execute('''INSERT INTO contrats(user_id,type_contrat,date_debut,temps_hebdo,fichier_nom)
        VALUES (?,'CDI','2027-01-01',35,'PDF conserve')''', (sample_users['salarie_id'],))
    db.commit()
    modele[0]['analyse'] = proposition('contrat')
    d = depot(admin_client).json
    assert d['statut'] == 'traite', d
    rows = db.execute('SELECT * FROM contrats').fetchall()
    assert len(rows) == 1 and rows[0]['fichier_nom'] == 'PDF conserve'


def test_arret_maladie_identification_et_lien_seulement(db, admin_client, modele):
    modele[0]['analyse'] = proposition('arret_maladie')
    d = depot(admin_client).json
    assert d['statut'] == 'traite' and d['resultat']['lien'] == '/absences', d
    assert d['analyse']['informations'] == []
    assert db.execute('SELECT COUNT(*) FROM absences').fetchone()[0] == 0


def test_autre_document_resume_seulement(db, admin_client, modele):
    modele[0]['analyse'] = proposition('autre')
    d = depot(admin_client).json
    assert d['statut'] == 'traite' and d['analyse']['resume'], d
    for t in ['contrats','subventions','factures','absences']:
        assert db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] == 0


@pytest.mark.parametrize('typ', ['facture','convention','contrat'])
def test_pilotage_depot_analyse_sans_extension_des_droits(db, auth_client, sample_users, modele, typ):
    db.execute('UPDATE secteurs SET nom=\'Pilotage\' WHERE id=?', (sample_users['secteur_id'],)); db.commit()
    modele[0]['analyse'] = proposition(typ)
    d = depot(auth_client).json
    assert d['statut'] == 'analyse' and not d['autorise'], d
    assert d['choix'] == {}
    for t in ['contrats','subventions','factures','fournisseurs']:
        assert db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] == 0


def test_responsable_refuse_cible_contrat_hors_equipe(app, db, resp_client, sample_users, modele):
    modele[0]['analyse'] = proposition('contrat')
    modele[0]['analyse']['champs'].pop('nom_salarie')
    d = depot(resp_client).json
    assert d['statut'] == 'precision', d
    assert preciser(resp_client, d, {'salarie_id':sample_users['comptable_id']}).status_code == 403
    assert db.execute('SELECT COUNT(*) FROM contrats').fetchone()[0] == 0


@pytest.mark.parametrize('reponses', [{'user_id':1}, {'profil':'directeur'}, {'sql':'DELETE FROM users'},
    {'assignees':[1,2,3]}, {'assignees':[True]}, {'etapes':[{'nom':'Bilan','date_echeance':'date invalide'}]}])
def test_precisions_invalides_sans_ecriture(db, admin_client, modele, reponses):
    modele[0]['analyse'] = proposition('notification')
    d = depot(admin_client).json
    assert preciser(admin_client, d, reponses).status_code == 400
    assert db.execute('SELECT COUNT(*) FROM subventions').fetchone()[0] == 0


def test_role_change_pendant_appel_aucune_creation(db, admin_client, sample_users, monkeypatch):
    def fake(*a, **k):
        db.execute('UPDATE users SET profil=\'responsable\' WHERE id=?', (sample_users['directeur_id'],)); db.commit()
        return proposition()
    monkeypatch.setattr(analyse_ia, 'appel_json', fake)
    r = depot(admin_client)
    assert r.status_code == 409, r.json
    assert db.execute('SELECT COUNT(*) FROM factures').fetchone()[0] == 0
    assert db.execute('SELECT en_cours FROM assistant_documents').fetchone()[0] is None


def test_erreur_fournisseur_ne_divulgue_pas_secret_document_conserve(db, admin_client, monkeypatch):
    def fake(*a, **k):
        raise RuntimeError('cle-factice-documentaire /srv/secret')
    monkeypatch.setattr(analyse_ia, 'appel_json', fake)
    r = depot(admin_client)
    assert r.status_code == 503 and 'cle-factice' not in r.get_data(as_text=True)
    row = db.execute('SELECT * FROM assistant_documents').fetchone()
    assert row and row['en_cours'] is None
    assert db.execute('SELECT COUNT(*) FROM factures').fetchone()[0] == 0


def test_appel_hors_verrou_et_bail_document(db, admin_client, monkeypatch):
    def fake(*a, **k):
        import database
        conn = database.get_db(); conn.execute('BEGIN IMMEDIATE'); conn.rollback(); conn.close()
        ident = db.execute('SELECT id FROM assistant_documents').fetchone()[0]
        r = admin_client.post('/api/assistant/documents/' + ident + '/analyser', json={'model':'gpt-5.5'})
        assert r.status_code == 409
        return proposition()
    monkeypatch.setattr(analyse_ia, 'appel_json', fake)
    assert depot(admin_client).status_code == 200


def test_quota_partage_et_oubli_conserve_documents(db, admin_client, modele):
    admin_client.get('/api/assistant/etat')
    db.execute('UPDATE assistant_etats SET tours=30'); db.commit()
    r = depot(admin_client)
    assert r.status_code == 429
    assert modele[1] == []
    assert db.execute('SELECT COUNT(*) FROM assistant_documents').fetchone()[0] == 1
    admin_client.post('/api/assistant/oublier', json={'tout':True})
    assert len(admin_client.get('/api/assistant/documents').json['documents']) == 1


def test_schema_neuf_migration_idempotente_et_rechiffrement(app, db, admin_client):
    d = depot(admin_client, modele_id='').json
    module_path = Path(__file__).resolve().parents[1] / 'migrations/0085_assistant_reception.py'
    spec = importlib.util.spec_from_file_location('migration85', module_path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    with sqlite3.connect(':memory:') as conn:
        conn.execute('CREATE TABLE users(id INTEGER PRIMARY KEY)')
        module.upgrade(conn); module.upgrade(conn)
        assert conn.execute('SELECT COUNT(*) FROM assistant_documents').fetchone()[0] == 0
    assert db.execute('SELECT statut FROM schema_migrations WHERE version=\'0085\'').fetchone()[0] == 'ok'
    from resilience import rechiffrer_parametres, fernet_pour
    with app.app_context():
        rechiffrer_parametres(db, app.secret_key, 'nouvelle-cle-factice')
    payload = db.execute('SELECT contenu FROM assistant_documents WHERE id=?', (d['id'],)).fetchone()[0]
    assert json.loads(fernet_pour('nouvelle-cle-factice').decrypt(payload.encode()))['pages']


def test_question_sur_document_avec_sources_et_isolation(app, admin_client, modele, monkeypatch):
    d = depot(admin_client, modele_id='').json
    appels = []
    def fake(model, messages):
        appels.append(messages)
        if len(appels) == 1:
            return {'consultations':[{'nom':'lire_document','arguments':{'query':'bilan financier'}}]}
        ctx = json.loads(messages[1]['content'])
        assert 'Bilan financier' in json.dumps(ctx['resultats_de_consultation'])
        return {'reponse':'Le bilan est attendu le 30 juin 2027 [S1].', 'resume':'Échéance du bilan.'}
    monkeypatch.setattr('assistant_agent.appel_json', fake)
    body = {'message':'Quand rendre le bilan ?', 'model':'gpt-5.5', 'request_id':str(uuid.uuid4()), 'document_id':d['id']}
    r = admin_client.post('/api/assistant/message', json=body)
    assert r.status_code == 200, r.json
    assert d['id'] in r.json['messages'][-1]['sources'][0]['url']
    assert '#page=1' in r.json['messages'][-1]['sources'][0]['url']
    autre = autre_client(app)
    body['request_id'] = str(uuid.uuid4())
    assert autre.post('/api/assistant/message', json=body).status_code == 404


def test_refus_contrat_sur_fiche_verrouillee_et_nettoyage(app, db, admin_client, modele,
        sample_users, fiche_complete, environnement_synthetique):
    # La fiche signée couvre une première période ; un nouveau contrat
    # rétroactif ne doit pas ajouter des jours dus à sa seconde moitié.
    db.execute('UPDATE contrats SET date_fin=\'2026-08-15\' WHERE user_id=?', (fiche_complete,))
    db.execute('DELETE FROM heures_reelles WHERE user_id=? AND date>\'2026-08-15\'', (fiche_complete,))
    db.commit()
    verrouiller(app, sample_users, fiche_complete)
    a = proposition('contrat')
    a['champs'].update(date_debut='2026-08-16', temps_hebdo=20)
    a['preuves'].update(date_debut='2026-08-16', temps_hebdo='20')
    modele[0]['analyse'] = a
    texte = TEXTE.replace('2027-01-01', '2026-08-16').replace('35 heures', '20 heures')
    avant = db.execute('SELECT COUNT(*) FROM contrats').fetchone()[0]
    r = depot(admin_client, contenu=pdf(texte))
    assert r.status_code == 409, r.json
    assert 'verrouillée' in r.json['error']
    assert db.execute('SELECT COUNT(*) FROM contrats').fetchone()[0] == avant
    assert db.execute('SELECT statut FROM assistant_documents').fetchone()[0] == 'analyse'
    assert len(list(environnement_synthetique.rglob('*.pdf'))) == 1


def test_changement_type_avant_creation_et_historique_conserve(db, admin_client, modele):
    modele[0]['analyse'] = proposition('autre')
    d = depot(admin_client).json
    modele[0]['analyse'] = proposition('notification')
    r = admin_client.post('/api/assistant/documents/' + d['id'] + '/analyser', json={
        'model':'gpt-5.5', 'type_document':'notification', 'commentaire':'Sans salarié assigné.'})
    assert r.status_code == 200 and r.json['type'] == 'notification', r.json
    from assistant_stockage import decoder
    with admin_client.application.app_context():
        data = decoder(db.execute('SELECT contenu FROM assistant_documents').fetchone()[0])
    assert data['analyses_precedentes'][0]['type'] == 'autre'
    assert 'Sans salarié' in data['complements'][0]


def test_reexamen_ne_modifie_pas_dossier_deja_cree(db, admin_client, modele):
    d = depot(admin_client).json
    r = admin_client.post('/api/assistant/documents/' + d['id'] + '/analyser', json={
        'model':'gpt-5.5', 'type_document':'notification', 'commentaire':'Changer la facture'})
    assert r.status_code == 409
    assert db.execute('SELECT COUNT(*) FROM factures').fetchone()[0] == 1
    assert len(modele[1]) == 1
    assert preciser(admin_client, d, {'montant_ttc':999}).status_code == 409
    assert db.execute('SELECT montant_ttc FROM factures').fetchone()[0] == 120


def test_revision_obsolete_refuse_les_precisions(db, admin_client, modele):
    modele[0]['analyse'] = proposition('notification')
    d = depot(admin_client).json
    r = preciser(admin_client, d, {'nom':'Autre nom'})
    assert r.status_code == 200 and r.json['statut'] == 'precision'
    assert preciser(admin_client, d, {'assignees':[]}).status_code == 409
    assert db.execute('SELECT COUNT(*) FROM subventions').fetchone()[0] == 0


def test_responsable_ne_rattache_pas_a_subvention_non_assignee(db, resp_client, modele):
    sid = creer_subvention(db)
    modele[0]['analyse'] = proposition('convention')
    d = depot(resp_client).json
    assert d['statut'] == 'precision', d
    assert preciser(resp_client, d, {'subvention_id':sid}).status_code == 403
    assert db.execute('SELECT justificatif_path FROM subventions WHERE id=?', (sid,)).fetchone()[0] is None


def test_responsable_peut_creer_contrat_equipe_et_subvention(db, resp_client, modele, sample_users):
    modele[0]['analyse'] = proposition('contrat')
    d = depot(resp_client).json
    assert d['statut'] == 'traite', d
    modele[0]['analyse'] = proposition('convention')
    d = depot(resp_client, contenu=pdf(TEXTE + '\nConvention distincte')).json
    r = preciser(resp_client, d, {'assignees':[sample_users['responsable_id']]})
    assert r.status_code == 200 and r.json['statut'] == 'traite', r.json
    assert r.json['resultat']['lien'].startswith('/subventions')
    assert db.execute('SELECT COUNT(*) FROM subventions').fetchone()[0] == 1


def test_piece_identique_autre_compte_pas_de_nouveau_sous_element(app, db, admin_client, modele):
    creer_subvention(db)
    modele[0]['analyse'] = proposition('convention')
    d = depot(admin_client).json
    autre = autre_client(app, 'compta_test', 'compta123')
    r = depot(autre)
    assert r.status_code == 200 and r.json['statut'] == 'traite', r.json
    assert r.json['resultat']['subvention_id'] == d['resultat']['subvention_id']
    assert db.execute('SELECT COUNT(*) FROM subventions_sous_elements').fetchone()[0] == 1


def test_facture_fournisseur_alias_pas_de_doublon(db, admin_client, modele):
    fid = db.execute('INSERT INTO fournisseurs(nom,alias1) VALUES (?,?)', ('Fournisseur officiel','Atelier Test')).lastrowid
    db.execute('''INSERT INTO factures(fournisseur_id,numero_facture,date_facture,montant_ttc)
        VALUES (?,'F001','2026-11-17',120)''', (fid,)); db.commit()
    d = depot(admin_client).json
    assert d['statut'] == 'traite', d
    assert db.execute('SELECT COUNT(*) FROM factures').fetchone()[0] == 1
    assert db.execute('SELECT nom FROM fournisseurs').fetchone()[0] == 'Fournisseur officiel'


def test_absence_de_champs_entreprise_arbitraires(db, admin_client, modele):
    modele[0]['analyse']['champs']['user_id'] = 1
    r = depot(admin_client)
    assert r.status_code == 502
    assert db.execute('SELECT COUNT(*) FROM factures').fetchone()[0] == 0


def test_pdf_trop_volumineux_et_contexte_client_refuses(admin_client, modele, db):
    assert depot(admin_client, contenu=b'%PDF-' + b'x' * (16 * 1024 * 1024)).status_code in (400,413)
    assert depot(admin_client, user_id='1').status_code == 400
    assert modele[1] == []
    assert db.execute('SELECT COUNT(*) FROM assistant_documents').fetchone()[0] == 0


def test_protection_csrf_sur_depot(app, admin_client, db):
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        assert depot(admin_client).status_code == 302
        assert db.execute('SELECT COUNT(*) FROM assistant_documents').fetchone()[0] == 0
    finally:
        app.config['WTF_CSRF_ENABLED'] = False


def test_reference_pdf_couverte_par_diagnostic(app, db, admin_client, environnement_synthetique):
    depot(admin_client, modele_id='')
    from resilience import _references
    refs, absentes, mapping = _references(db, environnement_synthetique)
    assert not absentes
    assert any(p.startswith('documents/assistant_reception/') for p in refs)


def test_import_manuel_factures_reutilise_enregistrement(app, db, admin_client, monkeypatch):
    monkeypatch.setattr('blueprints.factures._extract_invoice_info', lambda *a: proposition()['champs'])
    r = admin_client.post('/factures/importer', data={
        'fichiers':(BytesIO(pdf()), 'source.pdf'), 'model':'gpt-5.5'}, content_type='multipart/form-data')
    assert r.status_code == 302
    f = db.execute('SELECT * FROM factures').fetchone()
    assert f['numero_facture'] == 'F001' and f['montant_ttc'] == 120
    assert f['fichier_nom'].startswith('2026-11-17_FACTURE_')
    assert Path(f['fichier_path']).is_file()
    assert db.execute('SELECT COUNT(*) FROM facture_historique').fetchone()[0] == 1


def test_echec_import_manuel_annule_fournisseur_et_copie(db, admin_client, monkeypatch, environnement_synthetique):
    monkeypatch.setattr('blueprints.factures._extract_invoice_info', lambda *a: proposition()['champs'])
    db.execute('''CREATE TRIGGER test_echec_facture BEFORE INSERT ON factures
        BEGIN SELECT RAISE(ABORT,'Incident synthétique'); END'''); db.commit()
    r = admin_client.post('/factures/importer', data={
        'fichiers':(BytesIO(pdf()), 'source.pdf'), 'model':'gpt-5.5'}, content_type='multipart/form-data')
    assert r.status_code == 302
    assert db.execute('SELECT COUNT(*) FROM fournisseurs').fetchone()[0] == 0
    assert db.execute('SELECT COUNT(*) FROM factures').fetchone()[0] == 0
    assert list(environnement_synthetique.rglob('*.pdf')) == []


def test_annee_precisee_commentaire_pas_redemandee(admin_client, modele):
    a = proposition('notification')
    a['preuves']['annee_action'] = 'Pour 2027'
    modele[0]['analyse'] = a
    d = depot(admin_client, commentaire='Pour 2027').json
    assert 'annee_action' not in {q['champ'] for q in d['questions']}


@pytest.mark.parametrize('champs,texte', [
    ({'temps_hebdo':80}, TEXTE.replace('35 heures', '80 heures')),
    ({'date_fin':'2026-12-31'}, TEXTE + '\nFin de contrat 2026-12-31.'),
])
def test_extraction_incoherente_ne_bloque_pas_la_boite_et_peut_etre_reexaminee(
        admin_client, db, modele, champs, texte):
    ancien = depot(admin_client, contenu=pdf(TEXTE + '\nPremier depot'), modele_id='').json
    a = proposition('contrat')
    a['champs'].update(champs)
    a['preuves'].update({k:str(v) for k,v in champs.items()})
    modele[0]['analyse'] = a
    r = depot(admin_client, contenu=pdf(texte))
    assert r.status_code == 400
    boite = admin_client.get('/api/assistant/documents')
    assert boite.status_code == 200, boite.json
    documents = boite.json['documents']
    assert len(documents) == 2
    d = next(d for d in documents if d['id'] != ancien['id'])
    assert d['analyse']['type'] == 'contrat' and d['erreur'] and not d['autorise']
    assert admin_client.get(d['pdf']).status_code == 200
    assert db.execute('SELECT COUNT(*) FROM contrats').fetchone()[0] == 0
    modele[0]['analyse'] = proposition('autre')
    r = admin_client.post('/api/assistant/documents/' + d['id'] + '/analyser', json={
        'model':'gpt-5.5','type_document':'autre','commentaire':'Document à analyser sans création.'})
    assert r.status_code == 200 and r.json['statut'] == 'traite', r.json
