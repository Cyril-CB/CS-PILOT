"""
Tests de la page bénévoles : type de bénévolat, date de fin et suivi des heures.

Le volume d'heures de bénévolat était tenu à la main sur un classeur ; il est
maintenant calculé à partir des activités suivies, selon les deux modèles de ce
classeur : « à la séance » (on liste les jours de CA et on coche les présents)
et « au forfait annuel » (volume à l'année dont on retranche les absences).

PIÈGE : les fixtures de clients authentifiés partagent le même objet client.
Les tests qui changent de profil utilisent `client` avec connexion/déconnexion
explicites.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

ANNEE = 2026


def _connexion(client, login, mot_de_passe):
    return client.post('/login', data={'login': login, 'password': mot_de_passe},
                       follow_redirects=True)


def _creer_benevole(app, db, nom='Belgacem Noura', groupe='actif'):
    with app.app_context():
        db.execute("INSERT INTO benevoles (nom, groupe) VALUES (?, ?)", (nom, groupe))
        db.commit()
        return db.execute("SELECT id FROM benevoles WHERE nom = ?", (nom,)).fetchone()['id']


def _creer_activite(app, db, nom='Conseil d\'administration', mode='seance',
                    heures_seance=2, volume_annuel=0, nb_seances=0, annee=ANNEE):
    with app.app_context():
        db.execute('''
            INSERT INTO benevoles_activites
            (nom, annee, mode, heures_seance, volume_annuel, nb_seances)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (nom, annee, mode, heures_seance, volume_annuel, nb_seances))
        db.commit()
        return db.execute(
            "SELECT id FROM benevoles_activites ORDER BY id DESC LIMIT 1").fetchone()['id']


def _total_heures(app, db, benevole_id, annee=ANNEE):
    from blueprints.benevoles import _heures_par_benevole
    with app.app_context():
        return _heures_par_benevole(db, annee).get(benevole_id, 0)


class TestTypeBenevolat:
    """Type de bénévolat : liste fermée, éditable depuis le board."""

    def test_liste_des_types_proposee_sur_la_page(self, app, db, admin_client):
        _creer_benevole(app, db)
        html = admin_client.get('/benevoles').get_data(as_text=True)
        for attendu in ('Gouvernance', 'Activité', 'Coup de pouce',
                        'Gouvernance + Activité', 'Gouvernance + Coup de pouce',
                        'Activité + Coup de pouce'):
            assert attendu in html, f"« {attendu} » doit être proposé"
        assert 'Type de bénévolat' in html

    def test_enregistrement_du_type(self, app, db, admin_client):
        ben_id = _creer_benevole(app, db)
        r = admin_client.post(f'/api/benevoles/{ben_id}/modifier',
                              json={'field': 'type_benevolat',
                                    'value': 'gouvernance_activite'})
        assert r.status_code == 200 and r.get_json()['ok']
        with app.app_context():
            valeur = db.execute("SELECT type_benevolat FROM benevoles WHERE id = ?",
                                (ben_id,)).fetchone()['type_benevolat']
        assert valeur == 'gouvernance_activite'

    def test_type_inconnu_ne_sale_pas_la_fiche(self, app, db, admin_client):
        """Une valeur hors liste est ignorée : sinon la fiche porterait une
        étiquette qui ne correspond à aucun type et ne serait plus filtrable."""
        ben_id = _creer_benevole(app, db)
        admin_client.post(f'/api/benevoles/{ben_id}/modifier',
                          json={'field': 'type_benevolat', 'value': 'president_du_monde'})
        with app.app_context():
            valeur = db.execute("SELECT type_benevolat FROM benevoles WHERE id = ?",
                                (ben_id,)).fetchone()['type_benevolat']
        assert valeur == ''

    def test_pastille_affiche_le_type_enregistre(self, app, db, admin_client):
        """La pastille doit porter l'étiquette du type, pas rester vide.

        Un `{% set %}` placé dans une boucle Jinja ne survit pas à la boucle :
        la valeur retenue était systématiquement perdue.
        """
        ben_id = _creer_benevole(app, db)
        admin_client.post(f'/api/benevoles/{ben_id}/modifier',
                          json={'field': 'type_benevolat', 'value': 'gouvernance_activite'})
        html = admin_client.get('/benevoles').get_data(as_text=True)
        assert 'data-type="gouvernance_activite"' in html
        ligne = next(l for l in html.splitlines() if 'data-type="gouvernance_activite"' in l)
        assert 'Gouvernance + Activité' in ligne, \
            "la pastille doit afficher l'étiquette du type retenu"
        assert '#579bfc' in ligne, "et sa couleur, pas le gris par défaut"

    def test_pastille_heures_semaine_affiche_la_valeur(self, app, db, admin_client):
        """Même défaut sur la colonne « Heures / semaine », qui existait déjà."""
        ben_id = _creer_benevole(app, db)
        admin_client.post(f'/api/benevoles/{ben_id}/modifier',
                          json={'field': 'heures_semaine', 'value': '4-6'})
        html = admin_client.get('/benevoles').get_data(as_text=True)
        ligne = next(l for l in html.splitlines() if 'data-heures="4-6"' in l)
        assert '4-6h' in ligne and '#00c875' in ligne

    def test_champ_non_autorise_refuse(self, app, db, admin_client):
        ben_id = _creer_benevole(app, db)
        r = admin_client.post(f'/api/benevoles/{ben_id}/modifier',
                              json={'field': 'groupe; DROP TABLE benevoles', 'value': 'x'})
        assert r.status_code == 400


class TestDateFin:
    """Date de fin : renseignable pour les bénévoles qui ont arrêté."""

    def test_enregistrement_et_affichage(self, app, db, admin_client):
        ben_id = _creer_benevole(app, db, nom='Ancien Bénévole', groupe='inactif')
        r = admin_client.post(f'/api/benevoles/{ben_id}/modifier',
                              json={'field': 'date_fin', 'value': '2026-03-31'})
        assert r.status_code == 200
        with app.app_context():
            assert db.execute("SELECT date_fin FROM benevoles WHERE id = ?",
                              (ben_id,)).fetchone()['date_fin'] == '2026-03-31'
        html = admin_client.get('/benevoles').get_data(as_text=True)
        assert 'Date de fin' in html
        assert '31/03/2026' in html


class TestPresentationDuBoard:
    """Colonne figée et colonne en double retirée."""

    def test_premiere_colonne_figee(self, app, db, admin_client):
        _creer_benevole(app, db)
        html = admin_client.get('/benevoles').get_data(as_text=True)
        assert 'sv-col-name sv-sticky' in html, \
            "l'en-tête de la colonne Nom doit être figé au défilement"
        assert 'sv-cell-name sv-sticky' in html, \
            "les cellules de la colonne Nom doivent être figées"

    def test_colonne_nom_en_double_retiree(self, app, db, admin_client):
        _creer_benevole(app, db)
        html = admin_client.get('/benevoles').get_data(as_text=True)
        assert 'sv-col-name-end' not in html, \
            "la colonne Nom répétée en fin de tableau doit disparaître"


class TestHeuresALaSeance:
    """Activité « à la séance » : les jours de CA et les présences."""

    def _seance(self, app, db, act_id, date, heures=2):
        with app.app_context():
            db.execute("INSERT INTO benevoles_seances (activite_id, date, heures) "
                       "VALUES (?, ?, ?)", (act_id, date, heures))
            db.commit()
            return db.execute(
                "SELECT id FROM benevoles_seances ORDER BY id DESC LIMIT 1").fetchone()['id']

    def test_total_additionne_les_seances_suivies(self, app, db, admin_client):
        """Quatre CA de 2 h, présent à trois : 6 h, et non 8."""
        ben_id = _creer_benevole(app, db)
        act_id = _creer_activite(app, db)
        seances = [self._seance(app, db, act_id, f'{ANNEE}-0{m}-10') for m in (1, 2, 3, 4)]
        admin_client.post(f'/api/benevoles/activites/{act_id}/participants/ajouter',
                          json={'benevole_id': ben_id})
        for seance_id, present in zip(seances, (True, True, True, False)):
            r = admin_client.post('/api/benevoles/presences',
                                  json={'seance_id': seance_id, 'benevole_id': ben_id,
                                        'present': present})
            assert r.status_code == 200

        assert _total_heures(app, db, ben_id) == 6

    def test_absence_partout_ne_compte_aucune_heure(self, app, db, admin_client):
        ben_id = _creer_benevole(app, db)
        act_id = _creer_activite(app, db)
        seance_id = self._seance(app, db, act_id, f'{ANNEE}-01-10')
        admin_client.post(f'/api/benevoles/activites/{act_id}/participants/ajouter',
                          json={'benevole_id': ben_id})
        admin_client.post('/api/benevoles/presences',
                          json={'seance_id': seance_id, 'benevole_id': ben_id,
                                'present': False})
        assert _total_heures(app, db, ben_id) == 0

    def test_decocher_retire_les_heures(self, app, db, admin_client):
        ben_id = _creer_benevole(app, db)
        act_id = _creer_activite(app, db)
        seance_id = self._seance(app, db, act_id, f'{ANNEE}-01-10')
        for present in (True, False):
            admin_client.post('/api/benevoles/presences',
                              json={'seance_id': seance_id, 'benevole_id': ben_id,
                                    'present': present})
        assert _total_heures(app, db, ben_id) == 0

    def test_duree_par_defaut_de_l_activite(self, app, db, admin_client):
        """Une date ajoutée sans durée reprend celle de l'activité (2 h)."""
        act_id = _creer_activite(app, db, heures_seance=2)
        r = admin_client.post(f'/api/benevoles/activites/{act_id}/seances/ajouter',
                              json={'date': f'{ANNEE}-05-12'})
        assert r.status_code == 200
        with app.app_context():
            assert db.execute("SELECT heures FROM benevoles_seances WHERE activite_id = ?",
                              (act_id,)).fetchone()['heures'] == 2

    def test_seances_d_une_autre_annee_ignorees(self, app, db, admin_client):
        """Le total est annuel : une séance de l'exercice précédent n'y entre pas."""
        ben_id = _creer_benevole(app, db)
        act_precedente = _creer_activite(app, db, nom='CA 2025', annee=ANNEE - 1)
        seance_id = self._seance(app, db, act_precedente, f'{ANNEE - 1}-11-10')
        admin_client.post('/api/benevoles/presences',
                          json={'seance_id': seance_id, 'benevole_id': ben_id,
                                'present': True})
        assert _total_heures(app, db, ben_id, annee=ANNEE) == 0
        assert _total_heures(app, db, ben_id, annee=ANNEE - 1) == 2

    def test_pointage_renvoie_les_totaux_a_jour(self, app, db, admin_client):
        """La page se met à jour sans rechargement : le serveur renvoie les
        totaux du bénévole, de l'activité et de l'année."""
        ben_id = _creer_benevole(app, db)
        act_id = _creer_activite(app, db)
        seances = [self._seance(app, db, act_id, f'{ANNEE}-0{m}-10') for m in (1, 2)]
        admin_client.post(f'/api/benevoles/activites/{act_id}/participants/ajouter',
                          json={'benevole_id': ben_id})
        for seance_id in seances:
            corps = admin_client.post('/api/benevoles/presences',
                                      json={'seance_id': seance_id, 'benevole_id': ben_id,
                                            'present': True}).get_json()
        assert corps['activite_id'] == act_id
        assert corps['total_benevole_activite'] == 4
        assert corps['total_activite'] == 4
        assert corps['total_benevole_annee'] == 4
        assert corps['total_annee'] == 4

    def test_duree_d_une_seance_modifiable(self, app, db, admin_client):
        """Un CA plus long que les autres : la durée se corrige séance par séance."""
        ben_id = _creer_benevole(app, db)
        act_id = _creer_activite(app, db)
        seance_id = self._seance(app, db, act_id, f'{ANNEE}-01-10')
        admin_client.post('/api/benevoles/presences',
                          json={'seance_id': seance_id, 'benevole_id': ben_id,
                                'present': True})
        r = admin_client.post(f'/api/benevoles/seances/{seance_id}/modifier',
                              json={'field': 'heures', 'value': 3.5})
        assert r.status_code == 200
        assert _total_heures(app, db, ben_id) == 3.5

    def test_les_deux_totaux_annuels_portent_un_identifiant(self, app, db, admin_client):
        """Le total du bandeau et celui du récapitulatif affichent le même
        chiffre : les deux doivent être rafraîchis après un pointage, sinon la
        page montre deux totaux contradictoires jusqu'au rechargement."""
        _creer_benevole(app, db)
        _creer_activite(app, db)
        html = admin_client.get(f'/benevoles/heures?annee={ANNEE}').get_data(as_text=True)
        assert html.count('id="bh-total-general"') == 1
        assert html.count('id="bh-total-recap"') == 1
        assert "bhFixer('bh-total-recap'" in html, \
            "le total du récapitulatif doit être mis à jour au pointage"

    def test_recapitulatif_liste_les_benevoles_sans_heure(self, app, db, admin_client):
        """Un bénévole rattaché mais jamais présent doit figurer au récapitulatif
        (à zéro) : sinon son total ne peut pas s'afficher sans rechargement."""
        ben_id = _creer_benevole(app, db, nom='Jamais Present')
        act_id = _creer_activite(app, db)
        self._seance(app, db, act_id, f'{ANNEE}-01-10')
        admin_client.post(f'/api/benevoles/activites/{act_id}/participants/ajouter',
                          json={'benevole_id': ben_id})
        html = admin_client.get(f'/benevoles/heures?annee={ANNEE}').get_data(as_text=True)
        assert f'id="bh-recap-{ben_id}"' in html

    def test_suppression_seance_retire_les_presences(self, app, db, admin_client):
        ben_id = _creer_benevole(app, db)
        act_id = _creer_activite(app, db)
        seance_id = self._seance(app, db, act_id, f'{ANNEE}-01-10')
        admin_client.post('/api/benevoles/presences',
                          json={'seance_id': seance_id, 'benevole_id': ben_id,
                                'present': True})
        admin_client.post(f'/api/benevoles/seances/{seance_id}/supprimer')
        assert _total_heures(app, db, ben_id) == 0
        with app.app_context():
            assert db.execute(
                "SELECT COUNT(*) AS n FROM benevoles_presences WHERE seance_id = ?",
                (seance_id,)).fetchone()['n'] == 0


