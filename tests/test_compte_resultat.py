"""
Tests pour les blueprints compte_resultat et indicateurs_financiers.
"""
import io
import pytest
from datetime import datetime


# ── Fixtures helpers ──────────────────────────────────────────────────────────

def _seed_bi(db, annee, with_bilan=False):
    """Insère un import BI minimal (6x/7x, et optionnellement 1x/2x/5x)."""
    db.execute(
        "INSERT INTO bilan_fec_imports (fichier_nom, annee, nb_ecritures) VALUES (?, ?, ?)",
        (f'bi_{annee}.txt', annee, 10)
    )
    import_id = db.execute('SELECT id FROM bilan_fec_imports ORDER BY id DESC LIMIT 1').fetchone()['id']
    # Charges (débit-normal → debit - credit)
    db.execute(
        "INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ('641000', 'Salaires', '', annee, 1, 50000.0, import_id)
    )
    db.execute(
        "INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ('622000', 'Honoraires', '', annee, 1, 5000.0, import_id)
    )
    # Produits (crédit-normal → credit - debit)
    db.execute(
        "INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ('740000', 'Subvention CAF', '', annee, 1, 60000.0, import_id)
    )
    if with_bilan:
        # Capitaux 1x (crédit-normal → montant = credit - debit)
        db.execute(
            "INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ('106000', 'Réserves', '', annee, 12, 80000.0, import_id)
        )
        # Immobilisations 2x (débit-normal → montant = debit - credit)
        db.execute(
            "INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ('215000', 'Matériel bureau', '', annee, 12, 30000.0, import_id)
        )
        # Trésorerie 5x (débit-normal → montant = debit - credit)
        db.execute(
            "INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ('512000', 'Banque', '', annee, 12, 25000.0, import_id)
        )
    db.commit()
    return import_id


def _make_bi_content(rows):
    """Crée un contenu CSV BI avec séparateur tabulation."""
    header = (
        "Code journal\tDate de pièce\tNuméro de pièce\tNuméro de facture\t"
        "Numéro de règlement\tNuméro de compte général\tNuméro de compte tiers\t"
        "Intitulé compte tiers\tLibellé écriture\tLibellé du compte analytique\t"
        "Montant Débit\tMontant Crédit\tMode de règlement\tDate d'échéance\t"
        "Type d'écriture\tCompte analytique\tLettrage"
    )
    lines = [header]
    for r in rows:
        lines.append('\t'.join(str(x) for x in r))
    return '\n'.join(lines)


# ── Tests page compte-resultat ────────────────────────────────────────────────

class TestCompteResultatPage:
    def test_page_accessible_comptable(self, app, db, comptable_client, sample_users):
        resp = comptable_client.get('/compte-resultat')
        assert resp.status_code == 200
        assert 'C.R.' in resp.data.decode()

    def test_page_accessible_directeur(self, app, db, admin_client, sample_users):
        resp = admin_client.get('/compte-resultat')
        assert resp.status_code == 200

    def test_page_inaccessible_salarie(self, app, db, auth_client, sample_users):
        resp = auth_client.get('/compte-resultat', follow_redirects=True)
        assert resp.status_code == 200
        assert b'compte-resultat' not in resp.data or 'non autoris'.encode() in resp.data.lower()


