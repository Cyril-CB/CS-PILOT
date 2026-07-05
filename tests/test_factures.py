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


class TestDetailFournisseur:
    """Fiche fournisseur : infos, total annuel, liste des factures + filtre année."""

    def _annee(self):
        from utils import aujourd_hui
        return aujourd_hui().year

    def _fournisseur(self, db, nom='ACME', code='ACME', email='contact@acme.fr'):
        cur = db.execute(
            "INSERT INTO fournisseurs (nom, code_comptable, email_contact) VALUES (?, ?, ?)",
            (nom, code, email)
        )
        return cur.lastrowid

    def _facture(self, db, fid, numero, date_facture, montant, secteur_id=None,
                 fichier_path=None):
        db.execute(
            "INSERT INTO factures (fournisseur_id, numero_facture, date_facture, "
            "montant_ttc, secteur_id, fichier_path) VALUES (?, ?, ?, ?, ?, ?)",
            (fid, numero, date_facture, montant, secteur_id, fichier_path)
        )

    def test_infos_et_total_annee_courante(self, app, db, comptable_client, sample_users):
        n = self._annee()
        with app.app_context():
            fid = self._fournisseur(db)
            self._facture(db, fid, 'INV-A', f'{n}-02-10', 100.0, sample_users['secteur_id'])
            self._facture(db, fid, 'INV-B', f'{n}-05-20', 200.0, sample_users['secteur_id'])
            self._facture(db, fid, 'INV-OLD', f'{n-1}-03-01', 999.0)  # autre année
            db.commit()

        html = comptable_client.get(f'/fournisseurs/{fid}').get_data(as_text=True)
        assert 'ACME' in html
        assert 'contact@acme.fr' in html          # adresse de contact
        assert 'Secteur Test' in html             # secteur alloué
        assert 'INV-A' in html and 'INV-B' in html
        assert 'INV-OLD' not in html              # autre année masquée
        assert '300,00' in html                   # total année courante (100 + 200)
        assert '999' not in html

    def test_filtre_annee_precedente(self, app, db, comptable_client, sample_users):
        n = self._annee()
        with app.app_context():
            fid = self._fournisseur(db, nom='BETA', code='BETA')
            self._facture(db, fid, 'INV-N', f'{n}-02-10', 100.0)
            self._facture(db, fid, 'INV-PREC', f'{n-1}-07-01', 50.0)
            db.commit()

        html = comptable_client.get(f'/fournisseurs/{fid}?annee={n-1}').get_data(as_text=True)
        assert 'INV-PREC' in html
        assert 'INV-N' not in html
        assert '50,00' in html

    def test_annee_hors_plage_repli_annee_courante(self, app, db, comptable_client):
        """Une année hors plage (ex. N-10) passée en URL retombe sur l'année
        courante : le filtre affiché et les données interrogées restent cohérents."""
        n = self._annee()
        with app.app_context():
            fid = self._fournisseur(db, nom='THETA', code='THETA')
            self._facture(db, fid, 'INV-NOW', f'{n}-02-10', 100.0)
            self._facture(db, fid, 'INV-VERYOLD', f'{n-10}-05-01', 777.0)
            db.commit()

        html = comptable_client.get(f'/fournisseurs/{fid}?annee={n-10}').get_data(as_text=True)
        assert 'INV-NOW' in html          # année courante affichée (repli)
        assert 'INV-VERYOLD' not in html  # année hors plage non interrogée
        # Le sélecteur reflète bien l'année courante sélectionnée.
        assert f'<option value="{n}" selected>' in html

    def test_plage_annees_n_moins_3(self, app, db, comptable_client):
        n = self._annee()
        with app.app_context():
            fid = self._fournisseur(db, nom='GAMMA', code='GAMMA')
            db.commit()
        html = comptable_client.get(f'/fournisseurs/{fid}').get_data(as_text=True)
        # Le sélecteur propose N … N-3 (et pas N-4).
        assert f'<option value="{n}"' in html
        assert f'<option value="{n-3}"' in html
        assert f'<option value="{n-4}"' not in html

    def test_lien_telechargement_selon_fichier(self, app, db, comptable_client):
        n = self._annee()
        with app.app_context():
            fid = self._fournisseur(db, nom='DELTA', code='DELTA')
            self._facture(db, fid, 'AVEC-PDF', f'{n}-01-05', 10.0, fichier_path='/tmp/x.pdf')
            self._facture(db, fid, 'SANS-PDF', f'{n}-01-06', 20.0, fichier_path=None)
            db.commit()
        html = comptable_client.get(f'/fournisseurs/{fid}').get_data(as_text=True)
        with app.app_context():
            avec_pdf_id = db.execute(
                "SELECT id FROM factures WHERE numero_facture='AVEC-PDF'"
            ).fetchone()['id']
        assert f'/factures/{avec_pdf_id}/telecharger' in html

    def test_lien_present_sur_la_liste(self, app, db, comptable_client):
        with app.app_context():
            fid = self._fournisseur(db, nom='EPSILON', code='EPS')
            db.commit()
        html = comptable_client.get('/fournisseurs').get_data(as_text=True)
        assert f'/fournisseurs/{fid}' in html

    def test_fournisseur_inexistant_redirige(self, app, comptable_client):
        resp = comptable_client.get('/fournisseurs/999999', follow_redirects=False)
        assert resp.status_code == 302

    def test_acces_refuse_salarie_et_responsable(self, app, db, auth_client, resp_client):
        with app.app_context():
            fid = self._fournisseur(db, nom='ZETA', code='ZETA')
            db.commit()
        assert auth_client.get(f'/fournisseurs/{fid}', follow_redirects=False).status_code == 302
        assert resp_client.get(f'/fournisseurs/{fid}', follow_redirects=False).status_code == 302
