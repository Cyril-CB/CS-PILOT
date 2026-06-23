"""
Tests du blueprint ecritures_bp : génération, validation et modification des
écritures comptables.

Le point central est la génération via l'IA : selon le fournisseur, la réponse
peut être un tableau JSON, un objet englobant ``{"ecritures": [...]}`` (imposé
par le mode ``response_format=json_object`` d'OpenAI/Groq) ou une écriture
unique. Tous ces formats doivent produire des écritures.
"""
import json
from unittest.mock import patch


def _seed_facture(app, db, statut='a_traiter', montant=120.0,
                  code_comptable='FACME', echeance='2025-02-15'):
    """Insère un fournisseur + une facture et renvoie l'id de la facture."""
    with app.app_context():
        cur = db.execute(
            "INSERT INTO fournisseurs (nom, code_comptable) VALUES (?, ?)",
            ('ACME', code_comptable),
        )
        fid = cur.lastrowid
        cur = db.execute(
            "INSERT INTO factures (fournisseur_id, numero_facture, date_facture, "
            "date_echeance, montant_ttc, description, statut) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (fid, 'INV-001', '2025-01-15', echeance, montant, 'Fournitures', statut),
        )
        facture_id = cur.lastrowid
        db.commit()
        return facture_id


def _two_lines(facture_id, montant=120.0):
    """Deux lignes équilibrées (charge + fournisseur) pour une facture."""
    return [
        {"compte": "606100", "libelle": "acme facture inv-001",
         "debit": montant, "credit": 0, "code_analytique": "ANA01", "type": "charge"},
        {"compte": "FACME", "libelle": "acme facture inv-001",
         "debit": 0, "credit": montant, "code_analytique": None, "type": "fournisseur"},
    ]


def _count_ecritures(app, db, facture_id):
    with app.app_context():
        return db.execute(
            "SELECT COUNT(*) AS n FROM ecritures_comptables WHERE facture_id = ?",
            (facture_id,),
        ).fetchone()['n']


def _facture_statut(app, db, facture_id):
    with app.app_context():
        return db.execute(
            "SELECT statut FROM factures WHERE id = ?", (facture_id,)
        ).fetchone()['statut']


class TestAccesEcritures:
    def test_salarie_refuse(self, auth_client):
        resp = auth_client.get('/ecritures', follow_redirects=False)
        assert resp.status_code == 302

    def test_comptable_autorise(self, comptable_client):
        resp = comptable_client.get('/ecritures')
        assert resp.status_code == 200

    def test_generer_refuse_pour_salarie(self, auth_client):
        resp = auth_client.post('/ecritures/generer', data={'model': 'claude-sonnet-4-6'},
                                follow_redirects=False)
        assert resp.status_code == 302


