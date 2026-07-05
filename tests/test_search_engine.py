"""
Tests du moteur de la barre de recherche intelligente (search_engine.py) et de
l'endpoint /api/search.
"""
from search_engine import analyser_recherche


def _seed(db):
    db.execute("INSERT INTO secteurs (nom, synonymes) VALUES ('Babilhome', 'bab, babil')")
    db.execute("INSERT INTO fournisseurs (nom, code_comptable) VALUES ('EDF', 'EDF')")
    db.execute("INSERT INTO comptabilite_actions (nom) VALUES ('CLAS')")
    # Deux « Marie » supplémentaires (sample_users en crée déjà une) → désambiguïsation.
    db.execute("INSERT INTO users (nom, prenom, login, password, profil, actif) VALUES ('Lopez', 'Marie', 'ml', 'x', 'responsable', 1)")
    db.execute("INSERT INTO users (nom, prenom, login, password, profil, actif) VALUES ('Martin', 'Marie', 'mm', 'x', 'responsable', 1)")
    # « Fatou » : prénom unique (pas dans sample_users) pour les cas mono-résultat.
    db.execute("INSERT INTO users (nom, prenom, login, password, profil, actif) VALUES ('Bernard', 'Fatou', 'bf', 'x', 'responsable', 1)")
    db.execute("INSERT INTO factures (numero_facture, date_facture, montant_ttc) VALUES ('225678', '2026-03-01', 100)")
    db.execute("INSERT INTO subventions (nom, groupe, annee_action) VALUES ('CLAS Familles', 'en_cours', '2026')")
    db.commit()


def _analyse(app, db, q, profil='directeur'):
    from utils import aujourd_hui
    with app.test_request_context():
        return analyser_recherche(db, q, profil, aujourd_hui())


def _annee():
    from utils import aujourd_hui
    return aujourd_hui().year


