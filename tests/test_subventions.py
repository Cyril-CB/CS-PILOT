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
        # « SubvAncienne » sur une année dans la plage du menu (N-2) pour pouvoir
        # la sélectionner ; l'année courante reste le défaut.
        n = self._annee_courante()
        db.execute("INSERT INTO subventions (nom, groupe, annee_action) VALUES ('SubvActuelle','en_cours',?)", (str(n),))
        db.execute("INSERT INTO subventions (nom, groupe, annee_action) VALUES ('SubvAncienne','en_cours',?)", (str(n - 2),))
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
        html = admin_client.get(f'/subventions?annee={n - 2}').get_data(as_text=True)
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

    def test_annee_hors_plage_repli_sur_annee_courante(self, app, admin_client, db, sample_users):
        """Une année hors plage (N-5) passée en URL retombe sur l'année courante :
        le filtre affiché et les données interrogées restent cohérents."""
        n = self._annee_courante()
        with app.app_context():
            db.execute("INSERT INTO subventions (nom, groupe, annee_action) VALUES ('SubvActuelle','en_cours',?)", (str(n),))
            db.execute("INSERT INTO subventions (nom, groupe, annee_action) VALUES ('SubvHorsPlage','en_cours',?)", (str(n - 5),))
            db.commit()
        html = admin_client.get(f'/subventions?annee={n - 5}').get_data(as_text=True)
        assert 'SubvActuelle' in html
        assert 'SubvHorsPlage' not in html
        assert f'<option value="{n}" selected>' in html

    def test_le_filtre_est_visible_pour_le_responsable(self, app, resp_client, db, sample_users):
        # Le filtre par année est utile à tous (contrairement à « Gérer les types »).
        html = resp_client.get('/subventions').get_data(as_text=True)
        assert 'sv-annee-select' in html


