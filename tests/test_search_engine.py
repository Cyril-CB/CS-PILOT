"""
Tests du moteur de la barre de recherche intelligente (search_engine.py) et de
l'endpoint /api/search.
"""
from search_engine import analyser_recherche


def _seed(db):
    db.execute("INSERT INTO secteurs (nom, synonymes) VALUES ('Babilhome', 'bab, babil')")
    db.execute("INSERT INTO fournisseurs (nom, code_comptable) VALUES ('EDF', 'EDF')")
    db.execute("INSERT INTO comptabilite_actions (nom) VALUES ('CLAS')")
    db.execute("INSERT INTO comptabilite_actions (nom) VALUES ('Fracture numerique')")
    db.execute("INSERT INTO users (nom, prenom, login, password, profil, actif) VALUES ('Borand', 'Cyril', 'cb', 'x', 'directeur', 1)")
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

    def test_budget_action_construction_bilan_action(self, app, db, sample_users):
        # « budget <action> » → bilan-action (Budget action) ; onglet réalisé pour
        # une année passée récente (dans la fenêtre présélectionnable).
        n = _annee()
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, f'budget clas {n + 1}')
        assert '/bilan-action' in v['url'] and 'onglet=previsionnel' in v['url']
        v2 = _analyse(app, db, f'budget clas {n - 1}')
        assert '/bilan-action' in v2['url'] and 'onglet=realise' in v2['url']

    def test_budget_action_annee_ancienne_va_a_bilan_secteurs(self, app, db, sample_users):
        # Année réalisée hors fenêtre de « Budget action » (> 4 ans) : on renvoie la
        # consultation du clôturé vers bilan-secteurs (qui accepte toute année),
        # plutôt que vers bilan-action qui ignorerait l'année et retomberait sur
        # l'année courante.
        n = _annee()
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, f'budget clas {n - 6}')
        assert '/bilan-secteurs' in v['url'] and 'action_id=' in v['url']
        assert f'annee={n - 6}' in v['url']
        assert '/bilan-action' not in v['url']

    def test_bilan_secteur_va_a_bilan_secteurs(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, 'bilan babilhome 2025')
        assert '/bilan-secteurs' in v['url'] and 'secteur_id=' in v['url'] and 'annee=2025' in v['url']

    def test_bilan_action_va_a_bilan_secteurs(self, app, db, sample_users):
        # « bilan <action> » = consultation → bilan-secteurs (avec action_id).
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, 'bilan CLAS 2025')
        assert '/bilan-secteurs' in v['url'] and 'action_id=' in v['url']

    def test_bilan_seul_va_a_compte_resultat(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, 'bilan 2025')
        assert '/compte-resultat' in v['url'] and 'vue=bilan' in v['url']

    def test_budget_secteur_courant_va_a_previsionnel(self, app, db, sample_users):
        n = _annee()
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, f'budget babilhome {n}')
        assert '/budget-previsionnel' in v['url'] and 'secteur_id=' in v['url']

    def test_budget_secteur_passe_va_a_bilan_secteurs(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, 'budget babilhome 2020')
        assert '/bilan-secteurs' in v['url'] and 'secteur_id=' in v['url']

    def test_prev_et_budget_general_va_a_previsionnel(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        assert '/budget-previsionnel' in _analyse(app, db, 'prev 2026')['url']
        assert '/budget-previsionnel' in _analyse(app, db, 'budget 2026')['url']
        v = _analyse(app, db, 'actualisé babilhome 2026')
        assert '/budget-previsionnel' in v['url'] and 'secteur_id=' in v['url']

    def test_bp_et_bpa_synonymes_previsionnel(self, app, db, sample_users):
        # « BP » (budget prévisionnel) et « BPA » (budget prévisionnel actualisé)
        # sont des synonymes de prévisionnel.
        n = _annee()
        with app.app_context():
            _seed(db)
        assert '/budget-previsionnel' in _analyse(app, db, f'BP {n}')['url']
        assert '/budget-previsionnel' in _analyse(app, db, f'BPA {n}')['url']
        v = _analyse(app, db, f'BP babilhome {n}')
        assert '/budget-previsionnel' in v['url'] and 'secteur_id=' in v['url']

    def test_action_seule_propose_consultation_et_construction(self, app, db, sample_users):
        # Un nom d'action seul (sans mot-clé) → deux alternatives (doute).
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, 'fracture numerique')
        assert v['type'] == 'choices' and len(v['options']) == 2
        urls = ' '.join(o['url'] for o in v['options'])
        assert '/bilan-action' in urls and '/bilan-secteurs' in urls

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

    def test_absence_synonymes_maladie_arret(self, app, db, sample_users):
        # « maladie » / « arrêt(s) » sont des synonymes d'« absence » : ils doivent
        # déclencher la même intention (ex. « maladie Marie », « arrêts Marie »).
        with app.app_context():
            _seed(db)
        for q in ('maladie Fatou', 'arrêts Fatou', 'arret Fatou', 'malade Fatou'):
            v = _analyse(app, db, q)
            assert v['type'] == 'redirect' and '/absences' in v['url'] and 'search_user_id=' in v['url'], q
        # Comme « absence Marie », un synonyme + prénom ambigu propose un choix.
        v = _analyse(app, db, 'maladie Marie')
        assert v['type'] == 'choices' and all('search_user_id=' in o['url'] for o in v['options'])

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

    def test_cdi_en_cours_filtre_type_cdi(self, app, db, sample_users):
        # « cdi » doit ajouter type=CDI (au même titre que « cdd »).
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, 'CDI en cours')
        assert v['type'] == 'redirect' and '/contrats' in v['url'] and 'type=CDI' in v['url']


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

    def test_mot_seul_nom_de_subvention(self, app, db, sample_users):
        # Un nom de subvention seul doit être résolu (pas « Rien trouvé »).
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, 'CLAS Familles')
        assert v['type'] == 'redirect' and '/subventions' in v['url']

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


