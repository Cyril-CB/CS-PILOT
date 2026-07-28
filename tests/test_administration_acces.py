"""
Tests de contrôle d'accès des écrans d'administration système.

Enjeu : ces routes sont les plus destructrices de l'application (application de
migrations, réinitialisation complète de la base, activation/désactivation de
comptes, secrets des fournisseurs IA). Une entrée de menu masquée ne constitue
pas un contrôle d'accès : on vérifie ici que le serveur refuse réellement, et
surtout qu'un refus est **sans effet** sur les données.

Règles observées dans le code testé :
- `blueprints/administration.py` : `_check_admin()` n'autorise que `directeur`
  et `comptable`. Tout autre profil est redirigé vers le tableau de bord.
- `blueprints/admin.py` : mêmes profils autorisés (`directeur`, `comptable`) ;
  le `responsable` n'est jamais autorisé sur ces écrans.
- `blueprints/api_keys.py` : `PROFILS_AUTORISES` = `directeur`, `comptable` ;
  les routes JSON répondent 403 au lieu d'une redirection.

Les fixtures de clients authentifiés partagent le MÊME client de test : les
tests qui enchaînent plusieurs profils utilisent `client` et gèrent les
connexions explicitement.
"""
import os

import pytest


# Profils qui ne doivent JAMAIS accéder à l'administration système.
PROFILS_REFUSES = [
    ('salarie_test', 'sal123'),
    ('resp_test', 'resp123'),
]


def _connexion(client, login, mot_de_passe):
    """Connecte le client de test avec le profil demandé."""
    return client.post(
        '/login',
        data={'login': login, 'password': mot_de_passe},
        follow_redirects=True,
    )


def _deconnexion(client):
    """Ferme la session courante du client de test."""
    return client.get('/logout', follow_redirects=True)


def _etat_base(db):
    """Photographie l'état sensible de la base (tables, comptes, migrations).

    Sert de témoin : après une tentative refusée, l'état doit être identique.
    """
    tables = [
        row['name'] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]
    users = [
        tuple(row) for row in db.execute(
            "SELECT id, login, profil, actif, password FROM users ORDER BY id"
        ).fetchall()
    ]
    migrations = [
        tuple(row) for row in db.execute(
            "SELECT version, statut, appliquee_par FROM schema_migrations "
            "ORDER BY version"
        ).fetchall()
    ]
    return {'tables': tables, 'users': users, 'migrations': migrations}


def _est_redirection_connexion(reponse):
    """Vrai si la réponse renvoie l'anonyme vers le formulaire de connexion."""
    return reponse.status_code in (301, 302) and '/login' in reponse.headers.get('Location', '')


def _est_redirection_tableau_de_bord(reponse):
    """Vrai si la réponse renvoie un profil authentifié mais non autorisé."""
    return reponse.status_code in (301, 302) and '/dashboard' in reponse.headers.get('Location', '')