class TestMoteurFinance:
    def test_facture_par_numero(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, 'facture 225678')
        assert v['type'] == 'redirect'
        assert '/factures/' in v['url'] and '/detail' in v['url']

    def test_facture_numero_inconnu(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, 'facture 999999')
        assert v['type'] == 'none'

    def test_factures_fournisseur(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, 'factures edf')
        assert v['type'] == 'redirect' and '/fournisseurs/' in v['url']

    def test_budget_action_annee_passee_realise(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, 'budget clas 2020')
        assert v['type'] == 'redirect'
        assert '/bilan-secteurs' in v['url'] and 'action_id=' in v['url'] and 'annee=2020' in v['url']

    def test_budget_action_annee_future_previsionnel(self, app, db, sample_users):
        n = _annee()
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, f'budget clas {n + 1}')
        assert v['type'] == 'redirect'
        assert '/bilan-action' in v['url'] and f'annee={n + 1}' in v['url'] and 'onglet=previsionnel' in v['url']

    def test_budget_secteur_toujours_bilan_secteurs(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, 'budget babilhome 2020')
        assert v['type'] == 'redirect' and '/bilan-secteurs' in v['url'] and 'secteur_id=' in v['url']

    def test_tresorerie_mois(self, app, db, sample_users):
        n = _annee()
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, 'trésorerie avril')
        assert v['type'] == 'redirect' and '/tresorerie' in v['url'] and 'mois=4' in v['url']

    def test_bilan_annee(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, 'bilan 2025')
        assert v['type'] == 'redirect' and '/compte-resultat' in v['url'] and 'vue=bilan' in v['url'] and 'annee=2025' in v['url']

    def test_cr_annee(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, 'CR 2024')
        assert v['type'] == 'redirect' and 'vue=cr' in v['url'] and 'annee=2024' in v['url']

    def test_subventions_annee(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, 'liste subventions 2026')
        assert v['type'] == 'redirect' and '/subventions' in v['url'] and 'annee=2026' in v['url']

    def test_indicateurs_et_plan_comptable(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        assert '/indicateurs-financiers' in _analyse(app, db, 'indicateurs')['url']
        assert '/plan-comptable-general' in _analyse(app, db, 'liste compte')['url']
        assert '/plan-comptable-general' in _analyse(app, db, 'plan comptable')['url']


class TestMoteurRH:
    def test_absence_salarie_unique(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, 'absence Fatou')
        assert v['type'] == 'redirect' and '/absences' in v['url'] and 'search_user_id=' in v['url']

    def test_absence_plusieurs_marie_propose_choix(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, 'absence Marie')
        assert v['type'] == 'choices' and len(v['options']) >= 2
        assert all('search_user_id=' in o['url'] for o in v['options'])

    def test_heures_salarie(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, 'heures Fatou')
        assert v['type'] == 'redirect' and '/vue_mensuelle' in v['url'] and 'user_id=' in v['url']

    def test_salarie_et_contrat_ancre(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        assert '/infos_salaries' in _analyse(app, db, 'salarié Fatou')['url']
        v = _analyse(app, db, 'contrat Fatou')
        assert v['type'] == 'redirect' and '/infos_salaries' in v['url'] and v['url'].endswith('#contrats')

    def test_pesee_salarie_va_a_la_fiche(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, 'pesée Fatou')
        assert v['type'] == 'redirect' and '/infos_salaries' in v['url']

    def test_pesee_seul_va_a_postes_alisfa(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, 'pesée')
        assert v['type'] == 'redirect' and '/postes_alisfa' in v['url']

    def test_contrats_du_mois(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, 'contrats avril')
        assert v['type'] == 'redirect' and '/contrats' in v['url'] and 'mois=4' in v['url']

    def test_cdd_se_terminant(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, 'CDD se terminant en juillet')
        assert v['type'] == 'redirect' and '/contrats' in v['url'] and 'mois=7' in v['url']
        assert 'filtre=echeance' in v['url'] and 'type=CDD' in v['url']


class TestMoteurEntitesEtPeriodes:
    def test_mot_seul_fournisseur(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, 'EDF')
        assert v['type'] == 'redirect' and '/fournisseurs/' in v['url']

    def test_mot_seul_secteur(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, 'Babilhome')
        assert v['type'] == 'redirect' and '/bilan-secteurs' in v['url'] and 'secteur_id=' in v['url']

    def test_synonyme_secteur(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, 'bab')
        assert v['type'] == 'redirect' and 'secteur_id=' in v['url']

    def test_periode_mois_dernier(self, app, db, sample_users):
        from utils import aujourd_hui
        n = aujourd_hui()
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, 'trésorerie mois dernier')
        mois_attendu = n.month - 1 or 12
        assert f'mois={mois_attendu}' in v['url']

    def test_aide_et_inconnu(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        assert _analyse(app, db, 'aide')['type'] == 'none'
        assert _analyse(app, db, '')['type'] == 'none'
        assert _analyse(app, db, 'zzztotalementinconnu')['type'] == 'none'


class TestApiSearch:
    def test_directeur_ok(self, app, db, admin_client, sample_users):
        with app.app_context():
            _seed(db)
        r = admin_client.post('/api/search', json={'query': 'EDF'})
        assert r.status_code == 200 and r.get_json()['type'] == 'redirect'

    def test_salarie_refuse(self, app, auth_client, sample_users):
        assert auth_client.post('/api/search', json={'query': 'EDF'}).status_code == 403

    def test_responsable_refuse(self, app, resp_client, sample_users):
        assert resp_client.post('/api/search', json={'query': 'EDF'}).status_code == 403

    def test_barre_presente_sur_dashboard_direction(self, app, admin_client, sample_users):
        html = admin_client.get('/dashboard_direction').get_data(as_text=True)
        assert 'dsSearchInput' in html and '/api/search' in html


class TestSynonymesSecteurs:
    def test_synonyme_ajoute_via_gestion_secteurs_est_reconnu(self, app, db, admin_client, sample_users):
        admin_client.post('/gestion_secteurs', data={
            'action': 'ajouter', 'nom': 'Emploi Formation',
            'synonymes': 'ef, formation', 'type_secteur': ''})
        with app.app_context():
            row = db.execute("SELECT synonymes FROM secteurs WHERE nom = 'Emploi Formation'").fetchone()
        assert row is not None and row['synonymes'] == 'ef, formation'
        # Le moteur reconnaît le secteur par son synonyme.
        v = _analyse(app, db, 'ef')
        assert v['type'] == 'redirect' and 'secteur_id=' in v['url']