class TestPerimetreResponsableSubventions:
    """Cloisonnement des subventions entre responsables (escalade horizontale).

    Un responsable ne doit agir que sur les subventions qui lui sont assignées :
    exactement le périmètre déjà appliqué par la page de consultation. Sans ce
    contrôle, il pouvait modifier ou supprimer par ID les subventions d'un autre
    secteur.
    """

    def _seed(self, app, db, sample_users):
        """Crée une subvention assignée au responsable de test et une subvention
        qui ne le concerne pas, chacune avec un sous-élément."""
        resp_id = sample_users['responsable_id']
        with app.app_context():
            mienne = db.execute(
                "INSERT INTO subventions (nom, groupe, annee_action, assignee_1_id) "
                "VALUES ('Mienne', 'en_cours', '2026', ?)",
                (resp_id,)
            ).lastrowid
            se_mienne = db.execute(
                "INSERT INTO subventions_sous_elements (subvention_id, nom, ordre) "
                "VALUES (?, 'Bilan', 0)",
                (mienne,)
            ).lastrowid
            autre = db.execute(
                "INSERT INTO subventions (nom, groupe, annee_action) "
                "VALUES ('AutreSecteur', 'en_cours', '2026')"
            ).lastrowid
            se_autre = db.execute(
                "INSERT INTO subventions_sous_elements (subvention_id, nom, ordre) "
                "VALUES (?, 'Bilan autre', 0)",
                (autre,)
            ).lastrowid
            db.commit()
        return {'mienne': mienne, 'se_mienne': se_mienne,
                'autre': autre, 'se_autre': se_autre}

    def _pdf(self):
        return {'fichier': (io.BytesIO(b'%PDF-1.4\ntest\n'), 'piece.pdf')}

    def test_responsable_non_assigne_refuse_sur_les_routes_mutantes(
        self, app, resp_client, db, sample_users, monkeypatch, tmp_path
    ):
        from blueprints import subventions as subventions_module
        # Dossier dédié (tmp_path héberge aussi la base de test).
        documents_dir = tmp_path / 'documents_subventions'
        documents_dir.mkdir()
        monkeypatch.setattr(subventions_module, 'DOCUMENTS_DIR', str(documents_dir))
        ids = self._seed(app, db, sample_users)

        appels = [
            resp_client.post(f"/api/subventions/{ids['autre']}/modifier",
                             json={'field': 'nom', 'value': 'Piratee'}),
            resp_client.post(f"/api/subventions/{ids['autre']}/sous-elements/ajouter",
                             json={'nom': 'Etape pirate'}),
            resp_client.post(f"/api/subventions/sous-elements/{ids['se_autre']}/modifier",
                             json={'field': 'nom', 'value': 'Etape piratee'}),
            resp_client.post(f"/api/subventions/sous-elements/{ids['se_autre']}/supprimer"),
            resp_client.post(f"/api/subventions/{ids['autre']}/justificatif",
                             data=self._pdf(), content_type='multipart/form-data'),
            resp_client.post(f"/api/subventions/sous-elements/{ids['se_autre']}/document",
                             data=self._pdf(), content_type='multipart/form-data'),
            resp_client.post(f"/api/subventions/{ids['autre']}/supprimer"),
        ]
        for reponse in appels:
            assert reponse.status_code == 403
            assert reponse.get_json() == {'ok': False, 'error': 'Non autorisé'}

        # Aucun effet en base : la subvention d'autrui est intacte.
        with app.app_context():
            sub = db.execute(
                'SELECT nom, justificatif_path FROM subventions WHERE id = ?',
                (ids['autre'],)
            ).fetchone()
            sous_elements = db.execute(
                'SELECT nom, document_path FROM subventions_sous_elements '
                'WHERE subvention_id = ?',
                (ids['autre'],)
            ).fetchall()
        assert sub is not None
        assert sub['nom'] == 'AutreSecteur'
        assert sub['justificatif_path'] is None
        assert len(sous_elements) == 1
        assert sous_elements[0]['nom'] == 'Bilan autre'
        assert sous_elements[0]['document_path'] is None
        # Aucun fichier n'a été écrit malgré les tentatives de téléversement.
        assert list(documents_dir.iterdir()) == []

    def test_responsable_assigne_peut_toujours_travailler(
        self, app, resp_client, db, sample_users, monkeypatch, tmp_path
    ):
        from blueprints import subventions as subventions_module
        monkeypatch.setattr(subventions_module, 'DOCUMENTS_DIR', str(tmp_path))
        ids = self._seed(app, db, sample_users)

        assert resp_client.post(f"/api/subventions/{ids['mienne']}/modifier",
                                json={'field': 'nom', 'value': 'Mienne suivie'}
                                ).status_code == 200
        ajout = resp_client.post(f"/api/subventions/{ids['mienne']}/sous-elements/ajouter",
                                 json={'nom': 'Envoyer le bilan'})
        assert ajout.status_code == 200
        assert resp_client.post(f"/api/subventions/sous-elements/{ids['se_mienne']}/modifier",
                                json={'field': 'statut', 'value': 'fait'}
                                ).status_code == 200
        assert resp_client.post(f"/api/subventions/{ids['mienne']}/justificatif",
                                data=self._pdf(), content_type='multipart/form-data'
                                ).status_code == 200
        assert resp_client.post(f"/api/subventions/sous-elements/{ids['se_mienne']}/document",
                                data=self._pdf(), content_type='multipart/form-data'
                                ).status_code == 200
        assert resp_client.post(
            f"/api/subventions/sous-elements/{ajout.get_json()['id']}/supprimer"
        ).status_code == 200
        assert resp_client.post(f"/api/subventions/{ids['mienne']}/supprimer").status_code == 200

        with app.app_context():
            assert db.execute('SELECT COUNT(*) AS n FROM subventions WHERE id = ?',
                              (ids['mienne'],)).fetchone()['n'] == 0

    def test_responsable_assigne_via_sous_element_peut_agir_sur_le_parent(
        self, app, resp_client, db, sample_users
    ):
        # Même périmètre que la consultation : un sous-élément attribué suffit.
        resp_id = sample_users['responsable_id']
        with app.app_context():
            sub_id = db.execute(
                "INSERT INTO subventions (nom, groupe, annee_action) "
                "VALUES ('DossierSE', 'en_cours', '2026')"
            ).lastrowid
            db.execute(
                "INSERT INTO subventions_sous_elements (subvention_id, nom, assignee_id, ordre) "
                "VALUES (?, 'Bilan', ?, 0)",
                (sub_id, resp_id)
            )
            db.commit()

        reponse = resp_client.post(f'/api/subventions/{sub_id}/modifier',
                                   json={'field': 'montant_demande', 'value': 1500})
        assert reponse.status_code == 200
        with app.app_context():
            assert db.execute('SELECT montant_demande FROM subventions WHERE id = ?',
                              (sub_id,)).fetchone()['montant_demande'] == 1500

    def test_responsable_peut_toujours_creer_une_subvention(
        self, app, resp_client, db, sample_users
    ):
        # La création ne porte sur aucune subvention existante : aucun périmètre
        # à vérifier, le parcours du responsable reste ouvert.
        reponse = resp_client.post('/api/subventions/ajouter',
                                   json={'nom': 'Nouveau dossier', 'annee_action': '2026'})
        assert reponse.status_code == 200
        with app.app_context():
            assert db.execute('SELECT COUNT(*) AS n FROM subventions WHERE id = ?',
                              (reponse.get_json()['id'],)).fetchone()['n'] == 1

    def test_salarie_refuse_sur_les_routes_mutantes(
        self, app, auth_client, db, sample_users, monkeypatch, tmp_path
    ):
        from blueprints import subventions as subventions_module
        monkeypatch.setattr(subventions_module, 'DOCUMENTS_DIR', str(tmp_path))
        ids = self._seed(app, db, sample_users)

        appels = [
            auth_client.post(f"/api/subventions/{ids['mienne']}/modifier",
                             json={'field': 'nom', 'value': 'Piratee'}),
            auth_client.post(f"/api/subventions/{ids['mienne']}/sous-elements/ajouter",
                             json={'nom': 'Etape'}),
            auth_client.post(f"/api/subventions/sous-elements/{ids['se_mienne']}/modifier",
                             json={'field': 'nom', 'value': 'Etape piratee'}),
            auth_client.post(f"/api/subventions/sous-elements/{ids['se_mienne']}/supprimer"),
            auth_client.post(f"/api/subventions/{ids['mienne']}/justificatif",
                             data=self._pdf(), content_type='multipart/form-data'),
            auth_client.post(f"/api/subventions/sous-elements/{ids['se_mienne']}/document",
                             data=self._pdf(), content_type='multipart/form-data'),
            auth_client.post(f"/api/subventions/{ids['mienne']}/supprimer"),
        ]
        for reponse in appels:
            assert reponse.status_code == 403

        with app.app_context():
            assert db.execute('SELECT nom FROM subventions WHERE id = ?',
                              (ids['mienne'],)).fetchone()['nom'] == 'Mienne'

    def test_non_connecte_redirige_vers_la_connexion(self, app, client, db, sample_users):
        ids = self._seed(app, db, sample_users)
        routes = [
            f"/api/subventions/{ids['mienne']}/modifier",
            f"/api/subventions/{ids['mienne']}/supprimer",
            f"/api/subventions/{ids['mienne']}/sous-elements/ajouter",
            f"/api/subventions/sous-elements/{ids['se_mienne']}/modifier",
            f"/api/subventions/sous-elements/{ids['se_mienne']}/supprimer",
            f"/api/subventions/{ids['mienne']}/justificatif",
            f"/api/subventions/sous-elements/{ids['se_mienne']}/document",
        ]
        for route in routes:
            reponse = client.post(route, json={'field': 'nom', 'value': 'X'})
            assert reponse.status_code == 302
            assert '/login' in reponse.headers['Location']

        with app.app_context():
            assert db.execute('SELECT nom FROM subventions WHERE id = ?',
                              (ids['mienne'],)).fetchone()['nom'] == 'Mienne'

    def test_subvention_ou_sous_element_inexistant_renvoie_404(
        self, app, admin_client, db, sample_users
    ):
        # Une ressource absente se distingue d'un refus de périmètre.
        r_sub = admin_client.post('/api/subventions/999999/modifier',
                                  json={'field': 'nom', 'value': 'X'})
        assert r_sub.status_code == 404
        assert r_sub.get_json()['error'] == 'Subvention introuvable'

        r_se = admin_client.post('/api/subventions/sous-elements/999999/modifier',
                                 json={'field': 'nom', 'value': 'X'})
        assert r_se.status_code == 404
        assert r_se.get_json()['error'] == 'Sous-élément introuvable'

    def test_analytique_reservee_a_la_direction_et_comptabilite(
        self, app, client, db, sample_users
    ):
        """Le plan analytique est un référentiel global que l'interface n'expose
        pas aux responsables : sa création suit la règle des types."""
        client.post('/login', data={'login': 'resp_test', 'password': 'resp123'},
                    follow_redirects=True)
        refus = client.post('/api/subventions/analytiques/ajouter', json={'nom': 'ANALYTIQUE X'})
        assert refus.status_code == 403
        with app.app_context():
            assert db.execute(
                'SELECT COUNT(*) AS n FROM subventions_analytiques WHERE nom = ?',
                ('ANALYTIQUE X',)
            ).fetchone()['n'] == 0
        client.get('/logout', follow_redirects=True)

        client.post('/login', data={'login': 'compta_test', 'password': 'compta123'},
                    follow_redirects=True)
        assert client.post('/api/subventions/analytiques/ajouter',
                           json={'nom': 'ANALYTIQUE X'}).status_code == 200
        client.get('/logout', follow_redirects=True)

        client.post('/login', data={'login': 'salarie_test', 'password': 'sal123'},
                    follow_redirects=True)
        assert client.post('/api/subventions/analytiques/ajouter',
                           json={'nom': 'ANALYTIQUE Y'}).status_code == 403


