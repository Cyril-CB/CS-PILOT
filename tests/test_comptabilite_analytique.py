"""Tests pour le module comptabilite analytique et bilan secteurs/actions."""
import io


class TestPlanComptableAnalytique:
    """Tests pour la page Plan comptable analytique."""

    def test_page_accessible_directeur(self, admin_client):
        """Le directeur peut accéder au plan comptable analytique."""
        resp = admin_client.get('/plan-comptable-analytique')
        assert resp.status_code == 200
        assert 'Plan comptable analytique' in resp.get_data(as_text=True)

    def test_page_inaccessible_salarie(self, auth_client):
        """Un salarié ne peut pas accéder au plan comptable analytique."""
        resp = auth_client.get('/plan-comptable-analytique', follow_redirects=True)
        assert 'Accès non autorisé' in resp.get_data(as_text=True)

    def test_ajout_compte(self, admin_client, db):
        """On peut ajouter un compte analytique via l'API."""
        resp = admin_client.post('/api/comptabilite/comptes',
                                 json={'compte_num': '601000', 'libelle': 'Achats MP'},
                                 content_type='application/json')
        data = resp.get_json()
        assert data['success'] is True

        row = db.execute("SELECT * FROM comptabilite_comptes WHERE compte_num = '601000'").fetchone()
        assert row is not None
        assert row['libelle'] == 'Achats MP'

    def test_ajout_compte_doublon(self, admin_client, db):
        """Un doublon de numéro de compte retourne 409."""
        admin_client.post('/api/comptabilite/comptes',
                          json={'compte_num': '601000', 'libelle': 'Achats MP'},
                          content_type='application/json')
        resp = admin_client.post('/api/comptabilite/comptes',
                                 json={'compte_num': '601000', 'libelle': 'Doublon'},
                                 content_type='application/json')
        assert resp.status_code == 409

    def test_ajout_compte_champs_requis(self, admin_client):
        """L'ajout sans numéro ou libellé retourne 400."""
        resp = admin_client.post('/api/comptabilite/comptes',
                                 json={'compte_num': '', 'libelle': ''},
                                 content_type='application/json')
        assert resp.status_code == 400

    def test_suppression_compte(self, admin_client, db):
        """On peut supprimer un compte analytique."""
        db.execute("INSERT INTO comptabilite_comptes (compte_num, libelle) VALUES ('999999', 'Test')")
        db.commit()
        row = db.execute("SELECT id FROM comptabilite_comptes WHERE compte_num = '999999'").fetchone()

        resp = admin_client.delete(f'/api/comptabilite/comptes/{row["id"]}')
        data = resp.get_json()
        assert data['success'] is True

        row = db.execute("SELECT id FROM comptabilite_comptes WHERE compte_num = '999999'").fetchone()
        assert row is None

    def test_import_txt(self, admin_client, db):
        """L'import TXT tabulé crée des comptes."""
        content = "601000\tAchats matières\n602000\tAchats stockés\n"
        data = {'fichier': (io.BytesIO(content.encode('utf-8')), 'plan.txt')}
        resp = admin_client.post('/api/comptabilite/import-txt',
                                 data=data, content_type='multipart/form-data')
        result = resp.get_json()
        assert result['success'] is True
        assert result['nb_importes'] == 2

        rows = db.execute("SELECT COUNT(*) as nb FROM comptabilite_comptes").fetchone()
        assert rows['nb'] == 2

    def test_import_txt_mise_a_jour(self, admin_client, db):
        """L'import TXT met à jour les comptes existants."""
        db.execute("INSERT INTO comptabilite_comptes (compte_num, libelle) VALUES ('601000', 'Ancien')")
        db.commit()

        content = "601000\tNouveau libellé\n"
        data = {'fichier': (io.BytesIO(content.encode('utf-8')), 'plan.txt')}
        resp = admin_client.post('/api/comptabilite/import-txt',
                                 data=data, content_type='multipart/form-data')
        result = resp.get_json()
        assert result['nb_doublons'] == 1

        row = db.execute("SELECT libelle FROM comptabilite_comptes WHERE compte_num = '601000'").fetchone()
        assert row['libelle'] == 'Nouveau libellé'

    def test_affectation_secteur_action(self, admin_client, db, sample_users):
        """On peut affecter un secteur et une action à un compte."""
        db.execute("INSERT INTO comptabilite_comptes (compte_num, libelle) VALUES ('601000', 'Test')")
        db.execute("INSERT INTO comptabilite_actions (nom) VALUES ('Action Test')")
        db.commit()

        compte = db.execute("SELECT id FROM comptabilite_comptes WHERE compte_num = '601000'").fetchone()
        action = db.execute("SELECT id FROM comptabilite_actions WHERE nom = 'Action Test'").fetchone()
        secteur_id = sample_users['secteur_id']

        resp = admin_client.put(
            f'/api/comptabilite/comptes/{compte["id"]}/affectation',
            json={'secteur_id': secteur_id, 'action_id': action['id']},
            content_type='application/json')
        data = resp.get_json()
        assert data['success'] is True

        row = db.execute("SELECT secteur_id, action_id FROM comptabilite_comptes WHERE id = ?",
                         (compte['id'],)).fetchone()
        assert row['secteur_id'] == secteur_id
        assert row['action_id'] == action['id']

    def test_ajout_action(self, admin_client, db):
        """On peut ajouter une action analytique."""
        resp = admin_client.post('/api/comptabilite/actions',
                                 json={'nom': 'Nouvelle Action'},
                                 content_type='application/json')
        data = resp.get_json()
        assert data['id'] is not None
        assert data['nom'] == 'Nouvelle Action'

    def test_suppression_action_utilisee(self, admin_client, db):
        """On ne peut pas supprimer une action utilisée par un compte."""
        db.execute("INSERT INTO comptabilite_actions (nom) VALUES ('Action Utilisée')")
        db.commit()
        action = db.execute("SELECT id FROM comptabilite_actions WHERE nom = 'Action Utilisée'").fetchone()
        db.execute("INSERT INTO comptabilite_comptes (compte_num, libelle, action_id) VALUES ('601000', 'Test', ?)",
                   (action['id'],))
        db.commit()

        resp = admin_client.delete(f'/api/comptabilite/actions/{action["id"]}')
        assert resp.status_code == 409


