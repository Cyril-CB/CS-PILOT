"""
Tests d'accès et d'isolation du planificateur (blueprint planificateur_bp).

Le planning est strictement personnel : toutes les requêtes sont filtrées par
`user_id`. Ces tests couvrent le versant négatif, jusqu'ici absent :

- un utilisateur autorisé ne peut pas MUTER la tâche, le bloc ou la récurrence
  d'un autre utilisateur (IDOR), et la ressource visée reste strictement
  inchangée en base après la tentative ;
- aucune route du planificateur n'est accessible sans connexion ;
- un profil hors `PROFILS_AUTORISES` est refusé par le décorateur
  `planif_required` (réponse JSON sur les API, redirection sur la page).

Piège : les fixtures de clients authentifiés partagent le même client de test.
Pour enchaîner deux profils dans un même test, on utilise la fixture `client`
avec des connexions explicites.
"""
import re
from datetime import date, timedelta

import pytest


# ──────────────────────────────────────────────────────────────────────────
# Utilitaires
# ──────────────────────────────────────────────────────────────────────────

def _connexion(client, login, mot_de_passe):
    """Connecte le client de test avec le compte demandé."""
    reponse = client.post('/login', data={'login': login, 'password': mot_de_passe},
                          follow_redirects=True)
    assert reponse.status_code == 200
    return reponse


def _deconnexion(client):
    """Termine la session en cours (avant de connecter un autre profil)."""
    return client.get('/logout', follow_redirects=True)


def _creer_prestataire(db):
    """Crée le compte prestataire paie (profil hors périmètre du planificateur)."""
    from werkzeug.security import generate_password_hash
    db.execute(
        "INSERT INTO users (nom, prenom, login, password, profil) "
        "VALUES ('Cabinet', 'Paie', 'presta_test', ?, 'prestataire')",
        (generate_password_hash('presta123'),)
    )
    db.commit()


def _etat_planning(db, user_id):
    """Photographie complète du planning d'un utilisateur.

    Sert à vérifier qu'une tentative refusée n'a rien modifié : ni la tâche ou
    le bloc visé, ni le reste du planning (blocs orphelins, tâche « suite »
    créée par `terminer_partiel`, occurrences d'une récurrence supprimée...).
    """
    return {
        'taches': [dict(r) for r in db.execute(
            'SELECT * FROM planif_taches WHERE user_id = ? ORDER BY id',
            (user_id,)).fetchall()],
        'blocs': [dict(r) for r in db.execute(
            'SELECT * FROM planif_blocs WHERE user_id = ? ORDER BY id',
            (user_id,)).fetchall()],
        'recurrences': [dict(r) for r in db.execute(
            'SELECT * FROM planif_recurrences WHERE user_id = ? ORDER BY id',
            (user_id,)).fetchall()],
    }


def _payloads_tache():
    """Corps valide pour chaque route de mutation d'une tâche.

    Les payloads sont volontairement corrects : le refus attendu doit venir du
    contrôle de propriété, pas d'une validation d'entrée.
    """
    return {
        '': {'titre': 'Titre détourné', 'duree_min': 15},
        '/supprimer': {},
        '/statut': {'statut': 'fait'},
        '/reporter': {'date_min': (date.today() + timedelta(days=7)).isoformat()},
        '/terminer_partiel': {'minutes_faites': 30},
    }


def _payloads_bloc():
    """Corps valide pour chaque route de mutation d'un bloc."""
    return {
        '/statut': {'statut': 'fait'},
        '/supprimer': {},
        '/deplacer': {'date': (date.today() + timedelta(days=1)).isoformat(),
                      'heure_debut': '09:00'},
        '/verrou': {'verrouille': 1},
    }


def _routes_planificateur(app):
    """Toutes les routes du planificateur, identifiants d'URL remplacés par 1.

    L'énumération vient de la table de routage : une nouvelle route est donc
    automatiquement soumise au test « non connecté ».
    """
    routes = []
    for regle in app.url_map.iter_rules():
        if not regle.rule.startswith('/planificateur'):
            continue
        methode = 'POST' if 'POST' in regle.methods else 'GET'
        routes.append((methode, re.sub(r'<[^>]+>', '1', regle.rule)))
    return sorted(routes)