class TestGenerationEcritures:
    def test_modele_obligatoire(self, app, db, comptable_client):
        fid = _seed_facture(app, db)
        resp = comptable_client.post('/ecritures/generer', data={}, follow_redirects=False)
        assert resp.status_code == 302
        # Aucun appel IA, aucune écriture, facture toujours à traiter
        assert _count_ecritures(app, db, fid) == 0
        assert _facture_statut(app, db, fid) == 'a_traiter'

    @patch('blueprints.ecritures.call_ai')
    def test_aucune_facture_a_traiter(self, mock_call_ai, app, db, comptable_client):
        # Facture déjà traitée → rien à générer, l'IA n'est pas appelée
        _seed_facture(app, db, statut='traitee')
        resp = comptable_client.post('/ecritures/generer',
                                     data={'model': 'claude-sonnet-4-6'},
                                     follow_redirects=False)
        assert resp.status_code == 302
        mock_call_ai.assert_not_called()

    @patch('blueprints.ecritures.call_ai')
    def test_reponse_tableau(self, mock_call_ai, app, db, comptable_client):
        """Réponse IA = tableau JSON (Anthropic) → écritures créées."""
        fid = _seed_facture(app, db)
        mock_call_ai.return_value = json.dumps(
            [{"facture_id": fid, "lignes": _two_lines(fid)}]
        )
        comptable_client.post('/ecritures/generer',
                              data={'model': 'claude-sonnet-4-6'},
                              follow_redirects=False)
        assert _count_ecritures(app, db, fid) == 2
        assert _facture_statut(app, db, fid) == 'traitee'

    @patch('blueprints.ecritures.call_ai')
    def test_reponse_objet_englobant(self, mock_call_ai, app, db, comptable_client):
        """RÉGRESSION : OpenAI/Groq (json_object) renvoie {"ecritures": [...]}.

        Avant le correctif, ce format produisait 0 écriture tout en affichant un
        message de succès trompeur.
        """
        fid = _seed_facture(app, db)
        mock_call_ai.return_value = json.dumps(
            {"ecritures": [{"facture_id": fid, "lignes": _two_lines(fid)}]}
        )
        comptable_client.post('/ecritures/generer',
                              data={'model': 'gpt-4.1-mini'},
                              follow_redirects=False)
        assert _count_ecritures(app, db, fid) == 2
        assert _facture_statut(app, db, fid) == 'traitee'

    @patch('blueprints.ecritures.call_ai')
    def test_reponse_objet_markdown(self, mock_call_ai, app, db, comptable_client):
        """Réponse objet entourée de balises markdown ```json ... ```."""
        fid = _seed_facture(app, db)
        payload = {"ecritures": [{"facture_id": fid, "lignes": _two_lines(fid)}]}
        mock_call_ai.return_value = "```json\n" + json.dumps(payload) + "\n```"
        comptable_client.post('/ecritures/generer',
                              data={'model': 'gpt-4.1-mini'},
                              follow_redirects=False)
        assert _count_ecritures(app, db, fid) == 2

    @patch('blueprints.ecritures.call_ai')
    def test_reponse_ecriture_unique(self, mock_call_ai, app, db, comptable_client):
        """Réponse = un seul objet écriture (sans tableau)."""
        fid = _seed_facture(app, db)
        mock_call_ai.return_value = json.dumps(
            {"facture_id": fid, "lignes": _two_lines(fid)}
        )
        comptable_client.post('/ecritures/generer',
                              data={'model': 'claude-sonnet-4-6'},
                              follow_redirects=False)
        assert _count_ecritures(app, db, fid) == 2

    @patch('blueprints.ecritures.call_ai')
    def test_libelle_en_majuscules(self, mock_call_ai, app, db, comptable_client):
        fid = _seed_facture(app, db)
        mock_call_ai.return_value = json.dumps(
            {"ecritures": [{"facture_id": fid, "lignes": _two_lines(fid)}]}
        )
        comptable_client.post('/ecritures/generer',
                              data={'model': 'claude-sonnet-4-6'},
                              follow_redirects=False)
        with app.app_context():
            libelles = [r['libelle'] for r in db.execute(
                "SELECT libelle FROM ecritures_comptables WHERE facture_id=?", (fid,)
            ).fetchall()]
        assert libelles and all(lib == lib.upper() for lib in libelles)

    @patch('blueprints.ecritures.call_ai')
    def test_reponse_vide_ne_marque_pas_traitee(self, mock_call_ai, app, db, comptable_client):
        """Réponse inexploitable → 0 écriture ET facture toujours à traiter.

        Garantit qu'on n'affiche plus « 0 écriture générée avec succès » et que
        la facture n'est pas perdue dans l'état « traitée » sans écriture.
        """
        fid = _seed_facture(app, db)
        mock_call_ai.return_value = json.dumps({})
        comptable_client.post('/ecritures/generer',
                              data={'model': 'gpt-4.1-mini'},
                              follow_redirects=False)
        assert _count_ecritures(app, db, fid) == 0
        assert _facture_statut(app, db, fid) == 'a_traiter'

    @patch('blueprints.ecritures.call_ai')
    def test_erreur_ia_remonte_un_message(self, mock_call_ai, app, db, comptable_client):
        fid = _seed_facture(app, db)
        mock_call_ai.side_effect = Exception('clé API invalide')
        resp = comptable_client.post('/ecritures/generer',
                                     data={'model': 'claude-sonnet-4-6'},
                                     follow_redirects=True)
        assert resp.status_code == 200
        assert _count_ecritures(app, db, fid) == 0
        assert _facture_statut(app, db, fid) == 'a_traiter'


class TestValidationModification:
    def _seed_ecriture(self, app, db, facture_id, statut='brouillon'):
        with app.app_context():
            cur = db.execute(
                "INSERT INTO ecritures_comptables (facture_id, date_ecriture, compte, "
                "libelle, debit, credit, statut) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (facture_id, '2025-01-15', '606100', 'TEST', 120.0, 0, statut),
            )
            eid = cur.lastrowid
            db.commit()
            return eid

    def test_valider_ecritures(self, app, db, comptable_client):
        fid = _seed_facture(app, db)
        eid = self._seed_ecriture(app, db, fid)
        comptable_client.post('/ecritures/valider',
                              data={'ecriture_ids': [str(eid)]},
                              follow_redirects=False)
        with app.app_context():
            statut = db.execute(
                "SELECT statut FROM ecritures_comptables WHERE id=?", (eid,)
            ).fetchone()['statut']
        assert statut == 'validee'

    def test_modifier_ecriture(self, app, db, comptable_client):
        fid = _seed_facture(app, db)
        eid = self._seed_ecriture(app, db, fid)
        comptable_client.post(
            f'/ecritures/{eid}/modifier',
            data={'compte': '607000', 'libelle': 'nouveau', 'debit': '99.5',
                  'credit': '0', 'code_analytique': 'ANA02'},
            follow_redirects=False,
        )
        with app.app_context():
            row = db.execute(
                "SELECT compte, libelle, debit, code_analytique "
                "FROM ecritures_comptables WHERE id=?", (eid,)
            ).fetchone()
        assert row['compte'] == '607000'
        assert row['libelle'] == 'NOUVEAU'  # mis en majuscules
        assert row['debit'] == 99.5
        assert row['code_analytique'] == 'ANA02'
