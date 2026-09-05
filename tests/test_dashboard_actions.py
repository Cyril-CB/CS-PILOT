"""
Panneau « Actions à faire » des tableaux de bord (dashboard_actions.py).
"""
from datetime import date, datetime, timedelta, timezone

import pytest

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

        nommees = [t for t in titres if t.startswith('Fiche à valider')]
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

        fiches = [a for a in actions if a['titre'].startswith('Fiche à valider')]
        assert len(fiches) == 2
        assert 'Martin' in fiches[0]['titre'], [f['titre'] for f in fiches]
        assert fiches[0]['detail'] == 'heures supplémentaires sur le mois : +1 h'

    def test_la_carte_annonce_une_validation_pas_une_anomalie(
            self, app, db, sample_users, sample_planning):
        """Le fil signale qu'une fiche attend, il ne qualifie pas les écarts.

        Le solde y figure comme un fait. Les heures supplémentaires se
        récupèrent — elles ne se paient pas, sauf pour un CDD — donc rien n'y
        est « à trancher avant la paie ».
        """
        from utils import aujourd_hui
        mois, annee = _mois_precedent(aujourd_hui())
        salarie = sample_users['salarie_id']

        with app.app_context():
            jour = date(annee, mois, 1)
            while jour.weekday() >= 5:
                jour += timedelta(days=1)
            _saisir_journee(db, salarie, jour.isoformat())
            actions = construire_actions(db, 'directeur', sample_users['directeur_id'])

        fiches = [a for a in actions if a['titre'].startswith('Fiche à valider')]
        assert fiches
        for fiche in fiches:
            assert 'sur le mois' in fiche['detail'] or 'équilibre' in fiche['detail']
            for verdict in ('trancher', 'paie', 'expliquer', 'anomalie', 'écart à'):
                assert verdict not in fiche['detail'], fiche['detail']

    def test_aucune_carte_quand_tout_est_valide(self, app, db, sample_users):
        from utils import aujourd_hui
        mois, annee = _mois_precedent(aujourd_hui())

        with app.app_context():
            _valider_tout_le_monde(db, mois, annee)
            actions = construire_actions(db, 'directeur', sample_users['directeur_id'])

        assert not [a for a in actions if a['titre'].startswith('Fiche à valider')]
        assert not [a for a in actions if a['id'].startswith('reste-fiches')]

    def test_un_responsable_ne_voit_que_son_equipe(self, app, db, sample_users):
        with app.app_context():
            actions = construire_actions(db, 'responsable',
                                         sample_users['responsable_id'],
                                         secteur_id=sample_users['secteur_id'])

        titres = [a['titre'] for a in actions if a['titre'].startswith('Fiche à valider')]
        # Le comptable est hors secteur : il ne doit pas apparaître.
        assert titres and not any('Durand' in t for t in titres), titres


def _signer(db, user_id, mois, annee, colonne, quand='2026-08-10 09:00:00'):
    """Pose une seule signature sur la fiche, sans la verrouiller."""
    role = colonne.replace('validation_', '')
    db.execute(
        "INSERT OR IGNORE INTO validations (user_id, mois, annee) VALUES (?, ?, ?)",
        (user_id, mois, annee)
    )
    db.execute(
        f"UPDATE validations SET {colonne} = 'Signataire', date_{role} = ? "
        "WHERE user_id = ? AND mois = ? AND annee = ?",
        (quand, user_id, mois, annee)
    )
    from fiches_contenu import calculer_contenu
    from fiches_versions import enregistrer_version
    version_id = enregistrer_version(db, calculer_contenu(db, user_id, mois, annee), 'signature')
    db.execute(f'UPDATE validations SET version_courante_id=?, version_{role}_id=? '
               'WHERE user_id=? AND mois=? AND annee=?',
               (version_id, version_id, user_id, mois, annee))
    db.commit()