class TestHeuresAuForfait:
    """Activité régulière budgétée à l'année (« sur 80 h à l'année »)."""

    def test_absences_deduites_au_prorata(self, app, db, admin_client):
        """80 h sur 40 séances, 4 manquées : 72 h."""
        ben_id = _creer_benevole(app, db)
        act_id = _creer_activite(app, db, nom='Café sénior', mode='forfait',
                                 volume_annuel=80, nb_seances=40)
        admin_client.post(f'/api/benevoles/activites/{act_id}/participants/ajouter',
                          json={'benevole_id': ben_id})
        with app.app_context():
            part_id = db.execute(
                "SELECT id FROM benevoles_participations WHERE activite_id = ?",
                (act_id,)).fetchone()['id']
        r = admin_client.post(f'/api/benevoles/participations/{part_id}/modifier',
                              json={'absences': 4})
        assert r.status_code == 200
        assert _total_heures(app, db, ben_id) == 72

    def test_sans_absence_le_volume_entier(self, app, db, admin_client):
        ben_id = _creer_benevole(app, db)
        act_id = _creer_activite(app, db, nom='Comité de présidence', mode='forfait',
                                 volume_annuel=42, nb_seances=6)
        admin_client.post(f'/api/benevoles/activites/{act_id}/participants/ajouter',
                          json={'benevole_id': ben_id})
        assert _total_heures(app, db, ben_id) == 42

    def test_sans_nombre_de_seances_aucune_deduction(self, app, db, admin_client):
        """Le prorata est impossible : on retient le volume, la page l'annonce."""
        ben_id = _creer_benevole(app, db)
        act_id = _creer_activite(app, db, nom='Café culture', mode='forfait',
                                 volume_annuel=80, nb_seances=0)
        admin_client.post(f'/api/benevoles/activites/{act_id}/participants/ajouter',
                          json={'benevole_id': ben_id})
        with app.app_context():
            part_id = db.execute(
                "SELECT id FROM benevoles_participations WHERE activite_id = ?",
                (act_id,)).fetchone()['id']
        admin_client.post(f'/api/benevoles/participations/{part_id}/modifier',
                          json={'absences': 3})
        assert _total_heures(app, db, ben_id) == 80
        html = admin_client.get(f'/benevoles/heures?annee={ANNEE}').get_data(as_text=True)
        assert 'Sans nombre de séances' in html

    def test_plus_d_absences_que_de_seances_ne_donne_pas_de_negatif(self, app, db, admin_client):
        ben_id = _creer_benevole(app, db)
        act_id = _creer_activite(app, db, nom='Café sénior', mode='forfait',
                                 volume_annuel=80, nb_seances=10)
        admin_client.post(f'/api/benevoles/activites/{act_id}/participants/ajouter',
                          json={'benevole_id': ben_id})
        with app.app_context():
            part_id = db.execute(
                "SELECT id FROM benevoles_participations WHERE activite_id = ?",
                (act_id,)).fetchone()['id']
        admin_client.post(f'/api/benevoles/participations/{part_id}/modifier',
                          json={'absences': 25})
        assert _total_heures(app, db, ben_id) == 0