class TestBilanSecteurs:
    """Tests pour la page Bilan secteurs/actions."""

    def test_page_accessible_directeur(self, admin_client):
        """Le directeur peut accéder au bilan secteurs/actions."""
        resp = admin_client.get('/bilan-secteurs')
        assert resp.status_code == 200
        assert 'Bilan secteurs' in resp.get_data(as_text=True)

    def test_page_inaccessible_salarie(self, auth_client):
        """Un salarié ne peut pas accéder au bilan."""
        resp = auth_client.get('/bilan-secteurs', follow_redirects=True)
        assert 'Accès non autorisé' in resp.get_data(as_text=True)

    def test_import_fec(self, admin_client, db):
        """L'import FEC crée les données charges/produits."""
        fec_content = (
            "JournalCode\tJournalLib\tEcritureNum\tEcritureDate\tCompteNum\tCompteLib\t"
            "CompAuxNum\tCompAuxLib\tPieceRef\tPieceDate\tEcritureLib\tDebit\tCredit\n"
            "VE\tVentes\t001\t20250115\t701000\tVentes marchandises\tANA001\t\tF001\t20250115\tVente client\t0\t1000,50\n"
            "HA\tAchats\t002\t20250215\t601000\tAchats matières\tANA001\t\tF002\t20250215\tAchat fournisseur\t500,25\t0\n"
        )
        data = {'fichier': (io.BytesIO(fec_content.encode('utf-8')), 'fec_2025.txt')}
        resp = admin_client.post('/api/bilan/import-fec',
                                 data=data, content_type='multipart/form-data')
        result = resp.get_json()
        assert result['success'] is True
        assert result['nb_ecritures'] == 2
        assert result['annee'] == 2025

        rows = db.execute("SELECT COUNT(*) as nb FROM bilan_fec_donnees").fetchone()
        assert rows['nb'] == 2

        imports = db.execute("SELECT COUNT(*) as nb FROM bilan_fec_imports").fetchone()
        assert imports['nb'] == 1

    def test_import_fec_filtre_comptes(self, admin_client, db):
        """L'import FEC ne garde que les comptes 6x et 7x."""
        fec_content = (
            "JournalCode\tEcritureDate\tCompteNum\tCompteLib\tCompAuxNum\tEcritureLib\tDebit\tCredit\n"
            "VE\t20250115\t701000\tVentes\t\tVente\t0\t100\n"
            "BQ\t20250115\t512000\tBanque\t\tVirement\t100\t0\n"
            "HA\t20250115\t601000\tAchats\t\tAchat\t200\t0\n"
            "OD\t20250115\t401000\tFournisseurs\t\tPaiement\t0\t200\n"
        )
        data = {'fichier': (io.BytesIO(fec_content.encode('utf-8')), 'fec.txt')}
        resp = admin_client.post('/api/bilan/import-fec',
                                 data=data, content_type='multipart/form-data')
        result = resp.get_json()
        assert result['nb_ecritures'] == 2  # 701000 + 601000 seulement

    def test_suppression_annee(self, admin_client, db):
        """On peut supprimer les données d'une année."""
        db.execute("INSERT INTO bilan_fec_imports (fichier_nom, annee, nb_ecritures) VALUES ('test.txt', 2025, 1)")
        db.commit()
        imp = db.execute("SELECT id FROM bilan_fec_imports WHERE annee = 2025").fetchone()
        db.execute("INSERT INTO bilan_fec_donnees (compte_num, annee, mois, montant, import_id) VALUES ('601000', 2025, 1, 100, ?)",
                   (imp['id'],))
        db.commit()

        resp = admin_client.delete('/api/bilan/annee/2025')
        data = resp.get_json()
        assert data['success'] is True

        rows = db.execute("SELECT COUNT(*) as nb FROM bilan_fec_donnees WHERE annee = 2025").fetchone()
        assert rows['nb'] == 0
        imports = db.execute("SELECT COUNT(*) as nb FROM bilan_fec_imports WHERE annee = 2025").fetchone()
        assert imports['nb'] == 0

    def test_api_bilan_donnees_sans_filtre(self, admin_client):
        """L'API bilan donnees requiert au moins un secteur ou une action."""
        resp = admin_client.get('/api/bilan/donnees?annee=2025')
        assert resp.status_code == 400

    def test_api_bilan_donnees_avec_secteur(self, admin_client, db, sample_users):
        """L'API retourne les données filtrées par secteur."""
        secteur_id = sample_users['secteur_id']
        # Créer un compte analytique lié au secteur
        db.execute("INSERT INTO comptabilite_comptes (compte_num, libelle, secteur_id) VALUES ('ANA001', 'Analytique 1', ?)",
                   (secteur_id,))
        # Créer des données FEC avec ce code analytique
        db.execute("INSERT INTO bilan_fec_imports (fichier_nom, annee, nb_ecritures) VALUES ('test.txt', 2025, 2)")
        db.commit()
        imp = db.execute("SELECT id FROM bilan_fec_imports ORDER BY id DESC LIMIT 1").fetchone()
        db.execute("INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) VALUES ('601000', 'Charge', 'ANA001', 2025, 1, 500, ?)",
                   (imp['id'],))
        db.execute("INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) VALUES ('701000', 'Produit', 'ANA001', 2025, 1, 800, ?)",
                   (imp['id'],))
        db.commit()

        resp = admin_client.get(f'/api/bilan/donnees?annee=2025&secteur_id={secteur_id}')
        data = resp.get_json()
        assert data['total_charges'] == 500
        assert data['total_produits'] == 800

    def test_taux_logistique(self, admin_client, db):
        """On peut sauvegarder les taux de logistique."""
        resp = admin_client.post('/api/bilan/taux-logistique',
                                 json={'annee': 2025, 'taux_site1': 15.5,
                                       'taux_site2': 20.0, 'taux_global': 25.22,
                                       'taux_selectionne': 'global'},
                                 content_type='application/json')
        data = resp.get_json()
        assert data['success'] is True

        row = db.execute("SELECT * FROM bilan_taux_logistique WHERE annee = 2025").fetchone()
        assert row['taux_site1'] == 15.5
        assert row['taux_site2'] == 20.0
        assert row['taux_global'] == 25.22
        assert row['taux_selectionne'] == 'global'

    def test_taux_logistique_mise_a_jour(self, admin_client, db):
        """Les taux se mettent à jour pour la même année."""
        admin_client.post('/api/bilan/taux-logistique',
                          json={'annee': 2025, 'taux_global': 10.0, 'taux_selectionne': 'global'},
                          content_type='application/json')
        admin_client.post('/api/bilan/taux-logistique',
                          json={'annee': 2025, 'taux_global': 25.0, 'taux_selectionne': 'site1'},
                          content_type='application/json')

        row = db.execute("SELECT * FROM bilan_taux_logistique WHERE annee = 2025").fetchone()
        assert row['taux_global'] == 25.0
        assert row['taux_selectionne'] == 'site1'


