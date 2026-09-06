"""
Tests pour le module validation.py :
- Validation par salarié, responsable, directeur
- Verrouillage après double validation (responsable + directeur)
- Déverrouillage par directeur
- Contrôles d'accès sur la vue d'ensemble
"""
from datetime import datetime

from blueprints.validation import _get_vue_mensuelle_data_impl
from database import get_db
from tests.conftest import _login, _reference_fiche


def _creer_saisie_mois(db, user_id, mois, annee):
    """Helper : crée une saisie par jour ouvré du mois pour permettre la validation."""
    from datetime import timedelta
    premier_jour = datetime(annee, mois, 1)
    if mois == 12:
        dernier_jour = datetime(annee + 1, 1, 1) - timedelta(days=1)
    else:
        dernier_jour = datetime(annee, mois + 1, 1) - timedelta(days=1)

    jour = premier_jour
    while jour <= dernier_jour:
        if jour.weekday() < 5:  # Lundi à vendredi
            db.execute(
                """INSERT OR IGNORE INTO heures_reelles
                   (user_id, date, heure_debut_matin, heure_fin_matin,
                    heure_debut_aprem, heure_fin_aprem, type_saisie, declaration_conforme)
                   VALUES (?, ?, '08:30', '12:00', '13:30', '17:00', 'heures_modifiees', 0)""",
                (user_id, jour.strftime('%Y-%m-%d'))
            )
        jour += timedelta(days=1)
    db.commit()


def _ajouter_jour_ferie(db, date_str, libelle):
    """Helper : ajoute un jour férié en base."""
    db.execute(
        '''
        INSERT INTO jours_feries (annee, date, libelle)
        VALUES (?, ?, ?)
        ''',
        (int(date_str[:4]), date_str, libelle)
    )
    db.commit()


def _planning_sans_mercredi(db, planning_id):
    """Helper : retire le mercredi du planning théorique (jour non travaillé habituel)."""
    db.execute(
        '''
        UPDATE planning_theorique
        SET mercredi_matin_debut = NULL, mercredi_matin_fin = NULL,
            mercredi_aprem_debut = NULL, mercredi_aprem_fin = NULL
        WHERE id = ?
        ''',
        (planning_id,)
    )
    db.commit()


def _creer_contrat(db, user_id, date_debut, date_fin, type_contrat='CDD'):
    """Helper : enregistre un contrat (date_fin à None pour un CDI)."""
    db.execute(
        '''INSERT INTO contrats (user_id, type_contrat, date_debut, date_fin)
           VALUES (?, ?, ?, ?)''',
        (user_id, type_contrat, date_debut, date_fin)
    )
    db.commit()


def _charger_vue_mensuelle(app, user_id, mois, annee, profil='salarie'):
    """Helper : charge les données de la fiche mensuelle pour un utilisateur."""
    with app.test_request_context(f'/vue_mensuelle?mois={mois}&annee={annee}'):
        from flask import session

        session['user_id'] = user_id
        session['profil'] = profil

        conn = get_db()
        try:
            data, error_redirect = _get_vue_mensuelle_data_impl(
                conn, mois, annee, None, 'validation_bp.vue_mensuelle'
            )
        finally:
            conn.close()

    assert error_redirect is None
    return data