class TestHeuresPonctuelles:
    """Heures hors activité suivie (« Autre » sur le classeur)."""

    def test_ajout_et_total(self, app, db, admin_client):
        ben_id = _creer_benevole(app, db)
        r = admin_client.post('/api/benevoles/heures-autres/ajouter',
                              json={'benevole_id': ben_id, 'annee': ANNEE,
                                    'date': f'{ANNEE}-06-14',
                                    'libelle': 'Sortie familles', 'heures': 5.5})
        assert r.status_code == 200
        assert _total_heures(app, db, ben_id) == 5.5

    def test_heures_nulles_refusees(self, app, db, admin_client):
        ben_id = _creer_benevole(app, db)
        r = admin_client.post('/api/benevoles/heures-autres/ajouter',
                              json={'benevole_id': ben_id, 'heures': 0})
        assert r.status_code == 400
        assert _total_heures(app, db, ben_id) == 0

    def test_benevole_inexistant_refuse(self, app, db, admin_client):
        r = admin_client.post('/api/benevoles/heures-autres/ajouter',
                              json={'benevole_id': 999999, 'heures': 3})
        assert r.status_code == 404
        with app.app_context():
            assert db.execute(
                "SELECT COUNT(*) AS n FROM benevoles_heures_autres").fetchone()['n'] == 0


