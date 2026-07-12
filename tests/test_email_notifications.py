"""
Libellé des notifications e-mail selon le type de demande (récupération / congé).

Les demandes de congé réutilisent les mêmes constructeurs que les
récupérations : le paramètre `type_libelle` doit adapter l'objet et le corps
pour ne pas parler de « récupération » à propos d'un congé.
"""
import re
import smtplib

import email_service


def _capturer(monkeypatch):
    """Intercepte les envois : renvoie la liste des (sujet, contenu)."""
    calls = []
    monkeypatch.setattr(
        email_service, 'envoyer_email',
        lambda dest, sujet, contenu, prenom='': (calls.append((sujet, contenu)), (True, 'ok'))[1]
    )
    return calls


def test_emails_conge_disent_conge(monkeypatch):
    calls = _capturer(monkeypatch)
    email_service.notifier_nouvelle_demande_recup(
        'Jean', 'a@b.c', 'Marie', '2026-03-09', '2026-03-11', 3, 0, type_libelle='congé')
    email_service.notifier_demande_recup_validee_responsable(
        'a@b.c', 'Dir', 'Jean', 'Marie', '2026-03-09', '2026-03-11', 3, type_libelle='congé')
    email_service.notifier_demande_recup_decision(
        'a@b.c', 'Jean', 'validee', '2026-03-09', '2026-03-11', 3, type_libelle='congé')

    sujets = [s for s, _ in calls]
    assert sujets == [
        'Nouvelle demande de congé',
        'Demande de congé a valider',
        'Demande de congé validee',
    ]
    # Aucun e-mail de congé ne doit parler de « récupération ».
    for sujet, contenu in calls:
        assert 'récupération' not in sujet
        assert 'récupération' not in contenu


def test_emails_recup_restent_recuperation_par_defaut(monkeypatch):
    calls = _capturer(monkeypatch)
    email_service.notifier_nouvelle_demande_recup(
        'Jean', 'a@b.c', 'Marie', '2026-03-09', '2026-03-09', 1, 3.5)  # défaut

    sujet, contenu = calls[0]
    assert sujet == 'Nouvelle demande de récupération'
    assert '3.50h' in contenu  # les heures restent affichées pour une récup


def test_email_conge_masque_les_heures_nulles(monkeypatch):
    calls = _capturer(monkeypatch)
    email_service.notifier_nouvelle_demande_recup(
        'Jean', 'a@b.c', 'Marie', '2026-03-09', '2026-03-11', 3, 0, type_libelle='congé')
    _, contenu = calls[0]
    assert '0.00h' not in contenu       # pas de « - 0.00h » pour un congé
    assert '3 jour(s)' in contenu


def test_publication_cse_construit_le_message(monkeypatch):
    """La diffusion CSE échappe le texte, préserve les sauts de ligne et diffuse
    le même message à tous les destinataires sur un seul envoi groupé."""
    captures = []
    monkeypatch.setattr(
        email_service, 'envoyer_email_multiple',
        lambda dests, sujet, contenu: (
            captures.append((dests, sujet, contenu)), (len(dests), 0, []))[1]
    )
    dests = [('a@b.c', 'Alice'), ('d@e.f', 'Bob')]
    nb_ok, nb_ko, _ = email_service.notifier_publication_cse(
        dests, 'Réunion CSE', 'Ligne 1\nLigne 2 <b>', '2026-07-31', 'Marie Dupont')

    assert (nb_ok, nb_ko) == (2, 0)
    envoyes, sujet, contenu = captures[0]
    assert envoyes == dests                      # diffusé à tout le monde
    assert 'Réunion CSE' in sujet
    assert 'Ligne 1<br>Ligne 2' in contenu       # sauts de ligne convertis
    assert '&lt;b&gt;' in contenu                 # texte échappé (pas de HTML injecté)
    assert 'message du cse' in contenu.lower()
    assert '31/07/2026' in contenu               # date de validité formatée
    assert 'Marie Dupont' in contenu


def test_publication_cse_sans_titre(monkeypatch):
    captures = []
    monkeypatch.setattr(
        email_service, 'envoyer_email_multiple',
        lambda dests, sujet, contenu: (
            captures.append((dests, sujet, contenu)), (len(dests), 0, []))[1]
    )
    email_service.notifier_publication_cse([('a@b.c', 'Alice')], '', 'Bonjour')
    _, sujet, _ = captures[0]
    assert sujet == 'Nouveau message du CSE'


# ── Adresse publique (nom de domaine) pour les liens des emails ──