@pytest.fixture
def donnees_comptable(client, db, sample_users):
    """Tâche (avec son bloc) et récurrence appartenant au comptable.

    À la sortie, le client est connecté en tant que salarié : c'est lui qui
    tentera d'agir sur les ressources d'autrui.
    """
    _connexion(client, 'compta_test', 'compta123')

    reponse = client.post('/planificateur/api/tache', json={
        'type': 'tache', 'titre': 'Dossier confidentiel', 'duree_min': 60,
        'secable': 0, 'duree_min_bloc': 60,
    })
    assert reponse.status_code == 200

    reponse = client.post('/planificateur/api/recurrence', json={
        'titre': 'Point hebdo comptable', 'frequence': 'hebdomadaire',
        'duree_min': 30, 'jour_semaine': 0,
    })
    assert reponse.status_code == 200

    # Le bloc est relu APRÈS la création de la récurrence : la replanification
    # recrée les blocs non verrouillés (leur identifiant change).
    tache = db.execute(
        "SELECT id FROM planif_taches WHERE titre = 'Dossier confidentiel'").fetchone()
    bloc = db.execute(
        'SELECT id FROM planif_blocs WHERE tache_id = ?', (tache['id'],)).fetchone()
    recurrence = db.execute(
        "SELECT id FROM planif_recurrences WHERE titre = 'Point hebdo comptable'").fetchone()
    assert bloc is not None, "la tâche du comptable doit avoir au moins un bloc"

    _deconnexion(client)
    _connexion(client, 'salarie_test', 'sal123')

    return {
        'tache_id': tache['id'],
        'bloc_id': bloc['id'],
        'recurrence_id': recurrence['id'],
        'proprietaire_id': sample_users['comptable_id'],
    }


# ──────────────────────────────────────────────────────────────────────────
# Isolation entre utilisateurs (IDOR)
# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('suffixe', ['', '/supprimer', '/statut', '/reporter',
                                     '/terminer_partiel'])
def test_mutation_tache_autrui_refusee(client, db, donnees_comptable, suffixe):
    """Un salarié ne peut pas modifier la tâche d'un autre utilisateur."""
    tache_id = donnees_comptable['tache_id']
    avant = _etat_planning(db, donnees_comptable['proprietaire_id'])

    reponse = client.post(f'/planificateur/api/tache/{tache_id}{suffixe}',
                          json=_payloads_tache()[suffixe])

    assert reponse.status_code == 404
    corps = reponse.get_json()
    assert corps['ok'] is False
    assert corps['erreur'] == 'Tache introuvable.'
    assert _etat_planning(db, donnees_comptable['proprietaire_id']) == avant


@pytest.mark.parametrize('suffixe', ['/statut', '/supprimer', '/deplacer', '/verrou'])
def test_mutation_bloc_autrui_refusee(client, db, donnees_comptable, suffixe):
    """Un salarié ne peut pas agir sur le créneau d'un autre utilisateur."""
    bloc_id = donnees_comptable['bloc_id']
    avant = _etat_planning(db, donnees_comptable['proprietaire_id'])

    reponse = client.post(f'/planificateur/api/bloc/{bloc_id}{suffixe}',
                          json=_payloads_bloc()[suffixe])

    assert reponse.status_code == 404
    corps = reponse.get_json()
    assert corps['ok'] is False
    assert corps['erreur'] == 'Bloc introuvable.'
    assert _etat_planning(db, donnees_comptable['proprietaire_id']) == avant


def test_supprimer_recurrence_autrui_refusee(client, db, donnees_comptable):
    """Un salarié ne peut pas supprimer la récurrence d'un autre utilisateur."""
    avant = _etat_planning(db, donnees_comptable['proprietaire_id'])

    reponse = client.post(
        f'/planificateur/api/recurrence/{donnees_comptable["recurrence_id"]}/supprimer',
        json={})

    assert reponse.status_code == 404
    corps = reponse.get_json()
    assert corps['ok'] is False
    assert corps['erreur'] == 'Recurrence introuvable.'
    # Ni la récurrence ni ses occurrences (et leurs blocs) ne doivent bouger.
    assert _etat_planning(db, donnees_comptable['proprietaire_id']) == avant


def test_comparaisons_ne_reevaluent_pas_la_tache_dautrui(client, db, donnees_comptable):
    """La priorité relative ne peut pas servir à réécrire la tâche d'autrui.

    Des réponses de comparaison incohérentes réévaluent la tâche mal estimée :
    ce chemin d'écriture ne doit s'appliquer qu'aux tâches de l'utilisateur
    connecté.
    """
    tache_id = donnees_comptable['tache_id']
    avant = _etat_planning(db, donnees_comptable['proprietaire_id'])

    reponse = client.post('/planificateur/api/tache', json={
        'type': 'tache', 'titre': 'Tâche du salarié', 'duree_min': 30,
        'comparaisons': [{'tache_id': tache_id, 'reponse': 'superieur'}],
    })

    assert reponse.status_code == 200
    assert _etat_planning(db, donnees_comptable['proprietaire_id']) == avant