class TestValidationMois:
    """Tests de la validation mensuelle."""

    def test_salarie_valide_sa_fiche(self, auth_client, app, db, sample_users):
        """Un salarié peut valider sa propre fiche pour un mois terminé."""
        # Utiliser un mois passé (décembre 2024)
        mois, annee = 12, 2024
        with app.app_context():
            _creer_saisie_mois(db, sample_users['salarie_id'], mois, annee)

            response = auth_client.post('/valider_mois', data={
                'user_id': sample_users['salarie_id'],
                'mois': mois,
                'annee': annee,
                'empreinte_fiche': _reference_fiche(auth_client, sample_users['salarie_id'], mois, annee),
            }, follow_redirects=True)
            assert response.status_code == 200

            validation = db.execute(
                "SELECT * FROM validations WHERE user_id = ? AND mois = ? AND annee = ?",
                (sample_users['salarie_id'], mois, annee)
            ).fetchone()
            assert validation is not None
            assert validation['validation_salarie'] is not None
            assert validation['bloque'] == 0  # Pas encore verrouillé

    def test_responsable_valide_fiche_secteur(self, resp_client, app, db, sample_users):
        """Un responsable peut valider la fiche d'un salarié de son secteur."""
        mois, annee = 11, 2024
        with app.app_context():
            _creer_saisie_mois(db, sample_users['salarie_id'], mois, annee)

            response = resp_client.post('/valider_mois', data={
                'user_id': sample_users['salarie_id'],
                'mois': mois,
                'annee': annee,
                'empreinte_fiche': _reference_fiche(resp_client, sample_users['salarie_id'], mois, annee),
            }, follow_redirects=True)
            assert response.status_code == 200

            validation = db.execute(
                "SELECT * FROM validations WHERE user_id = ? AND mois = ? AND annee = ?",
                (sample_users['salarie_id'], mois, annee)
            ).fetchone()
            assert validation is not None
            assert validation['validation_responsable'] is not None

    def test_verrouillage_double_validation(self, app, db, sample_users):
        """La fiche est verrouillée quand responsable ET directeur ont validé."""
        mois, annee = 10, 2024
        with app.app_context():
            _creer_saisie_mois(db, sample_users['salarie_id'], mois, annee)

            # Client 1 : responsable
            client_resp = app.test_client()
            client_resp.post('/login', data={'login': 'resp_test', 'password': 'resp123'})
            client_resp.post('/valider_mois', data={
                'user_id': sample_users['salarie_id'],
                'mois': mois,
                'annee': annee,
                'empreinte_fiche': _reference_fiche(client_resp, sample_users['salarie_id'], mois, annee),
            }, follow_redirects=True)

            # Client 2 : directeur (session séparée)
            client_dir = app.test_client()
            client_dir.post('/login', data={'login': 'admin', 'password': 'Admin1234'})
            client_dir.post('/valider_mois', data={
                'user_id': sample_users['salarie_id'],
                'mois': mois,
                'annee': annee,
                'empreinte_fiche': _reference_fiche(client_dir, sample_users['salarie_id'], mois, annee),
            }, follow_redirects=True)

            validation = db.execute(
                "SELECT * FROM validations WHERE user_id = ? AND mois = ? AND annee = ?",
                (sample_users['salarie_id'], mois, annee)
            ).fetchone()
            assert validation is not None
            assert validation['bloque'] == 1  # Verrouillé !

    def test_directeur_responsable_secteur_valide_les_deux_roles(self, app, db, sample_users):
        """Un directeur responsable du secteur pose les validations responsable
        ET directeur en une seule action, et la fiche est verrouillée.

        Régression : auparavant la chaîne if/elif ne posait que la validation
        directeur, donc validation_responsable restait vide et la fiche ne se
        verrouillait jamais.
        """
        mois, annee = 6, 2024
        with app.app_context():
            # Le directeur (admin) devient aussi responsable du secteur du salarié
            db.execute(
                "UPDATE users SET secteur_id = ? WHERE id = ?",
                (sample_users['secteur_id'], sample_users['directeur_id'])
            )
            db.commit()

            _creer_saisie_mois(db, sample_users['salarie_id'], mois, annee)

            client_dir = app.test_client()
            client_dir.post('/login', data={'login': 'admin', 'password': 'Admin1234'})
            client_dir.post('/valider_mois', data={
                'user_id': sample_users['salarie_id'],
                'mois': mois,
                'annee': annee,
                'empreinte_fiche': _reference_fiche(client_dir, sample_users['salarie_id'], mois, annee),
            }, follow_redirects=True)

            validation = db.execute(
                "SELECT * FROM validations WHERE user_id = ? AND mois = ? AND annee = ?",
                (sample_users['salarie_id'], mois, annee)
            ).fetchone()
            assert validation is not None
            assert validation['validation_responsable'] is not None
            assert validation['validation_directeur'] is not None
            assert validation['bloque'] == 1  # Verrouillé en une seule validation

    def test_directeur_responsable_hierarchique_valide_les_deux_roles(self, app, db, sample_users):
        """Un directeur désigné comme responsable hiérarchique (responsable_id)
        d'un salarié pose les validations responsable ET directeur, même sans
        partager le secteur du salarié.

        Cas réel : un directeur supervise plusieurs secteurs (pas de secteur_id
        unique) mais est le responsable hiérarchique direct du salarié.
        """
        mois, annee = 6, 2024
        with app.app_context():
            # Le directeur n'a PAS de secteur, mais est le responsable
            # hiérarchique direct du salarié.
            db.execute(
                "UPDATE users SET secteur_id = NULL WHERE id = ?",
                (sample_users['directeur_id'],)
            )
            db.execute(
                "UPDATE users SET responsable_id = ? WHERE id = ?",
                (sample_users['directeur_id'], sample_users['salarie_id'])
            )
            db.commit()

            _creer_saisie_mois(db, sample_users['salarie_id'], mois, annee)

            client_dir = app.test_client()
            client_dir.post('/login', data={'login': 'admin', 'password': 'Admin1234'})
            client_dir.post('/valider_mois', data={
                'user_id': sample_users['salarie_id'],
                'mois': mois,
                'annee': annee,
                'empreinte_fiche': _reference_fiche(client_dir, sample_users['salarie_id'], mois, annee),
            }, follow_redirects=True)

            validation = db.execute(
                "SELECT * FROM validations WHERE user_id = ? AND mois = ? AND annee = ?",
                (sample_users['salarie_id'], mois, annee)
            ).fetchone()
            assert validation is not None
            assert validation['validation_responsable'] is not None
            assert validation['validation_directeur'] is not None
            assert validation['bloque'] == 1  # Verrouillé en une seule validation

    def test_directeur_responsable_hierarchique_comptable(self, app, db, sample_users):
        """Cas concret : le comptable (profil non 'salarie') a le directeur pour
        responsable hiérarchique. Le directeur verrouille sa fiche en une
        validation, sans partager de secteur.
        """
        mois, annee = 6, 2024
        with app.app_context():
            db.execute(
                "UPDATE users SET secteur_id = NULL WHERE id = ?",
                (sample_users['directeur_id'],)
            )
            db.execute(
                "UPDATE users SET responsable_id = ? WHERE id = ?",
                (sample_users['directeur_id'], sample_users['comptable_id'])
            )
            db.commit()

            _creer_saisie_mois(db, sample_users['comptable_id'], mois, annee)

            client_dir = app.test_client()
            client_dir.post('/login', data={'login': 'admin', 'password': 'Admin1234'})
            client_dir.post('/valider_mois', data={
                'user_id': sample_users['comptable_id'],
                'mois': mois,
                'annee': annee,
                'empreinte_fiche': _reference_fiche(client_dir, sample_users['comptable_id'], mois, annee),
            }, follow_redirects=True)

            validation = db.execute(
                "SELECT * FROM validations WHERE user_id = ? AND mois = ? AND annee = ?",
                (sample_users['comptable_id'], mois, annee)
            ).fetchone()
            assert validation is not None
            assert validation['validation_responsable'] is not None
            assert validation['validation_directeur'] is not None
            assert validation['bloque'] == 1

    def test_fiche_responsable_verrouillee_par_directeur_seul(self, app, db, sample_users):
        """La fiche d'un responsable (pas de supérieur au-dessus de lui) est
        verrouillée par la seule validation du directeur.

        Régression : le verrouillage exigeait validation_responsable ET
        directeur. Un responsable n'ayant pas de responsable assigné, sa fiche
        ne se verrouillait jamais même après validation du directeur.
        """
        mois, annee = 6, 2024
        with app.app_context():
            _creer_saisie_mois(db, sample_users['responsable_id'], mois, annee)

            # Le responsable valide sa propre fiche
            client_resp = app.test_client()
            client_resp.post('/login', data={'login': 'resp_test', 'password': 'resp123'})
            client_resp.post('/valider_mois', data={
                'user_id': sample_users['responsable_id'],
                'mois': mois,
                'annee': annee,
                'empreinte_fiche': _reference_fiche(client_resp, sample_users['responsable_id'], mois, annee),
            }, follow_redirects=True)

            # Le directeur valide la fiche du responsable
            client_dir = app.test_client()
            client_dir.post('/login', data={'login': 'admin', 'password': 'Admin1234'})
            client_dir.post('/valider_mois', data={
                'user_id': sample_users['responsable_id'],
                'mois': mois,
                'annee': annee,
                'empreinte_fiche': _reference_fiche(client_dir, sample_users['responsable_id'], mois, annee),
            }, follow_redirects=True)

            validation = db.execute(
                "SELECT * FROM validations WHERE user_id = ? AND mois = ? AND annee = ?",
                (sample_users['responsable_id'], mois, annee)
            ).fetchone()
            assert validation is not None
            assert validation['validation_directeur'] is not None
            assert validation['bloque'] == 1  # Verrouillée par le directeur seul

    def test_refus_validation_mois_en_cours(self, auth_client, app, db, sample_users):
        """On ne peut pas valider le mois en cours."""
        now = datetime.now()
        with app.app_context():
            response = auth_client.post('/valider_mois', data={
                'user_id': sample_users['salarie_id'],
                'mois': now.month,
                'annee': now.year,
            }, follow_redirects=True)
            assert response.status_code == 200
            assert 'Impossible de valider un mois en cours' in response.data.decode('utf-8')