class TestCumulEtAffichage:
    """Le total du board additionne les trois sources."""

    def test_total_affiche_sur_la_liste(self, app, db, admin_client):
        ben_id = _creer_benevole(app, db)
        act_seance = _creer_activite(app, db)
        with app.app_context():
            db.execute("INSERT INTO benevoles_seances (activite_id, date, heures) "
                       "VALUES (?, ?, 2)", (act_seance, f'{ANNEE}-01-10'))
            db.commit()
            seance_id = db.execute(
                "SELECT id FROM benevoles_seances ORDER BY id DESC LIMIT 1").fetchone()['id']
        admin_client.post('/api/benevoles/presences',
                          json={'seance_id': seance_id, 'benevole_id': ben_id,
                                'present': True})
        act_forfait = _creer_activite(app, db, nom='Café sénior', mode='forfait',
                                      volume_annuel=80, nb_seances=40)
        admin_client.post(f'/api/benevoles/activites/{act_forfait}/participants/ajouter',
                          json={'benevole_id': ben_id})
        admin_client.post('/api/benevoles/heures-autres/ajouter',
                          json={'benevole_id': ben_id, 'annee': ANNEE, 'heures': 3})

        assert _total_heures(app, db, ben_id) == 85     # 2 + 80 + 3
        html = admin_client.get(f'/benevoles?annee={ANNEE}').get_data(as_text=True)
        assert f'Heures {ANNEE}' in html
        assert '85 h' in html


