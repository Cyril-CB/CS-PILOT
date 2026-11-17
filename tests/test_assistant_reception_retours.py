"""PDF mixtes et suppression des seuls dépôts personnels, données synthétiques."""
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
import json
import uuid

import pytest
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

import assistant_reception as reception
from tests.test_assistant_reception import (
    TEXTE, pdf, proposition, depot, preciser, autre_client, creer_subvention,
    environnement_synthetique, modele,
)

OCR_SCAN = 'Bilan a produire le 2040-06-30 : somme 900000 euros.'


def pdf_mixte(page_scan=3, nb_pages=3):
    out = BytesIO()
    c = canvas.Canvas(out, pagesize=(600, 800), invariant=True, pageCompression=0)
    scans = {page_scan} if isinstance(page_scan, int) else set(page_scan)
    for numero in range(1, nb_pages + 1):
        if numero in scans:
            c.drawImage(ImageReader(Image.new('RGB', (600, 800), 'white')),
                        0, 0, width=600, height=800)
            c.drawString(20, 760, OCR_SCAN)
        else:
            for i, ligne in enumerate(TEXTE.splitlines()):
                c.drawString(30, 760 - i * 20, ligne)
        c.showPage()
    c.save()
    return out.getvalue()


def effacer(client, d):
    return client.delete('/api/assistant/documents/' + d['id'], json={'revision':d['revision']})


@pytest.mark.parametrize('page_scan', [1, 2, 3])
def test_pdf_mixte_accepte_annexe_ignoree_et_original_complet_conserve(
        db, admin_client, modele, page_scan):
    contenu = pdf_mixte(page_scan)
    r = depot(admin_client, contenu=contenu)
    assert r.status_code == 200, r.json
    d = r.json
    assert d['statut'] == 'traite' and d['pages_non_lues'] == [page_scan]
    assert str(page_scan) in d['avertissement'] and 'pas été analysée' in d['avertissement']
    assert admin_client.get(d['pdf']).data == contenu
    f = db.execute('SELECT fichier_path FROM factures').fetchone()
    assert Path(f['fichier_path']).read_bytes() == contenu
    contexte = json.loads(modele[1][0][1][1]['content'])
    assert contexte['pages_non_lues'] == [page_scan]
    assert [p['page'] for p in contexte['pages_du_document']] == [n for n in (1,2,3) if n != page_scan]
    assert OCR_SCAN not in json.dumps(contexte)


def test_scan_avec_texte_ocr_ne_justifie_pas_une_date(db, admin_client, modele):
    modele[0]['analyse']['champs']['date_facture'] = '2040-06-30'
    modele[0]['analyse']['preuves']['date_facture'] = OCR_SCAN
    r = depot(admin_client, contenu=pdf_mixte())
    assert r.status_code == 200, r.json
    assert r.json['statut'] == 'precision'
    assert 'date_facture' in {q['champ'] for q in r.json['questions']}
    assert db.execute('SELECT COUNT(*) FROM factures').fetchone()[0] == 0


def test_questions_sur_pdf_mixte_signalent_pages_non_lues(admin_client, modele, monkeypatch):
    d = depot(admin_client, contenu=pdf_mixte(2), modele_id='').json
    appels = []
    def fake(model, messages):
        ctx = json.loads(messages[1]['content'])
        appels.append(ctx)
        if len(appels) == 1:
            return {'consultations':[{'nom':'lire_document', 'arguments':{'query':'bilan'}}]}
        elements = ctx['resultats_de_consultation'][0]['elements']
        assert all('La page 2 semble scannée' in e['texte'] for e in elements)
        assert all(OCR_SCAN not in e['texte'] for e in elements)
        assert all('page 2' not in e['titre'] for e in elements)
        return {'reponse':'Le bilan est indiqué dans les pages lisibles [S1].', 'resume':'Document partiellement analysé.'}
    monkeypatch.setattr('assistant_agent.appel_json', fake)
    r = admin_client.post('/api/assistant/message', json={
        'message':'Quel bilan ?', 'model':'gpt-5.5', 'request_id':str(uuid.uuid4()), 'document_id':d['id']})
    assert r.status_code == 200, r.json


def test_facture_ttc_sans_precision_tva(db, admin_client, modele):
    modele[0]['analyse']['questions'] = ['Quel taux de TVA ?', 'Préciser le montant HT.',
        'Quel montant hors taxes ?', 'Le fournisseur est-il bien Atelier Test ?']
    d = depot(admin_client).json
    assert d['statut'] == 'traite'
    assert d['analyse']['questions'] == ['Le fournisseur est-il bien Atelier Test ?']
    assert db.execute('SELECT montant_ttc FROM factures').fetchone()[0] == 120
    assert 'Ne demande\njamais le montant HT' in modele[1][0][1][0]['content']