class TestDeverrouillage:
    """Tests du déverrouillage par le directeur."""

    def test_directeur_deverrouille_avec_motif(self, admin_client, app, db, sample_users):
        """Le directeur peut déverrouiller une fiche avec un motif."""
        mois, annee = 9, 2024
        with app.app_context():
            # Créer une validation verrouillée manuellement
            db.execute(
                """INSERT INTO validations (user_id, mois, annee, validation_responsable,
                   validation_directeur, bloque) VALUES (?, ?, ?, 'Resp', 'Dir', 1)""",
                (sample_users['salarie_id'], mois, annee)
            )
            db.commit()

            response = admin_client.post('/deverrouiller_mois', data={
                'user_id': sample_users['salarie_id'],
                'mois': mois,
                'annee': annee,
                'motif': 'Correction demandée par le salarié',
            }, follow_redirects=True)
            assert response.status_code == 200

            # Vérifier que la validation a été supprimée
            validation = db.execute(
                "SELECT * FROM validations WHERE user_id = ? AND mois = ? AND annee = ?",
                (sample_users['salarie_id'], mois, annee)
            ).fetchone()
            assert validation is None

    def test_deverrouillage_sans_motif_refuse(self, admin_client, app, db, sample_users):
        """Le déverrouillage sans motif est refusé."""
        mois, annee = 8, 2024
        with app.app_context():
            db.execute(
                """INSERT INTO validations (user_id, mois, annee, validation_responsable,
                   validation_directeur, bloque) VALUES (?, ?, ?, 'Resp', 'Dir', 1)""",
                (sample_users['salarie_id'], mois, annee)
            )
            db.commit()

            response = admin_client.post('/deverrouiller_mois', data={
                'user_id': sample_users['salarie_id'],
                'mois': mois,
                'annee': annee,
                'motif': '',
            }, follow_redirects=True)
            assert response.status_code == 200
            assert 'Le motif est obligatoire' in response.data.decode('utf-8')

    def test_salarie_ne_peut_pas_deverrouiller(self, auth_client, app, db, sample_users):
        """Un salarié ne peut PAS déverrouiller une fiche."""
        mois, annee = 7, 2024
        with app.app_context():
            db.execute(
                """INSERT INTO validations (user_id, mois, annee, validation_responsable,
                   validation_directeur, bloque) VALUES (?, ?, ?, 'Resp', 'Dir', 1)""",
                (sample_users['salarie_id'], mois, annee)
            )
            db.commit()

            response = auth_client.post('/deverrouiller_mois', data={
                'user_id': sample_users['salarie_id'],
                'mois': mois,
                'annee': annee,
                'motif': 'Je veux modifier',
            }, follow_redirects=True)
            assert response.status_code == 200
            # Doit rester verrouillé
            validation = db.execute(
                "SELECT * FROM validations WHERE user_id = ? AND mois = ? AND annee = ?",
                (sample_users['salarie_id'], mois, annee)
            ).fetchone()
            assert validation is not None
            assert validation['bloque'] == 1


