"""
Panneau « Actions à faire » des tableaux de bord (dashboard_actions.py).
"""
from datetime import date, timedelta

from dashboard_actions import construire_actions


def _demande_recup(db, user_id, statut, date_demande='2026-06-01'):
    db.execute(
        "INSERT INTO demandes_recup (user_id, date_debut, date_fin, nb_jours, nb_heures, statut, date_demande) "
        "VALUES (?, '2026-06-10', '2026-06-10', 1, 7, ?, ?)",
        (user_id, statut, date_demande)
    )


def _subvention_avec_etape(db, nom, echeance, assignee_1_id=None,
                           groupe='en_cours', se_assignee_id=None):
    cur = db.execute(
        "INSERT INTO subventions (nom, groupe, annee_action, assignee_1_id) VALUES (?, ?, '2026', ?)",
        (nom, groupe, assignee_1_id)
    )
    sid = cur.lastrowid
    db.execute(
        "INSERT INTO subventions_sous_elements (subvention_id, nom, assignee_id, statut, date_echeance, ordre) "
        "VALUES (?, 'Préparer le dossier', ?, 'en_cours', ?, 0)",
        (sid, se_assignee_id, echeance)
    )
    return sid


def test_direction_voit_validations_et_subventions(app, db, sample_users):
    """La direction agrège toutes les demandes en attente et toutes les
    échéances de subventions."""
    _demande_recup(db, sample_users['salarie_id'], 'en_attente_direction')
    _subvention_avec_etape(db, 'CLAS', (date.today() + timedelta(days=3)).isoformat())
    db.commit()

    with app.test_request_context():
        actions = construire_actions(db, 'directeur', sample_users['directeur_id'])

    categories = {a['categorie'] for a in actions}
    assert 'validation' in categories
    assert 'subvention' in categories
    titres = ' | '.join(a['titre'] for a in actions)
    assert 'CLAS' in titres and 'Préparer le dossier' in titres
    # Chaque item a un lien et un libellé d'action.
    assert all(a['lien'] and a['lien_texte'] for a in actions)


def test_echeance_passee_est_en_retard(app, db, sample_users):
    """Une étape de subvention dont l'échéance est passée est marquée 'retard'."""
    _subvention_avec_etape(db, 'Numerique', (date.today() - timedelta(days=2)).isoformat())
    db.commit()
    with app.test_request_context():
        actions = construire_actions(db, 'comptable', sample_users['comptable_id'])
    subv = [a for a in actions if a['categorie'] == 'subvention']
    assert subv and subv[0]['urgence'] == 'retard'


def test_responsable_scope_secteur_et_assignation(app, db, sample_users):
    """Le responsable ne voit que les demandes de son secteur et les subventions
    dont il est assigné."""
    resp_id = sample_users['responsable_id']
    # Demande d'un salarié de SON secteur, en attente responsable → visible.
    _demande_recup(db, sample_users['salarie_id'], 'en_attente_responsable')
    # Subvention NON assignée au responsable → non visible.
    _subvention_avec_etape(db, 'Autre', (date.today() + timedelta(days=3)).isoformat())
    # Subvention assignée au responsable → visible.
    _subvention_avec_etape(db, 'Amien', (date.today() + timedelta(days=3)).isoformat(),
                           assignee_1_id=resp_id)
    db.commit()

    with app.test_request_context():
        actions = construire_actions(db, 'responsable', resp_id, sample_users['secteur_id'])

    assert any(a['categorie'] == 'validation' for a in actions)
    titres_subv = [a['titre'] for a in actions if a['categorie'] == 'subvention']
    assert any('Amien' in t for t in titres_subv)
    assert not any('Autre' in t for t in titres_subv)