def test_lecture_pdf_apres_plusieurs_pages_scannees(admin_client, monkeypatch):
    d = depot(admin_client, contenu=pdf_mixte({1,2,3}, nb_pages=5), modele_id='').json
    appels = []
    def fake(model, messages):
        ctx = json.loads(messages[1]['content'])
        appels.append(ctx)
        if len(appels) == 1:
            return {'consultations':[{'nom':'lire_document','arguments':{'query':'information introuvable'}}]}
        elements = ctx['resultats_de_consultation'][0]['elements']
        assert [e['titre'].rsplit('page ',1)[1] for e in elements] == ['4','5']
        assert all('Les pages 1, 2, 3 semblent scannées' in e['texte'] for e in elements)
        return {'reponse':'Consultez les pages lisibles [S1].', 'resume':'Lecture limitée au texte.'}
    monkeypatch.setattr('assistant_agent.appel_json', fake)
    r = admin_client.post('/api/assistant/message', json={
        'message':'Information introuvable ?', 'model':'gpt-5.5', 'request_id':str(uuid.uuid4()), 'document_id':d['id']})
    assert r.status_code == 200, r.json


def test_suppression_personnelle_pdf_analyse_sans_effacer_conversation_ni_memoire(
        db, admin_client, modele):
    admin_client.post('/api/assistant/memoires', json={'texte':'Préférence à conserver', 'categorie':'preference'})
    from assistant_stockage import encoder
    with admin_client.application.app_context():
        db.execute('UPDATE assistant_etats SET contenu=?', (encoder({'messages':[], 'resume':'Fil conservé'}),))
        db.commit()
    d = depot(admin_client, modele_id='').json
    row = db.execute('SELECT fichier_path FROM assistant_documents').fetchone()
    p = reception.chemin_document(row['fichier_path'])
    assert effacer(admin_client, d).status_code == 200
    assert not p.exists()
    assert db.execute('SELECT COUNT(*) FROM assistant_documents').fetchone()[0] == 0
    assert admin_client.get(d['pdf']).status_code == 404
    assert admin_client.get('/api/assistant/documents').json['documents'] == []
    etat = admin_client.get('/api/assistant/etat').json
    assert etat['resume'] == 'Fil conservé' and len(etat['memoires']) == 1
    assert modele[1] == []


@pytest.mark.parametrize('typ,table', [('facture','factures'), ('convention','subventions'), ('contrat','contrats')])
def test_suppression_preserve_dossier_metier_et_sa_piece(db, admin_client, modele, typ, table):
    modele[0]['analyse'] = proposition(typ)
    d = depot(admin_client).json
    if typ == 'convention':
        d = preciser(admin_client, d, {'assignees':[]}).json
    assert d['statut'] == 'traite', d
    avant = dict(db.execute(f'SELECT * FROM {table}').fetchone())
    fichier = avant['justificatif_path'] if typ == 'convention' else avant['fichier_path']
    racine = 'documents/subventions' if typ == 'convention' else 'documents' if typ == 'contrat' else 'factures'
    from stockage_restaure import resoudre_fichier
    p = Path(resoudre_fichier(fichier, racine))
    contenu = p.read_bytes()
    etapes = [dict(r) for r in db.execute('SELECT * FROM subventions_sous_elements')]
    assert effacer(admin_client, d).status_code == 200
    assert dict(db.execute(f'SELECT * FROM {table}').fetchone()) == avant
    assert p.read_bytes() == contenu
    assert db.execute('SELECT COUNT(*) FROM assistant_documents').fetchone()[0] == 0
    assert [dict(r) for r in db.execute('SELECT * FROM subventions_sous_elements')] == etapes
    if typ == 'facture':
        nouveau = depot(admin_client).json
        assert nouveau['resultat']['facture_id'] == avant['id']
        assert db.execute('SELECT COUNT(*) FROM factures').fetchone()[0] == 1


def test_suppression_preserve_justificatif_et_pdf_du_sous_element(
        db, admin_client, modele, environnement_synthetique):
    dossier = environnement_synthetique / 'documents' / 'subventions'
    dossier.mkdir(parents=True)
    (dossier / 'principal.pdf').write_bytes(pdf(TEXTE + '\nPiece principale'))
    sid = creer_subvention(db, justificatif_path='principal.pdf', justificatif_nom='Principal')
    modele[0]['analyse'] = proposition('notification')
    d = depot(admin_client).json
    assert d['statut'] == 'traite', d
    avant = [dict(r) for r in db.execute('SELECT * FROM subventions_sous_elements')]
    copies = {p.name:p.read_bytes() for p in dossier.iterdir()}
    assert len(copies) == 2
    assert effacer(admin_client, d).status_code == 200
    assert [dict(r) for r in db.execute('SELECT * FROM subventions_sous_elements')] == avant
    assert {p.name:p.read_bytes() for p in dossier.iterdir()} == copies
    assert db.execute('SELECT justificatif_path FROM subventions WHERE id=?', (sid,)).fetchone()[0] == 'principal.pdf'