class TestVueEnsembleResponsable:
    """Lignes des responsables : pas d'étape « responsable » (validés par la
    direction) — croix dans la colonne et statut global adapté."""

    def _ligne(self, html, nom):
        """Extrait la ligne (tr) du tableau contenant le nom donné."""
        for tr in html.split('<tr')[1:]:
            tr = tr.split('</tr>')[0]
            if nom in tr:
                return tr
        raise AssertionError(f"ligne « {nom} » introuvable")

    def test_croix_colonne_responsable(self, admin_client, sample_users):
        html = admin_client.get('/vue_ensemble_validation').get_data(as_text=True)
        ligne = self._ligne(html, 'Marie Dupont')     # profil responsable
        assert '✗' in ligne
        assert 'Étape sans objet' in ligne
        # Un salarié classique garde sa case à cocher, pas de croix.
        ligne_salarie = self._ligne(html, 'Jean Martin')
        assert '✗' not in ligne_salarie

    def test_statut_global_sans_validation_reste_non_valide(self, admin_client, db, sample_users):
        html = admin_client.get('/vue_ensemble_validation?mois=3&annee=2026').get_data(as_text=True)
        ligne = self._ligne(html, 'Marie Dupont')
        assert 'Non validé' in ligne
        assert 'Attente responsable' not in ligne

    def test_statut_global_apres_validation_salarie_attend_directeur(self, admin_client, db, sample_users):
        """Dès que le responsable a validé SA fiche, le statut passe en
        « Attente directeur » (jamais « Attente responsable »)."""
        db.execute("INSERT INTO validations (user_id, mois, annee, validation_salarie, date_salarie) "
                   "VALUES (?, 3, 2026, 'Marie Dupont', '2026-04-02')",
                   (sample_users['responsable_id'],))
        db.commit()
        # Ce test décrit une approbation actuelle, pas une signature historique.
        db.execute('UPDATE validations SET version_salarie_id=version_courante_id '
                   'WHERE user_id=? AND mois=3 AND annee=2026', (sample_users['responsable_id'],))
        db.commit()
        html = admin_client.get('/vue_ensemble_validation?mois=3&annee=2026').get_data(as_text=True)
        ligne = self._ligne(html, 'Marie Dupont')
        assert 'Attente directeur' in ligne
        assert 'Attente responsable' not in ligne

    def test_salarie_classique_garde_attente_responsable(self, admin_client, db, sample_users):
        db.execute("INSERT INTO validations (user_id, mois, annee, validation_salarie, date_salarie) "
                   "VALUES (?, 3, 2026, 'Jean Martin', '2026-04-02')",
                   (sample_users['salarie_id'],))
        db.commit()
        html = admin_client.get('/vue_ensemble_validation?mois=3&annee=2026').get_data(as_text=True)
        ligne = self._ligne(html, 'Jean Martin')
        assert 'Attente responsable' in ligne