def test_etape_faite_non_listee(app, db, sample_users):
    """Une étape déjà 'fait' n'apparaît pas dans les actions."""
    cur = db.execute("INSERT INTO subventions (nom, groupe, annee_action) VALUES ('Finie','en_cours','2026')")
    db.execute(
        "INSERT INTO subventions_sous_elements (subvention_id, nom, statut, date_echeance, ordre) "
        "VALUES (?, 'Bilan', 'fait', ?, 0)",
        (cur.lastrowid, (date.today() + timedelta(days=3)).isoformat())
    )
    db.commit()
    with app.test_request_context():
        actions = construire_actions(db, 'directeur', sample_users['directeur_id'])
    assert not any(a['categorie'] == 'subvention' for a in actions)


def test_responsable_voit_etape_de_sous_element_assigne(app, db, sample_users):
    """Un responsable attribué à un sous-élément (mais pas à la subvention parente)
    voit l'étape dans son panneau, en cohérence avec la notification e-mail."""
    resp_id = sample_users['responsable_id']
    _subvention_avec_etape(db, 'Portage', (date.today() + timedelta(days=3)).isoformat(),
                           assignee_1_id=None, se_assignee_id=resp_id)
    db.commit()
    with app.test_request_context():
        actions = construire_actions(db, 'responsable', resp_id, sample_users['secteur_id'])
    titres = [a['titre'] for a in actions if a['categorie'] == 'subvention']
    assert any('Portage' in t for t in titres)


def test_subvention_acceptee_garde_ses_echeances(app, db, sample_users):
    """Une subvention acceptée conserve ses échéances actionnables (bilans)."""
    _subvention_avec_etape(db, 'Acceptee', (date.today() + timedelta(days=3)).isoformat(),
                           groupe='acceptee')
    db.commit()
    with app.test_request_context():
        actions = construire_actions(db, 'directeur', sample_users['directeur_id'])
    assert any('Acceptee' in a['titre'] for a in actions if a['categorie'] == 'subvention')


def test_subvention_refusee_exclue_du_panneau(app, db, sample_users):
    """Une subvention refusée n'apparaît pas, même avec une échéance passée."""
    _subvention_avec_etape(db, 'Refusee', (date.today() - timedelta(days=1)).isoformat(),
                           groupe='refusee')
    db.commit()
    with app.test_request_context():
        actions = construire_actions(db, 'directeur', sample_users['directeur_id'])
    assert not any('Refusee' in a['titre'] for a in actions if a['categorie'] == 'subvention')


def test_lien_action_cible_l_annee_de_la_subvention(app, db, sample_users):
    """Le lien d'une action pointe vers l'année de la subvention (si dans la plage
    du filtre N-3..N+2) pour que la ligne reste visible sur la page filtrée ;
    sinon vers « toutes » (année absente ou hors plage)."""
    from utils import aujourd_hui
    n = aujourd_hui().year
    ech = (date.today() + timedelta(days=3)).isoformat()

    def _sub(nom, annee_action):
        cur = db.execute(
            "INSERT INTO subventions (nom, groupe, annee_action) VALUES (?, 'en_cours', ?)",
            (nom, annee_action)
        )
        db.execute(
            "INSERT INTO subventions_sous_elements (subvention_id, nom, statut, date_echeance, ordre) "
            "VALUES (?, 'Bilan', 'en_cours', ?, 0)",
            (cur.lastrowid, ech)
        )

    _sub('AnCourante', str(n))       # dans la plage → année ciblée
    _sub('SansAnnee', None)          # sans année → toutes
    _sub('Vieille', str(n - 10))     # hors plage → toutes
    db.commit()

    with app.test_request_context():
        actions = construire_actions(db, 'directeur', sample_users['directeur_id'])

    def lien_de(nom):
        for a in actions:
            if a['categorie'] == 'subvention' and a['titre'].startswith(nom):
                return a['lien']
        return None

    assert f'annee={n}' in lien_de('AnCourante')
    assert 'annee=toutes' in lien_de('SansAnnee')
    assert 'annee=toutes' in lien_de('Vieille')


# ── Le fil nomme au lieu de compter ─────────────────────────────────────────