def test_suppression_refuse_chemin_hors_reception(db, admin_client, environnement_synthetique):
    d = depot(admin_client, modele_id='').json
    autre = environnement_synthetique / 'factures' / 'piece.pdf'
    autre.parent.mkdir()
    autre.write_bytes(b'piece metier a conserver')
    db.execute('UPDATE assistant_documents SET fichier_path=? WHERE id=?', (str(autre), d['id'])); db.commit()
    assert effacer(admin_client, d).status_code == 404
    assert autre.read_bytes() == b'piece metier a conserver'
    assert db.execute('SELECT COUNT(*) FROM assistant_documents').fetchone()[0] == 1


def test_suppression_refusee_a_autrui_et_revision_obsolete(app, db, admin_client):
    d = depot(admin_client, modele_id='').json
    autre = autre_client(app)
    assert effacer(autre, d).status_code == 404
    assert effacer(admin_client, {**d, 'revision':d['revision'] + 1}).status_code == 409
    assert admin_client.delete('/api/assistant/documents/' + d['id'], json={
        'revision':d['revision'], 'user_id':1}).status_code == 400
    assert admin_client.get(d['pdf']).status_code == 200


def test_pilotage_peut_supprimer_son_depot(db, auth_client, sample_users):
    db.execute("UPDATE secteurs SET nom='Pilotage' WHERE id=?", (sample_users['secteur_id'],)); db.commit()
    d = depot(auth_client, modele_id='').json
    assert effacer(auth_client, d).status_code == 200
    assert db.execute('SELECT COUNT(*) FROM assistant_documents').fetchone()[0] == 0


def test_suppression_protegee_csrf_et_connexion(app, db, admin_client):
    d = depot(admin_client, modele_id='').json
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        assert effacer(admin_client, d).status_code == 302
    finally:
        app.config['WTF_CSRF_ENABLED'] = False
    admin_client.get('/logout')
    assert effacer(admin_client, d).status_code == 302
    assert db.execute('SELECT COUNT(*) FROM assistant_documents').fetchone()[0] == 1


def test_echec_disque_annule_suppression(db, admin_client, monkeypatch):
    d = depot(admin_client, modele_id='').json
    p = reception.chemin_document(db.execute('SELECT fichier_path FROM assistant_documents').fetchone()[0])
    original = Path.unlink
    def echec(chemin, *args, **kwargs):
        if chemin == p:
            raise PermissionError('Incident synthétique')
        return original(chemin, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', echec)
    assert effacer(admin_client, d).status_code == 503
    assert p.read_bytes() == pdf()
    assert db.execute('SELECT COUNT(*) FROM assistant_documents').fetchone()[0] == 1


def test_echec_commit_restaure_pdf_et_depot(db, admin_client, monkeypatch):
    d = depot(admin_client, modele_id='').json
    p = reception.chemin_document(db.execute('SELECT fichier_path FROM assistant_documents').fetchone()[0])
    originale = reception.transaction
    @contextmanager
    def echec_commit():
        with originale() as conn:
            yield conn
            raise RuntimeError('Échec synthétique du commit')
    monkeypatch.setattr(reception, 'transaction', echec_commit)
    assert effacer(admin_client, d).status_code == 503
    assert p.read_bytes() == pdf()
    assert db.execute('SELECT COUNT(*) FROM assistant_documents').fetchone()[0] == 1


def test_suppression_pdf_deja_absent(db, admin_client):
    d = depot(admin_client, modele_id='').json
    reception.chemin_document(db.execute('SELECT fichier_path FROM assistant_documents').fetchone()[0]).unlink()
    assert effacer(admin_client, d).status_code == 200
    assert db.execute('SELECT COUNT(*) FROM assistant_documents').fetchone()[0] == 0


def test_suppression_pendant_analyse_empeche_creation(db, admin_client, monkeypatch):
    def fake(*args, **kwargs):
        row = db.execute('SELECT id,revision FROM assistant_documents').fetchone()
        assert effacer(admin_client, dict(row)).status_code == 200
        return proposition()
    monkeypatch.setattr('assistant_documents_analyse.appel_json', fake)
    assert depot(admin_client).status_code == 404
    assert db.execute('SELECT COUNT(*) FROM factures').fetchone()[0] == 0
    assert db.execute('SELECT COUNT(*) FROM assistant_documents').fetchone()[0] == 0


def test_suppression_invalide_reponse_chat_en_cours(db, admin_client, monkeypatch):
    d = depot(admin_client, modele_id='').json
    def fake(*args, **kwargs):
        assert effacer(admin_client, d).status_code == 200
        return {'consultations':[{'nom':'lire_document','arguments':{'query':'bilan'}}]}
    monkeypatch.setattr('assistant_agent.appel_json', fake)
    r = admin_client.post('/api/assistant/message', json={
        'message':'Quel bilan ?', 'model':'gpt-5.5', 'request_id':str(uuid.uuid4()), 'document_id':d['id']})
    assert r.status_code == 409, r.json
    assert admin_client.get('/api/assistant/etat').json['messages'] == []