def test_le_proprietaire_conserve_ses_donnees_apres_les_tentatives(client, db,
                                                                   donnees_comptable):
    """Après une série de tentatives refusées, le comptable retrouve tout.

    Vérification de bout en bout : le planning est relu par son propriétaire via
    l'API, pas seulement en base.
    """
    tache_id = donnees_comptable['tache_id']
    bloc_id = donnees_comptable['bloc_id']
    for chemin, payload in (
        (f'/planificateur/api/tache/{tache_id}/supprimer', {}),
        (f'/planificateur/api/tache/{tache_id}/statut', {'statut': 'fait'}),
        (f'/planificateur/api/bloc/{bloc_id}/supprimer', {}),
        (f'/planificateur/api/bloc/{bloc_id}/statut', {'statut': 'fait'}),
    ):
        assert client.post(chemin, json=payload).status_code == 404

    _deconnexion(client)
    _connexion(client, 'compta_test', 'compta123')

    debut = date.today().isoformat()
    fin = (date.today() + timedelta(days=90)).isoformat()
    donnees = client.get(
        f'/planificateur/api/blocs?debut={debut}&fin={fin}').get_json()
    assert donnees['ok'] is True
    assert any(b['id'] == bloc_id and b['tache_id'] == tache_id
               and b['titre'] == 'Dossier confidentiel'
               and b['statut'] == 'planifie'
               for b in donnees['blocs'])


# ──────────────────────────────────────────────────────────────────────────
# Accès non connecté
# ──────────────────────────────────────────────────────────────────────────

def test_toutes_les_routes_refusent_un_anonyme(client, app):
    """Aucune route du planificateur n'est servie sans connexion."""
    routes = _routes_planificateur(app)
    # Garde-fou : le blueprint expose 16 routes, dont 15 sous /planificateur/api.
    assert len(routes) >= 16

    for methode, chemin in routes:
        reponse = (client.post(chemin, json={}) if methode == 'POST'
                   else client.get(chemin))
        assert reponse.status_code == 302, f'{methode} {chemin}'
        assert '/login' in reponse.headers['Location'], f'{methode} {chemin}'


def test_mutations_anonymes_sans_effet(client, db, donnees_comptable):
    """Un anonyme ne peut rien changer aux données d'un utilisateur existant."""
    tache_id = donnees_comptable['tache_id']
    bloc_id = donnees_comptable['bloc_id']
    avant = _etat_planning(db, donnees_comptable['proprietaire_id'])
    _deconnexion(client)

    for chemin, payload in (
        (f'/planificateur/api/tache/{tache_id}/supprimer', {}),
        (f'/planificateur/api/tache/{tache_id}/statut', {'statut': 'fait'}),
        (f'/planificateur/api/bloc/{bloc_id}/supprimer', {}),
        (f'/planificateur/api/recurrence/{donnees_comptable["recurrence_id"]}/supprimer', {}),
    ):
        reponse = client.post(chemin, json=payload)
        assert reponse.status_code == 302, chemin
        assert '/login' in reponse.headers['Location'], chemin

    assert _etat_planning(db, donnees_comptable['proprietaire_id']) == avant


# ──────────────────────────────────────────────────────────────────────────
# Décorateur planif_required : profil non autorisé
# ──────────────────────────────────────────────────────────────────────────

def test_planif_required_refuse_les_api_au_profil_non_autorise(prestataire_client):
    """Un profil hors périmètre reçoit un refus JSON explicite sur les API."""
    from blueprints.planificateur import PROFILS_AUTORISES
    assert 'prestataire' not in PROFILS_AUTORISES

    for chemin in ('/planificateur/api/replanifier',
                   '/planificateur/api/tache',
                   '/planificateur/api/recurrence'):
        reponse = prestataire_client.post(chemin, json={'titre': 'X', 'duree_min': 30})
        assert reponse.status_code == 403, chemin
        assert reponse.get_json() == {'ok': False, 'erreur': 'Acces refuse.'}, chemin

    # La lecture des blocs est refusée de la même façon (aucune fuite de données).
    reponse = prestataire_client.get('/planificateur/api/blocs',
                                     headers={'X-Requested-With': 'XMLHttpRequest'})
    assert reponse.status_code == 403
    assert reponse.get_json()['ok'] is False


def test_planif_required_redirige_la_page_du_profil_non_autorise(prestataire_client):
    """Sur la page HTML, le refus prend la forme d'une redirection avec message."""
    reponse = prestataire_client.get('/planificateur', follow_redirects=False)
    assert reponse.status_code == 302
    assert '/dashboard' in reponse.headers['Location']

    # Le message flash est échappé par Jinja (l'apostrophe devient &#39;) :
    # on cherche la partie stable du libellé.
    suite = prestataire_client.get('/planificateur', follow_redirects=True)
    assert 'est pas accessible pour votre profil' in suite.get_data(as_text=True)


def test_profil_non_autorise_refuse_avant_le_controle_de_propriete(client, db,
                                                                   donnees_comptable):
    """Le contrôle de profil précède celui de la propriété : 403, et rien ne bouge."""
    avant = _etat_planning(db, donnees_comptable['proprietaire_id'])
    _deconnexion(client)
    _creer_prestataire(db)
    _connexion(client, 'presta_test', 'presta123')

    reponse = client.post(
        f'/planificateur/api/tache/{donnees_comptable["tache_id"]}/supprimer', json={})
    assert reponse.status_code == 403
    assert reponse.get_json()['erreur'] == 'Acces refuse.'
    assert _etat_planning(db, donnees_comptable['proprietaire_id']) == avant
