"""
Tests de la page Variables de paie :
- Types numeriques corrects dans le schema initial (bug "cases mutuelle
  toutes cochees apres enregistrement", colonnes creees en TEXT)
- Correction des anciennes bases par _corriger_types_variables_paie
  (fallback init_db + migration 0038)
- Cycle enregistrer -> reafficher : les cases mutuelle restent fideles
  a la saisie
- Cloture conges : remise a zero des soldes pour les salaries sans contrat
  actif le dernier jour du mois
"""
import json
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


class TestDevalidationPrepaPaie:
    """Toute modification d'une variable de paie retire la validation 'traite'
    de la preparation de paie pour le(s) salarie(s) reellement modifie(s)."""

    def _valider_prepa(self, db, user_id, mois=6, annee=2026):
        """Marque un salarie comme 'traite' en preparation de paie."""
        db.execute(
            'INSERT INTO prepa_paie_statut (user_id, mois, annee, traite) '
            'VALUES (?, ?, ?, 1)', (user_id, mois, annee)
        )
        db.commit()

    def _traite(self, db, user_id, mois=6, annee=2026):
        """Retourne la valeur 'traite' (ou None si aucune ligne)."""
        row = db.execute(
            'SELECT traite FROM prepa_paie_statut '
            'WHERE user_id = ? AND mois = ? AND annee = ?',
            (user_id, mois, annee)
        ).fetchone()
        return row['traite'] if row else None

    def test_modification_retire_la_validation(self, comptable_client, sample_users, app, db):
        """Modifier une variable d'un salarie deja valide retire sa case."""
        salarie_id = sample_users['salarie_id']
        with app.app_context():
            self._valider_prepa(db, salarie_id)

        comptable_client.post('/variables_paie/enregistrer', data={
            'mois': '6', 'annee': '2026',
            'user_ids': [str(salarie_id)],
            f'transport_{salarie_id}': '50',
        }, follow_redirects=True)

        with app.app_context():
            assert self._traite(db, salarie_id) == 0

    def test_sans_modification_conserve_la_validation(self, comptable_client, sample_users, app, db):
        """Re-enregistrer a l'identique ne doit PAS retirer la validation.

        Le formulaire resoumet toutes les lignes : sans detection de
        changement, la validation du prestataire serait effacee a chaque clic.
        """
        salarie_id = sample_users['salarie_id']
        # Etat de reference enregistre
        comptable_client.post('/variables_paie/enregistrer', data={
            'mois': '6', 'annee': '2026',
            'user_ids': [str(salarie_id)],
            f'transport_{salarie_id}': '50',
        }, follow_redirects=True)
        with app.app_context():
            self._valider_prepa(db, salarie_id)

        # Nouvel enregistrement avec exactement les memes valeurs
        comptable_client.post('/variables_paie/enregistrer', data={
            'mois': '6', 'annee': '2026',
            'user_ids': [str(salarie_id)],
            f'transport_{salarie_id}': '50',
        }, follow_redirects=True)

        with app.app_context():
            assert self._traite(db, salarie_id) == 1

    def test_seul_salarie_modifie_est_devalide(self, comptable_client, sample_users, app, db):
        """Seule la validation du salarie modifie est retiree (pas les autres)."""
        salarie_id = sample_users['salarie_id']
        responsable_id = sample_users['responsable_id']
        with app.app_context():
            self._valider_prepa(db, salarie_id)
            self._valider_prepa(db, responsable_id)

        # Le formulaire envoie les deux lignes, mais seul le salarie change
        comptable_client.post('/variables_paie/enregistrer', data={
            'mois': '6', 'annee': '2026',
            'user_ids': [str(salarie_id), str(responsable_id)],
            f'transport_{salarie_id}': '50',
        }, follow_redirects=True)

        with app.app_context():
            assert self._traite(db, salarie_id) == 0
            assert self._traite(db, responsable_id) == 1

    def test_modification_autre_mois_sans_effet(self, comptable_client, sample_users, app, db):
        """Une modification sur un mois ne touche pas la validation d'un autre mois."""
        salarie_id = sample_users['salarie_id']
        with app.app_context():
            self._valider_prepa(db, salarie_id, mois=5, annee=2026)

        # Modification sur juin : la validation de mai doit rester intacte
        comptable_client.post('/variables_paie/enregistrer', data={
            'mois': '6', 'annee': '2026',
            'user_ids': [str(salarie_id)],
            f'transport_{salarie_id}': '50',
        }, follow_redirects=True)

        with app.app_context():
            assert self._traite(db, salarie_id, mois=5, annee=2026) == 1