class TestNavigationMenus:
    """Vérifie que les nouveaux menus apparaissent dans la sidebar."""

    def test_menu_financier_bilan_directeur(self, admin_client):
        """Le menu Financier du directeur contient le lien Bilan secteurs/actions."""
        resp = admin_client.get('/', follow_redirects=True)
        html = resp.get_data(as_text=True)
        assert 'Bilan secteurs/actions' in html

    def test_menu_comptable_directeur(self, admin_client):
        """Le directeur voit le menu Comptable avec Plan comptable analytique."""
        resp = admin_client.get('/', follow_redirects=True)
        html = resp.get_data(as_text=True)
        assert 'Comptable' in html
        assert 'Plan comptable analytique' in html


class TestTablesCreees:
    """Vérifie que les nouvelles tables existent dans le schéma."""

    NOUVELLES_TABLES = [
        'comptabilite_actions',
        'comptabilite_comptes',
        'bilan_fec_imports',
        'bilan_fec_donnees',
        'bilan_taux_logistique',
    ]

    def test_tables_comptabilite_analytique(self, app, db):
        """Les tables du module comptabilité analytique existent."""
        with app.app_context():
            tables = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            noms_tables = {t['name'] for t in tables}

            for table in self.NOUVELLES_TABLES:
                assert table in noms_tables, f"Table manquante : {table}"