class TestVueEnsembleAcces:
    """Tests d'accès à la vue d'ensemble des validations."""

    def test_directeur_acces(self, admin_client):
        """Le directeur a accès à la vue d'ensemble."""
        response = admin_client.get('/vue_ensemble_validation')
        assert response.status_code == 200

    def test_salarie_refuse(self, auth_client):
        """Un salarié n'a PAS accès à la vue d'ensemble."""
        response = auth_client.get('/vue_ensemble_validation', follow_redirects=True)
        assert response.status_code == 200
        assert 'non autoris' in response.data.decode('utf-8').lower()

    def test_salarie_delegue_acces(self, app, sample_users):
        """Un salarié délégué peut accéder à la vue d'ensemble."""
        directeur_client = app.test_client()
        salarie_client = app.test_client()
        _login(directeur_client, 'admin', 'Admin1234')
        _login(salarie_client, 'salarie_test', 'sal123')

        response = directeur_client.post(
            '/delegations',
            data={
                'mission_key': 'suivi_validations_relances',
                'delegated_user_id': str(sample_users['salarie_id']),
            },
            follow_redirects=True,
        )
        assert response.status_code == 200

        vue_ensemble = salarie_client.get('/vue_ensemble_validation')
        assert vue_ensemble.status_code == 200
        html = vue_ensemble.get_data(as_text=True)
        assert 'État des validations' in html
        assert 'Marie Dupont' in html

        fiche_responsable = salarie_client.get(
            f"/vue_mensuelle?user_id={sample_users['responsable_id']}&mois=5&annee=2024",
            follow_redirects=True,
        )
        assert fiche_responsable.status_code == 200
        assert 'accès non autorisé' in fiche_responsable.get_data(as_text=True).lower()


class TestRelanceValidationDelegation:
    """Tests d'accès aux endpoints de relance par délégation."""

    def test_salarie_refuse_api_relance(self, auth_client):
        response = auth_client.post(
            '/api/email/relance_validation',
            json={'mois': 5, 'annee': 2024},
        )

        assert response.status_code == 403
        assert response.get_json() == {
            'error': 'Acces reserve a la direction ou aux utilisateurs delegues'
        }

    def test_salarie_delegue_peut_appeler_api_relance(self, app, sample_users):
        directeur_client = app.test_client()
        salarie_client = app.test_client()
        _login(directeur_client, 'admin', 'Admin1234')
        _login(salarie_client, 'salarie_test', 'sal123')

        response = directeur_client.post(
            '/delegations',
            data={
                'mission_key': 'suivi_validations_relances',
                'delegated_user_id': str(sample_users['salarie_id']),
            },
            follow_redirects=True,
        )
        assert response.status_code == 200

        res = salarie_client.post(
            '/api/email/relance_validation',
            json={'mois': 5, 'annee': 2024},
        )
        assert res.status_code == 400
        assert 'service email non configure' in res.get_data(as_text=True).lower()


class TestVueMensuelleJoursFeries:
    """Tests du pré-remplissage des jours fériés."""

    def test_helper_pre_remplit_un_jour_ferie_sans_non_declaration(self, app, db, sample_users, sample_planning):
        with app.app_context():
            _ajouter_jour_ferie(db, '2024-05-01', 'Fête du Travail')

            with app.test_request_context('/vue_mensuelle?mois=5&annee=2024'):
                from flask import session

                session['user_id'] = sample_users['salarie_id']
                session['profil'] = 'salarie'

                conn = get_db()
                try:
                    data, error_redirect = _get_vue_mensuelle_data_impl(
                        conn,
                        5,
                        2024,
                        None,
                        'validation_bp.vue_mensuelle'
                    )
                finally:
                    conn.close()

        assert error_redirect is None
        jour = next((j for j in data['journees'] if j['date'] == '2024-05-01'), None)
        assert jour is not None
        assert jour['type_saisie'] == 'ferie'
        assert jour['est_ferie'] is True
        assert jour['libelle_ferie'] == 'Fête du Travail'
        assert jour['commentaire'] == 'Fête du Travail'
        assert jour['est_declare'] is True
        assert jour['est_saisi'] is False
        assert jour['non_declare'] is False

    def test_vue_calendrier_affiche_le_libelle_du_jour_ferie(self, auth_client, app, db, sample_users, sample_planning):
        with app.app_context():
            _ajouter_jour_ferie(db, '2024-05-01', 'Fête du Travail')

        response = auth_client.get('/vue_calendrier?mois=5&annee=2024')
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert 'Fête du Travail' in html