class TestNettoyageDesSuppressions:
    """Aucune donnée orpheline : les clés étrangères ne sont pas activées."""

    def test_suppression_benevole_nettoie_le_suivi(self, app, db, admin_client):
        ben_id = _creer_benevole(app, db)
        act_id = _creer_activite(app, db)
        with app.app_context():
            db.execute("INSERT INTO benevoles_seances (activite_id, date, heures) "
                       "VALUES (?, ?, 2)", (act_id, f'{ANNEE}-01-10'))
            db.commit()
            seance_id = db.execute(
                "SELECT id FROM benevoles_seances ORDER BY id DESC LIMIT 1").fetchone()['id']
        admin_client.post(f'/api/benevoles/activites/{act_id}/participants/ajouter',
                          json={'benevole_id': ben_id})
        admin_client.post('/api/benevoles/presences',
                          json={'seance_id': seance_id, 'benevole_id': ben_id,
                                'present': True})
        admin_client.post('/api/benevoles/heures-autres/ajouter',
                          json={'benevole_id': ben_id, 'annee': ANNEE, 'heures': 4})

        admin_client.post(f'/api/benevoles/{ben_id}/supprimer')

        with app.app_context():
            for table in ('benevoles_presences', 'benevoles_participations',
                          'benevoles_heures_autres'):
                reste = db.execute(
                    f"SELECT COUNT(*) AS n FROM {table} WHERE benevole_id = ?",
                    (ben_id,)).fetchone()['n']
                assert reste == 0, f"{table} garde une ligne orpheline"

    def test_suppression_activite_nettoie_seances_et_presences(self, app, db, admin_client):
        ben_id = _creer_benevole(app, db)
        act_id = _creer_activite(app, db)
        with app.app_context():
            db.execute("INSERT INTO benevoles_seances (activite_id, date, heures) "
                       "VALUES (?, ?, 2)", (act_id, f'{ANNEE}-01-10'))
            db.commit()
            seance_id = db.execute(
                "SELECT id FROM benevoles_seances ORDER BY id DESC LIMIT 1").fetchone()['id']
        admin_client.post(f'/api/benevoles/activites/{act_id}/participants/ajouter',
                          json={'benevole_id': ben_id})
        admin_client.post('/api/benevoles/presences',
                          json={'seance_id': seance_id, 'benevole_id': ben_id,
                                'present': True})

        admin_client.post(f'/api/benevoles/activites/{act_id}/supprimer')

        assert _total_heures(app, db, ben_id) == 0
        with app.app_context():
            assert db.execute("SELECT COUNT(*) AS n FROM benevoles_seances "
                              "WHERE activite_id = ?", (act_id,)).fetchone()['n'] == 0
            assert db.execute("SELECT COUNT(*) AS n FROM benevoles_presences "
                              "WHERE seance_id = ?", (seance_id,)).fetchone()['n'] == 0

    def test_retrait_participant_efface_ses_presences(self, app, db, admin_client):
        ben_id = _creer_benevole(app, db)
        act_id = _creer_activite(app, db)
        with app.app_context():
            db.execute("INSERT INTO benevoles_seances (activite_id, date, heures) "
                       "VALUES (?, ?, 2)", (act_id, f'{ANNEE}-01-10'))
            db.commit()
            seance_id = db.execute(
                "SELECT id FROM benevoles_seances ORDER BY id DESC LIMIT 1").fetchone()['id']
        admin_client.post(f'/api/benevoles/activites/{act_id}/participants/ajouter',
                          json={'benevole_id': ben_id})
        admin_client.post('/api/benevoles/presences',
                          json={'seance_id': seance_id, 'benevole_id': ben_id,
                                'present': True})
        with app.app_context():
            part_id = db.execute(
                "SELECT id FROM benevoles_participations WHERE activite_id = ?",
                (act_id,)).fetchone()['id']

        admin_client.post(f'/api/benevoles/participations/{part_id}/supprimer')
        assert _total_heures(app, db, ben_id) == 0