class TestClotureCongesSansContrat:
    """La cloture mensuelle remet a zero les soldes des salaries sans contrat
    actif le dernier jour du mois (CP et CC)."""

    def _set_soldes(self, db, user_id, cp_acquis=5.0, cp_a_prendre=10.0,
                    cp_pris=2.0, cc_solde=3.0):
        db.execute(
            'UPDATE users SET cp_acquis=?, cp_a_prendre=?, cp_pris=?, cc_solde=? WHERE id=?',
            (cp_acquis, cp_a_prendre, cp_pris, cc_solde, user_id)
        )
        db.commit()

    def _get_soldes(self, db, user_id):
        return db.execute(
            'SELECT cp_acquis, cp_a_prendre, cp_pris, cc_solde FROM users WHERE id=?',
            (user_id,)
        ).fetchone()

    def _add_contrat(self, db, user_id, date_debut, date_fin=None):
        db.execute(
            '''INSERT INTO contrats (user_id, type_contrat, date_debut, date_fin)
               VALUES (?, 'CDI', ?, ?)''',
            (user_id, date_debut, date_fin)
        )
        db.commit()

    def test_sans_contrat_soldes_remis_a_zero(self, comptable_client, app, db, sample_users):
        """Un salarie sans aucun contrat voit ses soldes CP et CC remis a zero."""
        uid = sample_users['salarie_id']
        with app.app_context():
            self._set_soldes(db, uid)

        resp = comptable_client.post('/variables_paie/cloturer_conges', data={
            'mois': '6', 'annee': '2026',
        }, follow_redirects=True)
        assert resp.status_code == 200

        with app.app_context():
            row = self._get_soldes(db, uid)
            assert row['cp_acquis'] == 0
            assert row['cp_a_prendre'] == 0
            assert row['cp_pris'] == 0
            assert row['cc_solde'] == 0

    def test_contrat_termine_avant_fin_mois_reset(self, comptable_client, app, db, sample_users):
        """Contrat termine avant le dernier jour du mois -> reset a zero."""
        uid = sample_users['salarie_id']
        with app.app_context():
            self._set_soldes(db, uid)
            # Contrat termine le 15 juin, dernier jour du mois = 30 juin
            self._add_contrat(db, uid, '2024-01-01', '2026-06-15')

        resp = comptable_client.post('/variables_paie/cloturer_conges', data={
            'mois': '6', 'annee': '2026',
        }, follow_redirects=True)
        assert resp.status_code == 200

        with app.app_context():
            row = self._get_soldes(db, uid)
            assert row['cp_acquis'] == 0
            assert row['cp_a_prendre'] == 0
            assert row['cp_pris'] == 0
            assert row['cc_solde'] == 0

    def test_contrat_termine_le_dernier_jour_reset(self, comptable_client, app, db, sample_users):
        """Contrat dont la fin est exactement le dernier jour du mois : les conges
        sont soldes en paie, les compteurs doivent repasser a zero."""
        uid = sample_users['salarie_id']
        with app.app_context():
            self._set_soldes(db, uid)
            # Contrat se termine le 30 juin (dernier jour du mois)
            self._add_contrat(db, uid, '2024-01-01', '2026-06-30')

        resp = comptable_client.post('/variables_paie/cloturer_conges', data={
            'mois': '6', 'annee': '2026',
        }, follow_redirects=True)
        assert resp.status_code == 200

        with app.app_context():
            row = self._get_soldes(db, uid)
            assert row['cp_acquis'] == 0
            assert row['cp_a_prendre'] == 0
            assert row['cp_pris'] == 0
            assert row['cc_solde'] == 0

    def test_contrat_actif_acquiert_normalement(self, comptable_client, app, db, sample_users):
        """Un salarie avec contrat actif le dernier jour du mois acquiert ses conges."""
        uid = sample_users['salarie_id']
        with app.app_context():
            self._set_soldes(db, uid, cp_acquis=0, cp_a_prendre=0, cp_pris=0, cc_solde=0)
            self._add_contrat(db, uid, '2024-01-01')  # CDI sans fin

        resp = comptable_client.post('/variables_paie/cloturer_conges', data={
            'mois': '6', 'annee': '2026',
        }, follow_redirects=True)
        assert resp.status_code == 200

        with app.app_context():
            row = self._get_soldes(db, uid)
            assert abs(row['cp_acquis'] - round(25.0 / 12.0, 6)) < 0.001

    def test_prorata_depuis_date_contrat_pas_date_entree(self, comptable_client, app, db, sample_users):
        """Le prorata d'embauche en cours de mois utilise la date de début du
        contrat, et non users.date_entree (qui n'est plus fiable)."""
        uid = sample_users['salarie_id']
        with app.app_context():
            self._set_soldes(db, uid, cp_acquis=0, cp_a_prendre=0, cp_pris=0, cc_solde=0)
            # date_entree volontairement ancienne : doit être ignorée
            db.execute("UPDATE users SET date_entree = '2020-01-01' WHERE id = ?", (uid,))
            db.commit()
            self._add_contrat(db, uid, '2026-06-15')  # contrat démarrant en cours de mois

        resp = comptable_client.post('/variables_paie/cloturer_conges', data={
            'mois': '6', 'annee': '2026',
        }, follow_redirects=True)
        assert resp.status_code == 200

        with app.app_context():
            row = self._get_soldes(db, uid)
        # Juin = 30 jours ; du 15 au 30 = 16 jours -> prorata 16/30 (pas 1)
        attendu = round(25.0 / 12.0 * (16 / 30), 6)
        assert abs(row['cp_acquis'] - attendu) < 0.001

    def test_deux_salaries_un_avec_un_sans_contrat(self, comptable_client, app, db, sample_users):
        """Salarie avec contrat actif acquiert, salarie sans contrat est remis a zero."""
        uid_avec = sample_users['salarie_id']
        uid_sans = sample_users['responsable_id']
        with app.app_context():
            self._set_soldes(db, uid_avec, cp_acquis=0, cp_a_prendre=0, cp_pris=0, cc_solde=0)
            self._set_soldes(db, uid_sans, cp_acquis=5.0, cp_a_prendre=10.0,
                             cp_pris=2.0, cc_solde=3.0)
            self._add_contrat(db, uid_avec, '2024-01-01')  # contrat actif
            # uid_sans n'a pas de contrat

        resp = comptable_client.post('/variables_paie/cloturer_conges', data={
            'mois': '6', 'annee': '2026',
        }, follow_redirects=True)
        assert resp.status_code == 200

        with app.app_context():
            row_avec = self._get_soldes(db, uid_avec)
            assert row_avec['cp_acquis'] > 0

            row_sans = self._get_soldes(db, uid_sans)
            assert row_sans['cp_acquis'] == 0
            assert row_sans['cp_a_prendre'] == 0
            assert row_sans['cp_pris'] == 0
            assert row_sans['cc_solde'] == 0

    def test_salarie_inactif_sans_contrat_reset(self, comptable_client, app, db, sample_users):
        """Un salarie desactive (actif=0) avant la cloture voit aussi ses soldes
        remis a zero s'il n'a pas de contrat actif apres le dernier jour du mois."""
        uid = sample_users['salarie_id']
        with app.app_context():
            self._set_soldes(db, uid, cp_acquis=5.0, cp_a_prendre=10.0,
                             cp_pris=2.0, cc_solde=3.0)
            # Desactiver le salarie avant la cloture
            db.execute('UPDATE users SET actif = 0 WHERE id = ?', (uid,))
            db.commit()

        resp = comptable_client.post('/variables_paie/cloturer_conges', data={
            'mois': '6', 'annee': '2026',
        }, follow_redirects=True)
        assert resp.status_code == 200

        with app.app_context():
            row = self._get_soldes(db, uid)
            assert row['cp_acquis'] == 0
            assert row['cp_a_prendre'] == 0
            assert row['cp_pris'] == 0
            assert row['cc_solde'] == 0

    def test_salarie_inactif_avec_contrat_futur_non_reset(self, comptable_client, app, db, sample_users):
        """Un salarie inactif dont le contrat se prolonge au-dela du mois
        n'est pas remis a zero (cas theorique d'un contrat suspendu)."""
        uid = sample_users['salarie_id']
        with app.app_context():
            self._set_soldes(db, uid, cp_acquis=5.0, cp_a_prendre=10.0,
                             cp_pris=0, cc_solde=3.0)
            # Contrat toujours actif au-dela du dernier jour du mois
            self._add_contrat(db, uid, '2024-01-01', '2026-07-31')
            db.execute('UPDATE users SET actif = 0 WHERE id = ?', (uid,))
            db.commit()

        resp = comptable_client.post('/variables_paie/cloturer_conges', data={
            'mois': '6', 'annee': '2026',
        }, follow_redirects=True)
        assert resp.status_code == 200

        with app.app_context():
            row = self._get_soldes(db, uid)
            # Les soldes ne doivent pas avoir ete remis a zero
            assert row['cp_acquis'] == 5.0
            assert row['cp_a_prendre'] == 10.0
            assert row['cc_solde'] == 3.0

    def test_message_flash_mentionne_resets(self, comptable_client, app, db, sample_users):
        """Le message flash indique le nombre de soldes remis a zero."""
        uid = sample_users['salarie_id']
        with app.app_context():
            self._set_soldes(db, uid)
            # Pas de contrat : le salarie sera remis a zero

        resp = comptable_client.post('/variables_paie/cloturer_conges', data={
            'mois': '6', 'annee': '2026',
        }, follow_redirects=True)
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'remis a zero' in html or 'fin de contrat' in html