def _valider_tout_le_monde(db, mois, annee, sauf=()):
    """Verrouille les fiches du mois pour tous, sauf les IDs indiqués."""
    ids = [r['id'] for r in db.execute(
        "SELECT id FROM users WHERE actif = 1 "
        "AND profil NOT IN ('directeur', 'prestataire')"
    ).fetchall() if r['id'] not in sauf]
    for uid in ids:
        db.execute(
            "INSERT OR REPLACE INTO validations (user_id, mois, annee, bloque) "
            "VALUES (?, ?, ?, 1)", (uid, mois, annee)
        )
    db.commit()


def _saisir_journee(db, user_id, jour, debut='08:30', fin='18:00'):
    """Une journée saisie, volontairement longue pour créer des heures supp."""
    db.execute(
        """INSERT OR REPLACE INTO heures_reelles
           (user_id, date, heure_debut_matin, heure_fin_matin,
            heure_debut_aprem, heure_fin_aprem, type_saisie, declaration_conforme)
           VALUES (?, ?, ?, '12:00', '13:30', ?, 'heures_modifiees', 0)""",
        (user_id, jour, debut, fin)
    )
    db.commit()


def _mois_precedent(today):
    return (today.month - 1 or 12,
            today.year if today.month > 1 else today.year - 1)


class TestFichesNommees:
    """« 30 fiches à valider » n'est pas actionnable : le fil en nomme deux.

    Le classement suit le solde d'heures du mois — celui qui a accumulé des
    heures supplémentaires passe devant celui qui est à l'équilibre.
    """

    def test_deux_fiches_nommees_et_le_reste_en_une_ligne(self, app, db, sample_users):
        from utils import aujourd_hui
        mois, annee = _mois_precedent(aujourd_hui())

        with app.app_context():
            titres = [a['titre'] for a in construire_actions(
                db, 'directeur', sample_users['directeur_id'])]

        nommees = [t for t in titres if t.startswith('Fiche de')]
        assert len(nommees) == 2, titres
        # sample_users crée trois salariés non validés : un doit rester en file.
        assert any(t.startswith('et 1 autre') for t in titres), titres

    def test_le_solde_le_plus_lourd_passe_devant(self, app, db, sample_users,
                                                 sample_planning):
        """Le salarié à +heures supp passe devant celui qui n'a rien saisi."""
        from utils import aujourd_hui
        mois, annee = _mois_precedent(aujourd_hui())
        salarie = sample_users['salarie_id']

        with app.app_context():
            # Ne laisser que deux fiches ouvertes, dont une chargée d'heures.
            _valider_tout_le_monde(db, mois, annee,
                                   sauf=(salarie, sample_users['responsable_id']))
            jour = date(annee, mois, 1)
            while jour.weekday() >= 5:
                jour += timedelta(days=1)
            _saisir_journee(db, salarie, jour.isoformat())

            actions = construire_actions(db, 'directeur', sample_users['directeur_id'])

        fiches = [a for a in actions if a['titre'].startswith('Fiche de')]
        assert len(fiches) == 2
        assert 'Martin' in fiches[0]['titre'], [f['titre'] for f in fiches]
        assert '+' in fiches[0]['detail'] and 'h sur le mois' in fiches[0]['detail']

    def test_aucune_carte_quand_tout_est_valide(self, app, db, sample_users):
        from utils import aujourd_hui
        mois, annee = _mois_precedent(aujourd_hui())

        with app.app_context():
            _valider_tout_le_monde(db, mois, annee)
            actions = construire_actions(db, 'directeur', sample_users['directeur_id'])

        assert not [a for a in actions if a['titre'].startswith('Fiche de')]
        assert not [a for a in actions if a['id'].startswith('reste-fiches')]

    def test_un_responsable_ne_voit_que_son_equipe(self, app, db, sample_users):
        with app.app_context():
            actions = construire_actions(db, 'responsable',
                                         sample_users['responsable_id'],
                                         secteur_id=sample_users['secteur_id'])

        titres = [a['titre'] for a in actions if a['titre'].startswith('Fiche de')]
        # Le comptable est hors secteur : il ne doit pas apparaître.
        assert titres and not any('Durand' in t for t in titres), titres


