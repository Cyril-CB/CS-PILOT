"""
Libellé des notifications e-mail selon le type de demande (récupération / congé).

Les demandes de congé réutilisent les mêmes constructeurs que les
récupérations : le paramètre `type_libelle` doit adapter l'objet et le corps
pour ne pas parler de « récupération » à propos d'un congé.
"""
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
