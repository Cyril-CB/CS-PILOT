"""
Tests : demandes de congés par la direction (forfait jours).

La direction n'a pas de responsable au-dessus : sa demande de congé est
auto-validée à la création, reportée sur le calendrier forfait jour
(presence_forfait_jour) et sur la prépa paie (table absences), et éditable en
PDF avec les signatures Direction / Comité de présidence. Un nouveau type
« Forfait jour » lui est réservé.
"""
from datetime import date, timedelta

import pytest


def _jour_ouvre(annee=2026, mois=6, jour=1):
    """Retourne un jour ouvré (lun-ven) au format ISO, à partir d'une date donnée."""
    d = date(annee, mois, jour)
    while d.weekday() > 4:  # samedi / dimanche → avancer
        d += timedelta(days=1)
    return d.isoformat()


class TestDemandeCongeDirection:
    def test_directeur_conge_auto_valide_et_reporte(self, app, db, admin_client):
        jour = _jour_ouvre(mois=6, jour=2)
        r = admin_client.post('/demande_conge', data={
            'type_conge': 'Congé payé', 'date_debut': jour, 'date_fin': jour,
            'motif_demande': 'Test',
        }, follow_redirects=False)
        assert r.status_code in (301, 302)
        with app.app_context():
            d = db.execute("SELECT * FROM demandes_conges ORDER BY id DESC LIMIT 1").fetchone()
            assert d['statut'] == 'validee'
            assert d['validation_direction']  # auto-signé
            # Absence créée (→ visible en prépa paie)
            ab = db.execute(
                "SELECT * FROM absences WHERE user_id = ? AND motif = 'Congé payé'",
                (d['user_id'],)).fetchone()
            assert ab is not None
            # Reporté sur le calendrier forfait jour
            pf = db.execute(
                "SELECT type_journee FROM presence_forfait_jour WHERE user_id = ? AND date = ?",
                (d['user_id'], jour)).fetchone()
            assert pf is not None and pf['type_journee'] == 'conge_paye'

    def test_type_forfait_jour_mappe_sur_le_calendrier(self, app, db, admin_client):
        jour = _jour_ouvre(mois=6, jour=9)
        admin_client.post('/demande_conge', data={
            'type_conge': 'Forfait jour', 'date_debut': jour, 'date_fin': jour,
        })
        with app.app_context():
            d = db.execute("SELECT * FROM demandes_conges ORDER BY id DESC LIMIT 1").fetchone()
            assert d['type_conge'] == 'Forfait jour' and d['statut'] == 'validee'
            pf = db.execute(
                "SELECT type_journee FROM presence_forfait_jour WHERE user_id = ? AND date = ?",
                (d['user_id'], jour)).fetchone()
            assert pf is not None and pf['type_journee'] == 'forfait_jour'

    def test_forfait_jour_refuse_pour_un_salarie(self, app, db, auth_client):
        # « Forfait jour » n'est proposé qu'à la direction : un salarié qui le
        # soumet est rejeté (type invalide), aucune demande créée.
        jour = _jour_ouvre()
        auth_client.post('/demande_conge', data={
            'type_conge': 'Forfait jour', 'date_debut': jour, 'date_fin': jour,
        })
        with app.app_context():
            n = db.execute(
                "SELECT COUNT(*) FROM demandes_conges WHERE type_conge = 'Forfait jour'").fetchone()[0]
        assert n == 0

    def test_salarie_conge_reste_en_attente(self, app, db, auth_client):
        # Un salarié conserve le circuit de validation classique.
        jour = _jour_ouvre(mois=6, jour=16)
        auth_client.post('/demande_conge', data={
            'type_conge': 'Congé payé', 'date_debut': jour, 'date_fin': jour,
        })
        with app.app_context():
            d = db.execute("SELECT statut FROM demandes_conges ORDER BY id DESC LIMIT 1").fetchone()
            assert d is not None and d['statut'] == 'en_attente_responsable'

    @pytest.mark.parametrize('type_conge,type_journee,jour_pose,jour_demande', [
        ('Congé payé', 'conge_paye', _jour_ouvre(mois=6, jour=3), _jour_ouvre(mois=6, jour=4)),
        ('Congé conventionnel', 'conge_conv', _jour_ouvre(mois=6, jour=5), _jour_ouvre(mois=6, jour=8)),
    ])
    def test_directeur_demande_conge_aligne_alerte_sur_forfait(
        self, app, db, admin_client, sample_users, type_conge, type_journee, jour_pose, jour_demande
    ):
        """La pré-alerte lit le registre forfait, pas les colonnes users du directeur."""
        uid = sample_users['directeur_id']
        db.execute("UPDATE users SET cp_a_prendre = 0, cp_pris = 0, cc_solde = 0 WHERE id = ?", (uid,))
        db.execute(
            "INSERT INTO presence_forfait_jour (user_id, date, type_journee) VALUES (?, ?, ?)",
            (uid, jour_pose, type_journee)
        )
        db.commit()

        r = admin_client.post('/demande_conge', data={
            'type_conge': type_conge, 'date_debut': jour_demande, 'date_fin': jour_demande,
        }, follow_redirects=True)
        html = r.get_data(as_text=True)

        assert r.status_code == 200
        assert 'congé pris par anticipation' not in html
        with app.app_context():
            d = db.execute("SELECT * FROM demandes_conges ORDER BY id DESC LIMIT 1").fetchone()
            assert d is not None and d['type_conge'] == type_conge and d['statut'] == 'validee'
            pf = db.execute(
                "SELECT type_journee FROM presence_forfait_jour WHERE user_id = ? AND date = ?",
                (uid, jour_demande)
            ).fetchone()
            assert pf is not None and pf['type_journee'] == type_journee

    def _poser_jours_forfait(self, db, uid, type_journee, nb, exclus=()):
        """Pose nb jours ouvrés 2026 (hors dates exclues) dans le calendrier forfait."""
        d = date(2026, 1, 5)
        poses = 0
        while poses < nb:
            if d.weekday() < 5 and d.isoformat() not in exclus:
                db.execute(
                    "INSERT INTO presence_forfait_jour (user_id, date, type_journee) VALUES (?, ?, ?)",
                    (uid, d.isoformat(), type_journee)
                )
                poses += 1
            d += timedelta(days=1)
        db.commit()

    def test_directeur_forfait_jour_alerte_sur_repos_forfait_pas_sur_cc(
        self, app, db, admin_client, sample_users
    ):
        """« Forfait jour » se compare au solde de repos forfait, pas aux congés conventionnels."""
        uid = sample_users['directeur_id']
        jour_demande = _jour_ouvre(mois=9, jour=15)
        # Congés conventionnels épuisés (8/8) : ne doit pas déclencher d'alerte.
        self._poser_jours_forfait(db, uid, 'conge_conv', 8, exclus=(jour_demande,))

        r = admin_client.post('/demande_conge', data={
            'type_conge': 'Forfait jour', 'date_debut': jour_demande, 'date_fin': jour_demande,
        }, follow_redirects=True)
        html = r.get_data(as_text=True)

        assert r.status_code == 200
        assert 'passera à' not in html
        with app.app_context():
            d = db.execute("SELECT * FROM demandes_conges ORDER BY id DESC LIMIT 1").fetchone()
            assert d['type_conge'] == 'Forfait jour' and d['statut'] == 'validee'

    def test_directeur_forfait_jour_alerte_quand_repos_forfait_epuise(
        self, app, db, admin_client, sample_users
    ):
        """Cas négatif : quota de repos forfait épuisé → alerte, demande tout de même validée."""
        from utils import calculer_stats_forfait_jour

        uid = sample_users['directeur_id']
        jour_demande = _jour_ouvre(mois=12, jour=14)
        with app.app_context():
            restants = calculer_stats_forfait_jour(uid, 2026)['soldes']['repos_forfait_restants']
        assert restants > 0
        self._poser_jours_forfait(db, uid, 'repos_forfait', restants, exclus=(jour_demande,))

        r = admin_client.post('/demande_conge', data={
            'type_conge': 'Forfait jour', 'date_debut': jour_demande, 'date_fin': jour_demande,
        }, follow_redirects=True)
        html = r.get_data(as_text=True)

        assert 'passera à -1.0 jour(s)' in html
        assert 'quota annuel du forfait jours dépassé' in html
        assert 'peut être refusé' not in html
        with app.app_context():
            d = db.execute("SELECT * FROM demandes_conges ORDER BY id DESC LIMIT 1").fetchone()
            assert d['type_conge'] == 'Forfait jour' and d['statut'] == 'validee'

    def test_directeur_forfait_jour_pas_d_alerte_a_tort_avec_feries(
        self, app, db, admin_client, sample_users
    ):
        """Avec des fériés configurés, le dernier jour de repos restant ne déclenche pas d'alerte."""
        from utils import calculer_stats_forfait_jour

        uid = sample_users['directeur_id']
        feries = ['2026-01-01', '2026-04-06', '2026-05-01', '2026-05-08', '2026-05-14',
                  '2026-05-25', '2026-07-14', '2026-11-11', '2026-12-25']
        for jour in feries:
            db.execute("INSERT INTO jours_feries (annee, date, libelle) VALUES (2026, ?, 'Férié')", (jour,))
        db.commit()
        jour_demande = _jour_ouvre(mois=12, jour=14)
        with app.app_context():
            quota = calculer_stats_forfait_jour(uid, 2026)['config']['jours_repos_forfait']
        assert quota == 9
        # 8 repos déjà posés : il en reste 1, la demande d'un jour ne dépasse pas le quota.
        self._poser_jours_forfait(db, uid, 'repos_forfait', 8, exclus=set(feries) | {jour_demande})

        r = admin_client.post('/demande_conge', data={
            'type_conge': 'Forfait jour', 'date_debut': jour_demande, 'date_fin': jour_demande,
        }, follow_redirects=True)

        assert 'passera à' not in r.get_data(as_text=True)

    def test_formulaire_directeur_affiche_les_soldes_forfait(
        self, app, db, admin_client, sample_users, monkeypatch
    ):
        """Le formulaire de dépôt affiche les mêmes soldes que Mon espace pour la direction."""
        import blueprints.recup as recup_module

        monkeypatch.setattr(recup_module, 'aujourd_hui', lambda: date(2026, 6, 15))
        uid = sample_users['directeur_id']
        db.execute("UPDATE users SET cp_a_prendre = 0, cp_pris = 0, cc_solde = 0 WHERE id = ?", (uid,))
        db.commit()
        self._poser_jours_forfait(db, uid, 'conge_paye', 2)

        html = admin_client.get('/demande_conge').get_data(as_text=True)

        assert '23.0 jour(s)' in html   # 25 - 2 CP posés
        assert '8.0 jour(s)' in html    # 8 CC, aucun posé
        assert 'Solde repos forfait' in html

    def test_formulaire_salarie_garde_les_soldes_users(self, app, db, auth_client, sample_users):
        """Un salarié conserve les soldes issus de users, sans solde repos forfait."""
        db.execute(
            "UPDATE users SET cp_a_prendre = 12, cp_pris = 2.5, cc_solde = 3 WHERE id = ?",
            (sample_users['salarie_id'],)
        )
        db.commit()

        html = auth_client.get('/demande_conge').get_data(as_text=True)

        assert '9.5 jour(s)' in html
        assert '3.0 jour(s)' in html
        assert 'Solde repos forfait' not in html

    def test_pdf_demande_conge(self, app, db, admin_client):
        jour = _jour_ouvre(mois=6, jour=23)
        admin_client.post('/demande_conge', data={
            'type_conge': 'Forfait jour', 'date_debut': jour, 'date_fin': jour,
        })
        with app.app_context():
            demande_id = db.execute(
                "SELECT id FROM demandes_conges ORDER BY id DESC LIMIT 1").fetchone()['id']
        r = admin_client.get(f'/demande_conge/{demande_id}/pdf')
        assert r.status_code == 200
        assert r.headers['Content-Type'] == 'application/pdf'
        assert r.get_data()[:4] == b'%PDF'

    def test_pdf_refuse_a_un_autre_salarie(self, app, db, sample_users, auth_client):
        # Une demande de la direction ne doit pas être téléchargeable par un
        # salarié tiers (ni propriétaire, ni direction/comptabilité).
        jour = _jour_ouvre(mois=6, jour=24)
        with app.app_context():
            cur = db.execute(
                "INSERT INTO demandes_conges (user_id, type_conge, date_debut, date_fin, nb_jours, statut) "
                "VALUES (?, 'Congé payé', ?, ?, 1, 'validee')",
                (sample_users['directeur_id'], jour, jour))
            db.commit()
            demande_id = cur.lastrowid
        r = auth_client.get(f'/demande_conge/{demande_id}/pdf', follow_redirects=False)
        assert r.status_code in (301, 302)  # redirigé (accès refusé)

    def test_menu_directeur_expose_la_demande_de_conge(self, admin_client):
        html = admin_client.get('/dashboard_direction').get_data(as_text=True)
        assert '/demande_conge' in html

    def test_forfait_jour_consomme_le_quota_repos_forfait(self, app, db, sample_users):
        # Un jour « Forfait jour » doit décompter le quota de repos forfait
        # (sinon la direction pourrait en poser sans limite).
        from utils import calculer_stats_forfait_jour
        uid = sample_users['directeur_id']
        with app.app_context():
            base = calculer_stats_forfait_jour(uid, 2026)
            db.execute(
                "INSERT OR REPLACE INTO presence_forfait_jour (user_id, date, type_journee) "
                "VALUES (?, '2026-06-10', 'forfait_jour')", (uid,))
            db.commit()
            apres = calculer_stats_forfait_jour(uid, 2026)
        assert apres['repos_forfait'] == base['repos_forfait'] + 1
        assert apres['soldes']['repos_forfait_restants'] == base['soldes']['repos_forfait_restants'] - 1

    def test_calendrier_affiche_le_jour_forfait(self, app, db, admin_client):
        # Le calendrier forfait jour doit rendre le nouveau type sans erreur.
        jour = _jour_ouvre(mois=6, jour=10)
        admin_client.post('/demande_conge', data={
            'type_conge': 'Forfait jour', 'date_debut': jour, 'date_fin': jour,
        })
        r = admin_client.get('/calendrier_forfait_jour?mois=6&annee=2026')
        assert r.status_code == 200
        assert 'Forfait jour' in r.get_data(as_text=True)
