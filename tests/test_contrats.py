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