class TestReferencesInexistantes:
    """Une référence inconnue ne doit rien écrire."""

    @pytest.mark.parametrize('url,corps', [
        ('/api/benevoles/activites/999999/seances/ajouter', {'date': f'{ANNEE}-01-10'}),
        ('/api/benevoles/activites/999999/participants/ajouter', {'benevole_id': 1}),
        ('/api/benevoles/activites/999999/modifier', {'field': 'nom', 'value': 'X'}),
        ('/api/benevoles/seances/999999/modifier', {'field': 'heures', 'value': 2}),
        ('/api/benevoles/participations/999999/modifier', {'absences': 1}),
        ('/api/benevoles/presences', {'seance_id': 999999, 'benevole_id': 1,
                                      'present': True}),
    ])
    def test_404_sans_ecriture(self, app, db, admin_client, url, corps):
        _creer_benevole(app, db)
        r = admin_client.post(url, json=corps)
        assert r.status_code == 404
        with app.app_context():
            for table in ('benevoles_seances', 'benevoles_participations',
                          'benevoles_presences'):
                assert db.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()['n'] == 0

    def test_participant_benevole_inexistant(self, app, db, admin_client):
        act_id = _creer_activite(app, db)
        r = admin_client.post(f'/api/benevoles/activites/{act_id}/participants/ajouter',
                              json={'benevole_id': 999999})
        assert r.status_code == 404
        with app.app_context():
            assert db.execute(
                "SELECT COUNT(*) AS n FROM benevoles_participations").fetchone()['n'] == 0

    def test_mode_inconnu_refuse(self, app, db, admin_client):
        act_id = _creer_activite(app, db)
        r = admin_client.post(f'/api/benevoles/activites/{act_id}/modifier',
                              json={'field': 'mode', 'value': 'au_pif'})
        assert r.status_code == 400
        with app.app_context():
            assert db.execute("SELECT mode FROM benevoles_activites WHERE id = ?",
                              (act_id,)).fetchone()['mode'] == 'seance'