class TestTelechargementPiecesSubventions:
    """Cloisonnement des pièces jointes en LECTURE (découvert par le balayage
    des routes sensibles).

    Les deux routes de téléchargement ne vérifiaient que le profil : un
    responsable non assigné pouvait récupérer, en devinant l'identifiant, le
    justificatif d'une subvention d'un autre secteur — alors que la page de
    consultation ne la lui montre pas. C'est le pendant, en lecture, du
    cloisonnement appliqué aux routes de modification.
    """

    def _seed_avec_pieces(self, app, db, sample_users, tmp_path, monkeypatch):
        """Une subvention assignée au responsable et une qui ne l'est pas,
        chacune avec un justificatif et un sous-élément documenté sur disque."""
        import blueprints.subventions as mod
        monkeypatch.setattr(mod, 'DOCUMENTS_DIR', str(tmp_path))
        resp_id = sample_users['responsable_id']
        ids = {}
        with app.app_context():
            for cle, assignee in (('mienne', resp_id), ('autre', None)):
                fichier = f'justif_{cle}.pdf'
                (tmp_path / fichier).write_bytes(b'%PDF-1.4\n' + cle.encode() + b'\n')
                doc = f'doc_{cle}.pdf'
                (tmp_path / doc).write_bytes(b'%PDF-1.4\n' + cle.encode() + b'\n')
                sub_id = db.execute(
                    "INSERT INTO subventions (nom, groupe, annee_action, assignee_1_id, "
                    "justificatif_path, justificatif_nom) VALUES (?, 'en_cours', '2026', ?, ?, ?)",
                    (cle.capitalize(), assignee, fichier, fichier)
                ).lastrowid
                se_id = db.execute(
                    "INSERT INTO subventions_sous_elements (subvention_id, nom, ordre, "
                    "document_path, document_nom) VALUES (?, 'Bilan', 0, ?, ?)",
                    (sub_id, doc, doc)
                ).lastrowid
                ids[cle] = sub_id
                ids['se_' + cle] = se_id
            db.commit()
        return ids

    def test_responsable_non_assigne_ne_telecharge_pas_les_pieces(
            self, app, db, resp_client, sample_users, tmp_path, monkeypatch):
        ids = self._seed_avec_pieces(app, db, sample_users, tmp_path, monkeypatch)

        for url in (f"/subventions/justificatif/{ids['autre']}",
                    f"/subventions/sous-element-document/{ids['se_autre']}"):
            r = resp_client.get(url, follow_redirects=False)
            assert r.status_code in (301, 302), f"{url} devrait être refusée"
            assert '/subventions' in r.headers.get('Location', '')
            assert r.headers.get('Content-Disposition') is None
            assert not r.get_data().startswith(b'%PDF'), f"pièce servie par {url}"

    def test_responsable_assigne_telecharge_ses_pieces(
            self, app, db, resp_client, sample_users, tmp_path, monkeypatch):
        ids = self._seed_avec_pieces(app, db, sample_users, tmp_path, monkeypatch)

        for url in (f"/subventions/justificatif/{ids['mienne']}",
                    f"/subventions/sous-element-document/{ids['se_mienne']}"):
            r = resp_client.get(url)
            assert r.status_code == 200, f"{url} doit rester accessible à l'assigné"
            assert r.get_data().startswith(b'%PDF')

    def test_comptable_telecharge_toutes_les_pieces(
            self, app, db, comptable_client, sample_users, tmp_path, monkeypatch):
        ids = self._seed_avec_pieces(app, db, sample_users, tmp_path, monkeypatch)

        r = comptable_client.get(f"/subventions/justificatif/{ids['autre']}")
        assert r.status_code == 200 and r.get_data().startswith(b'%PDF')

    def test_salarie_et_anonyme_refuses(
            self, app, db, client, sample_users, tmp_path, monkeypatch):
        ids = self._seed_avec_pieces(app, db, sample_users, tmp_path, monkeypatch)
        url = f"/subventions/justificatif/{ids['mienne']}"

        r = client.get(url, follow_redirects=False)
        assert r.status_code in (301, 302) and '/login' in r.headers.get('Location', '')

        client.post('/login', data={'login': 'salarie_test', 'password': 'sal123'},
                    follow_redirects=True)
        r = client.get(url, follow_redirects=False)
        assert r.status_code in (301, 302)
        assert not r.get_data().startswith(b'%PDF')