def _journaliser_modification(db, user_id, mois, annee, quand):
    """Trace une modification de la fiche, comme le fait la saisie d'heures."""
    db.execute(
        """INSERT INTO historique_modifications
           (user_id_modifie, date_concernee, modifie_par, action, date_modification)
           VALUES (?, ?, ?, 'modification', ?)""",
        (user_id, f'{annee}-{mois:02d}-15', user_id, quand)
    )
    # Une annotation de journée modifie matériellement la fiche sans changer
    # le solde reporté aux autres mois. L'horloge n'est plus l'autorité.
    db.execute("INSERT INTO heures_reelles (user_id, date, commentaire, declaration_conforme) "
               "VALUES (?, ?, ?, 1) ON CONFLICT(user_id, date) DO UPDATE SET commentaire=excluded.commentaire",
               (user_id, f'{annee}-{mois:02d}-15', 'Modification ' + quand))
    db.commit()


class TestUneSignatureSortLaFicheDuFil:
    """Le fil ne redemande pas ce que son lecteur a déjà signé.

    Le verrouillage attend les deux signatures ; s'y fier laissait chacun
    devant une décision déjà prise — la direction retrouvait indéfiniment les
    fiches qu'elle avait validées, faute que le responsable ait fait sa part.
    """

    def test_la_direction_ne_revoit_pas_ce_qu_elle_a_signe(self, app, db, sample_users):
        from utils import aujourd_hui
        mois, annee = _mois_precedent(aujourd_hui())
        salarie = sample_users['salarie_id']

        with app.app_context():
            _valider_tout_le_monde(db, mois, annee, sauf=(salarie,))
            avant = [a['titre'] for a in construire_actions(
                db, 'directeur', sample_users['directeur_id'])
                if a['titre'].startswith('Fiche à valider')]

            _signer(db, salarie, mois, annee, 'validation_directeur')
            apres = [a['titre'] for a in construire_actions(
                db, 'directeur', sample_users['directeur_id'])
                if a['titre'].startswith('Fiche à valider')]

        assert len(avant) == 1, avant
        assert apres == [], apres

    def test_mais_le_responsable_la_voit_toujours(self, app, db, sample_users):
        """La signature de la direction ne dispense pas le responsable."""
        from utils import aujourd_hui
        mois, annee = _mois_precedent(aujourd_hui())
        salarie = sample_users['salarie_id']

        with app.app_context():
            _valider_tout_le_monde(db, mois, annee, sauf=(salarie,))
            _signer(db, salarie, mois, annee, 'validation_directeur')
            titres = [a['titre'] for a in construire_actions(
                db, 'responsable', sample_users['responsable_id'],
                secteur_id=sample_users['secteur_id'])
                if a['titre'].startswith('Fiche à valider')]

        assert len(titres) == 1, titres

    def test_le_responsable_ne_revoit_pas_ce_qu_il_a_signe(self, app, db, sample_users):
        from utils import aujourd_hui
        mois, annee = _mois_precedent(aujourd_hui())
        salarie = sample_users['salarie_id']

        with app.app_context():
            _valider_tout_le_monde(db, mois, annee, sauf=(salarie,))
            _signer(db, salarie, mois, annee, 'validation_responsable')
            responsable = [a['titre'] for a in construire_actions(
                db, 'responsable', sample_users['responsable_id'],
                secteur_id=sample_users['secteur_id'])
                if a['titre'].startswith('Fiche à valider')]
            direction = [a['titre'] for a in construire_actions(
                db, 'directeur', sample_users['directeur_id'])
                if a['titre'].startswith('Fiche à valider')]

        assert responsable == [], responsable
        assert len(direction) == 1, direction

    def test_la_comptabilite_suit_le_circuit_jusqu_au_verrouillage(
            self, app, db, sample_users):
        """Elle ne signe pas : aucune signature ne la libère, seul le verrou."""
        from utils import aujourd_hui
        mois, annee = _mois_precedent(aujourd_hui())
        salarie = sample_users['salarie_id']

        def fiches():
            return [a['titre'] for a in construire_actions(
                db, 'comptable', sample_users['comptable_id'])
                if a['titre'].startswith('Fiche à valider')]

        with app.app_context():
            _valider_tout_le_monde(db, mois, annee, sauf=(salarie,))
            _signer(db, salarie, mois, annee, 'validation_directeur')
            assert len(fiches()) == 1

            _signer(db, salarie, mois, annee, 'validation_responsable')
            assert len(fiches()) == 1

            db.execute("UPDATE validations SET bloque = 1 "
                       "WHERE user_id = ? AND mois = ? AND annee = ?",
                       (salarie, mois, annee))
            db.commit()
            assert fiches() == []

    def test_la_relance_ne_compte_que_ce_que_les_responsables_doivent(
            self, app, db, sample_users):
        """« Relancer les responsables » ne parle que des fiches qu'ils doivent.

        Une fiche signée par le responsable et en attente de la direction
        n'attend rien d'un rappel qui leur serait adressé.
        """
        from utils import aujourd_hui
        mois, annee = _mois_precedent(aujourd_hui())
        salarie = sample_users['salarie_id']

        def relance():
            actions = construire_actions(db, 'directeur',
                                         sample_users['directeur_id'], etendu=True)
            return next((a for a in actions if a['type'] == 'relance'), None)

        with app.app_context():
            _valider_tout_le_monde(db, mois, annee, sauf=(salarie,))
            assert relance()['detail'].startswith('1 fiche')

            _signer(db, salarie, mois, annee, 'validation_responsable')
            assert relance() is None