class TestCartesDuFil:
    """Chaque famille se tait quand elle n'a rien à dire."""

    def test_budget_depasse_remonte_dans_le_fil(self, app, db, sample_users):
        from utils import aujourd_hui
        annee = aujourd_hui().year
        with app.app_context():
            cur = db.execute(
                "INSERT INTO budgets (secteur_id, annee, montant_global) VALUES (?, ?, 1000)",
                (sample_users['secteur_id'], annee))
            budget_id = cur.lastrowid
            cur = db.execute(
                "INSERT INTO postes_depense (nom) VALUES ('Fournitures')")
            poste_id = cur.lastrowid
            db.execute("INSERT INTO budget_lignes (budget_id, poste_depense_id, periode, montant) "
                       "VALUES (?, ?, 'annuel', 500)", (budget_id, poste_id))
            db.execute("INSERT INTO budget_reel_lignes (budget_id, poste_depense_id, periode, montant) "
                       "VALUES (?, ?, 'annuel', 800)", (budget_id, poste_id))
            db.commit()

            actions = construire_actions(db, 'directeur', sample_users['directeur_id'])

        budgets = [a for a in actions if a['id'].startswith('budget-')]
        assert len(budgets) == 1
        assert 'Budget dépassé' in budgets[0]['titre']
        assert '300' in budgets[0]['detail']
        assert budgets[0]['urgence'] == 'retard'

    def test_pas_de_carte_budget_sans_depassement(self, app, db, sample_users):
        from utils import aujourd_hui
        annee = aujourd_hui().year
        with app.app_context():
            cur = db.execute(
                "INSERT INTO budgets (secteur_id, annee, montant_global) VALUES (?, ?, 1000)",
                (sample_users['secteur_id'], annee))
            budget_id = cur.lastrowid
            cur = db.execute("INSERT INTO postes_depense (nom) VALUES ('Fournitures')")
            poste_id = cur.lastrowid
            db.execute("INSERT INTO budget_lignes (budget_id, poste_depense_id, periode, montant) "
                       "VALUES (?, ?, 'annuel', 500)", (budget_id, poste_id))
            db.execute("INSERT INTO budget_reel_lignes (budget_id, poste_depense_id, periode, montant) "
                       "VALUES (?, ?, 'annuel', 400)", (budget_id, poste_id))
            db.commit()

            actions = construire_actions(db, 'directeur', sample_users['directeur_id'])

        assert not [a for a in actions if a['id'].startswith('budget-')]

    def test_fournitures_en_attente_classees_par_urgence(self, app, db, sample_users):
        with app.app_context():
            for description, urgence in (('Ramettes A4', 'peut_attendre'),
                                         ('Cartouches encre', 'urgent')):
                db.execute(
                    """INSERT INTO commandes_salaries
                       (user_id, date_demande, description, quantite, urgence, groupe)
                       VALUES (?, '2026-07-01', ?, 1, ?, 'en_cours')""",
                    (sample_users['salarie_id'], description, urgence))
            db.commit()

            actions = construire_actions(db, 'directeur', sample_users['directeur_id'])

        fournitures = [a for a in actions if a['id'].startswith('fourn-')]
        assert len(fournitures) == 2
        assert 'Cartouches' in fournitures[0]['titre']       # urgent d'abord
        assert fournitures[0]['urgence'] == 'urgent'
        assert fournitures[1]['urgence'] == 'normal'          # « peut attendre »

    def test_un_salarie_sans_delegation_ne_voit_pas_les_fournitures(
            self, app, db, sample_users):
        with app.app_context():
            db.execute(
                """INSERT INTO commandes_salaries
                   (user_id, date_demande, description, quantite, urgence, groupe)
                   VALUES (?, '2026-07-01', 'Ramettes', 1, 'urgent', 'en_cours')""",
                (sample_users['salarie_id'],))
            db.commit()

            actions = construire_actions(db, 'salarie', sample_users['salarie_id'])

        assert not [a for a in actions if a['id'].startswith('fourn-')]

    def test_taches_du_jour_renvoient_au_planificateur(self, app, db, sample_users):
        from utils import aujourd_hui
        today = aujourd_hui()
        with app.app_context():
            cur = db.execute(
                "INSERT INTO planif_taches (user_id, titre, statut) VALUES (?, 'Bilan', 'a_faire')",
                (sample_users['directeur_id'],))
            tache_id = cur.lastrowid
            db.execute(
                """INSERT INTO planif_blocs (tache_id, user_id, date, heure_debut,
                                             heure_fin, duree_min, statut)
                   VALUES (?, ?, ?, '09:00', '10:00', 60, 'planifie')""",
                (tache_id, sample_users['directeur_id'], today.isoformat()))
            db.commit()

            actions = construire_actions(db, 'directeur', sample_users['directeur_id'])

        planif = [a for a in actions if a['id'].startswith('planif-')]
        assert len(planif) == 1
        assert '1 tâche prévue' in planif[0]['titre']
        assert '/planificateur' in planif[0]['lien']

    def test_contrat_sans_pdf_pour_le_comptable_seul(self, app, db, sample_users):
        with app.app_context():
            db.execute(
                """INSERT INTO contrats (user_id, type_contrat, date_debut, date_fin)
                   VALUES (?, 'CDI', '2000-01-01', NULL)""",
                (sample_users['salarie_id'],))
            db.commit()

            vus_comptable = construire_actions(db, 'comptable', sample_users['comptable_id'])
            vus_directeur = construire_actions(db, 'directeur', sample_users['directeur_id'])

        assert [a for a in vus_comptable if a['id'].startswith('contratpdf-')]
        assert not [a for a in vus_directeur if a['id'].startswith('contratpdf-')]

    def test_contrat_avec_pdf_ne_remonte_pas(self, app, db, sample_users):
        with app.app_context():
            db.execute(
                """INSERT INTO contrats (user_id, type_contrat, date_debut, date_fin,
                                         fichier_path)
                   VALUES (?, 'CDI', '2000-01-01', NULL, 'contrats/cdi.pdf')""",
                (sample_users['salarie_id'],))
            db.commit()

            actions = construire_actions(db, 'comptable', sample_users['comptable_id'])

        assert not [a for a in actions if a['id'].startswith('contratpdf-')]


