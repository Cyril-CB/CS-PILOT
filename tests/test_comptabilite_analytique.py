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

    def test_import_bi(self, admin_client, db):
        """L'import BI crée les données charges/produits."""
        bi_content = (
            "Code journal\tDate de pièce\tNuméro de pièce\tNuméro de facture\t"
            "Numéro de règlement\tNuméro de compte général\tNuméro de compte tiers\t"
            "Intitulé compte tiers\tLibellé écriture\tLibellé du compte analytique\t"
            "Montant Débit\tMontant Crédit\tMode de règlement\tDate d'échéance\t"
            "Type d'écriture\tCompte analytique\tLettrage\n"
            "VE\t15/01/2025\t001\tF001\t\t701000\t\t\tVente client\tAnalytique 1\t0\t1000,50\t\t\tNOR\tANA001\t\n"
            "HA\t15/02/2025\t002\tF002\t\t601000\t\t\tAchat fournisseur\tAnalytique 1\t500,25\t0\t\t\tNOR\tANA001\t\n"
        )
        data = {'fichier': (io.BytesIO(bi_content.encode('utf-8')), 'export_bi_2025.txt')}
        resp = admin_client.post('/api/bilan/import-bi',
                                 data=data, content_type='multipart/form-data')
        result = resp.get_json()
        assert result['success'] is True
        assert result['nb_ecritures'] == 2
        assert result['annee'] == 2025

        rows = db.execute("SELECT COUNT(*) as nb FROM bilan_fec_donnees").fetchone()
        assert rows['nb'] == 2

        imports = db.execute("SELECT COUNT(*) as nb FROM bilan_fec_imports").fetchone()
        assert imports['nb'] == 1

        # Vérifier que le code analytique est bien extrait
        row = db.execute("SELECT code_analytique FROM bilan_fec_donnees WHERE compte_num = '601000'").fetchone()
        assert row['code_analytique'] == 'ANA001'

    def test_import_bi_filtre_comptes(self, admin_client, db):
        """L'import BI ne garde que les comptes 6x et 7x."""
        bi_content = (
            "Code journal\tDate de pièce\tNuméro de compte général\tLibellé écriture\t"
            "Montant Débit\tMontant Crédit\tCompte analytique\n"
            "VE\t15/01/2025\t701000\tVente\t0\t100\tANA001\n"
            "BQ\t15/01/2025\t512000\tVirement\t100\t0\t\n"
            "HA\t15/01/2025\t601000\tAchat\t200\t0\tANA001\n"
            "OD\t15/01/2025\t401000\tPaiement\t0\t200\t\n"
        )
        data = {'fichier': (io.BytesIO(bi_content.encode('utf-8')), 'bi.txt')}
        resp = admin_client.post('/api/bilan/import-bi',
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
        """L'API retourne les données filtrées par secteur (correspondance code analytique)."""
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

    def test_api_bilan_donnees_compte_num_exact(self, admin_client, db, sample_users):
        """L'API fonctionne quand le plan comptable a les mêmes numéros que le FEC."""
        secteur_id = sample_users['secteur_id']
        # Plan comptable avec numéros de compte généraux
        db.execute("INSERT INTO comptabilite_comptes (compte_num, libelle, secteur_id) VALUES ('601000', 'Achats', ?)",
                   (secteur_id,))
        db.execute("INSERT INTO comptabilite_comptes (compte_num, libelle, secteur_id) VALUES ('701000', 'Ventes', ?)",
                   (secteur_id,))
        # FEC avec les mêmes numéros, code_analytique vide (cas réel standard)
        db.execute("INSERT INTO bilan_fec_imports (fichier_nom, annee, nb_ecritures) VALUES ('fec.txt', 2025, 2)")
        db.commit()
        imp = db.execute("SELECT id FROM bilan_fec_imports ORDER BY id DESC LIMIT 1").fetchone()
        db.execute("INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) VALUES ('601000', 'Achat fournisseur', '', 2025, 1, 300, ?)",
                   (imp['id'],))
        db.execute("INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) VALUES ('701000', 'Vente client', '', 2025, 1, 600, ?)",
                   (imp['id'],))
        db.commit()

        resp = admin_client.get(f'/api/bilan/donnees?annee=2025&secteur_id={secteur_id}')
        data = resp.get_json()
        assert data['total_charges'] == 300
        assert data['total_produits'] == 600

    def test_api_bilan_donnees_prefixe(self, admin_client, db, sample_users):
        """L'API fonctionne avec des préfixes (601 correspond à 601000, 601100, etc.)."""
        secteur_id = sample_users['secteur_id']
        # Plan comptable avec des préfixes courts
        db.execute("INSERT INTO comptabilite_comptes (compte_num, libelle, secteur_id) VALUES ('601', 'Achats stockés', ?)",
                   (secteur_id,))
        db.execute("INSERT INTO comptabilite_comptes (compte_num, libelle, secteur_id) VALUES ('701', 'Ventes produits', ?)",
                   (secteur_id,))
        # FEC avec des comptes détaillés
        db.execute("INSERT INTO bilan_fec_imports (fichier_nom, annee, nb_ecritures) VALUES ('fec.txt', 2025, 4)")
        db.commit()
        imp = db.execute("SELECT id FROM bilan_fec_imports ORDER BY id DESC LIMIT 1").fetchone()
        db.execute("INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) VALUES ('601000', 'Achat MP', '', 2025, 1, 200, ?)",
                   (imp['id'],))
        db.execute("INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) VALUES ('601100', 'Achat alim', '', 2025, 1, 150, ?)",
                   (imp['id'],))
        db.execute("INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) VALUES ('701000', 'Vente A', '', 2025, 1, 500, ?)",
                   (imp['id'],))
        # Ce compte 602xxx ne doit PAS être inclus (pas de préfixe 602 assigné)
        db.execute("INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) VALUES ('602000', 'Achat non stocké', '', 2025, 1, 100, ?)",
                   (imp['id'],))
        db.commit()

        resp = admin_client.get(f'/api/bilan/donnees?annee=2025&secteur_id={secteur_id}')
        data = resp.get_json()
        # 601000 (200) + 601100 (150) = 350 charges
        assert data['total_charges'] == 350
        # 701000 (500) = 500 produits
        assert data['total_produits'] == 500

    def test_api_bilan_donnees_fallback_pcg_compte_manquant_analytique(self, admin_client, db, sample_users):
        """Fallback PCG : un compte présent dans plan_comptable_general mais absent du
        plan analytique (comptabilite_comptes) s'affiche quand même — cas typique d'une
        donnée 2024 dont l'entrée analytique a été supprimée."""
        secteur_id = sample_users['secteur_id']
        # Aucune entrée dans comptabilite_comptes pour ce compte
        # Mais le compte est reconnu dans plan_comptable_general
        db.execute("INSERT INTO plan_comptable_general (compte_num, libelle) VALUES ('601000', 'Achats matières')")
        db.execute("INSERT INTO plan_comptable_general (compte_num, libelle) VALUES ('701000', 'Ventes')")
        db.execute("INSERT INTO bilan_fec_imports (fichier_nom, annee, nb_ecritures) VALUES ('fec2024.txt', 2024, 2)")
        db.commit()
        imp = db.execute("SELECT id FROM bilan_fec_imports ORDER BY id DESC LIMIT 1").fetchone()
        db.execute(
            "INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) "
            "VALUES ('601000', 'Charge 2024', '', 2024, 1, 400, ?)", (imp['id'],))
        db.execute(
            "INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) "
            "VALUES ('701000', 'Produit 2024', '', 2024, 1, 600, ?)", (imp['id'],))
        db.commit()

        resp = admin_client.get(f'/api/bilan/donnees?annee=2024&secteur_id={secteur_id}')
        data = resp.get_json()
        # Les comptes du PCG sans entrée analytique doivent s'afficher via le fallback
        assert data['total_charges'] == 400
        assert data['total_produits'] == 600

    def test_api_bilan_donnees_fallback_pcg_libelle_utilise(self, admin_client, db, sample_users):
        """Le libellé du PCG est utilisé pour les comptes affichés via le fallback."""
        secteur_id = sample_users['secteur_id']
        db.execute("INSERT INTO plan_comptable_general (compte_num, libelle) VALUES ('621000', 'Salaires')")
        db.execute("INSERT INTO bilan_fec_imports (fichier_nom, annee, nb_ecritures) VALUES ('fec2024.txt', 2024, 1)")
        db.commit()
        imp = db.execute("SELECT id FROM bilan_fec_imports ORDER BY id DESC LIMIT 1").fetchone()
        db.execute(
            "INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) "
            "VALUES ('621000', 'Libelle FEC', '', 2024, 1, 1000, ?)", (imp['id'],))
        db.commit()

        resp = admin_client.get(f'/api/bilan/donnees?annee=2024&secteur_id={secteur_id}')
        data = resp.get_json()
        assert data['total_charges'] == 1000
        # Le libellé doit venir du PCG
        assert data['charges']['62']['comptes']['621000']['libelle'] == 'Salaires'

    def test_api_bilan_donnees_fallback_pcg_ne_depasse_pas_secteur(self, admin_client, db, sample_users):
        """Le fallback PCG n'affiche PAS les comptes déjà assignés à un autre secteur."""
        secteur_id = sample_users['secteur_id']
        # Créer un deuxième secteur
        db.execute("INSERT INTO secteurs (nom) VALUES ('Autre secteur')")
        db.commit()
        autre_secteur = db.execute("SELECT id FROM secteurs WHERE nom = 'Autre secteur'").fetchone()
        autre_secteur_id = autre_secteur['id']

        # Compte '611000' est dans plan_comptable_general ET assigné à autre_secteur (pas secteur_id)
        db.execute("INSERT INTO plan_comptable_general (compte_num, libelle) VALUES ('611000', 'Loyers')")
        db.execute(
            "INSERT INTO comptabilite_comptes (compte_num, libelle, secteur_id) VALUES ('611', 'Loyers', ?)",
            (autre_secteur_id,))
        db.execute("INSERT INTO bilan_fec_imports (fichier_nom, annee, nb_ecritures) VALUES ('fec2024.txt', 2024, 1)")
        db.commit()
        imp = db.execute("SELECT id FROM bilan_fec_imports ORDER BY id DESC LIMIT 1").fetchone()
        db.execute(
            "INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) "
            "VALUES ('611000', 'Loyer bureau', '', 2024, 1, 500, ?)", (imp['id'],))
        db.commit()

        # Quand on consulte secteur_id (pas autre_secteur_id), '611000' ne doit PAS apparaître
        resp = admin_client.get(f'/api/bilan/donnees?annee=2024&secteur_id={secteur_id}')
        data = resp.get_json()
        assert data['total_charges'] == 0

    def test_api_bilan_donnees_compte_absent_pcg_et_analytique_non_affiche(self, admin_client, db, sample_users):
        """Un compte absent du PCG ET du plan analytique ne s'affiche pas (pas de fallback)."""
        secteur_id = sample_users['secteur_id']
        # '609000' n'est ni dans plan_comptable_general ni dans comptabilite_comptes
        db.execute("INSERT INTO bilan_fec_imports (fichier_nom, annee, nb_ecritures) VALUES ('fec2024.txt', 2024, 1)")
        db.commit()
        imp = db.execute("SELECT id FROM bilan_fec_imports ORDER BY id DESC LIMIT 1").fetchone()
        db.execute(
            "INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) "
            "VALUES ('609000', 'Inconnu', '', 2024, 1, 200, ?)", (imp['id'],))
        db.commit()

        resp = admin_client.get(f'/api/bilan/donnees?annee=2024&secteur_id={secteur_id}')
        data = resp.get_json()
        # Sans PCG ni plan analytique, le compte n'est pas affiché
        assert data['total_charges'] == 0

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

    def test_export_pdf(self, admin_client, db, sample_users):
        """L'export PDF retourne un fichier PDF valide."""
        secteur_id = sample_users['secteur_id']
        db.execute("INSERT INTO comptabilite_comptes (compte_num, libelle, secteur_id) VALUES ('601000', 'Achats', ?)",
                   (secteur_id,))
        db.execute("INSERT INTO comptabilite_comptes (compte_num, libelle, secteur_id) VALUES ('701000', 'Ventes', ?)",
                   (secteur_id,))
        db.execute("INSERT INTO bilan_fec_imports (fichier_nom, annee, nb_ecritures) VALUES ('test.txt', 2025, 2)")
        db.commit()
        imp = db.execute("SELECT id FROM bilan_fec_imports ORDER BY id DESC LIMIT 1").fetchone()
        db.execute("INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) VALUES ('601000', 'Charge', '', 2025, 1, 500, ?)",
                   (imp['id'],))
        db.execute("INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) VALUES ('701000', 'Produit', '', 2025, 1, 800, ?)",
                   (imp['id'],))
        db.commit()

        resp = admin_client.get(f'/api/bilan/export-pdf?annee=2025&secteur_id={secteur_id}')
        assert resp.status_code == 200
        assert resp.content_type == 'application/pdf'
        assert resp.data[:5] == b'%PDF-'

    def test_export_pdf_sans_filtre(self, admin_client):
        """L'export PDF sans secteur ni action redirige."""
        resp = admin_client.get('/api/bilan/export-pdf?annee=2025', follow_redirects=True)
        assert 'Sélectionnez' in resp.get_data(as_text=True)


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


class TestUIStyle:
    """Vérifie que les pages utilisent les bons styles CSS."""

    def test_plan_comptable_utilise_data_table(self, admin_client, db):
        """Le tableau du plan comptable utilise la classe data-table."""
        db.execute("INSERT INTO comptabilite_comptes (compte_num, libelle) VALUES ('601000', 'Test')")
        db.commit()
        html = admin_client.get('/plan-comptable-analytique').get_data(as_text=True)
        assert 'class="data-table"' in html

    def test_plan_comptable_modal_padding(self, admin_client):
        """Les modales du plan comptable ont du padding."""
        html = admin_client.get('/plan-comptable-analytique').get_data(as_text=True)
        assert 'modal-body' in html
        assert 'padding:0 1.5rem 1.5rem' in html

    def test_bilan_secteurs_export_pdf_bouton(self, admin_client):
        """La page bilan secteurs contient le bouton export PDF."""
        html = admin_client.get('/bilan-secteurs').get_data(as_text=True)
        assert 'Export PDF' in html
        assert 'exporterPdf' in html

    def test_bilan_secteurs_data_table_in_js(self, admin_client):
        """Le JS du bilan secteurs utilise la classe data-table."""
        html = admin_client.get('/bilan-secteurs').get_data(as_text=True)
        assert 'class="data-table"' in html


class TestTablesCreees:
    """Vérifie que les nouvelles tables existent dans le schéma."""

    NOUVELLES_TABLES = [
        'comptabilite_actions',
        'comptabilite_comptes',
        'bilan_fec_imports',
        'bilan_fec_donnees',
        'bilan_taux_logistique',
        'plan_comptable_general',
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


class TestPlanComptableGeneral:
    """Tests pour la page Plan comptable général."""

    def test_page_accessible_directeur(self, admin_client):
        """Le directeur peut accéder au plan comptable général."""
        resp = admin_client.get('/plan-comptable-general')
        assert resp.status_code == 200
        assert 'Plan comptable' in resp.get_data(as_text=True)

    def test_page_inaccessible_salarie(self, auth_client):
        """Un salarié ne peut pas accéder au plan comptable général."""
        resp = auth_client.get('/plan-comptable-general', follow_redirects=True)
        assert 'Accès non autorisé' in resp.get_data(as_text=True)

    def test_ajout_compte(self, admin_client, db):
        """On peut ajouter un compte au plan comptable général."""
        resp = admin_client.post('/api/plan-general/comptes',
                                 json={'compte_num': '601000', 'libelle': 'Achats MP'},
                                 content_type='application/json')
        data = resp.get_json()
        assert data['success'] is True

        row = db.execute("SELECT * FROM plan_comptable_general WHERE compte_num = '601000'").fetchone()
        assert row is not None
        assert row['libelle'] == 'Achats MP'

    def test_ajout_compte_doublon(self, admin_client, db):
        """Un doublon de numéro de compte retourne 409."""
        admin_client.post('/api/plan-general/comptes',
                          json={'compte_num': '601000', 'libelle': 'Achats MP'},
                          content_type='application/json')
        resp = admin_client.post('/api/plan-general/comptes',
                                 json={'compte_num': '601000', 'libelle': 'Doublon'},
                                 content_type='application/json')
        assert resp.status_code == 409

    def test_ajout_compte_champs_requis(self, admin_client):
        """L'ajout sans numéro ou libellé retourne 400."""
        resp = admin_client.post('/api/plan-general/comptes',
                                 json={'compte_num': '', 'libelle': ''},
                                 content_type='application/json')
        assert resp.status_code == 400

    def test_suppression_compte(self, admin_client, db):
        """On peut supprimer un compte du plan comptable général."""
        db.execute("INSERT INTO plan_comptable_general (compte_num, libelle) VALUES ('999999', 'Test')")
        db.commit()
        row = db.execute("SELECT id FROM plan_comptable_general WHERE compte_num = '999999'").fetchone()

        resp = admin_client.delete(f'/api/plan-general/comptes/{row["id"]}')
        data = resp.get_json()
        assert data['success'] is True

        row = db.execute("SELECT id FROM plan_comptable_general WHERE compte_num = '999999'").fetchone()
        assert row is None

    def test_import_txt(self, admin_client, db):
        """L'import TXT tabulé crée des comptes."""
        content = "601000\tAchats matières\n602000\tAchats stockés\n"
        data = {'fichier': (io.BytesIO(content.encode('utf-8')), 'plan.txt')}
        resp = admin_client.post('/api/plan-general/import-txt',
                                 data=data, content_type='multipart/form-data')
        result = resp.get_json()
        assert result['success'] is True
        assert result['nb_importes'] == 2

        rows = db.execute("SELECT COUNT(*) as nb FROM plan_comptable_general").fetchone()
        assert rows['nb'] == 2

    def test_import_txt_mise_a_jour(self, admin_client, db):
        """L'import TXT met à jour les comptes existants."""
        db.execute("INSERT INTO plan_comptable_general (compte_num, libelle) VALUES ('601000', 'Ancien')")
        db.commit()

        content = "601000\tNouveau libellé\n"
        data = {'fichier': (io.BytesIO(content.encode('utf-8')), 'plan.txt')}
        resp = admin_client.post('/api/plan-general/import-txt',
                                 data=data, content_type='multipart/form-data')
        result = resp.get_json()
        assert result['nb_doublons'] == 1

        row = db.execute("SELECT libelle FROM plan_comptable_general WHERE compte_num = '601000'").fetchone()
        assert row['libelle'] == 'Nouveau libellé'

    def test_menu_plan_general_directeur(self, admin_client):
        """Le directeur voit le lien Plan comptable général dans la sidebar."""
        resp = admin_client.get('/', follow_redirects=True)
        html = resp.get_data(as_text=True)
        assert 'Plan comptable' in html

    def test_utilise_data_table(self, admin_client, db):
        """Le tableau du plan comptable général utilise la classe data-table."""
        db.execute("INSERT INTO plan_comptable_general (compte_num, libelle) VALUES ('601000', 'Test')")
        db.commit()
        html = admin_client.get('/plan-comptable-general').get_data(as_text=True)
        assert 'class="data-table"' in html


class TestBilanLabelsFromPCG:
    """Vérifie que le bilan utilise les libellés du plan comptable général."""

    def test_bilan_donnees_utilise_pcg(self, admin_client, db, sample_users):
        """L'API bilan utilise le libellé du PCG plutôt que celui de l'opération."""
        secteur_id = sample_users['secteur_id']
        # Plan comptable analytique
        db.execute("INSERT INTO comptabilite_comptes (compte_num, libelle, secteur_id) VALUES ('601000', 'Achats analytique', ?)",
                   (secteur_id,))
        # Plan comptable général avec le bon libellé
        db.execute("INSERT INTO plan_comptable_general (compte_num, libelle) VALUES ('601000', 'Achats matières premières')")
        # Données FEC avec un libellé d'opération
        db.execute("INSERT INTO bilan_fec_imports (fichier_nom, annee, nb_ecritures) VALUES ('test.txt', 2025, 1)")
        db.commit()
        imp = db.execute("SELECT id FROM bilan_fec_imports ORDER BY id DESC LIMIT 1").fetchone()
        db.execute("INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) VALUES ('601000', 'Facture XYZ', '', 2025, 1, 500, ?)",
                   (imp['id'],))
        db.commit()

        resp = admin_client.get(f'/api/bilan/donnees?annee=2025&secteur_id={secteur_id}')
        data = resp.get_json()
        # Le libellé du compte doit venir du PCG, pas de l'opération
        assert '60' in data['charges']
        assert '601000' in data['charges']['60']['comptes']
        assert data['charges']['60']['comptes']['601000']['libelle'] == 'Achats matières premières'

    def test_bilan_donnees_fallback_operation(self, admin_client, db, sample_users):
        """Sans PCG, le bilan utilise le libellé de l'opération comme fallback."""
        secteur_id = sample_users['secteur_id']
        db.execute("INSERT INTO comptabilite_comptes (compte_num, libelle, secteur_id) VALUES ('601000', 'Achats', ?)",
                   (secteur_id,))
        db.execute("INSERT INTO bilan_fec_imports (fichier_nom, annee, nb_ecritures) VALUES ('test.txt', 2025, 1)")
        db.commit()
        imp = db.execute("SELECT id FROM bilan_fec_imports ORDER BY id DESC LIMIT 1").fetchone()
        db.execute("INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) VALUES ('601000', 'Facture XYZ', '', 2025, 1, 500, ?)",
                   (imp['id'],))
        db.commit()

        resp = admin_client.get(f'/api/bilan/donnees?annee=2025&secteur_id={secteur_id}')
        data = resp.get_json()
        # Sans PCG, on doit avoir le libellé de l'opération
        assert data['charges']['60']['comptes']['601000']['libelle'] == 'Facture XYZ'