class TestUneFicheModifieeRevientDansLeFil:
    """Signer ne vaut que pour la fiche signée, pas pour celle qui l'a suivie.

    Un salarié peut modifier ses heures tant que la fiche n'est pas
    verrouillée : `saisie.py` l'autorise et garde la signature en place. Sans
    quoi la carte disparaîtrait pour de bon, et la direction verrouillerait une
    version que le responsable n'a jamais relue.
    """

    def test_une_modification_posterieure_ramene_la_carte(self, app, db, sample_users):
        from utils import aujourd_hui
        mois, annee = _mois_precedent(aujourd_hui())
        salarie = sample_users['salarie_id']

        def fiches():
            return [a['titre'] for a in construire_actions(
                db, 'responsable', sample_users['responsable_id'],
                secteur_id=sample_users['secteur_id'])
                if a['titre'].startswith('Fiche à valider')]

        with app.app_context():
            _valider_tout_le_monde(db, mois, annee, sauf=(salarie,))
            _signer(db, salarie, mois, annee, 'validation_responsable',
                    quand='2026-08-10 09:00:00')
            assert fiches() == []

            _journaliser_modification(db, salarie, mois, annee,
                                      '2026-08-10 14:00:00')
            assert len(fiches()) == 1

    def test_resigner_la_referme(self, app, db, sample_users):
        """La carte ne s'installe pas : elle repart quand on la re-signe."""
        from utils import aujourd_hui
        mois, annee = _mois_precedent(aujourd_hui())
        salarie = sample_users['salarie_id']

        with app.app_context():
            _valider_tout_le_monde(db, mois, annee, sauf=(salarie,))
            _signer(db, salarie, mois, annee, 'validation_responsable',
                    quand='2026-08-10 09:00:00')
            _journaliser_modification(db, salarie, mois, annee,
                                      '2026-08-10 14:00:00')
            _signer(db, salarie, mois, annee, 'validation_responsable',
                    quand='2026-08-10 17:00:00')

            titres = [a['titre'] for a in construire_actions(
                db, 'responsable', sample_users['responsable_id'],
                secteur_id=sample_users['secteur_id'])
                if a['titre'].startswith('Fiche à valider')]

        assert titres == [], titres

    def test_une_modification_anterieure_ne_change_rien(self, app, db, sample_users):
        """Ce que le signataire avait sous les yeux ne le rappelle pas."""
        from utils import aujourd_hui
        mois, annee = _mois_precedent(aujourd_hui())
        salarie = sample_users['salarie_id']

        with app.app_context():
            _valider_tout_le_monde(db, mois, annee, sauf=(salarie,))
            _journaliser_modification(db, salarie, mois, annee,
                                      '2026-08-09 08:00:00')
            _signer(db, salarie, mois, annee, 'validation_responsable',
                    quand='2026-08-10 09:00:00')

            titres = [a['titre'] for a in construire_actions(
                db, 'responsable', sample_users['responsable_id'],
                secteur_id=sample_users['secteur_id'])
                if a['titre'].startswith('Fiche à valider')]

        assert titres == [], titres

    def test_une_modification_d_un_autre_mois_ne_change_rien(
            self, app, db, sample_users):
        """Le journal est filtré sur le mois de la fiche, pas sur le salarié."""
        from utils import aujourd_hui
        mois, annee = _mois_precedent(aujourd_hui())
        autre = mois - 1 or 12
        salarie = sample_users['salarie_id']

        with app.app_context():
            _valider_tout_le_monde(db, mois, annee, sauf=(salarie,))
            _signer(db, salarie, mois, annee, 'validation_responsable',
                    quand='2026-08-10 09:00:00')
            _journaliser_modification(db, salarie, autre, annee,
                                      '2026-08-10 14:00:00')

            titres = [a['titre'] for a in construire_actions(
                db, 'responsable', sample_users['responsable_id'],
                secteur_id=sample_users['secteur_id'])
                if a['titre'].startswith('Fiche à valider')]

        assert titres == [], titres

    def test_la_direction_aussi(self, app, db, sample_users):
        from utils import aujourd_hui
        mois, annee = _mois_precedent(aujourd_hui())
        salarie = sample_users['salarie_id']

        with app.app_context():
            _valider_tout_le_monde(db, mois, annee, sauf=(salarie,))
            _signer(db, salarie, mois, annee, 'validation_directeur',
                    quand='2026-08-10 09:00:00')
            _journaliser_modification(db, salarie, mois, annee,
                                      '2026-08-10 14:00:00')

            titres = [a['titre'] for a in construire_actions(
                db, 'directeur', sample_users['directeur_id'])
                if a['titre'].startswith('Fiche à valider')]

        assert len(titres) == 1, titres

    def test_la_relance_recompte_la_fiche_modifiee(self, app, db, sample_users):
        from utils import aujourd_hui
        mois, annee = _mois_precedent(aujourd_hui())
        salarie = sample_users['salarie_id']

        def relance():
            actions = construire_actions(db, 'directeur',
                                         sample_users['directeur_id'], etendu=True)
            return next((a for a in actions if a['type'] == 'relance'), None)

        with app.app_context():
            _valider_tout_le_monde(db, mois, annee, sauf=(salarie,))
            _signer(db, salarie, mois, annee, 'validation_responsable',
                    quand='2026-08-10 09:00:00')
            assert relance() is None

            _journaliser_modification(db, salarie, mois, annee,
                                      '2026-08-10 14:00:00')
            assert relance()['detail'].startswith('1 fiche')


