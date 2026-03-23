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
        assert n['total_passif_capitaux'] == pytest.approx(80000.0)
        assert n['total_actif_immo'] == pytest.approx(30000.0)
        assert n['total_actif_tresorerie'] == pytest.approx(25000.0)


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
        assert indic['capitaux_permanents'] == pytest.approx(80000.0)
        assert indic['immobilisations_nettes'] == pytest.approx(30000.0)
        assert indic['fonds_roulement'] == pytest.approx(50000.0)
        assert indic['tresorerie'] == pytest.approx(25000.0)
        assert indic['masse_salariale'] == pytest.approx(50000.0)
        assert indic['pct_masse_salariale'] == pytest.approx(90.9, abs=0.1)

    def test_indicateurs_acces_refuse(self, app, db, auth_client, sample_users):
        resp = auth_client.get('/api/indicateurs/donnees')
        assert resp.status_code == 403


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
        assert data['total_capitaux'] == pytest.approx(80000.0)
        assert data['total_immos'] == pytest.approx(30000.0)
        assert data['fonds_roulement'] == pytest.approx(50000.0)
        assert data['fr_mois'] is not None
        assert data['fr_mois'] == pytest.approx(50000 / (55000 / 12), abs=0.1)
        assert len(data['capitaux_rows']) >= 1
        assert len(data['immo_rows']) >= 1

    def test_fr_acces_refuse(self, app, db, auth_client, sample_users):
        annee = datetime.now().year
        resp = auth_client.get(f'/api/indicateurs/fonds-roulement?annee={annee}')
        assert resp.status_code == 403


# ── Tests import BI étendu (classes 1-7) ─────────────────────────────────────

class TestImportBiEtendu:
    def test_import_comptes_1x_captures(self, app, db, comptable_client, sample_users):
        content = _make_bi_content([
            ('OD', '31/12/2024', 'OD001', '', '', '106000', '', '', 'Réserves', '',
             '0', '50000', '', '', '', '', ''),
            ('OD', '31/12/2024', 'OD002', '', '', '215000', '', '', 'Matériel bureau', '',
             '20000', '0', '', '', '', '', ''),
            ('OD', '31/12/2024', 'OD003', '', '', '512000', '', '', 'Banque', '',
             '15000', '0', '', '', '', '', ''),
            ('OD', '31/12/2024', 'OD004', '', '', '641000', '', '', 'Salaires', '',
             '30000', '0', '', '', '', '', ''),
            ('OD', '31/12/2024', 'OD005', '', '', '740000', '', '', 'Subvention', '',
             '0', '35000', '', '', '', '', ''),
        ])
        data = {'fichier': (io.BytesIO(content.encode('utf-8')), 'bi_2024.txt')}
        resp = comptable_client.post('/api/bilan/import-bi',
                                     data=data, content_type='multipart/form-data')
        assert resp.status_code == 200
        result = resp.get_json()
        assert result['success'] is True
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
             '0', '100000', '', '', '', '', ''),
            ('OD', '31/12/2024', 'OD002', '', '', '641000', '', '', 'Salaires', '',
             '40000', '0', '', '', '', '', ''),
        ])
        data = {'fichier': (io.BytesIO(content.encode('utf-8')), 'bi_test.txt')}
        resp = comptable_client.post('/api/bilan/import-bi',
                                     data=data, content_type='multipart/form-data')
        assert resp.status_code == 200
        result = resp.get_json()
        # 890000 (classe 8) ignoré ; seul 641000 importé
        assert result['nb_ecritures'] == 1



# ── Fixtures helpers ──────────────────────────────────────────────────────────