class TestAdministrationSysteme:
    """Page d'administration et opérations de migration (`_check_admin()`).

    Enjeu : la consultation expose le nom du fichier de base, sa taille et le
    volume de chaque table ; les POST modifient le schéma. Réservé à la
    direction et à la comptabilité.
    """

    def test_page_administration_refusee_hors_direction(self, client, sample_users):
        """Anonyme, salarié et responsable ne doivent pas voir l'inventaire des tables."""
        reponse = client.get('/administration', follow_redirects=False)
        assert _est_redirection_connexion(reponse)

        for login, mot_de_passe in PROFILS_REFUSES:
            _connexion(client, login, mot_de_passe)
            reponse = client.get('/administration', follow_redirects=False)
            assert _est_redirection_tableau_de_bord(reponse), (
                f"Le profil {login} ne doit pas accéder à /administration"
            )
            _deconnexion(client)

    def test_page_administration_refusee_prestataire(self, prestataire_client):
        """Le prestataire paie (cabinet externe) n'a rien à faire côté système."""
        reponse = prestataire_client.get('/administration', follow_redirects=False)
        assert _est_redirection_tableau_de_bord(reponse)

    def test_page_administration_ouverte_direction_et_comptabilite(self, client, sample_users):
        """Cas légitime : directeur et comptable consultent bien la page."""
        for login, mot_de_passe in (('admin', 'Admin1234'), ('compta_test', 'compta123')):
            _connexion(client, login, mot_de_passe)
            reponse = client.get('/administration')
            assert reponse.status_code == 200, f"{login} doit accéder à /administration"
            _deconnexion(client)

    @pytest.mark.parametrize('url, donnees', [
        ('/administration/appliquer_migration', {'version': '0001'}),
        ('/administration/appliquer_toutes', {}),
        ('/administration/initialiser_baseline', {}),
    ])
    def test_operations_migration_refusees_et_sans_effet(
        self, url, donnees, app, db, client, sample_users
    ):
        """Aucun profil non autorisé ne peut toucher au schéma de la base.

        On compare l'historique `schema_migrations` avant/après : un refus doit
        laisser la base strictement identique.
        """
        avant = _etat_base(db)

        # Non connecté : renvoyé vers la connexion.
        reponse = client.post(url, data=donnees, follow_redirects=False)
        assert _est_redirection_connexion(reponse)

        # Salarié et responsable : renvoyés vers leur tableau de bord.
        for login, mot_de_passe in PROFILS_REFUSES:
            _connexion(client, login, mot_de_passe)
            reponse = client.post(url, data=donnees, follow_redirects=False)
            assert _est_redirection_tableau_de_bord(reponse), (
                f"Le profil {login} ne doit pas déclencher {url}"
            )
            _deconnexion(client)

        assert _etat_base(db) == avant, (
            f"Une tentative refusée sur {url} a modifié la base"
        )

    def test_appliquer_migration_sans_version_refuse_cote_direction(self, db, admin_client):
        """Entrée invalide : une version manquante est rejetée, sans effet en base."""
        avant = _etat_base(db)

        reponse = admin_client.post(
            '/administration/appliquer_migration', data={}, follow_redirects=False
        )
        assert reponse.status_code in (301, 302)
        assert '/administration' in reponse.headers.get('Location', '')

        assert _etat_base(db) == avant


class TestReinitialisationBaseDeDonnees:
    """POST /administration/reinitialiser_bdd — route la plus dangereuse.

    Elle supprime le fichier SQLite et recrée un schéma vide : toutes les
    données RH, paie et comptables sont perdues. On ne déclenche JAMAIS le cas
    positif dans un test ; on prouve uniquement que le refus protège les
    données, et qu'aucune sauvegarde `.avant_reinit` n'est même amorcée.
    """

    def test_reinitialisation_refusee_hors_direction_et_base_intacte(
        self, app, db, client, sample_users
    ):
        """Anonyme, salarié et responsable : refus et base strictement intacte."""
        import database

        avant = _etat_base(db)
        assert avant['users'], 'Le jeu de données de test doit contenir des comptes'
        chemin_base = database.DATABASE
        chemin_sauvegarde = chemin_base + '.avant_reinit'

        donnees = {'confirmation': 'REINITIALISER'}

        reponse = client.post(
            '/administration/reinitialiser_bdd', data=donnees, follow_redirects=False
        )
        assert _est_redirection_connexion(reponse)

        for login, mot_de_passe in PROFILS_REFUSES:
            _connexion(client, login, mot_de_passe)
            reponse = client.post(
                '/administration/reinitialiser_bdd', data=donnees, follow_redirects=False
            )
            assert _est_redirection_tableau_de_bord(reponse), (
                f"Le profil {login} ne doit pas réinitialiser la base"
            )
            _deconnexion(client)

        assert os.path.exists(chemin_base), 'Le fichier de base a été supprimé'
        assert not os.path.exists(chemin_sauvegarde), (
            'La branche destructrice a été atteinte malgré le refus'
        )
        assert _etat_base(db) == avant, 'Les données ont été altérées malgré le refus'

    def test_reinitialisation_refusee_prestataire(self, app, db, prestataire_client):
        """Le prestataire paie ne peut pas non plus effacer la base."""
        import database

        avant = _etat_base(db)
        reponse = prestataire_client.post(
            '/administration/reinitialiser_bdd',
            data={'confirmation': 'REINITIALISER'},
            follow_redirects=False,
        )
        assert _est_redirection_tableau_de_bord(reponse)
        assert os.path.exists(database.DATABASE)
        assert not os.path.exists(database.DATABASE + '.avant_reinit')
        assert _etat_base(db) == avant

    @pytest.mark.parametrize('donnees', [
        {},
        {'confirmation': ''},
        {'confirmation': 'reinitialiser'},
        {'confirmation': 'OUI'},
    ])
    def test_jeton_de_confirmation_invalide_annule_la_reinitialisation(
        self, donnees, app, db, admin_client
    ):
        """Même pour un directeur, un jeton de confirmation incorrect annule tout.

        Le jeton attendu est exactement « REINITIALISER » (sensible à la casse).
        """
        import database

        avant = _etat_base(db)

        reponse = admin_client.post(
            '/administration/reinitialiser_bdd', data=donnees, follow_redirects=False
        )
        assert reponse.status_code in (301, 302)
        assert '/administration' in reponse.headers.get('Location', '')

        assert os.path.exists(database.DATABASE)
        assert not os.path.exists(database.DATABASE + '.avant_reinit')
        assert _etat_base(db) == avant