class TestHorlogeUniqueDesSignatures:
    """La comparaison signature / modification exige une seule horloge.

    Le défaut SQLite `CURRENT_TIMESTAMP` est en UTC ; l'application vit en
    heure applicative (`utils.maintenant`). Deux sources différentes
    décaleraient la comparaison de une à deux heures selon la saison — assez
    pour manquer précisément les modifications faites dans la foulée d'une
    signature.
    """

    def test_le_journal_est_horodate_par_l_application(self, auth_client, app, db,
                                                       sample_users, sample_contrat,
                                                       monkeypatch):
        from utils import maintenant
        salarie = sample_users['salarie_id']

        # La suite tourne en UTC, où l'horloge applicative et celle de SQLite
        # coïncident : le test ne prouverait rien. Sous une timezone décalée,
        # elles se séparent et l'écart devient mesurable.
        monkeypatch.setenv('APP_TIMEZONE', 'Europe/Paris')
        utc = datetime.now(timezone.utc).replace(tzinfo=None)
        if abs((maintenant() - utc).total_seconds()) < 120:
            pytest.skip("timezone Europe/Paris indisponible (tzdata manquant)")

        with app.app_context():
            auth_client.post('/saisie_heures', data={
                'date': '2025-01-06',
                'heure_debut_matin': '09:00', 'heure_fin_matin': '12:00',
                'heure_debut_aprem': '13:00', 'heure_fin_aprem': '17:00',
            }, follow_redirects=True)

            trace = db.execute(
                'SELECT date_modification FROM historique_modifications '
                'WHERE user_id_modifie = ? ORDER BY id DESC LIMIT 1',
                (salarie,)
            ).fetchone()

        assert trace, "la saisie doit laisser une trace dans le journal"
        ecart = abs((datetime.strptime(trace['date_modification'],
                                       '%Y-%m-%d %H:%M:%S') - maintenant())
                    .total_seconds())
        # Une heure d'écart signerait l'horodatage UTC de SQLite.
        assert ecart < 120, trace['date_modification']


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

    def _deleguer_les_fournitures(self, db, sample_users, user_id):
        from blueprints.delegations import (MISSION_SUIVI_COMMANDES_FOURNITURES,
                                            save_delegation)
        save_delegation(MISSION_SUIVI_COMMANDES_FOURNITURES, user_id,
                        sample_users['directeur_id'])

    def _deux_demandes(self, db, sample_users):
        for description, urgence in (('Ramettes A4', 'peut_attendre'),
                                     ('Cartouches encre', 'urgent')):
            db.execute(
                """INSERT INTO commandes_salaries
                   (user_id, date_demande, description, quantite, urgence, groupe)
                   VALUES (?, '2026-07-01', ?, 1, ?, 'en_cours')""",
                (sample_users['salarie_id'], description, urgence))
        db.commit()

    def test_fournitures_en_attente_classees_par_urgence(self, app, db, sample_users):
        with app.app_context():
            self._deux_demandes(db, sample_users)
            self._deleguer_les_fournitures(db, sample_users,
                                           sample_users['salarie_id'])

            actions = construire_actions(db, 'salarie', sample_users['salarie_id'])

        fournitures = [a for a in actions if a['id'].startswith('fourn-')]
        assert len(fournitures) == 2
        assert 'Cartouches' in fournitures[0]['titre']       # urgent d'abord
        assert fournitures[0]['urgence'] == 'urgent'
        assert fournitures[1]['urgence'] == 'normal'          # « peut attendre »

    def test_un_salarie_sans_delegation_ne_voit_pas_les_fournitures(
            self, app, db, sample_users):
        with app.app_context():
            self._deux_demandes(db, sample_users)

            actions = construire_actions(db, 'salarie', sample_users['salarie_id'])

        assert not [a for a in actions if a['id'].startswith('fourn-')]

    def test_la_direction_ne_recoit_pas_les_fournitures(self, app, db, sample_users):
        """La mission est confiée à quelqu'un : la doubler diluerait la
        responsabilité, chacun supposant que l'autre s'en charge."""
        with app.app_context():
            self._deux_demandes(db, sample_users)
            self._deleguer_les_fournitures(db, sample_users,
                                           sample_users['salarie_id'])

            vus_direction = construire_actions(db, 'directeur',
                                               sample_users['directeur_id'])
            vus_comptable = construire_actions(db, 'comptable',
                                               sample_users['comptable_id'])

        assert not [a for a in vus_direction if a['id'].startswith('fourn-')]
        assert not [a for a in vus_comptable if a['id'].startswith('fourn-')]

    def test_sans_delegue_personne_ne_recoit_les_fournitures(self, app, db,
                                                             sample_users):
        """La file se consulte alors sur sa page ; elle ne réclame personne."""
        with app.app_context():
            self._deux_demandes(db, sample_users)

            for profil, uid in (('directeur', sample_users['directeur_id']),
                                ('comptable', sample_users['comptable_id']),
                                ('responsable', sample_users['responsable_id'])):
                actions = construire_actions(db, profil, uid,
                                             secteur_id=sample_users['secteur_id'])
                assert not [a for a in actions if a['id'].startswith('fourn-')], profil

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
                   VALUES (?, 'Arrêt maladie', '2026-07-06', '2026-07-10', 5, ?, 'abs/arret.pdf')""",
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
                   VALUES (?, 'Arrêt maladie', '2026-07-06', '2026-07-10', 5, ?)""",
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


