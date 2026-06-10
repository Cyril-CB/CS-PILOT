"""
Tests de la page Variables de paie :
- Types numeriques corrects dans le schema initial (bug "cases mutuelle
  toutes cochees apres enregistrement", colonnes creees en TEXT)
- Correction des anciennes bases par _corriger_types_variables_paie
  (fallback init_db + migration 0038)
- Cycle enregistrer -> reafficher : les cases mutuelle restent fideles
  a la saisie
"""
import os
import re

import database


def _type_colonne(db, table, colonne):
    """Retourne le type declare d'une colonne via PRAGMA table_info."""
    for row in db.execute(f'PRAGMA table_info({table})'):
        if row[1] == colonne:
            return (row[2] or '').strip().upper()
    return None


def _case_mutuelle_cochee(html, user_id):
    """Retourne True si la checkbox mutuelle du salarie est cochee dans le HTML."""
    m = re.search(rf'<input[^>]*name="mutuelle_{user_id}"[^>]*>', html)
    assert m, f"Checkbox mutuelle_{user_id} absente de la page"
    return 'checked' in m.group(0)


class TestSchemaVariablesPaie:
    """Le schema initial doit utiliser des types numeriques (pas TEXT)."""

    def test_types_variables_paie(self, app, db):
        with app.app_context():
            assert _type_colonne(db, 'variables_paie', 'mutuelle') == 'INTEGER'
            assert _type_colonne(db, 'variables_paie', 'nb_enfants') == 'INTEGER'
            for col in ('transport', 'acompte', 'saisie_salaire',
                        'pret_avance', 'autres_regularisation'):
                assert _type_colonne(db, 'variables_paie', col) == 'REAL', col

    def test_types_variables_paie_defauts(self, app, db):
        with app.app_context():
            assert _type_colonne(db, 'variables_paie_defauts', 'mutuelle') == 'INTEGER'
            assert _type_colonne(db, 'variables_paie_defauts', 'nb_enfants') == 'INTEGER'
            for col in ('saisie_salaire', 'pret_avance'):
                assert _type_colonne(db, 'variables_paie_defauts', col) == 'REAL', col