class TestCoherenceDesDates:
    """La date d'une séance doit tomber dans l'année de l'activité.

    Le total annuel regroupe les séances par l'année de l'ACTIVITÉ : une date
    hors de cette année serait comptée dans le mauvais exercice.
    """

    @pytest.mark.parametrize('date_hors_annee', [f'{ANNEE - 1}-12-31', f'{ANNEE + 1}-01-02'])
    def test_date_hors_annee_refusee(self, app, db, admin_client, date_hors_annee):
        act_id = _creer_activite(app, db)
        r = admin_client.post(f'/api/benevoles/activites/{act_id}/seances/ajouter',
                              json={'date': date_hors_annee})
        assert r.status_code == 400
        assert str(ANNEE) in r.get_json()['error']
        with app.app_context():
            assert db.execute(
                "SELECT COUNT(*) AS n FROM benevoles_seances").fetchone()['n'] == 0

    @pytest.mark.parametrize('date_invalide', [f'{ANNEE}-02-31', f'{ANNEE}-13-01',
                                              '31/01/2026', 'demain', ''])
    def test_date_invalide_refusee(self, app, db, admin_client, date_invalide):
        act_id = _creer_activite(app, db)
        r = admin_client.post(f'/api/benevoles/activites/{act_id}/seances/ajouter',
                              json={'date': date_invalide})
        assert r.status_code == 400
        with app.app_context():
            assert db.execute(
                "SELECT COUNT(*) AS n FROM benevoles_seances").fetchone()['n'] == 0

    def test_date_dans_l_annee_acceptee(self, app, db, admin_client):
        act_id = _creer_activite(app, db)
        r = admin_client.post(f'/api/benevoles/activites/{act_id}/seances/ajouter',
                              json={'date': f'{ANNEE}-02-28'})
        assert r.status_code == 200

    def test_modification_vers_une_date_hors_annee_refusee(self, app, db, admin_client):
        """Même contrôle à la modification, sinon la correction contourne l'ajout."""
        act_id = _creer_activite(app, db)
        with app.app_context():
            db.execute("INSERT INTO benevoles_seances (activite_id, date, heures) "
                       "VALUES (?, ?, 2)", (act_id, f'{ANNEE}-01-10'))
            db.commit()
            seance_id = db.execute(
                "SELECT id FROM benevoles_seances ORDER BY id DESC LIMIT 1").fetchone()['id']
        r = admin_client.post(f'/api/benevoles/seances/{seance_id}/modifier',
                              json={'field': 'date', 'value': f'{ANNEE - 1}-06-01'})
        assert r.status_code == 400
        with app.app_context():
            assert db.execute("SELECT date FROM benevoles_seances WHERE id = ?",
                              (seance_id,)).fetchone()['date'] == f'{ANNEE}-01-10'