def test_base_url_normalisation(app, db):
    with app.app_context():
        email_service.save_base_url('cs-pilot.exemple.fr/')
        assert email_service.get_base_url() == 'https://cs-pilot.exemple.fr'   # https ajouté, slash retiré
        email_service.save_base_url('http://192.168.1.10:5000')
        assert email_service.get_base_url() == 'http://192.168.1.10:5000'      # schéma explicite conservé
        email_service.save_base_url('')
        assert email_service.get_base_url() is None                            # effacement


def test_construire_lien_avec_et_sans_base(app, db):
    with app.test_request_context('/'):
        # Sans base configurée : URL absolue reposant sur l'environnement (hôte
        # de la requête en prod ; SERVER_NAME='localhost' dans les tests). On
        # vérifie juste que c'est une URL absolue vers la bonne route.
        email_service.save_base_url('')
        lien = email_service.construire_lien('dashboard_direction_bp.dashboard_direction')
        assert lien.startswith('http://') and lien.endswith('/dashboard_direction')
        # Avec base configurée : le nom de domaine prend le dessus.
        email_service.save_base_url('cs-pilot.mon-centre.fr')
        lien = email_service.construire_lien('dashboard_direction_bp.dashboard_direction')
        assert lien == 'https://cs-pilot.mon-centre.fr/dashboard_direction'


def test_config_email_enregistre_base_url(admin_client, app):
    admin_client.post('/configuration_email', data={
        'sender': 'a@b.fr', 'password': 'secret', 'sender_name': 'CS',
        'smtp_server': 'smtp.gmail.com', 'smtp_port': '587',
        'base_url': 'cs-pilot.mon-centre.fr'})
    with app.app_context():
        assert email_service.get_base_url() == 'https://cs-pilot.mon-centre.fr'
    html = admin_client.get('/configuration_email').get_data(as_text=True)
    # Le champ est repris dans le formulaire, pré-rempli avec la valeur normalisée.
    # (comparaison exacte de l'attribut value, pas une sous-chaîne d'URL)
    m = re.search(r'name="base_url"[^>]*value="([^"]*)"', html)
    assert m is not None, 'champ base_url absent du formulaire'
    assert m.group(1) == 'https://cs-pilot.mon-centre.fr'


# ── Mot de passe conservé si le champ est laissé vide (édition d'un réglage) ──

def test_config_email_conserve_mot_de_passe_si_vide(admin_client, app):
    admin_client.post('/configuration_email', data={
        'sender': 'a@b.fr', 'password': 'secret-initial', 'sender_name': 'CS',
        'smtp_server': 'smtp.gmail.com', 'smtp_port': '587', 'base_url': ''})
    # On ne change QUE le domaine, mot de passe laissé vide → il doit être conservé.
    admin_client.post('/configuration_email', data={
        'sender': 'a@b.fr', 'password': '', 'sender_name': 'CS',
        'smtp_server': 'smtp.gmail.com', 'smtp_port': '587', 'base_url': 'cs-pilot.fr'})
    with app.app_context():
        assert email_service.get_email_config()['password'] == 'secret-initial'
        assert email_service.get_base_url() == 'https://cs-pilot.fr'


def test_config_email_nouveau_mot_de_passe_remplace(admin_client, app):
    admin_client.post('/configuration_email', data={
        'sender': 'a@b.fr', 'password': 'ancien', 'sender_name': 'CS',
        'smtp_server': 'smtp.gmail.com', 'smtp_port': '587', 'base_url': ''})
    admin_client.post('/configuration_email', data={
        'sender': 'a@b.fr', 'password': 'nouveau', 'sender_name': 'CS',
        'smtp_server': 'smtp.gmail.com', 'smtp_port': '587', 'base_url': ''})
    with app.app_context():
        assert email_service.get_email_config()['password'] == 'nouveau'


def test_config_email_premiere_config_exige_mot_de_passe(admin_client, app):
    # Aucun mot de passe existant + champ vide → refus (rien enregistré).
    admin_client.post('/configuration_email', data={
        'sender': 'a@b.fr', 'password': '', 'sender_name': 'CS',
        'smtp_server': 'smtp.gmail.com', 'smtp_port': '587', 'base_url': ''},
        follow_redirects=True)
    with app.app_context():
        assert not email_service.get_email_config().get('password')


def test_config_email_gmail_retire_les_espaces(admin_client, app):
    # Mot de passe d'application collé avec les espaces d'affichage → nettoyé
    # pour Gmail (Gmail refuse les espaces).
    admin_client.post('/configuration_email', data={
        'sender': 'a@b.fr', 'password': 'abcd efgh ijkl mnop', 'sender_name': 'CS',
        'smtp_server': 'smtp.gmail.com', 'smtp_port': '587', 'base_url': ''})
    with app.app_context():
        assert email_service.get_email_config()['password'] == 'abcdefghijklmnop'