class TestAdministrationUtilisateurs:
    """Écrans de gestion des comptes et référentiels (`blueprints/admin.py`).

    Enjeu : activer/désactiver un compte, changer un profil ou un mot de passe
    revient à donner ou retirer l'accès à toute l'application.
    """

    def test_toggle_user_refuse_et_statut_inchange(self, db, client, sample_users):
        """Personne hors direction/comptabilité ne peut désactiver un compte."""
        cible = sample_users['salarie_id']
        url = f'/toggle_user/{cible}'
        statut_initial = db.execute(
            'SELECT actif FROM users WHERE id = ?', (cible,)
        ).fetchone()['actif']

        reponse = client.post(url, follow_redirects=False)
        assert _est_redirection_connexion(reponse)

        for login, mot_de_passe in PROFILS_REFUSES:
            _connexion(client, login, mot_de_passe)
            reponse = client.post(url, follow_redirects=False)
            assert _est_redirection_tableau_de_bord(reponse), (
                f"Le profil {login} ne doit pas basculer le statut d'un compte"
            )
            _deconnexion(client)

        statut_final = db.execute(
            'SELECT actif FROM users WHERE id = ?', (cible,)
        ).fetchone()['actif']
        assert statut_final == statut_initial

    def test_toggle_user_refuse_prestataire(self, db, prestataire_client, sample_users):
        """Le prestataire paie ne peut pas désactiver un salarié."""
        cible = sample_users['salarie_id']
        statut_initial = db.execute(
            'SELECT actif FROM users WHERE id = ?', (cible,)
        ).fetchone()['actif']

        reponse = prestataire_client.post(f'/toggle_user/{cible}', follow_redirects=False)
        assert _est_redirection_tableau_de_bord(reponse)
        assert db.execute(
            'SELECT actif FROM users WHERE id = ?', (cible,)
        ).fetchone()['actif'] == statut_initial

    def test_modifier_user_refuse_et_compte_inchange(self, db, client, sample_users):
        """Ni consultation ni modification d'une fiche utilisateur hors habilitation.

        La tentative vise une élévation de privilège classique : un salarié qui
        se promeut « directeur » et se choisit un nouveau mot de passe.
        """
        cible = sample_users['salarie_id']
        url = f'/modifier_user/{cible}'
        avant = tuple(db.execute(
            'SELECT nom, prenom, login, profil, password FROM users WHERE id = ?',
            (cible,)
        ).fetchone())

        donnees = {
            'nom': 'Pirate',
            'prenom': 'Jean',
            'login': 'salarie_test',
            'profil': 'directeur',
            'nouveau_password': 'Pirate1234',
        }

        reponse = client.post(url, data=donnees, follow_redirects=False)
        assert _est_redirection_connexion(reponse)
        assert _est_redirection_connexion(client.get(url, follow_redirects=False))

        for login, mot_de_passe in PROFILS_REFUSES:
            _connexion(client, login, mot_de_passe)
            assert _est_redirection_tableau_de_bord(
                client.get(url, follow_redirects=False)
            ), f"Le profil {login} ne doit pas consulter la fiche d'un autre compte"
            assert _est_redirection_tableau_de_bord(
                client.post(url, data=donnees, follow_redirects=False)
            ), f"Le profil {login} ne doit pas modifier un compte"
            _deconnexion(client)

        apres = tuple(db.execute(
            'SELECT nom, prenom, login, profil, password FROM users WHERE id = ?',
            (cible,)
        ).fetchone())
        assert apres == avant, 'Le compte a été modifié malgré le refus'

    def test_gestion_secteurs_refusee_et_referentiel_inchange(self, db, client, sample_users):
        """Le référentiel des secteurs structure budgets et plannings : lecture
        et écriture réservées à la direction et à la comptabilité."""
        nb_avant = db.execute('SELECT COUNT(*) AS nb FROM secteurs').fetchone()['nb']
        donnees = {
            'action': 'ajouter',
            'nom': 'Secteur Intrus',
            'description': 'Créé par une tentative non autorisée',
        }

        assert _est_redirection_connexion(
            client.get('/gestion_secteurs', follow_redirects=False)
        )
        assert _est_redirection_connexion(
            client.post('/gestion_secteurs', data=donnees, follow_redirects=False)
        )

        for login, mot_de_passe in PROFILS_REFUSES:
            _connexion(client, login, mot_de_passe)
            assert _est_redirection_tableau_de_bord(
                client.get('/gestion_secteurs', follow_redirects=False)
            )
            assert _est_redirection_tableau_de_bord(
                client.post('/gestion_secteurs', data=donnees, follow_redirects=False)
            )
            # Tentative de suppression du secteur de rattachement.
            assert _est_redirection_tableau_de_bord(client.post(
                '/gestion_secteurs',
                data={'action': 'supprimer', 'secteur_id': sample_users['secteur_id']},
                follow_redirects=False,
            ))
            _deconnexion(client)

        assert db.execute('SELECT COUNT(*) AS nb FROM secteurs').fetchone()['nb'] == nb_avant
        assert db.execute(
            'SELECT COUNT(*) AS nb FROM secteurs WHERE nom = ?', ('Secteur Intrus',)
        ).fetchone()['nb'] == 0
        assert db.execute(
            'SELECT COUNT(*) AS nb FROM secteurs WHERE id = ?', (sample_users['secteur_id'],)
        ).fetchone()['nb'] == 1

    def test_gestion_jours_feries_refusee_et_calendrier_inchange(self, db, client, sample_users):
        """Les jours fériés pilotent les compteurs de temps : un ajout sauvage
        fausserait les heures théoriques de toute l'association."""
        nb_avant = db.execute('SELECT COUNT(*) AS nb FROM jours_feries').fetchone()['nb']
        donnees = {
            'action': 'ajouter',
            'date': '2026-03-17',
            'libelle': 'Jour férié frauduleux',
        }

        assert _est_redirection_connexion(
            client.get('/gestion_jours_feries', follow_redirects=False)
        )
        assert _est_redirection_connexion(
            client.post('/gestion_jours_feries', data=donnees, follow_redirects=False)
        )

        for login, mot_de_passe in PROFILS_REFUSES:
            _connexion(client, login, mot_de_passe)
            assert _est_redirection_tableau_de_bord(
                client.get('/gestion_jours_feries', follow_redirects=False)
            )
            assert _est_redirection_tableau_de_bord(
                client.post('/gestion_jours_feries', data=donnees, follow_redirects=False)
            )
            _deconnexion(client)

        assert db.execute('SELECT COUNT(*) AS nb FROM jours_feries').fetchone()['nb'] == nb_avant
        assert db.execute(
            'SELECT COUNT(*) AS nb FROM jours_feries WHERE date = ?', ('2026-03-17',)
        ).fetchone()['nb'] == 0