class TestBaseNeuve:
    """Une installation neuve ne doit pas réclamer une migration déjà incluse."""

    def test_migration_0061_marquee_appliquee(self, app, db):
        """`init_db()` crée déjà le schéma 0061 : la version doit être
        enregistrée, sinon l'administrateur d'une base neuve voit une mise à
        jour en attente qui n'a rien à faire."""
        import database
        assert any(v == '0061' for v, _ in database.ALL_MIGRATION_VERSIONS), \
            "0061 doit figurer dans ALL_MIGRATION_VERSIONS"
        with app.app_context():
            ligne = db.execute(
                "SELECT statut FROM schema_migrations WHERE version = '0061'").fetchone()
        assert ligne and ligne['statut'] == 'ok'


class TestAccesSuiviDesHeures:
    """Tests négatifs : le suivi est réservé à la direction et à la comptabilité."""

    def test_page_refusee_aux_autres_profils(self, app, db, client, sample_users):
        for login, mot_de_passe in (('salarie_test', 'sal123'), ('resp_test', 'resp123')):
            _connexion(client, login, mot_de_passe)
            r = client.get('/benevoles/heures', follow_redirects=False)
            assert r.status_code == 302, f"{login} ne doit pas voir le suivi des heures"
            assert '/dashboard' in r.headers['Location']
            client.get('/logout', follow_redirects=True)

    def test_page_accessible_direction_et_comptabilite(self, app, db, client, sample_users):
        for login, mot_de_passe in (('admin', 'Admin1234'), ('compta_test', 'compta123')):
            _connexion(client, login, mot_de_passe)
            assert client.get('/benevoles/heures').status_code == 200
            client.get('/logout', follow_redirects=True)

    def test_apis_refusees_sans_effet(self, app, db, client, sample_users):
        """Un profil non autorisé est refusé ET ne modifie rien."""
        ben_id = _creer_benevole(app, db)
        act_id = _creer_activite(app, db)
        appels = [
            ('/api/benevoles/activites/ajouter', {'nom': 'Intrus'}),
            (f'/api/benevoles/activites/{act_id}/supprimer', {}),
            (f'/api/benevoles/activites/{act_id}/seances/ajouter', {'date': f'{ANNEE}-02-02'}),
            (f'/api/benevoles/activites/{act_id}/participants/ajouter',
             {'benevole_id': ben_id}),
            ('/api/benevoles/heures-autres/ajouter', {'benevole_id': ben_id, 'heures': 9}),
        ]
        for login, mot_de_passe in (('salarie_test', 'sal123'), ('resp_test', 'resp123')):
            _connexion(client, login, mot_de_passe)
            for url, corps in appels:
                r = client.post(url, json=corps)
                assert r.status_code == 403, f"{login} ne doit pas pouvoir appeler {url}"
            client.get('/logout', follow_redirects=True)

        with app.app_context():
            assert db.execute("SELECT COUNT(*) AS n FROM benevoles_activites"
                              ).fetchone()['n'] == 1, "l'activité ne doit être ni créée ni supprimée"
            for table in ('benevoles_seances', 'benevoles_participations',
                          'benevoles_heures_autres'):
                assert db.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()['n'] == 0

    def test_bouton_suivi_absent_pour_le_responsable(self, app, db, client, sample_users):
        _creer_benevole(app, db)
        _connexion(client, 'resp_test', 'resp123')
        html = client.get('/benevoles').get_data(as_text=True)
        assert '/benevoles/heures' not in html, \
            "le lien vers le suivi ne doit pas être proposé au responsable"

    def test_anonyme_redirige_vers_login(self, app, db, client):
        r = client.get('/benevoles/heures', follow_redirects=False)
        assert r.status_code in (301, 302)
        assert '/login' in r.headers['Location']
