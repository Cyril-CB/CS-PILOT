"""
Tests de la page Preparation de paie :
- controle d'acces
- rendu de la grille : colonnes figees (Traite, Nom Prenom) presentes,
  colonne "Nom Prenom" dupliquee en fin de tableau supprimee
"""


def _inserer_contrat(db, user_id):
    """Cree un contrat actif pour que le salarie apparaisse dans la grille."""
    db.execute(
        "INSERT INTO contrats (user_id, type_contrat, date_debut, date_fin) "
        "VALUES (?, 'CDI', '2026-01-01', NULL)", (user_id,)
    )
    db.commit()


class TestPagePrepaPaie:

    def test_acces_refuse_salarie(self, auth_client):
        resp = auth_client.get('/prepa_paie', follow_redirects=False)
        assert resp.status_code == 302

    def test_grille_colonnes_figees_sans_doublon_nom(self, comptable_client, sample_users, app, db):
        with app.app_context():
            _inserer_contrat(db, sample_users['salarie_id'])

        resp = comptable_client.get('/prepa_paie?mois=6&annee=2026')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')

        # La grille est bien rendue avec le salarie sous contrat
        assert f"traite_{sample_users['salarie_id']}" in html
        # Colonnes figees a gauche
        assert 'pp-col-traite' in html
        assert 'pp-col-nom' in html
        # L'en-tete "Nom Prenom" n'apparait qu'une fois : la colonne dupliquee
        # en fin de tableau a ete supprimee
        assert html.count('>Nom Prenom</th>') == 1
        # Le nom du salarie n'apparait qu'une fois par ligne (plus de rappel a droite)
        assert html.count('<strong>Martin</strong>') == 1
