"""
Tests du blueprint factures_bp : contrôle d'accès et suppression (avec
nettoyage des écritures liées).
"""


def _seed_facture(app, db, statut='a_traiter', secteur_id=None):
    with app.app_context():
        cur = db.execute("INSERT INTO fournisseurs (nom) VALUES (?)", ('ACME',))
        fid = cur.lastrowid
        cur = db.execute(
            "INSERT INTO factures (fournisseur_id, numero_facture, date_facture, "
            "montant_ttc, statut, secteur_id) VALUES (?, ?, ?, ?, ?, ?)",
            (fid, 'INV-001', '2025-01-15', 120.0, statut, secteur_id),
        )
        facture_id = cur.lastrowid
        db.commit()
        return facture_id


class TestAccesFactures:
    def test_salarie_refuse(self, auth_client):
        resp = auth_client.get('/factures', follow_redirects=False)
        assert resp.status_code == 302

    def test_responsable_refuse_gestion(self, resp_client):
        # La gestion des factures est réservée à directeur/comptable
        resp = resp_client.get('/factures', follow_redirects=False)
        assert resp.status_code == 302

    def test_comptable_autorise(self, comptable_client):
        resp = comptable_client.get('/factures')
        assert resp.status_code == 200

    def test_page_approbation_accessible_responsable(self, resp_client):
        # Les responsables accèdent à la page d'approbation
        resp = resp_client.get('/factures/approbation')
        assert resp.status_code == 200


class TestSuppressionFacture:
    def test_supprimer_facture_supprime_les_ecritures(self, app, db, comptable_client):
        fid = _seed_facture(app, db)
        with app.app_context():
            db.execute(
                "INSERT INTO ecritures_comptables (facture_id, date_ecriture, compte, "
                "libelle, debit, credit) VALUES (?, ?, ?, ?, ?, ?)",
                (fid, '2025-01-15', '606100', 'TEST', 120.0, 0),
            )
            db.commit()

        comptable_client.post(f'/factures/{fid}/supprimer', follow_redirects=False)

        with app.app_context():
            assert db.execute(
                "SELECT COUNT(*) AS n FROM factures WHERE id=?", (fid,)
            ).fetchone()['n'] == 0
            assert db.execute(
                "SELECT COUNT(*) AS n FROM ecritures_comptables WHERE facture_id=?", (fid,)
            ).fetchone()['n'] == 0
