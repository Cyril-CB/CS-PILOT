"""Parcours réel du formulaire ; SMTP simulé et données/fichiers exclusivement fictifs."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
import hashlib
import io
import json
from pathlib import Path
import smtplib
import sqlite3
from unittest.mock import Mock
import zipfile

import pytest
from openpyxl import Workbook

import database
import email_service
import propositions


class Champs(HTMLParser):
    def __init__(self, texte):
        super().__init__()
        self.valeurs = {}
        self.feed(texte)

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == 'input' and d.get('name'):
            self.valeurs[d['name']] = d.get('value', '')


@pytest.fixture
def environnement(app, db, sample_users, monkeypatch, tmp_path):
    monkeypatch.setattr(database, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(propositions, '_revision_sources', lambda: 'a' * 40)
    db.execute("UPDATE users SET email='personne' || id || '@exemple.test'")
    db.commit()
    with app.app_context():
        email_service.save_email_config('smtp.exemple.test', 587, 'centre@exemple.test',
                                        'mot-de-passe-fictif', 'Centre de test')
        email_service.save_base_url('https://centre.exemple.test')
    smtp = Mock()
    smtp.send_message.return_value = {}
    monkeypatch.setattr(email_service, '_ouvrir_connexion_smtp', Mock(return_value=smtp))
    return smtp


def connecter(app, login='admin', password='Admin1234'):
    client = app.test_client()
    assert client.post('/login', data={'login': login, 'password': password}).status_code == 302
    return client


def preparer(client, recherche='SIRET asso', origine='sans_resultat'):
    reponse = client.post('/propositions/nouvelle', data={
        'action': 'preparer', 'recherche': recherche,
        'origine': origine, 'page': 'dashboard_direction_bp.dashboard_direction'})
    assert reponse.status_code == 200
    champs = Champs(reponse.text).valeurs
    return {'action': 'envoyer', 'contexte': champs['contexte'],
        'csrf_token': champs['csrf_token'], 'recherche': recherche,
        'titre': 'Fiche de l’association',
        'besoin': 'Disposer des données légales et des documents récurrents de l’association.',
        'email_reponse': 'reponse@exemple.test', 'frequence': 'annuel'}


def soumettre(client, data=None):
    return client.post('/propositions/nouvelle', data=data or preparer(client),
                       content_type='multipart/form-data')


def dernier(db):
    return db.execute('SELECT * FROM propositions_amelioration ORDER BY cree_le DESC, rowid DESC').fetchone()


def classeur():
    f = io.BytesIO()
    livre = Workbook()
    livre.active.append(['Fréquentation', 'Repas', 'Simulation'])
    livre.active.append([10, 25, '=A2*B2'])
    livre.save(f)
    livre.close()
    return f.getvalue()


@pytest.mark.parametrize('interface_flux', [False, True])
def test_liens_du_parcours_respectent_la_charte(
        app, db, environnement, monkeypatch, tmp_path, interface_flux):
    from app_options import set_option_bool

    class LiensPage(HTMLParser):
        def __init__(self, html):
            super().__init__()
            self.profondeur = 0
            self.dans_pied_de_page = False
            self.liens = []
            self.liens_pied_de_page = []
            self.feed(html)

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'div':
                if self.profondeur or 'proposition-page' in attrs.get('class', '').split():
                    self.profondeur += 1
            if tag == 'p' and 'proposition-liens' in attrs.get('class', '').split():
                self.dans_pied_de_page = True
            if tag == 'a' and (self.profondeur or self.dans_pied_de_page):
                self.liens.append(attrs)
                if self.dans_pied_de_page:
                    self.liens_pied_de_page.append(attrs)

        def handle_endtag(self, tag):
            if tag == 'div' and self.profondeur:
                self.profondeur -= 1
            if tag == 'p':
                self.dans_pied_de_page = False

    with app.app_context():
        set_option_bool('interface_sans_menu_active', interface_flux)
    client = connecter(app)
    pages = {'formulaire': client.get('/propositions/nouvelle')}
    data = preparer(client)
    data['pieces'] = (io.BytesIO(b'Document synthetique'), 'exemple.txt')
    assert soumettre(client, data).status_code == 302
    reference = dernier(db)['id']
    pages['detail'] = client.get(f'/propositions/{reference}')
    # Couvrir également configuration absente et transmission en cours.
    import blueprints.propositions as routes
    monkeypatch.setattr(routes, 'is_email_configured', lambda: False)
    pages['formulaire_sans_email'] = client.get('/propositions/nouvelle')
    db.execute("UPDATE propositions_amelioration SET statut='en_cours', derniere_tentative=?",
               (datetime.now(timezone.utc).isoformat(),))
    db.commit()
    pages['detail_en_cours'] = client.get(f'/propositions/{reference}')
    pages['liste'] = client.get('/propositions')
    pages['centre'] = client.get('/propositions?centre=1')
    for nom, reponse in pages.items():
        assert reponse.status_code == 200
        page = LiensPage(reponse.text)
        liens = page.liens
        assert liens, nom
        # Le pied de page commun est rendu dans les deux modes ; le CSS le
        # masque en flux. Il doit rester couvert hors du contenu central.
        assert [l['href'] for l in page.liens_pied_de_page] == [
            '/propositions/nouvelle', '/propositions'
        ], nom
        for lien in liens:
            classes = set(lien.get('class', '').split())
            assert 'btn' in classes or 'proposition-lien-titre' in classes, (nom, lien)
            if 'btn' in classes:
                assert classes & {'btn-primary', 'btn-secondary'}, (nom, lien)
        # Pages synthétiques disponibles dans le répertoire temporaire pour
        # la vérification navigateur ; aucune donnée du centre ni appel SMTP réel.
        (tmp_path / f'{nom}.html').write_text(reponse.text, encoding='utf-8')
    for nom in ('liste', 'centre'):
        actifs = [l for l in LiensPage(pages[nom].text).liens if l.get('aria-current') == 'page']
        assert len(actifs) == 1
        assert 'btn-primary' in actifs[0]['class'].split()


def test_envoi_complet_et_mail_exploitable(app, db, environnement, sample_users):
    client = connecter(app)
    data = preparer(client)
    fichier = classeur()
    data.update(resultat_attendu='Un tableau de simulation réutilisable.',
                solution_actuelle='Un classeur Excel à ressaisir.',
                personnes_concernees='Les responsables de crèche',
                echeance='2026-12-01', raison_echeance='Préparation du budget',
                pieces=[(io.BytesIO(fichier), 'budget crèche.xlsx')],
                destinataire='attaquant@exemple.test', user_id=999, nom='Faux auteur')
    reponse = soumettre(client, data)
    assert reponse.status_code == 302
    row = dernier(db)
    assert row['statut'] == 'envoyee' and row['tentatives'] == 1
    assert row['user_id'] == sample_users['directeur_id']
    appel = environnement.send_message.call_args
    assert appel.kwargs == {'from_addr': 'centre@exemple.test', 'to_addrs': ['cspilot@outlook.fr']}
    message = BytesParser(policy=policy.default).parsebytes(appel.args[0].as_bytes())
    assert message['To'] == 'cspilot@outlook.fr'
    assert message['Reply-To'] == 'reponse@exemple.test'
    assert message['X-CS-PILOT-Type'] == 'proposition-v1'
    assert message['X-CS-PILOT-Reference'] == row['id']
    assert row['id'] in message['Message-ID'] and row['id'] in message['Subject']
    fichiers = list(message.iter_attachments())
    assert [f.get_filename() for f in fichiers] == ['cspilot-proposition-v1.json', '01-budget crèche.xlsx']
    fiche = json.loads(fichiers[0].get_payload(decode=True))
    assert fiche == json.loads(row['contenu_json'])
    assert fiche['format'] == 'cspilot.proposition' and fiche['version'] == 1
    assert fiche['demande']['resultat_attendu'] == data['resultat_attendu']
    assert fiche['auteur']['nom'] == 'Admin' and fiche['auteur']['profil'] == 'directeur'
    assert fiche['contexte']['recherche'] == 'SIRET asso'
    assert fiche['contexte']['origine_declaree'] == 'sans_resultat'
    assert fiche['contexte']['application']['revision'] == 'a' * 40
    assert fiche['centre']['url_configuree'] == 'https://centre.exemple.test'
    assert 'mot-de-passe-fictif' not in json.dumps(fiche)
    assert 'fichier_path' not in fiche['pieces_jointes'][0]
    assert fichiers[1].get_payload(decode=True) == fichier
    assert fiche['pieces_jointes'][0]['sha256'] == hashlib.sha256(fichier).hexdigest()
    piece = db.execute('SELECT * FROM propositions_pieces').fetchone()
    assert piece['fichier_path'].startswith('propositions/')
    chemin = Path(database.DATA_DIR) / 'documents' / piece['fichier_path']
    assert chemin.read_bytes() == fichier
    assert client.get(reponse.location).status_code == 200
    telechargement = client.get(f'/propositions/{row["id"]}/pieces/{piece["id"]}')
    assert telechargement.data == fichier
    assert 'attachment' in telechargement.headers['Content-Disposition']
    assert telechargement.headers['X-Content-Type-Options'] == 'nosniff'
    assert json.loads(client.get(f'/propositions/{row["id"]}/fiche.json').data) == fiche


@pytest.mark.parametrize('profil', propositions.PROFILS)
def test_tous_profils_peuvent_proposer_avec_identite_actuelle(app, db, environnement, sample_users, profil):
    client = connecter(app)
    db.execute('UPDATE users SET profil=? WHERE id=?', (profil, sample_users['directeur_id']))
    db.commit()
    form = client.get('/propositions/nouvelle')
    assert form.status_code == 200
    assert f'personne{sample_users["directeur_id"]}@exemple.test' in form.text
    assert soumettre(client).status_code == 302
    assert json.loads(dernier(db)['contenu_json'])['auteur']['profil'] == profil


def test_anonyme_et_profil_inconnu_refuses(app, db, environnement, sample_users):
    anonyme = app.test_client()
    for path in ('/propositions', '/propositions/nouvelle', '/propositions/inconnue',
                 '/propositions/inconnue/pieces/inconnue', '/propositions/inconnue/fiche.json'):
        assert anonyme.get(path).status_code == 302
    assert anonyme.post('/propositions/inconnue/envoyer').status_code == 302
    assert anonyme.post('/propositions/nouvelle', data={'besoin': 'x' * 50}).status_code == 302
    client = connecter(app)
    db.execute("UPDATE users SET profil='inconnu' WHERE id=?", (sample_users['directeur_id'],))
    db.commit()
    assert client.get('/propositions/nouvelle').status_code == 403
    environnement.send_message.assert_not_called()


def test_autre_utilisateur_ne_lit_ni_ne_renvoie_les_pieces(app, db, environnement):
    auteur = connecter(app, 'salarie_test', 'sal123')
    data = preparer(auteur)
    data['pieces'] = [(io.BytesIO(b'exemple,fictif\n1,2\n'), 'modele.csv')]
    soumettre(auteur, data)
    reference = dernier(db)['id']
    piece = db.execute('SELECT id FROM propositions_pieces').fetchone()[0]
    autre = connecter(app, 'resp_test', 'resp123')
    for path in (f'/propositions/{reference}', f'/propositions/{reference}/pieces/{piece}',
                 f'/propositions/{reference}/fiche.json'):
        assert autre.get(path).status_code == 404
    assert autre.post(f'/propositions/{reference}/envoyer').status_code == 404
    assert autre.get('/propositions?centre=1').status_code == 403
    assert reference not in autre.get('/propositions').text
    direction = connecter(app)
    assert direction.get(f'/propositions/{reference}').status_code == 200
    assert reference in direction.get('/propositions?centre=1').text
    assert environnement.send_message.call_count == 1


def test_contexte_signe_et_session_revoquee(app, db, environnement, sample_users):
    client = connecter(app)
    data = preparer(client)
    data['contexte'] += 'falsifie'
    assert soumettre(client, data).status_code == 400
    autre = connecter(app, 'salarie_test', 'sal123')
    assert soumettre(autre, preparer(client)).status_code == 400
    data = preparer(client)
    db.execute('UPDATE users SET actif=0 WHERE id=?', (sample_users['directeur_id'],))
    db.commit()
    assert soumettre(client, data).status_code == 302
    assert dernier(db) is None
    environnement.send_message.assert_not_called()


def test_double_soumission_ne_duplique_ni_demande_ni_mail(app, db, environnement):
    client = connecter(app)
    data = preparer(client)
    a = soumettre(client, dict(data))
    b = soumettre(client, dict(data))
    assert a.location == b.location
    assert db.execute('SELECT COUNT(*) FROM propositions_amelioration').fetchone()[0] == 1
    assert environnement.send_message.call_count == 1
    assert client.post(a.location + '/envoyer').status_code == 302
    assert environnement.send_message.call_count == 1


@pytest.mark.parametrize('champ,valeur', [
    ('besoin', 'trop court'), ('besoin', 'x' * 10001),
    ('email_reponse', 'nom@example.test\r\nBcc: pirate@exemple.test'),
    ('email_reponse', 'nom@example.test,autre@example.test'),
    ('email_reponse', ''), ('titre', 'titre\nAutre en-tête: oui'),
    ('frequence', 'inconnue'), ('echeance', '2026-02-30'),
])
def test_erreur_validation_conserve_texte_sans_envoi(app, db, environnement, champ, valeur):
    client = connecter(app)
    data = preparer(client)
    data[champ] = valeur
    response = soumettre(client, data)
    assert response.status_code == 400
    assert 'Votre texte est conservé' in response.text
    assert 'contexte' in Champs(response.text).valeurs
    assert dernier(db) is None
    environnement.send_message.assert_not_called()


@pytest.mark.parametrize('nom,contenu', [
    ('../../piece.csv', b'a,b\n'), ('piece.exe', b'MZ-fictif'),
    ('piece.svg', b'<svg/>'), ('piece.xlsx', b'pas un classeur'),
    ('piece.pdf', b'<script>alert(1)</script>'), ('piece.txt', b'\x00binaire'),
    ('piece.csv', b''), ('piece\r\n.csv', b'a,b\n'),
])
def test_piece_invalide_refusee_sans_trace_persistante(app, db, environnement, nom, contenu):
    client = connecter(app)
    data = preparer(client)
    data['pieces'] = [(io.BytesIO(contenu), nom)]
    assert soumettre(client, data).status_code == 400
    assert dernier(db) is None
    assert not list(Path(database.DATA_DIR).glob('documents/propositions/*'))
    environnement.send_message.assert_not_called()


def test_nombre_taille_et_total_bornes(app, db, environnement, monkeypatch):
    client = connecter(app)
    monkeypatch.setattr(propositions, 'MAX_FICHIER', 100)
    monkeypatch.setattr(propositions, 'MAX_TOTAL', 150)
    for contenus in ([b'x'] * 4, [b'x' * 101], [b'x' * 80] * 2):
        data = preparer(client)
        data['pieces'] = [(io.BytesIO(c), f'fichier{i}.txt') for i, c in enumerate(contenus)]
        assert soumettre(client, data).status_code == 400
    assert dernier(db) is None


@pytest.mark.parametrize('entree', ['../intrus', 'xl/vbaProject.bin'])
def test_archive_traversee_ou_macro_refusee(app, db, environnement, entree):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as z:
        for nom in ('[Content_Types].xml', 'xl/workbook.xml', entree):
            z.writestr(nom, 'fictif')
    client = connecter(app)
    data = preparer(client)
    data['pieces'] = [(io.BytesIO(archive.getvalue()), 'renomme.xlsx')]
    assert soumettre(client, data).status_code == 400
    environnement.send_message.assert_not_called()


def test_transaction_annulee_nettoie_les_pieces(app, db, environnement, monkeypatch):
    original = propositions.enregistrer
    def echec(*args):
        original(*args)
        raise sqlite3.OperationalError('échec fictif')
    monkeypatch.setattr(propositions, 'enregistrer', echec)
    client = connecter(app)
    data = preparer(client)
    data['pieces'] = [(io.BytesIO(b'exemple fictif'), 'modele.txt')]
    assert soumettre(client, data).status_code == 503
    assert dernier(db) is None
    assert not list(Path(database.DATA_DIR).glob('documents/propositions/*'))
    environnement.send_message.assert_not_called()


def test_smtp_indisponible_conserve_et_permet_reprise(app, db, environnement):
    client = connecter(app)
    with app.app_context():
        email_service.set_email_enabled(False)
    data = preparer(client)
    data['pieces'] = [(io.BytesIO(b'exemple fictif'), 'modele.txt')]
    response = soumettre(client, data)
    row = dernier(db)
    assert row['statut'] == 'a_envoyer' and row['erreur_code'] == 'configuration'
    environnement.send_message.assert_not_called()
    assert 'Configurer la messagerie' in client.get(response.location).text
    with app.app_context():
        email_service.set_email_enabled(True)
    assert client.post(response.location + '/envoyer').status_code == 302
    assert dernier(db)['statut'] == 'envoyee'
    assert environnement.send_message.call_count == 1
    assert len(list(environnement.send_message.call_args.args[0].iter_attachments())) == 2


def test_refus_smtp_et_quit_apres_acceptation(app, db, environnement):
    client = connecter(app)
    environnement.send_message.side_effect = smtplib.SMTPDataError(552, b'refus fictif')
    response = soumettre(client)
    assert dernier(db)['statut'] == 'a_envoyer'
    environnement.send_message.side_effect = None
    environnement.quit.side_effect = smtplib.SMTPServerDisconnected('coupure fictive apres acceptation')
    client.post(response.location + '/envoyer')
    assert dernier(db)['statut'] == 'envoyee'
    assert environnement.send_message.call_count == 2


def test_interruption_ambigue_exige_confirmation_garde_reference(app, db, environnement):
    client = connecter(app)
    environnement.send_message.side_effect = smtplib.SMTPServerDisconnected('coupure fictive')
    response = soumettre(client)
    assert dernier(db)['statut'] == 'incertain'
    premier_id = environnement.send_message.call_args.args[0]['Message-ID']
    client.post(response.location + '/envoyer')
    assert environnement.send_message.call_count == 1
    environnement.send_message.side_effect = None
    client.post(response.location + '/envoyer', data={'confirmer_reenvoi': 'oui'})
    assert dernier(db)['statut'] == 'envoyee'
    assert environnement.send_message.call_count == 2
    assert environnement.send_message.call_args.args[0]['Message-ID'] == premier_id


def test_envoi_deja_en_cours_et_reprise_apres_arret(app, db, environnement):
    client = connecter(app)
    with app.app_context():
        email_service.set_email_enabled(False)
    response = soumettre(client)
    db.execute("UPDATE propositions_amelioration SET statut='en_cours', derniere_tentative=?",
               (datetime.now(timezone.utc).isoformat(),))
    db.commit()
    client.post(response.location + '/envoyer', data={'confirmer_reenvoi': 'oui'})
    assert dernier(db)['statut'] == 'en_cours'
    with app.app_context():
        email_service.set_email_enabled(True)
    db.execute("UPDATE propositions_amelioration SET derniere_tentative=?",
               ((datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat(),))
    db.commit()
    assert 'transmis' in client.get(response.location).text
    client.post(response.location + '/envoyer')
    environnement.send_message.assert_not_called()
    client.post(response.location + '/envoyer', data={'confirmer_reenvoi': 'oui'})
    assert dernier(db)['statut'] == 'envoyee'


@pytest.mark.parametrize('centre', [False, True])
@pytest.mark.parametrize('age_secondes,statut_attendu', [
    (599, 'en_cours'), (600, 'incertain'), (660, 'incertain'),
])
def test_historique_signale_envoi_interrompu_comme_la_fiche(
        app, db, environnement, monkeypatch, centre, age_secondes, statut_attendu):
    import blueprints.propositions as routes

    maintenant = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)

    class HorlogeFixe(datetime):
        @classmethod
        def now(cls, tz=None):
            return maintenant.astimezone(tz)

    monkeypatch.setattr(routes, 'datetime', HorlogeFixe)
    auteur = connecter(app, 'salarie_test', 'sal123')
    with app.app_context():
        email_service.set_email_enabled(False)
    response = soumettre(auteur)
    db.execute("UPDATE propositions_amelioration SET statut='en_cours', derniere_tentative=?",
               ((maintenant - timedelta(seconds=age_secondes)).isoformat(),))
    db.commit()
    avant = dict(dernier(db))
    lecteur = connecter(app) if centre else auteur
    historique = lecteur.get('/propositions?centre=1' if centre else '/propositions')
    fiche = lecteur.get(response.location)
    badge = f'class="proposition-statut proposition-statut-{statut_attendu}"'
    assert historique.status_code == fiche.status_code == 200
    assert badge in historique.text
    assert badge in fiche.text
    assert response.location in historique.text
    assert dict(dernier(db)) == avant
    environnement.send_message.assert_not_called()


def test_piece_absente_interdit_envoi_partiel(app, db, environnement):
    client = connecter(app)
    environnement.send_message.return_value = {'cspilot@outlook.fr': (550, b'refus')}
    data = preparer(client)
    data['pieces'] = [(io.BytesIO(b'exemple fictif'), 'modele.txt')]
    response = soumettre(client, data)
    p = db.execute('SELECT fichier_path FROM propositions_pieces').fetchone()[0]
    (Path(database.DATA_DIR) / 'documents' / p).unlink()
    client.post(response.location + '/envoyer')
    assert dernier(db)['erreur_code'] == 'piece'
    assert environnement.send_message.call_count == 1


def test_second_envoi_pendant_smtp_refuse_sans_verrou_sqlite(app, db, environnement):
    client = connecter(app)
    autre_onglet = connecter(app)
    def pendant_smtp(message, **kwargs):
        reference = message['X-CS-PILOT-Reference']
        # Cette seconde requête doit pouvoir prendre le verrou SQLite puis
        # constater l'envoi en cours, sans ouvrir une deuxième connexion SMTP.
        assert autre_onglet.post(f'/propositions/{reference}/envoyer').status_code == 302
        assert dernier(db)['statut'] == 'en_cours'
        return {}
    environnement.send_message.side_effect = pendant_smtp
    assert soumettre(client).status_code == 302
    assert dernier(db)['statut'] == 'envoyee'
    assert environnement.send_message.call_count == 1


def test_limite_centre_reprise_dans_formulaire_et_validation(app, db, environnement, monkeypatch):
    client = connecter(app)
    monkeypatch.setitem(app.config, 'MAX_CONTENT_LENGTH', 1024 * 1024)
    page = client.get('/propositions/nouvelle').text
    limite = 1024 * 1024 - 64 * 1024
    assert f'data-max-total="{limite}"' in page
    data = preparer(client)
    data['pieces'] = [(io.BytesIO(b'x' * (limite + 1)), 'limite.txt')]
    assert soumettre(client, data).status_code == 400
    environnement.send_message.assert_not_called()


@pytest.mark.parametrize('url,attendu', [
    ('https://centre.exemple.test/app?secret=valeur-fictive#fragment', 'https://centre.exemple.test/app'),
    ('https://compte:valeur-fictive@centre.exemple.test', None),
    ('https://[valeur-fictive', None),
])
def test_url_centre_ne_transmet_pas_les_parametres(app, db, environnement, url, attendu):
    with app.app_context():
        email_service.save_base_url(url)
    soumettre(connecter(app))
    donnees = json.loads(dernier(db)['contenu_json'])
    assert donnees['centre']['url_configuree'] == attendu
    assert 'valeur-fictive' not in dernier(db)['contenu_json']


@pytest.mark.parametrize('jeton_valide', [True, False])
def test_csrf_reel(app, db, environnement, monkeypatch, jeton_valide):
    client = connecter(app)
    data = preparer(client)
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    if not jeton_valide:
        data.pop('csrf_token')
    soumettre(client, data)
    assert (dernier(db) is not None) == jeton_valide
    assert environnement.send_message.call_count == int(jeton_valide)


def test_limite_multipart_appliquee_avant_csrf(app, db, environnement, monkeypatch):
    client = connecter(app)
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    response = client.post('/propositions/nouvelle', data=b'x' * (propositions.MAX_REQUETE + 1),
        content_type='multipart/form-data; boundary=fictif', headers={'Accept': 'application/json'})
    assert response.status_code == 413
    assert '10 Mo' in response.json['error']
    environnement.send_message.assert_not_called()


def test_rendu_mobile_classique_et_flux_xss(app, db, environnement):
    client = connecter(app)
    for agent in ('Mozilla/5.0 desktop', 'Mozilla/5.0 iPhone Mobile'):
        response = client.get('/propositions/nouvelle', headers={'User-Agent': agent})
        assert response.status_code == 200
        assert 'name="besoin"' in response.text and 'multipart/form-data' in response.text
        assert 'data-proposer-amelioration' in response.text
        assert 'name="viewport"' in response.text
    data = preparer(client, '<img src=x onerror=alert(1)>')
    data['besoin'] = '<script>alert("exemple fictif")</script> dans un besoin à décrire.'
    response = soumettre(client, data)
    detail = client.get(response.location).text
    assert '<script>alert("exemple fictif")' not in detail
    assert '&lt;script&gt;' in detail


def test_sauvegarde_restaure_demande_et_pieces(app, db, environnement, tmp_path):
    from resilience import sauvegarder, restaurer, diagnostiquer
    client = connecter(app)
    data = preparer(client)
    data['pieces'] = [(io.BytesIO(b'exemple pour la restauration'), 'modele.txt')]
    soumettre(client, data)
    reference = dernier(db)['id']
    with closing(sqlite3.connect(tmp_path / 'cspilot.db')) as copie:
        db.backup(copie)
    archive = tmp_path.parent / (tmp_path.name + '.cspbackup')
    sauvegarder(tmp_path, archive, 'phrase-fictive-assez-longue',
                arret_confirme=True, secret_key='test-secret-key-for-pytest')
    destination = tmp_path.parent / (tmp_path.name + '-restauree')
    restaurer(archive, destination, 'phrase-fictive-assez-longue')
    with closing(sqlite3.connect(destination / 'cspilot.db')) as conn:
        assert conn.execute('SELECT id FROM propositions_amelioration').fetchone()[0] == reference
        relatif = conn.execute('SELECT fichier_path FROM propositions_pieces').fetchone()[0]
    assert (destination / 'documents' / relatif).read_bytes() == b'exemple pour la restauration'
    assert diagnostiquer(destination, secret_key='test-secret-key-for-pytest')['ok']