class TestJoursNonTravaillesHabituels:
    """La saisie des jours non travaillés habituels est facultative.

    Un salarié qui ne travaille pas le mercredi n'a pas à déclarer ce jour : il
    ne doit pas être marqué « non déclaré » ni empêcher la validation du mois.
    En décembre 2024, le 02 est un lundi (travaillé) et le 04 un mercredi.
    """

    def test_mercredi_non_travaille_marque_repos_et_pas_non_declare(self, app, db, sample_users, sample_planning):
        with app.app_context():
            _planning_sans_mercredi(db, sample_planning['planning_id'])
            data = _charger_vue_mensuelle(app, sample_users['salarie_id'], 12, 2024)

        mercredi = next(j for j in data['journees'] if j['date'] == '2024-12-04')
        assert mercredi['jour_semaine'] == 'Mercredi'
        assert mercredi['heures_theoriques'] == 0
        assert mercredi['non_declare'] is False
        assert mercredi['est_repos_habituel'] is True

    def test_lundi_travaille_non_saisi_reste_non_declare(self, app, db, sample_users, sample_planning):
        with app.app_context():
            _planning_sans_mercredi(db, sample_planning['planning_id'])
            data = _charger_vue_mensuelle(app, sample_users['salarie_id'], 12, 2024)

        lundi = next(j for j in data['journees'] if j['date'] == '2024-12-02')
        assert lundi['jour_semaine'] == 'Lundi'
        assert lundi['heures_theoriques'] > 0
        assert lundi['non_declare'] is True
        assert lundi['est_repos_habituel'] is False

    def test_jour_sans_planning_reste_non_declare(self, app, db, sample_users):
        """Sans aucun planning défini, un jour ouvré passé non saisi reste
        « non déclaré » : on ne masque pas le manque de configuration et on
        n'autorise pas la validation d'une fiche entièrement vide."""
        with app.app_context():
            # Volontairement pas de fixture sample_planning : aucun planning.
            data = _charger_vue_mensuelle(app, sample_users['salarie_id'], 12, 2024)

        lundi = next(j for j in data['journees'] if j['date'] == '2024-12-02')
        assert lundi['heures_theoriques'] == 0
        assert lundi['non_declare'] is True
        assert lundi['est_repos_habituel'] is False
        assert data['nb_jours_non_declares'] > 0
        assert data['peut_valider_mois'] is False

    def test_validation_possible_sans_saisir_les_mercredis(self, app, db, sample_users, sample_planning):
        from datetime import timedelta

        with app.app_context():
            _planning_sans_mercredi(db, sample_planning['planning_id'])

            # Saisir uniquement les jours travaillés (lun, mar, jeu, ven),
            # en laissant tous les mercredis vides.
            jour = datetime(2024, 12, 1)
            fin = datetime(2024, 12, 31)
            while jour <= fin:
                if jour.weekday() < 5 and jour.weekday() != 2:  # exclure le mercredi
                    db.execute(
                        """INSERT OR IGNORE INTO heures_reelles
                           (user_id, date, heure_debut_matin, heure_fin_matin,
                            heure_debut_aprem, heure_fin_aprem, type_saisie, declaration_conforme)
                           VALUES (?, ?, '08:30', '12:00', '13:30', '17:00', 'heures_modifiees', 0)""",
                        (sample_users['salarie_id'], jour.strftime('%Y-%m-%d'))
                    )
                jour += timedelta(days=1)
            db.commit()

            data = _charger_vue_mensuelle(app, sample_users['salarie_id'], 12, 2024)

        assert data['nb_jours_non_declares'] == 0
        assert data['peut_valider_mois'] is True

        mercredis = [j for j in data['journees'] if j['jour_semaine'] == 'Mercredi']
        assert mercredis  # le mois en compte plusieurs
        assert all(j['est_repos_habituel'] for j in mercredis)
        assert all(not j['non_declare'] for j in mercredis)


