"""
Tests pour les nouvelles fonctionnalités :
- rh_statistiques : page de statistiques RH
- contrats : champ temps_hebdo
- budget_previsionnel : masquage boutons pour responsable
"""
import pytest
from werkzeug.security import generate_password_hash


# ── Helpers ──────────────────────────────────────────────────────────────────

def _login(client, login, password):
    return client.post('/login', data={'login': login, 'password': password},
                       follow_redirects=True)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def users_with_contracts(app, db):
    """Crée un jeu de données avec secteurs, utilisateurs et contrats."""
    with app.app_context():
        c = db.cursor()

        # Secteur
        c.execute("INSERT INTO secteurs (nom) VALUES (?)", ('Crèche',))
        secteur_id = c.lastrowid

        # Directeur
        c.execute(
            "INSERT INTO users (nom, prenom, login, password, profil) VALUES (?,?,?,?,?)",
            ('Dir', 'Test', 'dir_test', generate_password_hash('Dir1234'), 'directeur')
        )
        dir_id = c.lastrowid

        # Responsable
        c.execute(
            "INSERT INTO users (nom, prenom, login, password, profil, secteur_id) VALUES (?,?,?,?,?,?)",
            ('Resp', 'Test', 'resp_test2', generate_password_hash('Resp1234'), 'responsable', secteur_id)
        )
        resp_id = c.lastrowid

        # Salarié CDI 35h
        c.execute(
            "INSERT INTO users (nom, prenom, login, password, profil, secteur_id, actif) VALUES (?,?,?,?,?,?,?)",
            ('Salarié', 'Un', 'sal1', generate_password_hash('Sal1234'), 'salarie', secteur_id, 1)
        )
        sal1_id = c.lastrowid
        c.execute(
            "INSERT INTO contrats (user_id, type_contrat, date_debut, temps_hebdo, saisi_par) VALUES (?,?,?,?,?)",
            (sal1_id, 'CDI', '2023-01-01', 35.0, dir_id)
        )

        # Salarié CDD 28h
        c.execute(
            "INSERT INTO users (nom, prenom, login, password, profil, secteur_id, actif) VALUES (?,?,?,?,?,?,?)",
            ('Salarié', 'Deux', 'sal2', generate_password_hash('Sal1234'), 'salarie', secteur_id, 1)
        )
        sal2_id = c.lastrowid
        c.execute(
            "INSERT INTO contrats (user_id, type_contrat, date_debut, temps_hebdo, saisi_par) VALUES (?,?,?,?,?)",
            (sal2_id, 'CDD', '2024-01-01', 28.0, dir_id)
        )

        db.commit()
        return {
            'dir_id': dir_id, 'resp_id': resp_id,
            'sal1_id': sal1_id, 'sal2_id': sal2_id,
            'secteur_id': secteur_id,
        }


# ── Tests rh_statistiques ─────────────────────────────────────────────────────

class TestRhStatistiques:

    def test_acces_directeur(self, client, users_with_contracts):
        _login(client, 'dir_test', 'Dir1234')
        resp = client.get('/rh/statistiques')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'Statistiques RH' in html

    def test_acces_refuse_responsable(self, client, users_with_contracts):
        _login(client, 'resp_test2', 'Resp1234')
        resp = client.get('/rh/statistiques', follow_redirects=True)
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'Statistiques RH' not in html or 'Accès non autorisé' in html

    def test_affiche_types_contrat(self, client, users_with_contracts):
        _login(client, 'dir_test', 'Dir1234')
        resp = client.get('/rh/statistiques')
        html = resp.get_data(as_text=True)
        assert 'CDI' in html
        assert 'CDD' in html

    def test_affiche_etp(self, client, users_with_contracts):
        _login(client, 'dir_test', 'Dir1234')
        resp = client.get('/rh/statistiques')
        html = resp.get_data(as_text=True)
        assert 'ETP' in html

    def test_ne_affiche_plus_la_section_a_recuperer(self, client, users_with_contracts):
        _login(client, 'dir_test', 'Dir1234')
        resp = client.get('/rh/statistiques')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'À récupérer' not in html


# ── Tests contrats temps_hebdo ────────────────────────────────────────────────

