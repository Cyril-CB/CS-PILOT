"""
Tests du journal d'audit des actions metier (journal_actions) :
- schema de la table
- journaliser_action() ecrit dans la transaction de l'appelant (atomicite)
- les actions sensibles (variables paie, cloture conges) produisent une trace
"""
import database
from access_log import (journaliser_action, ACTION_CLOTURE_CONGES,
                        ACTION_ENREG_VARIABLES_PAIE)


def _colonnes(db, table):
    return {row[1] for row in db.execute(f'PRAGMA table_info({table})')}


class TestSchemaJournalActions:

    def test_table_et_colonnes(self, app, db):
        with app.app_context():
            cols = _colonnes(db, 'journal_actions')
            for c in ('id', 'date_heure', 'user_id', 'action',
                      'cible_type', 'cible_id', 'details', 'adresse_ip'):
                assert c in cols, c


class TestJournaliserAction:
    """journaliser_action ecrit dans la transaction de l'appelant."""

    def test_ecrit_dans_la_transaction_de_l_appelant(self, app, db, sample_users):
        with app.app_context():
            journaliser_action(
                db, ACTION_CLOTURE_CONGES,
                user_id=sample_users['comptable_id'],
                cible_type='mois_paie', details='mois=5/2026',
            )
            # Non commite : invisible depuis une autre connexion
            autre = database.get_db()
            try:
                n = autre.execute('SELECT COUNT(*) AS n FROM journal_actions').fetchone()['n']
                assert n == 0
            finally:
                autre.close()

            db.commit()

            autre = database.get_db()
            try:
                row = autre.execute('SELECT * FROM journal_actions').fetchone()
                assert row['action'] == ACTION_CLOTURE_CONGES
                assert row['user_id'] == sample_users['comptable_id']
                assert row['cible_type'] == 'mois_paie'
                assert row['details'] == 'mois=5/2026'
            finally:
                autre.close()

    def test_rollback_annule_la_trace(self, app, db, sample_users):
        with app.app_context():
            journaliser_action(db, ACTION_CLOTURE_CONGES,
                               user_id=sample_users['comptable_id'])
            db.rollback()
            n = db.execute('SELECT COUNT(*) AS n FROM journal_actions').fetchone()['n']
            assert n == 0


class TestAuditViaHTTP:
    """Les actions metier sensibles laissent une trace d'audit."""

    def test_enregistrement_variables_paie_audite(self, comptable_client, sample_users, app, db):
        ids = [sample_users['salarie_id'], sample_users['responsable_id']]
        resp = comptable_client.post('/variables_paie/enregistrer', data={
            'mois': '6', 'annee': '2026',
            'user_ids': [str(i) for i in ids],
        }, follow_redirects=True)
        assert resp.status_code == 200

        with app.app_context():
            row = db.execute(
                "SELECT * FROM journal_actions WHERE action = ? ORDER BY id DESC LIMIT 1",
                (ACTION_ENREG_VARIABLES_PAIE,)
            ).fetchone()
            assert row is not None, "aucune trace d'audit pour l'enregistrement des variables de paie"
            assert row['user_id'] == sample_users['comptable_id']
            assert 'mois=6/2026' in (row['details'] or '')

    def test_cloture_conges_auditee(self, comptable_client, sample_users, app, db):
        resp = comptable_client.post('/variables_paie/cloturer_conges', data={
            'mois': '6', 'annee': '2026',
        }, follow_redirects=True)
        assert resp.status_code == 200

        with app.app_context():
            row = db.execute(
                "SELECT * FROM journal_actions WHERE action = ? ORDER BY id DESC LIMIT 1",
                (ACTION_CLOTURE_CONGES,)
            ).fetchone()
            assert row is not None, "aucune trace d'audit pour la cloture des conges"
            assert row['user_id'] == sample_users['comptable_id']