class TestJoursHorsContrat:
    """Hors de son contrat, une journée n'est ni due ni à saisir.

    Le planning théorique ne sait pas répondre : il n'a pas de fin de validité
    (celui d'un CDD reste « valide » après son terme) et n'existe pas avant son
    premier jour. C'est le contrat qui borne l'emploi.

    Repères de décembre 2024 : le 02 est un lundi, le 13 un vendredi, le 16 le
    lundi suivant.
    """

    def test_jours_avant_le_debut_du_cdd_ne_sont_pas_a_saisir(
            self, app, db, sample_users, sample_planning):
        with app.app_context():
            _creer_contrat(db, sample_users['salarie_id'], '2024-12-09', '2024-12-20')
            data = _charger_vue_mensuelle(app, sample_users['salarie_id'], 12, 2024)

        lundi_avant = next(j for j in data['journees'] if j['date'] == '2024-12-02')
        assert lundi_avant['hors_contrat'] is True
        assert lundi_avant['non_declare'] is False
        assert lundi_avant['heures_theoriques'] == 0

    def test_jours_apres_la_fin_du_cdd_ne_sont_pas_a_saisir(
            self, app, db, sample_users, sample_planning):
        with app.app_context():
            _creer_contrat(db, sample_users['salarie_id'], '2024-12-02', '2024-12-13')
            data = _charger_vue_mensuelle(app, sample_users['salarie_id'], 12, 2024)

        lundi_apres = next(j for j in data['journees'] if j['date'] == '2024-12-16')
        assert lundi_apres['hors_contrat'] is True
        assert lundi_apres['non_declare'] is False
        assert lundi_apres['heures_theoriques'] == 0

    def test_le_dernier_jour_du_contrat_reste_du(self, app, db, sample_users, sample_planning):
        """`date_fin` est le dernier jour travaillé : il est encore à saisir."""
        with app.app_context():
            _creer_contrat(db, sample_users['salarie_id'], '2024-12-02', '2024-12-13')
            data = _charger_vue_mensuelle(app, sample_users['salarie_id'], 12, 2024)

        dernier_jour = next(j for j in data['journees'] if j['date'] == '2024-12-13')
        assert dernier_jour['hors_contrat'] is False
        assert dernier_jour['non_declare'] is True
        assert dernier_jour['heures_theoriques'] > 0

    def test_le_cdd_peut_valider_son_mois_partiel(self, app, db, sample_users, sample_planning):
        """Le blocage à la validation était la vraie conséquence du défaut."""
        from datetime import timedelta

        with app.app_context():
            _creer_contrat(db, sample_users['salarie_id'], '2024-12-09', '2024-12-20')

            # Saisir les seuls jours ouvrés couverts par le contrat.
            jour = datetime(2024, 12, 9)
            while jour <= datetime(2024, 12, 20):
                if jour.weekday() < 5:
                    db.execute(
                        """INSERT OR IGNORE INTO heures_reelles
                           (user_id, date, heure_debut_matin, heure_fin_matin,
                            heure_debut_aprem, heure_fin_aprem, type_saisie,
                            declaration_conforme)
                           VALUES (?, ?, '08:30', '12:00', '13:30', '17:00',
                                   'heures_modifiees', 0)""",
                        (sample_users['salarie_id'], jour.strftime('%Y-%m-%d'))
                    )
                jour += timedelta(days=1)
            db.commit()

            data = _charger_vue_mensuelle(app, sample_users['salarie_id'], 12, 2024)

        assert data['nb_jours_non_declares'] == 0
        assert data['peut_valider_mois'] is True

    def test_le_total_theorique_se_limite_au_contrat(self, app, db, sample_users, sample_planning):
        """Sinon la fiche réclame au CDD les heures d'un mois plein."""
        with app.app_context():
            _creer_contrat(db, sample_users['salarie_id'], '2024-12-09', '2024-12-20')
            partiel = _charger_vue_mensuelle(app, sample_users['salarie_id'], 12, 2024)

            db.execute("DELETE FROM contrats WHERE user_id = ?",
                       (sample_users['salarie_id'],))
            db.commit()
            plein = _charger_vue_mensuelle(app, sample_users['salarie_id'], 12, 2024)

        # 10 jours ouvrés couverts, à 7h : le reste du mois ne compte plus.
        assert partiel['total_heures_theoriques'] == 70
        assert plein['total_heures_theoriques'] > partiel['total_heures_theoriques']

    def test_trou_entre_deux_contrats(self, app, db, sample_users, sample_planning):
        """Un CDD renouvelé après une interruption : le trou n'est pas à saisir."""
        with app.app_context():
            _creer_contrat(db, sample_users['salarie_id'], '2024-12-02', '2024-12-06')
            _creer_contrat(db, sample_users['salarie_id'], '2024-12-16', '2024-12-31')
            data = _charger_vue_mensuelle(app, sample_users['salarie_id'], 12, 2024)

        par_date = {j['date']: j for j in data['journees']}
        assert par_date['2024-12-06']['hors_contrat'] is False   # fin du premier
        assert par_date['2024-12-10']['hors_contrat'] is True    # dans le trou
        assert par_date['2024-12-16']['hors_contrat'] is False   # début du second

    def test_le_trou_entre_deux_cdd_n_empeche_pas_la_validation(
            self, app, db, sample_users, sample_planning):
        """Cas de référence : CDD du 01 au 10/07, retour du 16 au 31/07.

        Du 11 au 15 il n'y a rien à saisir, donc rien qui doive rougir ni
        retenir la validation du mois. Le 14 juillet, férié tombé dans le
        trou, ne compte pas davantage : il n'est pas chômé pour quelqu'un qui
        n'est pas employé.
        """
        from datetime import timedelta

        with app.app_context():
            _ajouter_jour_ferie(db, '2026-07-14', 'Fête nationale')
            _creer_contrat(db, sample_users['salarie_id'], '2026-07-01', '2026-07-10')
            _creer_contrat(db, sample_users['salarie_id'], '2026-07-16', '2026-07-31')

            # Saisir les jours ouvrés des deux périodes, et eux seuls.
            jour = datetime(2026, 7, 1)
            while jour <= datetime(2026, 7, 31):
                dans_contrat = (jour.day <= 10 or jour.day >= 16)
                if jour.weekday() < 5 and dans_contrat:
                    db.execute(
                        """INSERT OR IGNORE INTO heures_reelles
                           (user_id, date, heure_debut_matin, heure_fin_matin,
                            heure_debut_aprem, heure_fin_aprem, type_saisie,
                            declaration_conforme)
                           VALUES (?, ?, '08:30', '12:00', '13:30', '17:00',
                                   'heures_modifiees', 0)""",
                        (sample_users['salarie_id'], jour.strftime('%Y-%m-%d'))
                    )
                jour += timedelta(days=1)
            db.commit()

            data = _charger_vue_mensuelle(app, sample_users['salarie_id'], 7, 2026)

        par_date = {j['date']: j for j in data['journees']}
        for jour_du_trou in ('2026-07-13', '2026-07-14', '2026-07-15'):
            assert par_date[jour_du_trou]['hors_contrat'] is True, jour_du_trou
            assert par_date[jour_du_trou]['non_declare'] is False, jour_du_trou
            assert par_date[jour_du_trou]['heures_theoriques'] == 0, jour_du_trou

        assert data['nb_jours_non_declares'] == 0
        assert data['peut_valider_mois'] is True

    def test_contrat_sans_terme_ne_retranche_rien(self, app, db, sample_users, sample_planning):
        """Un CDI (date_fin vide) couvre tout ce qui suit son début."""
        with app.app_context():
            _creer_contrat(db, sample_users['salarie_id'], '2024-01-01', None)
            data = _charger_vue_mensuelle(app, sample_users['salarie_id'], 12, 2024)

        assert not any(j['hors_contrat'] for j in data['journees'])
        assert data['nb_jours_non_declares'] > 0

    def test_sans_contrat_au_dossier_rien_ne_change(self, app, db, sample_users, sample_planning):
        """Un contrat non saisi ne doit pas vider la fiche.

        La table s'est remplie après coup : « aucun contrat » veut dire
        « on ne sait pas », pas « jamais employé ».
        """
        with app.app_context():
            data = _charger_vue_mensuelle(app, sample_users['salarie_id'], 12, 2024)

        lundi = next(j for j in data['journees'] if j['date'] == '2024-12-02')
        assert lundi['hors_contrat'] is False
        assert lundi['non_declare'] is True

    def test_une_saisie_hors_contrat_reste_visible(self, app, db, sample_users, sample_planning):
        """Des heures enregistrées se montrent toujours : elles révèlent un
        contrat oublié au dossier plutôt que de disparaître."""
        with app.app_context():
            _creer_contrat(db, sample_users['salarie_id'], '2024-12-09', '2024-12-20')
            db.execute(
                """INSERT INTO heures_reelles
                   (user_id, date, heure_debut_matin, heure_fin_matin,
                    heure_debut_aprem, heure_fin_aprem, type_saisie, declaration_conforme)
                   VALUES (?, '2024-12-02', '08:30', '12:00', '13:30', '17:00',
                           'heures_modifiees', 0)""",
                (sample_users['salarie_id'],)
            )
            db.commit()
            data = _charger_vue_mensuelle(app, sample_users['salarie_id'], 12, 2024)

        lundi = next(j for j in data['journees'] if j['date'] == '2024-12-02')
        assert lundi['est_saisi'] is True
        assert lundi['hors_contrat'] is False
        assert lundi['heures_reelles'] > 0

    def test_la_fiche_explique_l_absence_de_contrat(self, auth_client, app, db,
                                                    sample_users, sample_planning):
        """Sans contrat, la fiche réclame des journées que la saisie refuse.

        Le blocage doit être expliqué là où on le rencontre, sinon les jours
        rouges deviennent une impasse muette.
        """
        html = auth_client.get('/vue_mensuelle?mois=12&annee=2024').get_data(as_text=True)
        assert 'Aucun contrat enregistré' in html
        assert 'jour(s) non déclaré(s)' in html

    def test_la_fiche_d_un_salarie_sous_contrat_ne_dit_rien(
            self, auth_client, app, db, sample_users, sample_planning, sample_contrat):
        html = auth_client.get('/vue_mensuelle?mois=12&annee=2024').get_data(as_text=True)
        assert 'Aucun contrat enregistré' not in html

    def test_la_fiche_affiche_hors_contrat(self, auth_client, app, db, sample_users,
                                           sample_planning):
        with app.app_context():
            _creer_contrat(db, sample_users['salarie_id'], '2024-12-09', '2024-12-20')

        html = auth_client.get('/vue_mensuelle?mois=12&annee=2024').get_data(as_text=True)
        assert 'Hors contrat' in html
        # Décembre 2024 compte 22 jours ouvrés ; seuls les 10 du contrat
        # restent à saisir, contre le mois entier auparavant.
        assert '10 jour(s) non déclaré(s)' in html
        assert '22 jour(s) non déclaré(s)' not in html


class TestPlanningTheoriqueAffichage:
    """Tests de l'affichage des totaux du planning théorique."""

    def test_affiche_le_total_si_seule_l_apres_midi_est_renseignee(self, auth_client, app, db, sample_planning):
        with app.app_context():
            db.execute(
                '''
                UPDATE planning_theorique
                SET lundi_matin_debut = NULL,
                    lundi_matin_fin = NULL,
                    lundi_aprem_debut = ?,
                    lundi_aprem_fin = ?,
                    total_hebdo = ?
                WHERE id = ?
                ''',
                ('13:00', '17:00', 32.0, sample_planning['planning_id'])
            )
            db.commit()

        response = auth_client.get('/planning_theorique')
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert '13:00 - 17:00' in html
        assert '4.0h' in html
        assert 'Non travaillé' not in html