class TestCorrectionAncienneBase:
    """Reconstruction des tables creees en TEXT par d'anciennes versions."""

    def _creer_ancien_schema(self, db):
        """Recree les tables avec l'ancien schema bogue (colonnes TEXT)."""
        db.execute('DROP TABLE variables_paie')
        db.execute('DROP TABLE variables_paie_defauts')
        db.execute('''
            CREATE TABLE variables_paie_defauts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                mutuelle TEXT,
                nb_enfants INTEGER DEFAULT 0,
                saisie_salaire TEXT,
                pret_avance TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        db.execute('''
            CREATE TABLE variables_paie (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                mois INTEGER NOT NULL,
                annee INTEGER NOT NULL,
                mutuelle TEXT,
                nb_enfants INTEGER DEFAULT 0,
                transport TEXT,
                acompte TEXT,
                saisie_salaire TEXT,
                pret_avance TEXT,
                autres_regularisation TEXT,
                commentaire TEXT,
                heures_reelles REAL,
                heures_supps REAL,
                saisi_par INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (saisi_par) REFERENCES users(id),
                UNIQUE(user_id, mois, annee)
            )
        ''')

    def test_reconstruction_et_conversion(self, app, db, sample_users):
        with app.app_context():
            self._creer_ancien_schema(db)
            uid = sample_users['salarie_id']
            uid2 = sample_users['responsable_id']
            db.execute(
                'INSERT INTO variables_paie (user_id, mois, annee, mutuelle, nb_enfants, transport) '
                'VALUES (?, 6, 2026, 0, 2, 12.5)', (uid,)
            )
            db.execute(
                'INSERT INTO variables_paie (user_id, mois, annee, mutuelle) '
                'VALUES (?, 6, 2026, 1)', (uid2,)
            )
            db.execute(
                'INSERT INTO variables_paie_defauts (user_id, mutuelle, pret_avance) '
                'VALUES (?, 0, 50)', (uid,)
            )
            db.commit()

            # Le bug d'origine : la colonne TEXT stocke '0', chaine non vide
            # donc consideree comme vraie cote Python (case affichee cochee).
            brut = db.execute(
                'SELECT mutuelle, typeof(mutuelle) AS t FROM variables_paie WHERE user_id = ?',
                (uid,)
            ).fetchone()
            assert brut['t'] == 'text'
            assert bool(brut['mutuelle'])

            database._corriger_types_variables_paie(db.cursor())
            db.commit()

            assert _type_colonne(db, 'variables_paie', 'mutuelle') == 'INTEGER'
            row = db.execute(
                'SELECT *, typeof(mutuelle) AS t FROM variables_paie WHERE user_id = ?',
                (uid,)
            ).fetchone()
            assert row['t'] == 'integer'
            assert row['mutuelle'] == 0
            assert not bool(row['mutuelle'])
            assert row['nb_enfants'] == 2
            assert row['transport'] == 12.5

            row2 = db.execute(
                'SELECT mutuelle FROM variables_paie WHERE user_id = ?', (uid2,)
            ).fetchone()
            assert row2['mutuelle'] == 1

            defaut = db.execute(
                'SELECT mutuelle, pret_avance, typeof(mutuelle) AS t '
                'FROM variables_paie_defauts WHERE user_id = ?', (uid,)
            ).fetchone()
            assert defaut['t'] == 'integer'
            assert defaut['mutuelle'] == 0
            assert defaut['pret_avance'] == 50.0

    def test_idempotent_sur_schema_correct(self, app, db):
        with app.app_context():
            database._corriger_types_variables_paie(db.cursor())
            assert _type_colonne(db, 'variables_paie', 'mutuelle') == 'INTEGER'
            assert _type_colonne(db, 'variables_paie_defauts', 'mutuelle') == 'INTEGER'

    def test_migration_0038_applique_le_correctif(self, app, db, sample_users):
        with app.app_context():
            self._creer_ancien_schema(db)
            db.execute(
                'INSERT INTO variables_paie (user_id, mois, annee, mutuelle) '
                'VALUES (?, 6, 2026, 0)', (sample_users['salarie_id'],)
            )
            db.commit()

            from migration_manager import _load_migration_module, MIGRATIONS_DIR
            module = _load_migration_module(
                os.path.join(MIGRATIONS_DIR, '0038_correctif_types_variables_paie.py')
            )
            module.upgrade(db)

            assert _type_colonne(db, 'variables_paie', 'mutuelle') == 'INTEGER'
            row = db.execute(
                'SELECT mutuelle FROM variables_paie WHERE user_id = ?',
                (sample_users['salarie_id'],)
            ).fetchone()
            assert row['mutuelle'] == 0


class TestPageVariablesPaie:
    """Cycle HTTP complet : enregistrement puis reaffichage de la grille."""

    def test_acces_refuse_salarie(self, auth_client):
        resp = auth_client.get('/variables_paie', follow_redirects=False)
        assert resp.status_code == 302

    def test_cases_non_cochees_restent_decochees(self, comptable_client, sample_users):
        """Bug d'origine : apres validation, toutes les cases se cochaient."""
        ids = [sample_users['salarie_id'], sample_users['responsable_id'],
               sample_users['directeur_id'], sample_users['comptable_id']]
        resp = comptable_client.post('/variables_paie/enregistrer', data={
            'mois': '6',
            'annee': '2026',
            'user_ids': [str(i) for i in ids],
        }, follow_redirects=True)
        assert resp.status_code == 200

        html = comptable_client.get('/variables_paie?mois=6&annee=2026').data.decode('utf-8')
        for uid in ids:
            assert _case_mutuelle_cochee(html, uid) is False, \
                f"La case mutuelle du salarie {uid} ne doit pas se cocher toute seule"

    def test_case_cochee_conservee(self, comptable_client, sample_users, app, db):
        """Une case cochee doit le rester, les autres rester decochees."""
        salarie_id = sample_users['salarie_id']
        responsable_id = sample_users['responsable_id']
        comptable_client.post('/variables_paie/enregistrer', data={
            'mois': '6',
            'annee': '2026',
            'user_ids': [str(salarie_id), str(responsable_id)],
            f'mutuelle_{salarie_id}': '1',
        }, follow_redirects=True)

        html = comptable_client.get('/variables_paie?mois=6&annee=2026').data.decode('utf-8')
        assert _case_mutuelle_cochee(html, salarie_id) is True
        assert _case_mutuelle_cochee(html, responsable_id) is False

        # La valeur doit etre stockee en entier, pas en texte
        with app.app_context():
            row = db.execute(
                'SELECT mutuelle, typeof(mutuelle) AS t FROM variables_paie WHERE user_id = ?',
                (salarie_id,)
            ).fetchone()
            assert row['t'] == 'integer'
            assert row['mutuelle'] == 1
