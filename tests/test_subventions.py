import io


class TestTypesSubvention:
    """Catégories de la page subventions par type (créer / supprimer / assigner)."""

    def test_types_par_defaut_sont_seedes(self, app, db):
        with app.app_context():
            noms = [r['nom'] for r in db.execute(
                'SELECT nom FROM subventions_types ORDER BY ordre'
            ).fetchall()]
        assert noms == ['SUBV. GLOBAL', 'CAF PS', 'CAF', 'VILLE',
                        'METROPOLE', 'ETAT', 'AUTRES']

    def test_page_regroupe_par_type(self, app, admin_client, db, sample_users):
        # Chaque type est un groupe (swimlane) ; la colonne « Type » remplace
        # « Statut » qui devient une petite étiquette.
        resp = admin_client.get('/subventions')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'SUBV. GLOBAL' in html
        assert 'AUTRES' in html
        assert '>Type<' in html
        assert '>Statut<' in html

    def test_creer_type(self, app, admin_client, db, sample_users):
        resp = admin_client.post('/api/subventions/types/ajouter',
                                 json={'nom': 'RÉGION'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['ok'] is True
        with app.app_context():
            row = db.execute('SELECT nom FROM subventions_types WHERE id = ?',
                             (data['id'],)).fetchone()
        assert row['nom'] == 'RÉGION'

    def test_creer_type_doublon_renvoie_existant(self, app, admin_client, db, sample_users):
        r1 = admin_client.post('/api/subventions/types/ajouter', json={'nom': 'CAF'})
        assert r1.get_json()['existe'] is True
        with app.app_context():
            nb = db.execute(
                "SELECT COUNT(*) AS n FROM subventions_types WHERE nom = 'CAF'"
            ).fetchone()['n']
        assert nb == 1

    def test_subvention_creee_avec_type(self, app, admin_client, db, sample_users):
        with app.app_context():
            type_id = db.execute(
                "SELECT id FROM subventions_types WHERE nom = 'VILLE'"
            ).fetchone()['id']
        resp = admin_client.post('/api/subventions/ajouter',
                                 json={'nom': 'Aide locale', 'type_id': type_id,
                                       'annee_action': '2026'})
        assert resp.status_code == 200
        sub_id = resp.get_json()['id']
        with app.app_context():
            row = db.execute('SELECT groupe, type_id FROM subventions WHERE id = ?',
                             (sub_id,)).fetchone()
        # Le type est enregistré ; le statut par défaut reste « nouveau_projet ».
        assert row['type_id'] == type_id
        assert row['groupe'] == 'nouveau_projet'

    def test_modifier_type_subvention(self, app, admin_client, db, sample_users):
        with app.app_context():
            cur = db.execute("INSERT INTO subventions (nom, groupe) VALUES ('X', 'nouveau_projet')")
            sub_id = cur.lastrowid
            type_id = db.execute("SELECT id FROM subventions_types WHERE nom = 'ETAT'").fetchone()['id']
            db.commit()
        resp = admin_client.post(f'/api/subventions/{sub_id}/modifier',
                                 json={'field': 'type_id', 'value': type_id})
        assert resp.status_code == 200
        with app.app_context():
            assert db.execute('SELECT type_id FROM subventions WHERE id = ?',
                              (sub_id,)).fetchone()['type_id'] == type_id

    def test_supprimer_type_bascule_subventions_en_sans_type(self, app, admin_client, db, sample_users):
        with app.app_context():
            type_id = db.execute("SELECT id FROM subventions_types WHERE nom = 'METROPOLE'").fetchone()['id']
            cur = db.execute(
                "INSERT INTO subventions (nom, groupe, type_id) VALUES ('Dossier M', 'en_cours', ?)",
                (type_id,)
            )
            sub_id = cur.lastrowid
            db.commit()

        resp = admin_client.post(f'/api/subventions/types/{type_id}/supprimer', json={})
        assert resp.status_code == 200
        with app.app_context():
            assert db.execute('SELECT COUNT(*) AS n FROM subventions_types WHERE id = ?',
                              (type_id,)).fetchone()['n'] == 0
            # La subvention n'est pas supprimée : elle devient « Sans type ».
            row = db.execute('SELECT type_id FROM subventions WHERE id = ?', (sub_id,)).fetchone()
        assert row is not None
        assert row['type_id'] is None

    def test_subvention_sans_type_apparait_dans_groupe_dedie(self, app, admin_client, db, sample_users):
        with app.app_context():
            db.execute("INSERT INTO subventions (nom, groupe) VALUES ('Non classee', 'nouveau_projet')")
            db.commit()
        # ?annee=toutes : la subvention n'a pas d'année, on veut la voir ici.
        html = admin_client.get('/subventions?annee=toutes').get_data(as_text=True)
        assert 'Non classee' in html
        assert 'Sans type' in html

    def test_statut_reste_editable_et_valide(self, app, admin_client, db, sample_users):
        with app.app_context():
            cur = db.execute("INSERT INTO subventions (nom, groupe) VALUES ('Y', 'nouveau_projet')")
            sub_id = cur.lastrowid
            db.commit()
        # Statut valide accepté.
        ok = admin_client.post(f'/api/subventions/{sub_id}/modifier',
                               json={'field': 'groupe', 'value': 'acceptee'})
        assert ok.status_code == 200
        with app.app_context():
            assert db.execute('SELECT groupe FROM subventions WHERE id = ?',
                              (sub_id,)).fetchone()['groupe'] == 'acceptee'
        # Statut invalide rejeté.
        ko = admin_client.post(f'/api/subventions/{sub_id}/modifier',
                               json={'field': 'groupe', 'value': 'nimportequoi'})
        assert ko.status_code == 400

    def test_responsable_ne_peut_pas_gerer_les_types(self, app, resp_client, db, sample_users):
        # Le bouton de gestion des types n'est pas rendu pour un responsable...
        html = resp_client.get('/subventions').get_data(as_text=True)
        assert 'Gérer les types' not in html
        # ...et les endpoints de gestion des types lui sont interdits (403),
        # même en appel direct : gérer les types est une action globale réservée
        # à la direction / comptabilité.
        with app.app_context():
            type_id = db.execute("SELECT id FROM subventions_types WHERE nom = 'CAF'").fetchone()['id']
        assert resp_client.post('/api/subventions/types/ajouter', json={'nom': 'X'}).status_code == 403
        assert resp_client.post(f'/api/subventions/types/{type_id}/modifier',
                                json={'field': 'nom', 'value': 'Y'}).status_code == 403
        assert resp_client.post(f'/api/subventions/types/{type_id}/supprimer', json={}).status_code == 403
        # La suppression n'a pas eu lieu.
        with app.app_context():
            assert db.execute('SELECT COUNT(*) AS n FROM subventions_types WHERE id = ?',
                              (type_id,)).fetchone()['n'] == 1

    def test_salarie_ne_peut_pas_gerer_les_types(self, app, auth_client, db, sample_users):
        assert auth_client.post('/api/subventions/types/ajouter', json={'nom': 'Z'}).status_code == 403

    def test_creer_type_nom_vide_refuse(self, app, admin_client, db, sample_users):
        assert admin_client.post('/api/subventions/types/ajouter',
                                 json={'nom': '   '}).status_code == 400

    def test_creer_type_insensible_a_la_casse(self, app, admin_client, db, sample_users):
        # « caf » ne crée pas de doublon de « CAF » (déjà seedé).
        r = admin_client.post('/api/subventions/types/ajouter', json={'nom': 'caf'})
        assert r.status_code == 200 and r.get_json()['existe'] is True
        with app.app_context():
            assert db.execute(
                "SELECT COUNT(*) AS n FROM subventions_types WHERE nom = 'CAF' COLLATE NOCASE"
            ).fetchone()['n'] == 1

    def test_renommer_type_en_doublon_refuse(self, app, admin_client, db, sample_users):
        with app.app_context():
            ville = db.execute("SELECT id FROM subventions_types WHERE nom = 'VILLE'").fetchone()['id']
        # Renommer VILLE en « CAF » (déjà pris) doit échouer.
        r = admin_client.post(f'/api/subventions/types/{ville}/modifier',
                              json={'field': 'nom', 'value': 'CAF'})
        assert r.status_code == 400

    def test_modifier_type_couleur_valide_et_invalide(self, app, admin_client, db, sample_users):
        with app.app_context():
            tid = db.execute("SELECT id FROM subventions_types WHERE nom = 'ETAT'").fetchone()['id']
        assert admin_client.post(f'/api/subventions/types/{tid}/modifier',
                                 json={'field': 'couleur', 'value': '#123abc'}).status_code == 200
        # Une couleur non hexadécimale est refusée (protège le JS/CSS de la page).
        assert admin_client.post(f'/api/subventions/types/{tid}/modifier',
                                 json={'field': 'couleur', 'value': 'red; evil'}).status_code == 400
        with app.app_context():
            assert db.execute('SELECT couleur FROM subventions_types WHERE id = ?',
                              (tid,)).fetchone()['couleur'] == '#123abc'

    def test_modifier_subvention_type_inexistant_refuse(self, app, admin_client, db, sample_users):
        with app.app_context():
            cur = db.execute("INSERT INTO subventions (nom, groupe) VALUES ('Z', 'nouveau_projet')")
            sub_id = cur.lastrowid
            db.commit()
        r = admin_client.post(f'/api/subventions/{sub_id}/modifier',
                              json={'field': 'type_id', 'value': 999999})
        assert r.status_code == 404
        with app.app_context():
            assert db.execute('SELECT type_id FROM subventions WHERE id = ?',
                              (sub_id,)).fetchone()['type_id'] is None


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

        response = admin_client.get('/subventions?annee=toutes')
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

        resp = resp_client.get('/subventions?annee=toutes')
        assert resp.status_code == 200
        assert b'DossierSE' in resp.data
        assert b'Cachee' not in resp.data


class TestFiltreAnnee:
    """Filtre par année de l'action : plage N-3..N+2, année courante par défaut."""

    def _annee_courante(self):
        from utils import aujourd_hui
        return aujourd_hui().year

    def _seed_deux_annees(self, db):
        n = self._annee_courante()
        db.execute("INSERT INTO subventions (nom, groupe, annee_action) VALUES ('SubvActuelle','en_cours',?)", (str(n),))
        db.execute("INSERT INTO subventions (nom, groupe, annee_action) VALUES ('SubvAncienne','en_cours',?)", (str(n - 5),))
        db.commit()
        return n

    def test_defaut_affiche_annee_courante_seulement(self, app, admin_client, db, sample_users):
        with app.app_context():
            self._seed_deux_annees(db)
        html = admin_client.get('/subventions').get_data(as_text=True)
        assert 'SubvActuelle' in html
        assert 'SubvAncienne' not in html

    def test_annee_specifique_filtre(self, app, admin_client, db, sample_users):
        with app.app_context():
            n = self._seed_deux_annees(db)
        html = admin_client.get(f'/subventions?annee={n - 5}').get_data(as_text=True)
        assert 'SubvAncienne' in html
        assert 'SubvActuelle' not in html

    def test_toutes_annees_affiche_tout(self, app, admin_client, db, sample_users):
        with app.app_context():
            self._seed_deux_annees(db)
        html = admin_client.get('/subventions?annee=toutes').get_data(as_text=True)
        assert 'SubvActuelle' in html
        assert 'SubvAncienne' in html

    def test_selecteur_annee_rendu(self, app, admin_client, db, sample_users):
        n = self._annee_courante()
        html = admin_client.get('/subventions').get_data(as_text=True)
        # Plage N-3 .. N+2 présente, année courante sélectionnée, option « Toutes ».
        assert f'<option value="{n - 3}"' in html
        assert f'<option value="{n + 2}"' in html
        assert f'<option value="{n}" selected>' in html
        assert 'Toutes les années' in html
        # Hors plage : N-4 et N+3 absents du sélecteur.
        assert f'<option value="{n - 4}"' not in html
        assert f'<option value="{n + 3}"' not in html

    def test_annee_invalide_retombe_sur_annee_courante(self, app, admin_client, db, sample_users):
        with app.app_context():
            self._seed_deux_annees(db)
        # Un paramètre non valide ne doit pas planter et retombe sur l'année courante.
        html = admin_client.get('/subventions?annee=abcd').get_data(as_text=True)
        assert 'SubvActuelle' in html
        assert 'SubvAncienne' not in html

    def test_le_filtre_est_visible_pour_le_responsable(self, app, resp_client, db, sample_users):
        # Le filtre par année est utile à tous (contrairement à « Gérer les types »).
        html = resp_client.get('/subventions').get_data(as_text=True)
        assert 'sv-annee-select' in html
