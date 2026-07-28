"""
Tests du blueprint factures_bp : contrôle d'accès (profil et périmètre de
secteur) et suppression (avec nettoyage des écritures liées).
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


def _seed_secteur_avec_responsable(app, db, nom_secteur, login, mot_de_passe):
    """Crée un second secteur et son responsable (pour tester le cloisonnement)."""
    from werkzeug.security import generate_password_hash

    with app.app_context():
        cur = db.execute("INSERT INTO secteurs (nom) VALUES (?)", (nom_secteur,))
        secteur_id = cur.lastrowid
        db.execute(
            "INSERT INTO users (nom, prenom, login, password, profil, secteur_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ('Voisin', 'Paul', login, generate_password_hash(mot_de_passe),
             'responsable', secteur_id),
        )
        db.commit()
        return secteur_id


def _compte(app, db, table, facture_id):
    """Nombre de lignes liées à une facture dans la table indiquée."""
    with app.app_context():
        return db.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE facture_id=?", (facture_id,)
        ).fetchone()['n']


def _connexion(client, login, mot_de_passe):
    return client.post('/login', data={'login': login, 'password': mot_de_passe},
                       follow_redirects=True)


class TestCommentaireFacture:
    """Ajout d'un commentaire : profil ET périmètre de secteur, comme les
    routes voisines (détail, téléchargement, approbation)."""

    def test_commenter_controle_acces_et_perimetre(self, app, db, client, sample_users):
        """Non connecté redirigé, salarié refusé, responsable d'un autre secteur
        refusé sans écriture en base, responsable du secteur accepté. Les
        fixtures de clients authentifiés partagent le même client de test : on
        gère les connexions explicitement pour enchaîner plusieurs profils."""
        facture_id = _seed_facture(app, db, secteur_id=sample_users['secteur_id'])
        _seed_secteur_avec_responsable(app, db, 'Secteur Voisin', 'resp_autre', 'autre123')
        url = f'/factures/{facture_id}/commenter'

        # Non connecté : redirigé vers la connexion, aucun commentaire enregistré.
        reponse = client.post(url, data={'commentaire': 'Anonyme'}, follow_redirects=False)
        assert reponse.status_code in (301, 302)
        assert _compte(app, db, 'facture_commentaires', facture_id) == 0

        # Salarié : profil hors consultation des factures.
        _connexion(client, 'salarie_test', 'sal123')
        reponse = client.post(url, data={'commentaire': 'Salarié'}, follow_redirects=False)
        assert reponse.status_code == 302
        assert _compte(app, db, 'facture_commentaires', facture_id) == 0
        client.get('/logout', follow_redirects=True)

        # Responsable d'un autre secteur : refusé, aucune trace en base.
        _connexion(client, 'resp_autre', 'autre123')
        reponse = client.post(url, data={'commentaire': 'Hors secteur'}, follow_redirects=False)
        assert reponse.status_code == 302
        assert '/factures/approbation' in reponse.headers['Location']
        assert _compte(app, db, 'facture_commentaires', facture_id) == 0
        assert _compte(app, db, 'facture_historique', facture_id) == 0
        client.get('/logout', follow_redirects=True)

        # Responsable du secteur : commentaire vide refusé, puis cas légitime accepté.
        _connexion(client, 'resp_test', 'resp123')
        reponse = client.post(url, data={'commentaire': '   '}, follow_redirects=False)
        assert reponse.status_code == 302
        assert _compte(app, db, 'facture_commentaires', facture_id) == 0

        reponse = client.post(url, data={'commentaire': 'RAS pour mon secteur'},
                              follow_redirects=False)
        assert reponse.status_code == 302
        assert _compte(app, db, 'facture_commentaires', facture_id) == 1
        assert _compte(app, db, 'facture_historique', facture_id) == 1
        client.get('/logout', follow_redirects=True)

    def test_commenter_hors_secteur_invisible_dans_le_detail(self, app, db, client, sample_users):
        """Le refus doit aussi empêcher l'apparition du texte dans l'historique
        visible par le responsable légitime."""
        facture_id = _seed_facture(app, db, secteur_id=sample_users['secteur_id'])
        _seed_secteur_avec_responsable(app, db, 'Secteur Voisin', 'resp_autre', 'autre123')

        _connexion(client, 'resp_autre', 'autre123')
        client.post(f'/factures/{facture_id}/commenter',
                    data={'commentaire': 'Commentaire intrus'}, follow_redirects=False)
        client.get('/logout', follow_redirects=True)

        _connexion(client, 'compta_test', 'compta123')
        html = client.get(f'/factures/{facture_id}/detail').get_data(as_text=True)
        assert 'Commentaire intrus' not in html

    def test_commenter_facture_inexistante_sans_orphelin(self, app, db, comptable_client):
        """Une facture absente ne doit produire ni commentaire ni historique orphelin."""
        reponse = comptable_client.post('/factures/999999/commenter',
                                        data={'commentaire': 'Fantôme'},
                                        follow_redirects=False)
        assert reponse.status_code == 302
        assert _compte(app, db, 'facture_commentaires', 999999) == 0
        assert _compte(app, db, 'facture_historique', 999999) == 0


class TestAssignationFacture:
    """Assignation d'une facture : réservée à la gestion (directeur/comptable)
    et refusée sur une facture inexistante."""

    def test_assigner_controle_acces(self, app, db, client, sample_users):
        facture_id = _seed_facture(app, db)
        url = f'/factures/{facture_id}/assigner'
        donnees = {'secteur_id': sample_users['secteur_id']}

        # Non connecté : redirigé vers la connexion.
        reponse = client.post(url, data=donnees, follow_redirects=False)
        assert reponse.status_code in (301, 302)

        # Salarié et responsable : profils hors gestion.
        for login, mot_de_passe in (('salarie_test', 'sal123'), ('resp_test', 'resp123')):
            _connexion(client, login, mot_de_passe)
            assert client.post(url, data=donnees).status_code == 403
            client.get('/logout', follow_redirects=True)

        with app.app_context():
            assert db.execute(
                "SELECT secteur_id FROM factures WHERE id=?", (facture_id,)
            ).fetchone()['secteur_id'] is None
        assert _compte(app, db, 'facture_historique', facture_id) == 0

        # Comptable : assignation effective et tracée.
        _connexion(client, 'compta_test', 'compta123')
        assert client.post(url, data=donnees, follow_redirects=False).status_code == 302
        with app.app_context():
            assert db.execute(
                "SELECT secteur_id FROM factures WHERE id=?", (facture_id,)
            ).fetchone()['secteur_id'] == sample_users['secteur_id']
        assert _compte(app, db, 'facture_historique', facture_id) == 1

    def test_assigner_facture_inexistante_sans_orphelin(self, app, db, comptable_client,
                                                        sample_users):
        reponse = comptable_client.post(
            '/factures/999999/assigner',
            json={'secteur_id': sample_users['secteur_id']},
        )
        assert reponse.status_code == 404
        assert _compte(app, db, 'facture_historique', 999999) == 0


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