class TestNouvellesIntentions:
    def test_planning_salarie(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        for q in ('planning Cyril', 'horaire Cyril'):
            v = _analyse(app, db, q)
            assert v['type'] == 'redirect' and '/planning_theorique' in v['url'] and 'user_id=' in v['url']

    def test_rh(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        for q in ('RH', 'infos RH', 'information RH'):
            assert '/rh/statistiques' in _analyse(app, db, q)['url']

    def test_analyse_pesee(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        for q in ('analyse poste', 'analyse pesée', 'calcul pesée', 'estimation pesée'):
            assert '/pesee_alisfa' in _analyse(app, db, q)['url']

    def test_salles(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        for q in ('salles', 'salle', 'réservation'):
            assert '/salles' in _analyse(app, db, q)['url']


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


class TestJournalRecherches:
    def test_recherche_est_journalisee_avec_resultat(self, app, db, admin_client, sample_users):
        # Chaque recherche est tracée avec le fait qu'elle ait abouti ou non.
        with app.app_context():
            _seed(db)
        admin_client.post('/api/search', json={'query': 'EDF'})
        admin_client.post('/api/search', json={'query': 'zzztotalementinconnu'})
        with app.app_context():
            rows = db.execute(
                "SELECT terme, a_resultat FROM recherche_log ORDER BY id").fetchall()
        termes = {r['terme']: r['a_resultat'] for r in rows}
        assert termes.get('EDF') == 1
        assert termes.get('zzztotalementinconnu') == 0

    def test_recherche_vide_non_journalisee(self, app, db, admin_client, sample_users):
        with app.app_context():
            _seed(db)
        admin_client.post('/api/search', json={'query': '   '})
        with app.app_context():
            nb = db.execute("SELECT COUNT(*) FROM recherche_log").fetchone()[0]
        assert nb == 0

    def test_onglet_barre_intelligente_liste_les_recherches(self, app, db, admin_client, sample_users):
        with app.app_context():
            _seed(db)
        admin_client.post('/api/search', json={'query': 'EDF'})
        html = admin_client.get('/securite/journal-recherches').get_data(as_text=True)
        assert 'Barre intelligente' in html
        assert 'EDF' in html

    def test_noms_salaries_anonymises_dans_le_terme(self, app, db, admin_client, sample_users):
        # Le terme journalisé ne doit pas révéler le nom du salarié recherché.
        with app.app_context():
            _seed(db)
        admin_client.post('/api/search', json={'query': 'absence Fatou'})
        with app.app_context():
            row = db.execute(
                "SELECT terme FROM recherche_log ORDER BY id DESC LIMIT 1").fetchone()
        assert 'Fatou' not in row['terme']
        assert 'salarié' in row['terme']
        assert 'absence' in row['terme']  # l'intention reste visible

    def test_nom_dans_libelle_destination_anonymise(self, app, db, admin_client, sample_users):
        # Même la destination (« Prénom Nom » d'une fiche salarié) est anonymisée.
        with app.app_context():
            _seed(db)
        admin_client.post('/api/search', json={'query': 'salarié Fatou'})
        with app.app_context():
            row = db.execute(
                "SELECT terme, libelle FROM recherche_log ORDER BY id DESC LIMIT 1").fetchone()
        assert 'Fatou' not in row['terme']
        assert 'Fatou' not in (row['libelle'] or '') and 'Bernard' not in (row['libelle'] or '')

    def test_journal_recherches_refuse_salarie(self, app, auth_client, sample_users):
        r = auth_client.get('/securite/journal-recherches', follow_redirects=False)
        assert r.status_code in (301, 302)


class TestDemandeConge:
    def test_variantes_renvoient_vers_la_demande(self, app, db, sample_users):
        with app.app_context():
            _seed(db)
        for q in ('demande de congés', 'demande congé', 'demande congés',
                  'poser congé', 'poser des congés', 'prendre congé',
                  'prendre un congé', 'demander un congé', 'faire une demande de congé'):
            v = _analyse(app, db, q)
            assert v['type'] == 'redirect' and '/demande_conge' in v['url'], q

    def test_accessible_au_comptable(self, app, db, sample_users):
        # La barre est réservée direction + comptable : les deux y ont droit.
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, 'demande de congés', profil='comptable')
        assert v['type'] == 'redirect' and '/demande_conge' in v['url']

    def test_absence_non_confondue_avec_demande(self, app, db, sample_users):
        # Sans verbe, « absence/congé <nom> » reste l'intention « absences ».
        with app.app_context():
            _seed(db)
        v = _analyse(app, db, 'absence Fatou')
        assert '/absences' in v['url'] and '/demande_conge' not in v['url']
