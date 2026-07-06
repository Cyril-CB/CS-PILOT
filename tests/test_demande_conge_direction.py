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