def test_config_email_non_gmail_preserve_les_espaces(admin_client, app):
    # Autre serveur SMTP : un mot de passe avec espaces est conservé tel quel.
    admin_client.post('/configuration_email', data={
        'sender': 'a@b.fr', 'password': 'mon pass', 'sender_name': 'CS',
        'smtp_server': 'smtp.ovh.net', 'smtp_port': '587', 'base_url': ''})
    with app.app_context():
        assert email_service.get_email_config()['password'] == 'mon pass'


# ── Diagnostic d'échec d'authentification : remonter la réponse du serveur ──

def test_message_auth_inclut_la_reponse_du_serveur():
    err = smtplib.SMTPAuthenticationError(
        535, b'5.7.8 Username and Password not accepted. https://support.google.com/... - gsmtp')
    msg = email_service._message_auth_refusee(err)
    assert msg.lower().startswith("echec d'authentification")
    assert 'Reponse du serveur' in msg
    assert 'Username and Password not accepted' in msg   # la cause exacte est visible


def test_message_auth_sans_reponse_serveur():
    # Pas de corps de réponse → on garde le message générique, sans « None ».
    err = smtplib.SMTPAuthenticationError(535, None)
    msg = email_service._message_auth_refusee(err)
    assert 'Reponse du serveur' not in msg
    assert 'None' not in msg


def test_envoyer_email_auth_refusee_remonte_la_reponse(app, db, monkeypatch):
    with app.app_context():
        email_service.save_email_config('smtp.gmail.com', '587', 'a@b.fr', 'x' * 16, 'CS')

        def _refuser(config):
            raise smtplib.SMTPAuthenticationError(
                535, b'5.7.8 Username and Password not accepted')

        monkeypatch.setattr(email_service, '_ouvrir_connexion_smtp', _refuser)
        ok, msg = email_service.envoyer_email('dest@x.fr', 'Sujet', '<p>x</p>')
    assert ok is False
    assert 'Username and Password not accepted' in msg   # remonté à l'utilisateur


# ── Avertissement de longueur : 16 caractères attendus pour Gmail ──

def test_config_email_gmail_longueur_incorrecte_avertit(admin_client):
    # « trop court » → espaces retirés → 9 caractères ≠ 16 → avertissement.
    r = admin_client.post('/configuration_email', data={
        'sender': 'a@b.fr', 'password': 'trop court', 'sender_name': 'CS',
        'smtp_server': 'smtp.gmail.com', 'smtp_port': '587', 'base_url': ''},
        follow_redirects=True)
    assert 'or celui saisi en fait' in r.get_data(as_text=True)


def test_config_email_gmail_16_caracteres_pas_d_avertissement(admin_client):
    r = admin_client.post('/configuration_email', data={
        'sender': 'a@b.fr', 'password': 'abcdefghijklmnop', 'sender_name': 'CS',
        'smtp_server': 'smtp.gmail.com', 'smtp_port': '587', 'base_url': ''},
        follow_redirects=True)
    assert 'or celui saisi en fait' not in r.get_data(as_text=True)


def test_config_email_champ_vide_pas_d_avertissement(admin_client):
    # Config initiale valide puis on ne touche qu'au domaine : aucun avertissement
    # (le mot de passe conservé n'est pas re-jugé).
    admin_client.post('/configuration_email', data={
        'sender': 'a@b.fr', 'password': 'abcdefghijklmnop', 'sender_name': 'CS',
        'smtp_server': 'smtp.gmail.com', 'smtp_port': '587', 'base_url': ''})
    r = admin_client.post('/configuration_email', data={
        'sender': 'a@b.fr', 'password': '', 'sender_name': 'CS',
        'smtp_server': 'smtp.gmail.com', 'smtp_port': '587', 'base_url': 'cs-pilot.fr'},
        follow_redirects=True)
    assert 'or celui saisi en fait' not in r.get_data(as_text=True)


def test_config_email_non_gmail_pas_d_avertissement_longueur(admin_client):
    # Serveur non-Gmail : la règle des 16 caractères ne s'applique pas.
    r = admin_client.post('/configuration_email', data={
        'sender': 'a@b.fr', 'password': 'court', 'sender_name': 'CS',
        'smtp_server': 'smtp.ovh.net', 'smtp_port': '587', 'base_url': ''},
        follow_redirects=True)
    assert 'or celui saisi en fait' not in r.get_data(as_text=True)
