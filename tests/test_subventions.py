import io


class TestSousElementDocumentNaming:
    def _login_admin(self, client):
        client.post('/login', data={'login': 'admin', 'password': 'Admin1234'}, follow_redirects=False)

    def _create_subvention_with_sous_element(self, app, db, subvention_nom, annee_action, sous_element_nom):
        with app.app_context():
            cursor = db.execute(
                'INSERT INTO subventions (nom, annee_action) VALUES (?, ?)',
                (subvention_nom, annee_action)
            )
            sub_id = cursor.lastrowid
            cursor = db.execute(
                'INSERT INTO subventions_sous_elements (subvention_id, nom, ordre) VALUES (?, ?, ?)',
                (sub_id, sous_element_nom, 0)
            )
            db.commit()
            return cursor.lastrowid

    def test_upload_genere_nom_document_unique_par_sous_element(
        self, app, db, client, sample_users, monkeypatch, tmp_path
    ):
        from blueprints import subventions as subventions_module
        monkeypatch.setattr(subventions_module, 'DOCUMENTS_DIR', str(tmp_path))

        se1_id = self._create_subvention_with_sous_element(app, db, 'Aide CAF', '2026', 'Bilan')
        se2_id = self._create_subvention_with_sous_element(app, db, 'Aide CAF', '2026', 'Bilan')

        self._login_admin(client)
        response_1 = client.post(
            f'/api/subventions/sous-elements/{se1_id}/document',
            data={'fichier': (io.BytesIO(b'pdf-one'), 'document.pdf')},
            content_type='multipart/form-data'
        )
        response_2 = client.post(
            f'/api/subventions/sous-elements/{se2_id}/document',
            data={'fichier': (io.BytesIO(b'pdf-two'), 'document.pdf')},
            content_type='multipart/form-data'
        )

        assert response_1.status_code == 200
        assert response_2.status_code == 200

        with app.app_context():
            se1 = db.execute(
                'SELECT document_path FROM subventions_sous_elements WHERE id = ?',
                (se1_id,)
            ).fetchone()
            se2 = db.execute(
                'SELECT document_path FROM subventions_sous_elements WHERE id = ?',
                (se2_id,)
            ).fetchone()

        assert se1['document_path'] != se2['document_path']
        assert se1['document_path'].endswith(f'_{se1_id}.pdf')
        assert se2['document_path'].endswith(f'_{se2_id}.pdf')

    def test_supprimer_un_sous_element_ne_supprime_pas_le_fichier_dun_autre(
        self, app, db, client, sample_users, monkeypatch, tmp_path
    ):
        from blueprints import subventions as subventions_module
        monkeypatch.setattr(subventions_module, 'DOCUMENTS_DIR', str(tmp_path))

        se1_id = self._create_subvention_with_sous_element(app, db, 'Aide CAF', '2026', 'Bilan')
        se2_id = self._create_subvention_with_sous_element(app, db, 'Aide CAF', '2026', 'Bilan')

        self._login_admin(client)
        client.post(
            f'/api/subventions/sous-elements/{se1_id}/document',
            data={'fichier': (io.BytesIO(b'pdf-one'), 'document.pdf')},
            content_type='multipart/form-data'
        )
        client.post(
            f'/api/subventions/sous-elements/{se2_id}/document',
            data={'fichier': (io.BytesIO(b'pdf-two'), 'document.pdf')},
            content_type='multipart/form-data'
        )

        with app.app_context():
            se1 = db.execute(
                'SELECT document_path FROM subventions_sous_elements WHERE id = ?',
                (se1_id,)
            ).fetchone()
            se2 = db.execute(
                'SELECT document_path FROM subventions_sous_elements WHERE id = ?',
                (se2_id,)
            ).fetchone()

        assert (tmp_path / se1['document_path']).exists()
        assert (tmp_path / se2['document_path']).exists()

        response = client.post(f'/api/subventions/sous-elements/{se1_id}/supprimer')
        assert response.status_code == 200

        assert not (tmp_path / se1['document_path']).exists()
        assert (tmp_path / se2['document_path']).exists()


class TestSubventionsBenevolesRendering:
    def test_benevoles_ids_sont_compares_exactement(self, app, db, admin_client, sample_users):
        with app.app_context():
            db.execute(
                'INSERT INTO benevoles (id, nom, groupe) VALUES (?, ?, ?)',
                (1, 'Benevole 1', 'nouveau')
            )
            db.execute(
                'INSERT INTO benevoles (id, nom, groupe) VALUES (?, ?, ?)',
                (10, 'Benevole 10', 'nouveau')
            )
            db.execute(
                'INSERT INTO subventions (nom, benevoles_ids) VALUES (?, ?)',
                ('Subvention test', '[10]')
            )
            db.commit()

        response = admin_client.get('/subventions')
        assert response.status_code == 200

        html = response.get_data(as_text=True)
        assert '<span class="sv-tag">Benevole 10</span>' in html
        assert '<span class="sv-tag">Benevole 1</span>' not in html


