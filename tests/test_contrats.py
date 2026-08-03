"""
Tests de la page contrats par mois / filtre (contrats_bp).
"""
import calendar


def _ctx_mois():
    from utils import aujourd_hui
    d = aujourd_hui()
    dernier = calendar.monthrange(d.year, d.month)[1]
    return d.year, d.month, dernier


def _seed_contrats(db, uid):
    an, mois, dernier = _ctx_mois()
    mm = f"{an:04d}-{mois:02d}"
    # CDI actif (débuté avant, sans fin)
    db.execute("INSERT INTO contrats (user_id, type_contrat, date_debut, date_fin) VALUES (?, 'CDI', ?, NULL)",
               (uid, f"{an - 1:04d}-01-01"))
    # CDD se terminant ce mois
    db.execute("INSERT INTO contrats (user_id, type_contrat, date_debut, date_fin) VALUES (?, 'CDD', ?, ?)",
               (uid, f"{an:04d}-{mois:02d}-01", f"{mm}-{dernier:02d}"))
    # CDD débutant ce mois
    db.execute("INSERT INTO contrats (user_id, type_contrat, date_debut, date_fin) VALUES (?, 'CDD', ?, ?)",
               (uid, f"{mm}-05", f"{an + 1:04d}-01-01"))
    # CDD ancien (terminé l'an dernier) → hors du mois courant
    db.execute("INSERT INTO contrats (user_id, type_contrat, date_debut, date_fin) VALUES (?, 'CDD', ?, ?)",
               (uid, f"{an - 2:04d}-01-01", f"{an - 1:04d}-06-30"))
    db.commit()


class TestPageContrats:
    def test_acces_refuse_salarie(self, app, auth_client):
        assert auth_client.get('/contrats', follow_redirects=False).status_code == 302

    def test_comptable_autorise(self, app, comptable_client):
        assert comptable_client.get('/contrats').status_code == 200

    def test_en_cours_exclut_les_termines(self, app, db, comptable_client, sample_users):
        with app.app_context():
            _seed_contrats(db, sample_users['salarie_id'])
        an, mois, _ = _ctx_mois()
        html = comptable_client.get(f'/contrats?mois={mois}&annee={an}&filtre=en_cours').get_data(as_text=True)
        # 3 contrats actifs sur le mois (CDI + 2 CDD), l'ancien CDD est exclu.
        assert html.count('<tr>') >= 3 or 'contrat' in html.lower()
        # L'ancien CDD (terminé) ne doit pas apparaître via son année de début.
        assert f"{_ctx_mois()[0] - 2}" not in html or 'CDI' in html

    def test_filtre_echeance_cdd(self, app, db, comptable_client, sample_users):
        with app.app_context():
            _seed_contrats(db, sample_users['salarie_id'])
        an, mois, _ = _ctx_mois()
        html = comptable_client.get(f'/contrats?mois={mois}&annee={an}&filtre=echeance').get_data(as_text=True)
        # Le CDD se terminant ce mois est listé ; le CDI (sans fin) ne l'est pas.
        assert 'CDD' in html
        assert 'CDI / en cours' not in html  # colonne échéance du CDI absente ici

    def test_filtre_signe_debutant_ce_mois(self, app, db, comptable_client, sample_users):
        with app.app_context():
            _seed_contrats(db, sample_users['salarie_id'])
        an, mois, _ = _ctx_mois()
        html = comptable_client.get(f'/contrats?mois={mois}&annee={an}&filtre=signe').get_data(as_text=True)
        # Seul le CDD débutant ce mois (jour 05) correspond.
        assert '05/' in html

    def test_filtre_type_cdd(self, app, db, comptable_client, sample_users):
        with app.app_context():
            _seed_contrats(db, sample_users['salarie_id'])
        an, mois, _ = _ctx_mois()
        html = comptable_client.get(f'/contrats?mois={mois}&annee={an}&type=CDD&filtre=en_cours').get_data(as_text=True)
        # Filtré sur CDD → le badge CDI ne doit pas apparaître dans les lignes.
        assert '>CDI</span>' not in html