class TestPerimetreEtAgregation:
    """Trois angles morts relevés en revue : périmètre, motifs, agrégation."""

    def _le_20(self, monkeypatch):
        import dashboard_actions
        monkeypatch.setattr(dashboard_actions, 'aujourd_hui',
                            lambda: date(2026, 7, 20))

    def test_un_responsable_ne_compte_que_son_equipe(self, app, db, sample_users,
                                                     monkeypatch):
        """Sinon il lit les situations RH des autres équipes."""
        self._le_20(monkeypatch)
        with app.app_context():
            # Un CDD sans fiche, hors du secteur du responsable.
            cur = db.execute(
                "INSERT INTO users (nom, prenom, login, password, profil) "
                "VALUES ('Ailleurs', 'Luc', 'ailleurs', 'x', 'salarie')")
            etranger = cur.lastrowid
            db.execute(
                "INSERT INTO contrats (user_id, type_contrat, date_debut, date_fin) "
                "VALUES (?, 'CDD', '2026-07-01', '2026-07-31')", (etranger,))
            db.commit()

            vu_responsable = construire_actions(
                db, 'responsable', sample_users['responsable_id'],
                secteur_id=sample_users['secteur_id'])
            vu_direction = construire_actions(db, 'directeur',
                                              sample_users['directeur_id'])

        paie_resp = [a for a in vu_responsable if a['type'] == 'paie']
        paie_dir = next(a for a in vu_direction if a['type'] == 'paie')
        assert 'CDD' in paie_dir['detail']              # la direction le voit
        assert not paie_resp or 'CDD' not in paie_resp[0]['detail']

    def test_un_conge_valide_ne_compte_pas_comme_absence_injustifiee(
            self, app, db, sample_users, monkeypatch):
        """Un congé validé crée une absence sans pièce, par construction.

        La compter ferait sonner le rappel tous les mois, et un rappel qui
        se déclenche toujours cesse d'être lu.
        """
        self._le_20(monkeypatch)
        with app.app_context():
            db.execute(
                """INSERT INTO absences (user_id, motif, date_debut, date_fin,
                                         jours_ouvres, saisi_par, commentaire)
                   VALUES (?, 'Congé payé', '2026-07-06', '2026-07-10', 5, ?,
                           'Congé validé - Demande #1')""",
                (sample_users['salarie_id'], sample_users['directeur_id']))
            db.commit()
            actions = construire_actions(db, 'directeur', sample_users['directeur_id'])

        paie = next(a for a in actions if a['type'] == 'paie')
        assert 'sans justificatif' not in paie['detail']

    def test_un_arret_maladie_sans_piece_compte_toujours(self, app, db, sample_users,
                                                         monkeypatch):
        self._le_20(monkeypatch)
        with app.app_context():
            db.execute(
                """INSERT INTO absences (user_id, motif, date_debut, date_fin,
                                         jours_ouvres, saisi_par)
                   VALUES (?, 'Arrêt maladie', '2026-07-06', '2026-07-10', 5, ?)""",
                (sample_users['salarie_id'], sample_users['directeur_id']))
            db.commit()
            actions = construire_actions(db, 'directeur', sample_users['directeur_id'])

        paie = next(a for a in actions if a['type'] == 'paie')
        assert '1 absence(s) sans justificatif' in paie['detail']

    def test_un_poste_alp_se_juge_sur_le_total_de_ses_periodes(self, app, db,
                                                               sample_users):
        """150 dépensés sur une période budgétée 100 ne sont pas un dépassement
        si le poste, budgété 1000 au total, reste sous enveloppe."""
        from utils import aujourd_hui
        annee = aujourd_hui().year
        with app.app_context():
            cur = db.execute(
                "INSERT INTO budgets (secteur_id, annee, montant_global) VALUES (?, ?, 2000)",
                (sample_users['secteur_id'], annee))
            budget_id = cur.lastrowid
            cur = db.execute("INSERT INTO postes_depense (nom) VALUES ('Sorties ALP')")
            poste_id = cur.lastrowid
            for periode, prevu, reel in (('mercredis', 100, 150), ('ete', 900, 0)):
                db.execute("INSERT INTO budget_lignes (budget_id, poste_depense_id, "
                           "periode, montant) VALUES (?, ?, ?, ?)",
                           (budget_id, poste_id, periode, prevu))
                db.execute("INSERT INTO budget_reel_lignes (budget_id, poste_depense_id, "
                           "periode, montant) VALUES (?, ?, ?, ?)",
                           (budget_id, poste_id, periode, reel))
            db.commit()

            actions = construire_actions(db, 'directeur', sample_users['directeur_id'])

        assert not [a for a in actions if a['id'].startswith('budget-')]

    def test_un_poste_alp_reellement_depasse_remonte(self, app, db, sample_users):
        from utils import aujourd_hui
        annee = aujourd_hui().year
        with app.app_context():
            cur = db.execute(
                "INSERT INTO budgets (secteur_id, annee, montant_global) VALUES (?, ?, 2000)",
                (sample_users['secteur_id'], annee))
            budget_id = cur.lastrowid
            cur = db.execute("INSERT INTO postes_depense (nom) VALUES ('Sorties ALP')")
            poste_id = cur.lastrowid
            for periode, prevu, reel in (('mercredis', 100, 150), ('ete', 900, 1000)):
                db.execute("INSERT INTO budget_lignes (budget_id, poste_depense_id, "
                           "periode, montant) VALUES (?, ?, ?, ?)",
                           (budget_id, poste_id, periode, prevu))
                db.execute("INSERT INTO budget_reel_lignes (budget_id, poste_depense_id, "
                           "periode, montant) VALUES (?, ?, ?, ?)",
                           (budget_id, poste_id, periode, reel))
            db.commit()

            actions = construire_actions(db, 'directeur', sample_users['directeur_id'])

        budgets = [a for a in actions if a['id'].startswith('budget-')]
        assert len(budgets) == 1
        assert '150' in budgets[0]['detail']      # 1150 réels − 1000 prévus


