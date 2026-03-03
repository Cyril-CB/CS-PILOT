"""Tests UI ciblés pour le module comptabilité et profils utilisateurs."""


def _seed_compta_rows(db, user_id):
    """Insère un minimum de données pour afficher les actions des pages comptables."""
    cur = db.cursor()
    cur.execute("INSERT INTO fournisseurs (nom) VALUES (%s) RETURNING id", ("Fournisseur Test",))
    fournisseur_id = cur.lastrowid

    cur.execute(
        """INSERT INTO factures
           (fournisseur_id, numero_facture, date_facture, montant_ttc, fichier_path, fichier_nom, created_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (fournisseur_id, "FAC-001", "2026-01-15", 120.50, "/tmp/fac.pdf", "fac.pdf", user_id),
    )
    facture_id = cur.lastrowid

    cur.execute(
        """INSERT INTO regles_comptables (nom, type_regle, cible, compte_comptable)
           VALUES (%s, %s, %s, %s)""",
        ("Règle test", "type_depense", "Fournitures", "606100"),
    )

    cur.execute(
        """INSERT INTO ecritures_comptables
           (facture_id, date_ecriture, compte, libelle, numero_facture, debit, credit, statut)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (facture_id, "2026-01-15", "606100", "FOURNISSEUR TEST", "FAC-001", 120.50, 0, "brouillon"),
    )

    cur.execute(
        """INSERT INTO ecritures_comptables
           (facture_id, date_ecriture, compte, libelle, numero_facture, debit, credit, statut)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (facture_id, "2026-01-15", "401000", "FOURNISSEUR TEST", "FAC-001", 0, 120.50, "validee"),
    )

    cur.execute(
        """INSERT INTO archives_export (nom_fichier, fichier_path, nb_ecritures, created_by)
           VALUES (%s, %s, %s, %s)""",
        ("export_test.txt", "/tmp/export_test.txt", 1, user_id),
    )
    db.commit()


def test_pages_comptables_utilisent_des_icones_pour_actions(admin_client, db, sample_users):
    _seed_compta_rows(db, sample_users["directeur_id"])

    factures_html = admin_client.get("/factures").get_data(as_text=True)
    assert 'title="Assigner"' in factures_html
    assert ">Assigner<" not in factures_html
    assert 'title="Détail"' in factures_html
    assert ">Détail<" not in factures_html
    assert 'title="Supprimer"' in factures_html
    assert ">Supprimer<" not in factures_html

    fournisseurs_html = admin_client.get("/fournisseurs").get_data(as_text=True)
    assert 'title="Éditer"' in fournisseurs_html
    assert ">Éditer<" not in fournisseurs_html
    assert ">Supprimer<" not in fournisseurs_html

    regles_html = admin_client.get("/regles-comptables").get_data(as_text=True)
    assert 'title="Éditer"' in regles_html
    assert ">Éditer<" not in regles_html
    assert ">Supprimer<" not in regles_html

    ecritures_html = admin_client.get("/ecritures").get_data(as_text=True)
    assert 'title="Éditer"' in ecritures_html
    assert ">Éditer<" not in ecritures_html

    exportation_html = admin_client.get("/exportation").get_data(as_text=True)
    assert 'title="Supprimer"' in exportation_html
    assert ">Supprimer<" not in exportation_html


def test_profil_comptable_peut_etre_assigne_secteur_et_responsable_ui(admin_client, db, sample_users):
    creer_html = admin_client.get("/creer_user").get_data(as_text=True)
    assert "profil === 'comptable'" in creer_html
    assert "Peut être rattaché à un secteur (optionnel)" in creer_html

    cur = db.cursor()
    cur.execute(
        """INSERT INTO users (nom, prenom, login, password, profil)
           VALUES (%s, %s, %s, %s, %s) RETURNING id""",
        ("Comptable", "Test", "comptable_ui", "hash", "comptable"),
    )
    user_id = cur.lastrowid
    db.commit()

    modifier_html = admin_client.get(f"/modifier_user/{user_id}").get_data(as_text=True)
    assert "profil === 'comptable'" in modifier_html
    assert "secteurGroup.style.display = 'block';" in modifier_html
    assert "responsableGroup.style.display = 'block';" in modifier_html