class TestApiCrDonnees:
    def test_cr_donnees_annee_requise(self, app, db, comptable_client, sample_users):
        resp = comptable_client.get('/api/cr/donnees')
        assert resp.status_code == 400
        assert b'requise' in resp.data.lower()

    def test_cr_donnees_basic(self, app, db, comptable_client, sample_users):
        annee = datetime.now().year
        with app.app_context():
            _seed_bi(db, annee)
        resp = comptable_client.get(f'/api/cr/donnees?annee={annee}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['annee'] == annee
        n = data['n']
        assert n['total_charges'] == pytest.approx(55000.0)
        assert n['total_produits'] == pytest.approx(60000.0)
        assert n['resultat'] == pytest.approx(5000.0)

    def test_cr_donnees_n1_disponible(self, app, db, comptable_client, sample_users):
        annee = datetime.now().year
        with app.app_context():
            _seed_bi(db, annee)
            _seed_bi(db, annee - 1)
        resp = comptable_client.get(f'/api/cr/donnees?annee={annee}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['n1'] is not None
        assert data['n1']['total_charges'] == pytest.approx(55000.0)

    def test_cr_donnees_n1_absent(self, app, db, comptable_client, sample_users):
        annee = datetime.now().year
        with app.app_context():
            _seed_bi(db, annee)
        resp = comptable_client.get(f'/api/cr/donnees?annee={annee}')
        data = resp.get_json()
        assert data['n1'] is None

    def test_cr_acces_refuse_non_comptable(self, app, db, auth_client, sample_users):
        annee = datetime.now().year
        resp = auth_client.get(f'/api/cr/donnees?annee={annee}')
        assert resp.status_code == 403


class TestApiCrBilanDonnees:
    def test_bilan_sans_comptes_bilan(self, app, db, comptable_client, sample_users):
        annee = datetime.now().year
        with app.app_context():
            _seed_bi(db, annee, with_bilan=False)
        resp = comptable_client.get(f'/api/cr/bilan-donnees?annee={annee}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['has_bilan'] is False

    def test_bilan_avec_comptes_bilan(self, app, db, comptable_client, sample_users):
        annee = datetime.now().year
        with app.app_context():
            _seed_bi(db, annee, with_bilan=True)
        resp = comptable_client.get(f'/api/cr/bilan-donnees?annee={annee}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['has_bilan'] is True
        n = data['n']
        # Le résultat (produits 60 000 − charges 55 000 = +5 000) doit être injecté
        # en compte 120000 dans passif_capitaux (classe 12).
        assert n['total_passif_capitaux'] == pytest.approx(85000.0)  # 80000 + 5000
        assert n['total_passif'] == pytest.approx(85000.0)
        assert n['total_actif_immo'] == pytest.approx(30000.0)
        assert n['total_actif_tresorerie'] == pytest.approx(25000.0)
        # Vérifier que le compte 120000 est présent dans passif_capitaux['12']
        assert '12' in n['passif_capitaux']
        assert '120000' in n['passif_capitaux']['12']['comptes']


# ── Tests page indicateurs-financiers ────────────────────────────────────────

class TestIndicateursFinanciers:
    def test_page_accessible_comptable(self, app, db, comptable_client, sample_users):
        resp = comptable_client.get('/indicateurs-financiers')
        assert resp.status_code == 200
        assert 'Indicateurs' in resp.data.decode()

    def test_page_inaccessible_salarie(self, app, db, auth_client, sample_users):
        resp = auth_client.get('/indicateurs-financiers', follow_redirects=True)
        assert resp.status_code == 200


class TestApiIndicateursDonnees:
    def test_indicateurs_vide(self, app, db, comptable_client, sample_users):
        resp = comptable_client.get('/api/indicateurs/donnees')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['indicateurs'] == []

    def test_indicateurs_avec_donnees(self, app, db, comptable_client, sample_users):
        annee = datetime.now().year
        with app.app_context():
            _seed_bi(db, annee, with_bilan=True)
        resp = comptable_client.get('/api/indicateurs/donnees')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data['indicateurs']) == 1
        indic = data['indicateurs'][0]
        assert indic['annee'] == annee
        # capitaux permanents = comptes 1x (80 000) + résultat (60 000 − 55 000 = +5 000)
        assert indic['capitaux_permanents'] == pytest.approx(85000.0)
        assert indic['immobilisations_nettes'] == pytest.approx(30000.0)
        assert indic['fonds_roulement'] == pytest.approx(55000.0)  # 85000 − 30000
        assert indic['bfr'] == pytest.approx(0.0)
        assert indic['tresorerie'] == pytest.approx(25000.0)
        assert indic['caf'] == pytest.approx(5000.0)
        assert indic['sante_globale_stars'] == 5
        assert indic['masse_salariale'] == pytest.approx(50000.0)
        assert indic['pct_masse_salariale'] == pytest.approx(90.9, abs=0.1)

    def test_indicateurs_bfr_et_caf(self, app, db, comptable_client, sample_users):
        annee = datetime.now().year
        with app.app_context():
            import database
            conn = database.get_db()
            conn.execute(
                "INSERT INTO bilan_fec_imports (fichier_nom, annee, nb_ecritures) VALUES (?, ?, ?)",
                (f'bi_{annee}.txt', annee, 8)
            )
            import_id = conn.execute(
                'SELECT id FROM bilan_fec_imports ORDER BY id DESC LIMIT 1'
            ).fetchone()['id']
            # Résultat = (70 000 + 500 de reprises) - (60 000 + 3 000 de dotations) = +7 500
            rows = [
                ('106000', 'Réserves', '', annee, 12, 80000.0, import_id),   # 1x
                ('215000', 'Immo', '', annee, 12, 30000.0, import_id),       # 2x
                ('310000', 'Stocks', '', annee, 12, 7000.0, import_id),      # 3x
                ('411000', 'Clients', '', annee, 12, 9000.0, import_id),     # 4x
                ('512000', 'Banque', '', annee, 12, 12000.0, import_id),     # 5x
                ('641000', 'Salaires', '', annee, 12, 60000.0, import_id),   # 6x
                ('681000', 'Dotations', '', annee, 12, 3000.0, import_id),   # 68x
                ('740000', 'Produits', '', annee, 12, 70000.0, import_id),   # 7x
                ('781000', 'Reprises', '', annee, 12, 500.0, import_id),     # 78x
            ]
            for row in rows:
                conn.execute(
                    "INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    row
                )
            conn.commit()
            conn.close()

        resp = comptable_client.get('/api/indicateurs/donnees')
        assert resp.status_code == 200
        data = resp.get_json()
        indic = data['indicateurs'][0]

        # Capitaux permanents = 1x (80 000) + résultat (7 500) = 87 500
        assert indic['capitaux_permanents'] == pytest.approx(87500.0)
        assert indic['immobilisations_nettes'] == pytest.approx(30000.0)
        assert indic['fonds_roulement'] == pytest.approx(57500.0)
        # BFR = stocks (3x) + comptes de tiers (4x)
        assert indic['bfr'] == pytest.approx(16000.0)
        # CAF = résultat + dotations (68x) - reprises (78x)
        assert indic['caf'] == pytest.approx(10000.0)
        # Tous les critères sont au vert => 5 étoiles
        assert indic['sante_globale_stars'] == 5

    def test_indicateurs_acces_refuse(self, app, db, auth_client, sample_users):
        resp = auth_client.get('/api/indicateurs/donnees')
        assert resp.status_code == 403

    def test_masse_salariale_inclut_tous_comptes_64(self, app, db, comptable_client, sample_users):
        """Tous les comptes 64xxxx (brut 641, cotisations sociales 645, etc.)
        doivent être inclus dans la masse salariale."""
        annee = datetime.now().year
        with app.app_context():
            import database
            conn = database.get_db()
            conn.execute(
                "INSERT INTO bilan_fec_imports (fichier_nom, annee, nb_ecritures) VALUES (?, ?, ?)",
                (f'bi_{annee}.txt', annee, 3)
            )
            import_id = conn.execute(
                'SELECT id FROM bilan_fec_imports ORDER BY id DESC LIMIT 1'
            ).fetchone()['id']
            # 641xxx : salaires bruts
            conn.execute(
                "INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ('641000', 'Salaires bruts', '', annee, 1, 40000.0, import_id)
            )
            # 645xxx : cotisations sociales patronales
            conn.execute(
                "INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ('645000', 'Cotisations sociales', '', annee, 1, 15000.0, import_id)
            )
            # 622xxx : honoraires (hors masse salariale)
            conn.execute(
                "INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, mois, montant, import_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ('622000', 'Honoraires', '', annee, 1, 5000.0, import_id)
            )
            conn.commit()
            conn.close()
        resp = comptable_client.get('/api/indicateurs/donnees')
        data = resp.get_json()
        indic = data['indicateurs'][0]
        # masse salariale = 641000 (40 000) + 645000 (15 000) = 55 000
        assert indic['masse_salariale'] == pytest.approx(55000.0)
        # total charges = 40 000 + 15 000 + 5 000 = 60 000
        assert indic['total_charges'] == pytest.approx(60000.0)
        # pct = 55000 / 60000 * 100 ≈ 91.7 %
        assert indic['pct_masse_salariale'] == pytest.approx(91.7, abs=0.1)


class TestApiFondsRoulementDetail:
    def test_fr_annee_requise(self, app, db, comptable_client, sample_users):
        resp = comptable_client.get('/api/indicateurs/fonds-roulement')
        assert resp.status_code == 400

    def test_fr_detail(self, app, db, comptable_client, sample_users):
        annee = datetime.now().year
        with app.app_context():
            _seed_bi(db, annee, with_bilan=True)
        resp = comptable_client.get(f'/api/indicateurs/fonds-roulement?annee={annee}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['annee'] == annee
        # total_capitaux = comptes 1x (80 000) + résultat (5 000) = 85 000
        assert data['total_capitaux'] == pytest.approx(85000.0)
        assert data['total_immos'] == pytest.approx(30000.0)
        assert data['fonds_roulement'] == pytest.approx(55000.0)  # 85000 − 30000
        assert data['fr_mois'] is not None
        # fr_mois = 55000 / (55000 / 12) = 12.0
        assert data['fr_mois'] == pytest.approx(12.0, abs=0.1)
        # La ligne synthétique résultat (120000) doit figurer dans capitaux_rows
        comptes_cap = [r['compte_num'] for r in data['capitaux_rows']]
        assert '120000' in comptes_cap
        assert len(data['immo_rows']) >= 1

    def test_fr_acces_refuse(self, app, db, auth_client, sample_users):
        annee = datetime.now().year
        resp = auth_client.get(f'/api/indicateurs/fonds-roulement?annee={annee}')
        assert resp.status_code == 403


# ── Tests import BI étendu (classes 1-7) ─────────────────────────────────────

class TestImportBiEtendu:
    def test_import_comptes_1x_captures(self, app, db, comptable_client, sample_users):
        # Comptes 1x/2x/5x : pas de code analytique (G seulement) → importés tels quels.
        # Comptes 6x/7x : seules les lignes avec code analytique sont importées.
        content = _make_bi_content([
            ('OD', '31/12/2024', 'OD001', '', '', '106000', '', '', 'Réserves', '',
             '0', '50000', '', '', 'G', '', ''),
            ('OD', '31/12/2024', 'OD002', '', '', '215000', '', '', 'Matériel bureau', '',
             '20000', '0', '', '', 'G', '', ''),
            ('OD', '31/12/2024', 'OD003', '', '', '512000', '', '', 'Banque', '',
             '15000', '0', '', '', 'G', '', ''),
            # Ligne G pour 641000 → ignorée (6x sans code analytique)
            ('OD', '31/12/2024', 'OD004', '', '', '641000', '', '', 'Salaires', '',
             '30000', '0', '', '', 'G', '', ''),
            # Ligne A pour 641000 → importée (6x avec code analytique)
            ('OD', '31/12/2024', 'OD004', '', '', '641000', '', '', 'Salaires',
             'PILOTAGE', '30000', '0', '', '', 'A', 'ANA001', ''),
            # Ligne G pour 740000 → ignorée (7x sans code analytique)
            ('OD', '31/12/2024', 'OD005', '', '', '740000', '', '', 'Subvention', '',
             '0', '35000', '', '', 'G', '', ''),
            # Ligne A pour 740000 → importée (7x avec code analytique)
            ('OD', '31/12/2024', 'OD005', '', '', '740000', '', '', 'Subvention',
             'SUBV', '0', '35000', '', '', 'A', 'ANA002', ''),
        ])
        data = {'fichier': (io.BytesIO(content.encode('utf-8')), 'bi_2024.txt')}
        resp = comptable_client.post('/api/bilan/import-bi',
                                     data=data, content_type='multipart/form-data')
        assert resp.status_code == 200
        result = resp.get_json()
        assert result['success'] is True
        # 3 lignes bilan (1x/2x/5x) + 1 ligne analytique 641000 + 1 ligne analytique 740000 = 5
        assert result['nb_ecritures'] == 5
        # Vérifier les montants en base
        with app.app_context():
            import database
            conn = database.get_db()
            rows = conn.execute(
                "SELECT compte_num, montant FROM bilan_fec_donnees ORDER BY compte_num"
            ).fetchall()
            conn.close()
        montants = {r['compte_num']: r['montant'] for r in rows}
        # 106000 crédit-normal → credit − debit = 50000 − 0 = 50000
        assert montants.get('106000') == pytest.approx(50000.0)
        # 215000 débit-normal → debit − credit = 20000 − 0 = 20000
        assert montants.get('215000') == pytest.approx(20000.0)
        # 512000 débit-normal → debit − credit = 15000 − 0 = 15000
        assert montants.get('512000') == pytest.approx(15000.0)
        # 641000 débit-normal → debit − credit = 30000 − 0 = 30000
        assert montants.get('641000') == pytest.approx(30000.0)
        # 740000 crédit-normal → credit − debit = 35000 − 0 = 35000
        assert montants.get('740000') == pytest.approx(35000.0)

    def test_import_ignore_classes_89(self, app, db, comptable_client, sample_users):
        content = _make_bi_content([
            ('OD', '31/12/2024', 'OD001', '', '', '890000', '', '', 'Bilan ouverture', '',
             '0', '100000', '', '', 'G', '', ''),
            # 641000 avec code analytique → importé
            ('OD', '31/12/2024', 'OD002', '', '', '641000', '', '', 'Salaires',
             'PILOTAGE', '40000', '0', '', '', 'A', 'ANA001', ''),
        ])
        data = {'fichier': (io.BytesIO(content.encode('utf-8')), 'bi_test.txt')}
        resp = comptable_client.post('/api/bilan/import-bi',
                                     data=data, content_type='multipart/form-data')
        assert resp.status_code == 200
        result = resp.get_json()
        # 890000 (classe 8) ignoré ; seul 641000 importé
        assert result['nb_ecritures'] == 1


    def test_reimport_meme_annee_ne_double_pas(self, app, db, comptable_client, sample_users):
        """Un ré-import pour la même année remplace les données (pas de doublon)."""
        content = _make_bi_content([
            # 641000 avec code analytique (seule forme acceptée pour les 6x)
            ('OD', '31/12/2024', 'OD001', '', '', '641000', '', '', 'Salaires',
             'PILOTAGE', '40000', '0', '', '', 'A', 'ANA001', ''),
            # 740000 avec code analytique (seule forme acceptée pour les 7x)
            ('OD', '31/12/2024', 'OD002', '', '', '740000', '', '', 'Subvention',
             'SUBV', '0', '50000', '', '', 'A', 'ANA002', ''),
        ])
        data1 = {'fichier': (io.BytesIO(content.encode('utf-8')), 'bi_2024_v1.txt')}
        resp1 = comptable_client.post('/api/bilan/import-bi',
                                      data=data1, content_type='multipart/form-data')
        assert resp1.get_json()['success'] is True

        # Ré-import de la même année avec le même contenu
        data2 = {'fichier': (io.BytesIO(content.encode('utf-8')), 'bi_2024_v2.txt')}
        resp2 = comptable_client.post('/api/bilan/import-bi',
                                      data=data2, content_type='multipart/form-data')
        assert resp2.get_json()['success'] is True

        # Les totaux ne doivent pas être doublés
        resp_cr = comptable_client.get('/api/cr/donnees?annee=2024')
        cr = resp_cr.get_json()
        assert cr['n']['total_charges'] == pytest.approx(40000.0)
        assert cr['n']['total_produits'] == pytest.approx(50000.0)

        # Un seul import doit exister en base pour 2024
        with app.app_context():
            import database
            conn = database.get_db()
            nb_imports = conn.execute(
                "SELECT COUNT(*) as nb FROM bilan_fec_imports WHERE annee = 2024"
            ).fetchone()['nb']
            conn.close()
        assert nb_imports == 1

    def test_import_bi_ignore_entrees_6x7x_sans_analytique(self, app, db, comptable_client, sample_users):
        """Les entrées 6x/7x sans code analytique (lignes 'G') sont ignorées.
        Seules les lignes 6x/7x avec un code analytique (lignes 'A') sont importées.
        Les comptes 1x-5x sans code analytique sont toujours importés."""
        content = _make_bi_content([
            # 654400 – ligne G (sans code analytique) → IGNORÉE
            ('OD', '13/12/2024', '', '', '', '654400', '', '', 'DUPONT Jean', '',
             '59,60', '0,00', '', '31/12/2024', 'G', '', ''),
            # 654400 – ligne A (avec code analytique) → IMPORTÉE
            ('OD', '13/12/2024', '', '', '', '654400', '', '', 'DUPONT Jean',
             'PILOTAGE NON ELIGIBLE', '59,60', '0,00', '', '31/12/2024', 'A', '5P882000', ''),
            # 740000 – ligne G (sans code analytique) → IGNORÉE
            ('OD', '13/12/2024', '', '', '', '740000', '', '', 'Subvention CAF', '',
             '0,00', '1200,00', '', '31/12/2024', 'G', '', ''),
            # 740000 – ligne A (avec code analytique) → IMPORTÉE
            ('OD', '13/12/2024', '', '', '', '740000', '', '', 'Subvention CAF',
             'SUBV', '0,00', '1200,00', '', '31/12/2024', 'A', '5P882000', ''),
            # 411100 (classe 4) – ligne G seulement, pas d'analytique → IMPORTÉE
            ('OD', '13/12/2024', '0120070066', '', '', '411100', 'DUPONT', 'DUPONT Jean',
             'DUPONT Jean', '', '0,00', '59,60', '', '31/12/2024', 'G', '', ''),
        ])
        data = {'fichier': (io.BytesIO(content.encode('utf-8')), 'bi_ga.txt')}
        resp = comptable_client.post('/api/bilan/import-bi',
                                     data=data, content_type='multipart/form-data')
        result = resp.get_json()
        assert result['success'] is True
        # 1 ligne A pour 654400 + 1 ligne A pour 740000 + 1 ligne G pour 411100 = 3
        assert result['nb_ecritures'] == 3

        # Le C.R. doit afficher les bons montants (pas doublés)
        resp_cr = comptable_client.get('/api/cr/donnees?annee=2024')
        cr = resp_cr.get_json()
        # 654400 : débit-normal → debit - credit = 59,60 - 0 = 59,60
        assert cr['n']['total_charges'] == pytest.approx(59.60)
        # 740000 : crédit-normal → credit - debit = 1200 - 0 = 1200
        assert cr['n']['total_produits'] == pytest.approx(1200.0)