class TestClesApiFournisseursIA:
    """Écrans et API des clés des fournisseurs IA (`blueprints/api_keys.py`).

    Enjeu : ces clés sont des secrets facturables. Un profil non autorisé ne
    doit ni les lire, ni les remplacer, ni les supprimer — et aucune réponse ne
    doit contenir la clé en clair.
    """

    CLE_FACTICE = 'sk-CLE-DE-TEST-NE-PAS-UTILISER-0123456789'

    @pytest.fixture
    def cle_enregistree(self, app):
        """Enregistre une clé OpenAI factice dans les réglages chiffrés."""
        from utils import save_setting

        with app.app_context():
            save_setting('openai_api_key', self.CLE_FACTICE)
        return self.CLE_FACTICE

    @staticmethod
    def _interdire_appel_reseau(monkeypatch):
        """Fait échouer tout appel HTTP sortant : un refus ne doit rien appeler."""
        import blueprints.api_keys as api_keys

        def _refuser(*args, **kwargs):
            raise AssertionError('Aucun appel au fournisseur IA ne doit être émis')

        monkeypatch.setattr(api_keys.http_requests, 'post', _refuser)

    def test_page_cles_api_refusee_et_aucune_fuite(self, client, sample_users, cle_enregistree):
        """La page de gestion des clés reste inaccessible et ne fuit rien."""
        assert _est_redirection_connexion(
            client.get('/gestion_cles_api', follow_redirects=False)
        )

        for login, mot_de_passe in PROFILS_REFUSES:
            _connexion(client, login, mot_de_passe)
            reponse = client.get('/gestion_cles_api', follow_redirects=False)
            assert _est_redirection_tableau_de_bord(reponse), (
                f"Le profil {login} ne doit pas accéder à /gestion_cles_api"
            )
            # Même en suivant la redirection, la clé ne doit apparaître nulle part.
            suivie = client.get('/gestion_cles_api', follow_redirects=True)
            assert cle_enregistree not in suivie.get_data(as_text=True)
            _deconnexion(client)

    def test_statut_cles_refuse_en_403_sans_divulgation(
        self, client, sample_users, cle_enregistree
    ):
        """L'API de statut répond 403 (JSON) et ne renvoie aucun secret."""
        assert _est_redirection_connexion(
            client.get('/api/api_keys/status', follow_redirects=False)
        )

        for login, mot_de_passe in PROFILS_REFUSES:
            _connexion(client, login, mot_de_passe)
            reponse = client.get('/api/api_keys/status')
            assert reponse.status_code == 403
            corps = reponse.get_data(as_text=True)
            assert cle_enregistree not in corps
            assert 'configured' not in corps
            _deconnexion(client)

    def test_enregistrement_cle_refuse_sans_ecriture_ni_appel_reseau(
        self, app, monkeypatch, client, sample_users, cle_enregistree
    ):
        """Un profil non autorisé ne peut pas écraser la clé configurée.

        On vérifie aussi qu'aucune requête n'est envoyée au fournisseur : le
        contrôle d'accès doit précéder toute validation coûteuse de la clé.
        """
        from utils import get_setting

        self._interdire_appel_reseau(monkeypatch)
        charge = {'provider': 'openai', 'api_key': 'sk-CLE-INTRUSE-9999'}

        assert _est_redirection_connexion(
            client.post('/api/api_keys/save', json=charge, follow_redirects=False)
        )

        for login, mot_de_passe in PROFILS_REFUSES:
            _connexion(client, login, mot_de_passe)
            reponse = client.post('/api/api_keys/save', json=charge)
            assert reponse.status_code == 403
            assert 'Accès non autorisé' in reponse.get_json()['error']
            _deconnexion(client)

        with app.app_context():
            assert get_setting('openai_api_key') == cle_enregistree

    def test_suppression_cle_refusee_et_cle_conservee(
        self, app, client, sample_users, cle_enregistree
    ):
        """La suppression d'une clé (perte de service IA) est refusée et sans effet."""
        from utils import get_setting

        charge = {'provider': 'openai'}

        assert _est_redirection_connexion(
            client.post('/api/api_keys/delete', json=charge, follow_redirects=False)
        )

        for login, mot_de_passe in PROFILS_REFUSES:
            _connexion(client, login, mot_de_passe)
            reponse = client.post('/api/api_keys/delete', json=charge)
            assert reponse.status_code == 403
            _deconnexion(client)

        with app.app_context():
            assert get_setting('openai_api_key') == cle_enregistree

    def test_prestataire_refuse_sur_toutes_les_routes_cles_api(
        self, app, monkeypatch, prestataire_client, cle_enregistree
    ):
        """Le prestataire paie est exclu de la gestion des secrets IA."""
        from utils import get_setting

        self._interdire_appel_reseau(monkeypatch)

        assert _est_redirection_tableau_de_bord(
            prestataire_client.get('/gestion_cles_api', follow_redirects=False)
        )
        assert prestataire_client.get('/api/api_keys/status').status_code == 403
        assert prestataire_client.post(
            '/api/api_keys/save', json={'provider': 'openai', 'api_key': 'sk-intrus'}
        ).status_code == 403
        assert prestataire_client.post(
            '/api/api_keys/delete', json={'provider': 'openai'}
        ).status_code == 403

        with app.app_context():
            assert get_setting('openai_api_key') == cle_enregistree

    def test_profil_autorise_ne_recoit_jamais_la_cle_en_clair(
        self, admin_client, cle_enregistree
    ):
        """Même le directeur ne récupère qu'un indicateur de configuration.

        La page n'expose que `has_key` (« Configuree » / « Non configuree ») et
        l'API de statut ne renvoie que des booléens : la valeur du secret ne
        transite jamais vers le navigateur.
        """
        page = admin_client.get('/gestion_cles_api')
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        assert cle_enregistree not in html
        # Aucun fragment significatif de la clé ne doit apparaître.
        assert 'CLE-DE-TEST' not in html
        assert 'Configuree' in html

        statut = admin_client.get('/api/api_keys/status')
        assert statut.status_code == 200
        assert cle_enregistree not in statut.get_data(as_text=True)
        donnees = statut.get_json()
        assert donnees['configured']['openai'] is True
        assert donnees['configured']['anthropic'] is False