class TestRappelPreparationPaie:
    """Le 20, un rappel daté ; avant, rien.

    Le geste attendu se fait hors de l'application — prévenir la comptabilité
    — d'où un bouton déclaratif, et une marque posée au nom de celui qui
    clique : chacun ne répond que de son périmètre.
    """

    def _le(self, jour, mois=7, annee=2026):
        return date(annee, mois, jour)

    def test_rien_avant_le_20(self, app, db, sample_users, monkeypatch):
        import dashboard_actions
        monkeypatch.setattr(dashboard_actions, 'aujourd_hui',
                            lambda: self._le(19))
        with app.app_context():
            actions = construire_actions(db, 'directeur', sample_users['directeur_id'])
        assert not [a for a in actions if a['type'] == 'paie']

    def test_le_rappel_parait_le_20(self, app, db, sample_users, monkeypatch):
        import dashboard_actions
        monkeypatch.setattr(dashboard_actions, 'aujourd_hui',
                            lambda: self._le(20))
        with app.app_context():
            actions = construire_actions(db, 'directeur', sample_users['directeur_id'])

        paie = [a for a in actions if a['type'] == 'paie']
        assert len(paie) == 1
        assert 'Signaler à la comptabilité' in paie[0]['titre']
        # Ce que l'application ne sait pas déduire, elle le rappelle en toutes
        # lettres : ni la mise à pied ni le licenciement ne sont modélisés.
        assert 'mises à pied et licenciements' in paie[0]['detail']

    def test_le_comptable_ne_recoit_pas_le_rappel(self, app, db, sample_users, monkeypatch):
        """Il reçoit le signalement ; il n'a pas à se le faire à lui-même."""
        import dashboard_actions
        monkeypatch.setattr(dashboard_actions, 'aujourd_hui',
                            lambda: self._le(20))
        with app.app_context():
            actions = construire_actions(db, 'comptable', sample_users['comptable_id'])
        assert not [a for a in actions if a['type'] == 'paie']

    def test_les_cdd_sans_fiche_sont_nommes(self, app, db, sample_users, monkeypatch):
        import dashboard_actions
        monkeypatch.setattr(dashboard_actions, 'aujourd_hui',
                            lambda: self._le(20))
        with app.app_context():
            db.execute(
                """INSERT INTO contrats (user_id, type_contrat, date_debut, date_fin)
                   VALUES (?, 'CDD', '2026-07-01', '2026-07-31')""",
                (sample_users['salarie_id'],))
            db.commit()
            actions = construire_actions(db, 'directeur', sample_users['directeur_id'])

        paie = next(a for a in actions if a['type'] == 'paie')
        assert "1 CDD sans aucune fiche d'heures" in paie['detail']

    def test_une_absence_justifiee_ne_compte_pas(self, app, db, sample_users, monkeypatch):
        import dashboard_actions
        monkeypatch.setattr(dashboard_actions, 'aujourd_hui',
                            lambda: self._le(20))
        with app.app_context():
            db.execute(
                """INSERT INTO absences (user_id, motif, date_debut, date_fin,
                                         jours_ouvres, saisi_par, justificatif_path)
                   VALUES (?, 'maladie', '2026-07-06', '2026-07-10', 5, ?, 'abs/arret.pdf')""",
                (sample_users['salarie_id'], sample_users['directeur_id']))
            db.commit()
            actions = construire_actions(db, 'directeur', sample_users['directeur_id'])

        paie = next(a for a in actions if a['type'] == 'paie')
        assert 'sans justificatif' not in paie['detail']

    def test_une_absence_sans_justificatif_est_signalee(self, app, db, sample_users,
                                                        monkeypatch):
        import dashboard_actions
        monkeypatch.setattr(dashboard_actions, 'aujourd_hui',
                            lambda: self._le(20))
        with app.app_context():
            db.execute(
                """INSERT INTO absences (user_id, motif, date_debut, date_fin,
                                         jours_ouvres, saisi_par)
                   VALUES (?, 'maladie', '2026-07-06', '2026-07-10', 5, ?)""",
                (sample_users['salarie_id'], sample_users['directeur_id']))
            db.commit()
            actions = construire_actions(db, 'directeur', sample_users['directeur_id'])

        paie = next(a for a in actions if a['type'] == 'paie')
        assert '1 absence(s) sans justificatif' in paie['detail']

    def test_c_est_fait_n_eteint_que_le_sien(self, app, db, sample_users, monkeypatch):
        """Chacun signale pour son périmètre : un clic ne vaut pas pour tous."""
        import dashboard_actions
        from utils import save_setting
        monkeypatch.setattr(dashboard_actions, 'aujourd_hui',
                            lambda: self._le(20))

        with app.app_context():
            save_setting(dashboard_actions.cle_preparation_paie(
                7, 2026, sample_users['directeur_id']), '1')

            vu_directeur = construire_actions(db, 'directeur', sample_users['directeur_id'])
            vu_responsable = construire_actions(
                db, 'responsable', sample_users['responsable_id'],
                secteur_id=sample_users['secteur_id'])

        assert not [a for a in vu_directeur if a['type'] == 'paie']
        assert [a for a in vu_responsable if a['type'] == 'paie']