class TestContratsTempsHebdo:

    def test_colonne_temps_hebdo_dans_tableau(self, client, users_with_contracts):
        """La colonne Temps Hebdo apparaît dans le tableau des contrats."""
        _login(client, 'dir_test', 'Dir1234')
        resp = client.get(f'/infos_salaries?user_id={users_with_contracts["sal1_id"]}')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'Temps Hebdo' in html

    def test_champ_saisie_temps_hebdo(self, client, users_with_contracts):
        """Le formulaire d'ajout de contrat contient le champ temps_hebdo."""
        _login(client, 'dir_test', 'Dir1234')
        resp = client.get(f'/infos_salaries?user_id={users_with_contracts["sal1_id"]}')
        html = resp.get_data(as_text=True)
        assert 'name="temps_hebdo"' in html

    def test_ajout_contrat_avec_temps_hebdo(self, client, db, users_with_contracts):
        """Ajouter un contrat avec temps_hebdo enregistre la valeur."""
        _login(client, 'dir_test', 'Dir1234')
        user_id = users_with_contracts['sal1_id']
        resp = client.post('/infos_salaries/contrat', data={
            'user_id': user_id,
            'type_contrat': 'CDI',
            'date_debut': '2025-01-01',
            'temps_hebdo': '35',
        }, follow_redirects=True)
        assert resp.status_code == 200
        with client.application.app_context():
            import database
            conn = database.get_db()
            row = conn.execute(
                'SELECT temps_hebdo FROM contrats WHERE user_id=? ORDER BY id DESC LIMIT 1',
                (user_id,)
            ).fetchone()
            conn.close()
        assert row is not None
        assert row['temps_hebdo'] == 35.0


# ── Tests budget_previsionnel boutons ─────────────────────────────────────────

class TestBudgetPrevisionnelBoutons:

    def test_responsable_ne_voit_pas_import_bi(self, client, users_with_contracts):
        """Le responsable ne doit pas voir les boutons d'import BI (déplacés sur /import-bi)."""
        _login(client, 'resp_test2', 'Resp1234')
        resp = client.get('/budget-previsionnel')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'Importer BI' not in html
        assert 'Supprimer année importée' not in html
        assert 'Export PDF' in html

    def test_directeur_ne_voit_pas_import_bi_sur_budget(self, client, users_with_contracts):
        """L'import BI a été déplacé sur /import-bi ; il ne doit plus apparaître sur /budget-previsionnel."""
        _login(client, 'dir_test', 'Dir1234')
        resp = client.get('/budget-previsionnel')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        # Les boutons import/suppression BI ne sont plus sur cette page
        assert 'importBiModal' not in html
        assert 'supprimerAnneeImport' not in html
        assert 'Supprimer année importée' not in html
        # Les boutons PDF sont toujours là
        assert 'Export PDF' in html


# ── Tests ajout PDF sur contrat existant ──────────────────────────────────────

class TestAjouterPdfContrat:

    def test_ajout_pdf_sur_contrat_sans_fichier(self, client, users_with_contracts):
        """Un contrat sans PDF peut recevoir un PDF via la nouvelle route."""
        import io
        sal1_id = users_with_contracts['sal1_id']
        _login(client, 'dir_test', 'Dir1234')

        with client.application.app_context():
            import database
            conn = database.get_db()
            contrat = conn.execute(
                'SELECT id, fichier_path FROM contrats WHERE user_id=?', (sal1_id,)
            ).fetchone()
            conn.close()
        contrat_id = contrat['id']
        assert contrat['fichier_path'] is None

        resp = client.post(
            f'/infos_salaries/contrat/{contrat_id}/pdf',
            data={'fichier_contrat': (io.BytesIO(b'%PDF-1.4 test'), 'contrat.pdf')},
            content_type='multipart/form-data',
            follow_redirects=True,
        )
        assert resp.status_code == 200

        with client.application.app_context():
            import database
            conn = database.get_db()
            row = conn.execute(
                'SELECT fichier_path, fichier_nom FROM contrats WHERE id=?', (contrat_id,)
            ).fetchone()
            conn.close()
        assert row['fichier_path'] is not None
        assert row['fichier_nom'] == 'contrat.pdf'

    def test_refus_fichier_non_pdf(self, client, users_with_contracts):
        """Un fichier non-PDF est refusé."""
        import io
        sal1_id = users_with_contracts['sal1_id']
        _login(client, 'dir_test', 'Dir1234')

        with client.application.app_context():
            import database
            conn = database.get_db()
            contrat_id = conn.execute(
                'SELECT id FROM contrats WHERE user_id=?', (sal1_id,)
            ).fetchone()['id']
            conn.close()

        resp = client.post(
            f'/infos_salaries/contrat/{contrat_id}/pdf',
            data={'fichier_contrat': (io.BytesIO(b'image data'), 'photo.jpg')},
            content_type='multipart/form-data',
            follow_redirects=True,
        )
        assert resp.status_code == 200

        with client.application.app_context():
            import database
            conn = database.get_db()
            fichier_path = conn.execute(
                'SELECT fichier_path FROM contrats WHERE id=?', (contrat_id,)
            ).fetchone()['fichier_path']
            conn.close()
        assert fichier_path is None