class TestSoldesDeCongesEleves:
    """Même forme que les autres familles : deux nommés, puis le total."""

    def _salaries_au_dessus_du_seuil(self, db, combien, solde=12):
        for rang in range(combien):
            db.execute(
                "INSERT INTO users (nom, prenom, login, password, profil, cc_solde) "
                "VALUES (?, 'Test', ?, 'x', 'salarie', ?)",
                (f'Solde{rang}', f'solde{rang}', solde + rang))
        db.commit()

    def _cartes(self, db, sample_users):
        from blueprints.dashboard_direction import _lire_seuils
        return construire_actions(db, 'directeur', sample_users['directeur_id'],
                                  etendu=True, seuils=_lire_seuils(), surcharges=[])

    def test_deux_nommes_puis_une_ligne_pour_le_reste(self, app, db, sample_users):
        with app.app_context():
            self._salaries_au_dessus_du_seuil(db, 5)
            actions = self._cartes(db, sample_users)

        nommes = [a for a in actions if a['id'].startswith('conge-')]
        assert len(nommes) == 2
        reste = [a for a in actions if a['id'] == 'reste-conges-eleves']
        assert len(reste) == 1
        assert 'et 3 autres' in reste[0]['titre']

    def test_les_soldes_les_plus_eleves_passent_devant(self, app, db, sample_users):
        with app.app_context():
            self._salaries_au_dessus_du_seuil(db, 4)
            actions = self._cartes(db, sample_users)

        nommes = [a for a in actions if a['id'].startswith('conge-')]
        assert 'Solde3' in nommes[0]['titre']      # 15 j, le plus haut
        assert 'Solde2' in nommes[1]['titre']      # 14 j

    def test_pas_de_ligne_de_reste_quand_deux_suffisent(self, app, db, sample_users):
        with app.app_context():
            self._salaries_au_dessus_du_seuil(db, 2)
            actions = self._cartes(db, sample_users)

        assert len([a for a in actions if a['id'].startswith('conge-')]) == 2
        assert not [a for a in actions if a['id'] == 'reste-conges-eleves']