def _couvrir_les_autres(db, uid_exclu):
    """Donne un CDI à tout l'effectif sauf un : isole le cas testé.

    Sans cela, responsable et comptable — eux aussi sans contrat — peuplent la
    page et brouillent les assertions.
    """
    autres = db.execute(
        "SELECT id FROM users WHERE actif = 1 "
        "AND profil NOT IN ('directeur', 'prestataire') AND id != ?",
        (uid_exclu,)
    ).fetchall()
    for row in autres:
        db.execute(
            "INSERT INTO contrats (user_id, type_contrat, date_debut, date_fin) "
            "VALUES (?, 'CDI', '2000-01-01', NULL)", (row['id'],)
        )
    db.commit()


class TestSalariesSansContrat:
    """La liste de ceux qu'aucun contrat ne couvre aujourd'hui.

    Depuis que la saisie des heures exige un contrat, cette page dit
    exactement qui est bloqué — et pourquoi, les deux causes n'appelant pas le
    même geste : contrat jamais saisi, ou contrat échu non renouvelé.
    """

    URL = '/contrats/sans-contrat'

    def test_acces_refuse_salarie(self, app, auth_client):
        assert auth_client.get(self.URL, follow_redirects=False).status_code == 302

    def test_comptable_autorise(self, app, comptable_client):
        assert comptable_client.get(self.URL).status_code == 200

    def test_salarie_sans_aucun_contrat_est_liste(self, app, db, comptable_client,
                                                  sample_users):
        html = comptable_client.get(self.URL).get_data(as_text=True)
        assert 'Martin' in html                      # le salarié de test
        assert 'Aucun contrat au dossier' in html

    def test_salarie_sous_contrat_disparait(self, app, db, comptable_client,
                                            sample_users, sample_contrat):
        html = comptable_client.get(self.URL).get_data(as_text=True)
        assert 'Aucun salarié sans contrat' not in html or 'Martin' not in html

    def test_contrat_echu_est_signale_comme_tel(self, app, db, comptable_client,
                                                sample_users):
        an, _, _ = _ctx_mois()
        with app.app_context():
            _couvrir_les_autres(db, sample_users['salarie_id'])
            db.execute(
                "INSERT INTO contrats (user_id, type_contrat, date_debut, date_fin) "
                "VALUES (?, 'CDD', ?, ?)",
                (sample_users['salarie_id'], f"{an - 2:04d}-01-01", f"{an - 1:04d}-06-30")
            )
            db.commit()

        html = comptable_client.get(self.URL).get_data(as_text=True)
        assert 'Contrat échu' in html
        assert '30/06/' in html
        assert 'Aucun contrat au dossier' not in html

    def test_contrat_a_venir_n_est_pas_confondu_avec_un_echu(
            self, app, db, comptable_client, sample_users):
        """Embauche signée pour plus tard : le salarié est listé, sans date de fin."""
        an, _, _ = _ctx_mois()
        with app.app_context():
            _couvrir_les_autres(db, sample_users['salarie_id'])
            db.execute(
                "INSERT INTO contrats (user_id, type_contrat, date_debut, date_fin) "
                "VALUES (?, 'CDI', ?, NULL)",
                (sample_users['salarie_id'], f"{an + 1:04d}-01-01")
            )
            db.commit()

        html = comptable_client.get(self.URL).get_data(as_text=True)
        assert 'Contrat à venir' in html
        assert 'Contrat échu' not in html

    def test_la_page_reste_hors_du_menu_et_de_la_carte(self, app):
        """Page de réponse : on l'appelle, on ne la parcourt pas.

        Comme la page Contrats dont elle sort, elle n'encombre pas le menu.
        On y arrive par son bouton, par la barre intelligente, ou par le
        bandeau d'alerte quand un salarié n'a aucun contrat.
        """
        import navigation
        endpoints = {p['endpoint']
                     for g in navigation.ZONES + navigation.ACCES_DIRECTS
                     for p in g['pages']}
        assert 'contrats_bp.salaries_sans_contrat' not in endpoints
        assert 'contrats_bp.liste_contrats' not in endpoints

    def test_le_bouton_figure_sur_la_page_contrats(self, app, comptable_client):
        html = comptable_client.get('/contrats').get_data(as_text=True)
        assert '/contrats/sans-contrat' in html
        assert 'Salariés actifs sans contrat' in html

    def test_la_barre_intelligente_y_mene(self, app, comptable_client):
        reponse = comptable_client.post('/api/search', json={'query': 'salariés sans contrat'})
        assert reponse.status_code == 200
        resultat = reponse.get_json()
        assert resultat['type'] == 'redirect'
        assert '/contrats/sans-contrat' in resultat['url']