class TestNotificationAttribution:
    """Notification e-mail lors de l'attribution d'une subvention / sous-élément."""

    def _capturer(self, monkeypatch):
        import email_service
        captures = []
        monkeypatch.setattr(email_service, 'is_email_configured', lambda: True)
        monkeypatch.setattr(email_service, 'peut_envoyer_email', lambda uid: (True, f'u{uid}@ex.fr'))

        def fake(email, prenom, nom, annee=None, se=None):
            captures.append({'email': email, 'nom': nom, 'annee': annee, 'se': se})
            return (True, 'ok')
        monkeypatch.setattr(email_service, 'notifier_subvention_assignee', fake)
        return captures

    def test_attribution_subvention_notifie(self, app, admin_client, db, sample_users, monkeypatch):
        captures = self._capturer(monkeypatch)
        db.execute("INSERT INTO subventions (nom, groupe, annee_action) VALUES ('CLAS','en_cours','2026')")
        sid = db.execute("SELECT id FROM subventions WHERE nom='CLAS'").fetchone()['id']
        db.commit()

        resp = admin_client.post(f'/api/subventions/{sid}/modifier',
                                 json={'field': 'assignee_1_id', 'value': sample_users['salarie_id']})
        assert resp.status_code == 200
        assert len(captures) == 1
        assert captures[0]['nom'] == 'CLAS'
        assert captures[0]['annee'] == '2026'
        assert captures[0]['se'] is None

    def test_attribution_sous_element_precise_l_etape(self, app, admin_client, db, sample_users, monkeypatch):
        captures = self._capturer(monkeypatch)
        cur = db.execute("INSERT INTO subventions (nom, groupe, annee_action) VALUES ('Numerique','en_cours','2026')")
        sid = cur.lastrowid
        se_id = db.execute(
            "INSERT INTO subventions_sous_elements (subvention_id, nom, ordre) VALUES (?, 'Envoyer le bilan', 0)",
            (sid,)
        ).lastrowid
        db.commit()

        resp = admin_client.post(f'/api/subventions/sous-elements/{se_id}/modifier',
                                 json={'field': 'assignee_id', 'value': sample_users['responsable_id']})
        assert resp.status_code == 200
        assert len(captures) == 1
        assert captures[0]['nom'] == 'Numerique'
        assert captures[0]['annee'] == '2026'
        assert captures[0]['se'] == 'Envoyer le bilan'

    def test_pas_de_notification_si_inchange_ou_vide(self, app, admin_client, db, sample_users, monkeypatch):
        captures = self._capturer(monkeypatch)
        db.execute(
            "INSERT INTO subventions (nom, groupe, annee_action, assignee_1_id) VALUES ('X','en_cours','2026',?)",
            (sample_users['salarie_id'],)
        )
        sid = db.execute("SELECT id FROM subventions WHERE nom='X'").fetchone()['id']
        db.commit()

        # Ré-assigner la même personne : pas de notification.
        admin_client.post(f'/api/subventions/{sid}/modifier',
                          json={'field': 'assignee_1_id', 'value': sample_users['salarie_id']})
        # Vider l'assignation : pas de notification.
        admin_client.post(f'/api/subventions/{sid}/modifier',
                          json={'field': 'assignee_1_id', 'value': None})
        assert captures == []


class TestVisibiliteResponsable:
    """Un responsable voit les subventions dont un sous-élément lui est attribué,
    même s'il n'est pas assigné à la subvention parente."""

    def test_responsable_voit_subvention_via_sous_element(self, app, resp_client, db, sample_users):
        resp_id = sample_users['responsable_id']
        # Subvention attribuée au responsable via un sous-élément uniquement.
        cur = db.execute(
            "INSERT INTO subventions (nom, groupe, annee_action) VALUES ('DossierSE','en_cours','2026')"
        )
        db.execute(
            "INSERT INTO subventions_sous_elements (subvention_id, nom, assignee_id, ordre) VALUES (?, 'Bilan', ?, 0)",
            (cur.lastrowid, resp_id)
        )
        # Subvention sans aucun lien avec le responsable : ne doit pas apparaître.
        db.execute("INSERT INTO subventions (nom, groupe, annee_action) VALUES ('Cachee','en_cours','2026')")
        db.commit()

        resp = resp_client.get('/subventions')
        assert resp.status_code == 200
        assert b'DossierSE' in resp.data
        assert b'Cachee' not in resp.data
