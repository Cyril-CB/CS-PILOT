"""
Contrôle d'accès des routes d'EXPORT (fichiers téléchargeables).

Les tests de refus existants portent sur les routes de DONNÉES (pages et API
JSON) ; leurs exports servent pourtant les mêmes informations financières et
nominatives, mais dans un fichier qui sort de l'application. Un découplage
futur entre la page et son export ne serait détecté par aucun test : ce
fichier verrouille donc, pour chaque export, le cas non connecté, le cas d'un
profil non autorisé, l'absence de document dans la réponse de refus, et
l'absence d'effet en base pour les exports qui écrivent.

Rappel de la mécanique de test : les fixtures de clients authentifiés
partagent le même client. Dès qu'un test enchaîne plusieurs profils, il part
de la fixture `client` et gère les connexions explicitement.
"""
from io import BytesIO


# Signature d'un classeur Excel (xlsx = archive ZIP) et d'un PDF.
SIGNATURE_XLSX = b'PK\x03\x04'
SIGNATURE_PDF = b'%PDF'

TYPE_XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def _connexion(client, login, password):
    """Connecte le client de test avec le compte demandé."""
    return client.post('/login', data={'login': login, 'password': password},
                       follow_redirects=True)


def _deconnexion(client):
    return client.get('/logout', follow_redirects=True)


def _assert_aucun_document(response):
    """Vérifie qu'une réponse de refus ne transporte aucun fichier exporté."""
    assert response.headers.get('Content-Type') != 'application/pdf'
    assert response.headers.get('Content-Type') != TYPE_XLSX
    assert not response.data.startswith(SIGNATURE_PDF)
    assert not response.data.startswith(SIGNATURE_XLSX)


def _assert_redirige_vers_login(response):
    """Utilisateur non connecté : renvoyé vers la page de connexion."""
    assert response.status_code in (301, 302)
    assert '/login' in response.headers['Location']
    _assert_aucun_document(response)


# ── Jeux de données minimaux ─────────────────────────────────────────────────

def _seed_bilan_secteur(db, annee, secteur_id, compte_num, montant, libelle):
    """Rattache un compte à un secteur et lui associe un montant importé."""
    db.execute(
        "INSERT INTO comptabilite_comptes (compte_num, libelle, secteur_id) VALUES (?, ?, ?)",
        (compte_num, libelle, secteur_id)
    )
    cur = db.execute(
        "INSERT INTO bilan_fec_imports (fichier_nom, annee, nb_ecritures) VALUES (?, ?, ?)",
        (f'fec_{annee}_{compte_num}.txt', annee, 1)
    )
    db.execute(
        "INSERT INTO bilan_fec_donnees (compte_num, libelle, code_analytique, annee, "
        "mois, montant, import_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (compte_num, libelle, '', annee, 1, montant, cur.lastrowid)
    )
    db.commit()


def _seed_ecriture_validee(db, montant=120.0):
    """Crée une écriture comptable validée, prête à être exportée."""
    cur = db.execute(
        "INSERT INTO fournisseurs (nom) VALUES (?)", ('Fournisseur Test',)
    )
    cur = db.execute(
        "INSERT INTO factures (fournisseur_id, numero_facture, date_facture, "
        "montant_ttc, description, statut) VALUES (?, ?, ?, ?, ?, ?)",
        (cur.lastrowid, 'INV-EXPORT-001', '2026-01-15', montant, 'Fournitures', 'traitee')
    )
    cur = db.execute(
        "INSERT INTO ecritures_comptables (facture_id, date_ecriture, compte, libelle, "
        "numero_facture, debit, credit, statut) VALUES (?, ?, ?, ?, ?, ?, ?, 'validee')",
        (cur.lastrowid, '2026-01-15', '606100', 'Fournitures', 'INV-EXPORT-001', montant, 0)
    )
    db.commit()
    return cur.lastrowid


def _seed_archive(db, tmp_path, created_by):
    """Crée une archive d'export réellement présente sur le disque."""
    fichier = tmp_path / 'export_ecritures_20260115_120000.txt'
    fichier.write_text('AC\t15012026\t606100\tFOURNITURES\n', encoding='utf-8')
    cur = db.execute(
        "INSERT INTO archives_export (nom_fichier, fichier_path, nb_ecritures, created_by) "
        "VALUES (?, ?, ?, ?)",
        (fichier.name, str(fichier), 1, created_by)
    )
    db.commit()
    return cur.lastrowid, fichier


def _verrouiller_fiche(db, user_id, mois, annee):
    """Verrouille la fiche mensuelle : condition préalable à l'export PDF."""
    db.execute('''
        INSERT INTO validations (
            user_id, mois, annee, bloque,
            validation_salarie, validation_responsable, validation_directeur,
            date_salarie, date_responsable, date_directeur
        ) VALUES (?, ?, ?, 1, 'Salarié', 'Responsable', 'Directeur',
                  '2026-01-31', '2026-01-31', '2026-01-31')
    ''', (user_id, mois, annee))
    db.commit()


# ── Prépa paie : export Excel de toute la paie nominative du mois ────────────

def test_prepa_paie_export_excel_controle_acces(client, sample_users, app, db):
    """L'export Excel de la prépa paie contient la paie nominative de tout
    l'effectif : seuls comptable, directeur et prestataire y ont droit."""
    url = '/prepa_paie/export_excel?mois=6&annee=2026'

    # Non connecté : renvoyé vers la connexion, aucun classeur servi.
    _assert_redirige_vers_login(client.get(url, follow_redirects=False))

    # Salarié : refusé vers le tableau de bord.
    _connexion(client, 'salarie_test', 'sal123')
    reponse = client.get(url, follow_redirects=False)
    assert reponse.status_code == 302
    assert reponse.headers['Location'].endswith('/dashboard')
    _assert_aucun_document(reponse)
    _deconnexion(client)

    # Responsable : refusé lui aussi, la paie ne relève pas de son périmètre.
    _connexion(client, 'resp_test', 'resp123')
    reponse = client.get(url, follow_redirects=False)
    assert reponse.status_code == 302
    assert reponse.headers['Location'].endswith('/dashboard')
    _assert_aucun_document(reponse)
    _deconnexion(client)

    # Comptable : export légitime.
    _connexion(client, 'compta_test', 'compta123')
    reponse = client.get(url)
    assert reponse.status_code == 200
    assert reponse.headers['Content-Type'] == TYPE_XLSX
    _deconnexion(client)


def test_prepa_paie_export_excel_autorise_le_prestataire(prestataire_client):
    """Élargissement VOULU (confirmé par l'utilisateur) : le cabinet de paie
    externe télécharge bien le classeur, c'est sa matière de travail."""
    reponse = prestataire_client.get('/prepa_paie/export_excel?mois=6&annee=2026')

    assert reponse.status_code == 200
    assert reponse.headers['Content-Type'] == TYPE_XLSX
    assert reponse.data.startswith(SIGNATURE_XLSX)


# ── Compte de résultat / indicateurs financiers ─────────────────────────────

def test_cr_export_pdf_controle_acces(client, sample_users, app, db):
    """Le PDF du compte de résultat suit les droits de la page : direction et
    comptabilité uniquement."""
    annee = 2026
    with app.app_context():
        _seed_bilan_secteur(db, annee, sample_users['secteur_id'],
                            '606100', 1500.0, 'Fournitures')
    url = f'/api/cr/export-pdf?annee={annee}'

    _assert_redirige_vers_login(client.get(url, follow_redirects=False))

    for login, mot_de_passe in (('salarie_test', 'sal123'), ('resp_test', 'resp123')):
        _connexion(client, login, mot_de_passe)
        reponse = client.get(url)
        assert reponse.status_code == 403, login
        _assert_aucun_document(reponse)
        _deconnexion(client)

    _connexion(client, 'compta_test', 'compta123')
    reponse = client.get(url)
    assert reponse.status_code == 200
    assert reponse.headers['Content-Type'] == 'application/pdf'
    assert reponse.data.startswith(SIGNATURE_PDF)
    _deconnexion(client)


def test_indicateurs_export_pdf_controle_acces(client, sample_users, app, db):
    """Le PDF des indicateurs financiers agrège tous les exercices : refusé au
    salarié et au responsable."""
    with app.app_context():
        _seed_bilan_secteur(db, 2026, sample_users['secteur_id'],
                            '706100', 9000.0, 'Prestations')
    url = '/api/indicateurs/export-pdf'

    _assert_redirige_vers_login(client.get(url, follow_redirects=False))

    for login, mot_de_passe in (('salarie_test', 'sal123'), ('resp_test', 'resp123')):
        _connexion(client, login, mot_de_passe)
        reponse = client.get(url)
        assert reponse.status_code == 403, login
        _assert_aucun_document(reponse)
        _deconnexion(client)

    _connexion(client, 'admin', 'Admin1234')
    reponse = client.get(url)
    assert reponse.status_code == 200
    assert reponse.headers['Content-Type'] == 'application/pdf'
    assert reponse.data.startswith(SIGNATURE_PDF)
    _deconnexion(client)


# ── Bilan secteurs : cloisonnement du responsable ───────────────────────────

def test_bilan_export_pdf_refuse_hors_perimetre(client, sample_users, app, db):
    """Le PDF du bilan secteurs est fermé au salarié comme au prestataire de
    paie : ni l'un ni l'autre n'a affaire aux comptes de l'association.
    (Le prestataire est créé ici plutôt que via sa fixture, qui monopolise le
    client de test partagé.)"""
    from werkzeug.security import generate_password_hash

    with app.app_context():
        db.execute(
            "INSERT INTO users (nom, prenom, login, password, profil) VALUES (?, ?, ?, ?, ?)",
            ('Cabinet', 'Paie', 'presta_bilan', generate_password_hash('presta123'),
             'prestataire')
        )
        db.commit()

    url = '/api/bilan/export-pdf?annee=2026'

    _assert_redirige_vers_login(client.get(url, follow_redirects=False))

    for login, mot_de_passe in (('salarie_test', 'sal123'), ('presta_bilan', 'presta123')):
        _connexion(client, login, mot_de_passe)
        reponse = client.get(url, follow_redirects=False)
        assert reponse.status_code == 302, login
        assert reponse.headers['Location'].endswith('/dashboard'), login
        _assert_aucun_document(reponse)
        _deconnexion(client)


def test_bilan_export_pdf_cloisonne_le_secteur_du_responsable(
        client, sample_users, app, db):
    """Test central du lot : le responsable est autorisé sur cet export, mais
    le serveur FORCE son secteur assigné. Même en réclamant explicitement le
    secteur d'un collègue dans l'URL, il reçoit le PDF de son propre secteur,
    sans le moindre montant du secteur voisin."""
    annee = 2026
    with app.app_context():
        cur = db.execute(
            "INSERT INTO secteurs (nom, description) VALUES (?, ?)",
            ('Secteur Confidentiel', 'Secteur hors périmètre du responsable')
        )
        secteur_autre_id = cur.lastrowid
        db.commit()

        # Un montant distinctif par secteur pour les repérer dans le PDF.
        _seed_bilan_secteur(db, annee, sample_users['secteur_id'],
                            '606100', 1111.0, 'Achats Secteur Test')
        _seed_bilan_secteur(db, annee, secteur_autre_id,
                            '606200', 8888.0, 'Achats Secteur Confidentiel')

    _connexion(client, 'resp_test', 'resp123')
    reponse = client.get(
        f'/api/bilan/export-pdf?annee={annee}&secteur_id={secteur_autre_id}')

    # L'export lui est bien servi (accès légitime, périmètre restreint).
    assert reponse.status_code == 200
    assert reponse.headers['Content-Type'] == 'application/pdf'
    # Le nom de fichier est construit à partir du secteur RÉELLEMENT interrogé.
    assert f'secteur{sample_users["secteur_id"]}.pdf' in \
        reponse.headers['Content-Disposition']
    assert f'secteur{secteur_autre_id}.pdf' not in \
        reponse.headers['Content-Disposition']

    import pdfplumber
    with pdfplumber.open(BytesIO(reponse.data)) as pdf:
        texte = '\n'.join(page.extract_text() or '' for page in pdf.pages)
    # Les montants sont formatés avec une espace insécable : on normalise pour
    # que l'assertion ne dépende pas de l'extraction de texte.
    texte = texte.replace('\xa0', ' ')

    assert 'Secteur Test' in texte
    assert 'Secteur Confidentiel' not in texte
    # Le montant du secteur voisin (8 888,00) ne doit apparaître nulle part ;
    # celui du secteur du responsable, si.
    assert '1 111,00' in texte
    assert '8 888,00' not in texte
    assert '606200' not in texte


def test_bilan_export_pdf_responsable_sans_secteur_est_refuse(client, app, db):
    """Un responsable sans secteur assigné ne doit pas récupérer le bilan
    global par défaut : le forçage de secteur le renvoie vers la page."""
    from werkzeug.security import generate_password_hash

    with app.app_context():
        db.execute(
            "INSERT INTO users (nom, prenom, login, password, profil) VALUES (?, ?, ?, ?, ?)",
            ('Sansecteur', 'Paul', 'resp_orphelin', generate_password_hash('resp123'),
             'responsable')
        )
        db.commit()

    _connexion(client, 'resp_orphelin', 'resp123')
    reponse = client.get('/api/bilan/export-pdf?annee=2026&secteur_id=1',
                         follow_redirects=False)

    assert reponse.status_code == 302
    assert '/bilan-secteurs' in reponse.headers['Location']
    _assert_aucun_document(reponse)


# ── Bilan action ────────────────────────────────────────────────────────────

def test_bilan_action_export_pdf_controle_acces(client, sample_users, app, db):
    """Le PDF du budget d'une action est réservé à la direction et à la
    comptabilité ; le responsable en est exclu."""
    with app.app_context():
        cur = db.execute("INSERT INTO comptabilite_actions (nom) VALUES (?)",
                         ('Action Export',))
        action_id = cur.lastrowid
        db.commit()
    url = f'/api/bilan-action/export-pdf?annee=2026&action_id={action_id}'

    _assert_redirige_vers_login(client.get(url, follow_redirects=False))

    for login, mot_de_passe in (('salarie_test', 'sal123'), ('resp_test', 'resp123')):
        _connexion(client, login, mot_de_passe)
        reponse = client.get(url, follow_redirects=False)
        assert reponse.status_code == 302, login
        assert '/bilan-action' in reponse.headers['Location'], login
        _assert_aucun_document(reponse)
        _deconnexion(client)

    _connexion(client, 'admin', 'Admin1234')
    reponse = client.get(url)
    assert reponse.status_code == 200
    assert reponse.headers['Content-Type'] == 'application/pdf'
    assert reponse.data.startswith(SIGNATURE_PDF)
    _deconnexion(client)


# ── Journal d'audit ─────────────────────────────────────────────────────────

def test_journal_actions_export_controle_acces(client, sample_users):
    """Le CSV du journal des actions trace qui a fait quoi (avec l'adresse
    IP) : hors direction et comptabilité, aucun export."""
    url = '/securite/journal-actions/export'

    _assert_redirige_vers_login(client.get(url, follow_redirects=False))

    for login, mot_de_passe in (('salarie_test', 'sal123'), ('resp_test', 'resp123')):
        _connexion(client, login, mot_de_passe)
        reponse = client.get(url, follow_redirects=False)
        assert reponse.status_code == 302, login
        assert reponse.headers['Location'].endswith('/dashboard'), login
        assert 'text/csv' not in (reponse.headers.get('Content-Type') or ''), login
        _assert_aucun_document(reponse)
        _deconnexion(client)

    _connexion(client, 'compta_test', 'compta123')
    reponse = client.get(url)
    assert reponse.status_code == 200
    assert 'text/csv' in reponse.content_type
    _deconnexion(client)


# ── Exportation des écritures comptables ────────────────────────────────────

def test_exportation_page_et_archive_refusees(client, sample_users, app, db, tmp_path):
    """Page d'exportation et téléchargement d'archive : réservés au directeur
    et au comptable."""
    with app.app_context():
        archive_id, fichier = _seed_archive(db, tmp_path, sample_users['directeur_id'])

    urls = ('/exportation', f'/exportation/archives/{archive_id}/telecharger')

    for url in urls:
        _assert_redirige_vers_login(client.get(url, follow_redirects=False))

    for login, mot_de_passe in (('salarie_test', 'sal123'), ('resp_test', 'resp123')):
        _connexion(client, login, mot_de_passe)
        for url in urls:
            reponse = client.get(url, follow_redirects=False)
            assert reponse.status_code == 302, (login, url)
            assert reponse.headers['Location'].endswith('/dashboard'), (login, url)
            # Le contenu de l'archive n'est jamais servi.
            assert b'FOURNITURES' not in reponse.data, (login, url)
        _deconnexion(client)

    # L'archive reste intacte et téléchargeable pour un profil habilité.
    _connexion(client, 'compta_test', 'compta123')
    reponse = client.get(f'/exportation/archives/{archive_id}/telecharger')
    assert reponse.status_code == 200
    assert b'FOURNITURES' in reponse.data
    _deconnexion(client)
    assert fichier.exists()


def test_exportation_exporter_refuse_sans_effet_en_base(client, sample_users, app, db,
                                                        monkeypatch, tmp_path):
    """POST /exportation/exporter change le statut des écritures en base :
    un refus ne doit ni générer le fichier, ni marquer quoi que ce soit
    « exportée », ni créer d'archive."""
    from blueprints import exportation as exportation_module
    archives_dir = tmp_path / 'exports'
    archives_dir.mkdir()
    monkeypatch.setattr(exportation_module, 'ARCHIVES_DIR', str(archives_dir))

    with app.app_context():
        ecriture_id = _seed_ecriture_validee(db)

    def _statut():
        with app.app_context():
            return db.execute(
                "SELECT statut FROM ecritures_comptables WHERE id = ?", (ecriture_id,)
            ).fetchone()['statut']

    def _nb_archives():
        with app.app_context():
            return db.execute(
                "SELECT COUNT(*) AS n FROM archives_export").fetchone()['n']

    donnees = {'ecriture_ids': [str(ecriture_id)]}

    # Non connecté.
    reponse = client.post('/exportation/exporter', data=donnees, follow_redirects=False)
    assert reponse.status_code in (301, 302)
    assert '/login' in reponse.headers['Location']
    assert _statut() == 'validee'
    assert _nb_archives() == 0

    # Salarié puis responsable : refus et aucune écriture consommée.
    for login, mot_de_passe in (('salarie_test', 'sal123'), ('resp_test', 'resp123')):
        _connexion(client, login, mot_de_passe)
        reponse = client.post('/exportation/exporter', data=donnees,
                              follow_redirects=False)
        assert reponse.status_code == 302, login
        assert reponse.headers['Location'].endswith('/dashboard'), login
        assert b'606100' not in reponse.data, login
        assert _statut() == 'validee', login
        assert _nb_archives() == 0, login
        _deconnexion(client)

    # Le comptable, lui, obtient le fichier et l'écriture bascule en « exportee ».
    _connexion(client, 'compta_test', 'compta123')
    reponse = client.post('/exportation/exporter', data=donnees)
    assert reponse.status_code == 200
    assert b'606100' in reponse.data
    assert _statut() == 'exportee'
    assert _nb_archives() == 1
    # L'archive a bien été écrite dans le répertoire d'archives (isolé ici).
    assert list(archives_dir.iterdir())
    _deconnexion(client)


def test_exportation_supprimer_archive_refuse_sans_effet(client, sample_users,
                                                         app, db, tmp_path):
    """La suppression d'archive efface un fichier et une ligne en base : sur
    refus, l'archive et son fichier doivent être intacts."""
    with app.app_context():
        archive_id, fichier = _seed_archive(db, tmp_path, sample_users['directeur_id'])

    url = f'/exportation/archives/{archive_id}/supprimer'

    def _archive_existe():
        with app.app_context():
            return db.execute(
                "SELECT COUNT(*) AS n FROM archives_export WHERE id = ?", (archive_id,)
            ).fetchone()['n'] == 1

    # Non connecté.
    reponse = client.post(url, follow_redirects=False)
    assert reponse.status_code in (301, 302)
    assert '/login' in reponse.headers['Location']
    assert _archive_existe()
    assert fichier.exists()

    # Salarié puis responsable : refus, archive conservée.
    for login, mot_de_passe in (('salarie_test', 'sal123'), ('resp_test', 'resp123')):
        _connexion(client, login, mot_de_passe)
        reponse = client.post(url, follow_redirects=False)
        assert reponse.status_code == 302, login
        assert reponse.headers['Location'].endswith('/dashboard'), login
        assert _archive_existe(), login
        assert fichier.exists(), login
        _deconnexion(client)

    # Le comptable supprime effectivement l'archive (fichier compris).
    _connexion(client, 'compta_test', 'compta123')
    reponse = client.post(url, follow_redirects=False)
    assert reponse.status_code == 302
    assert '/exportation' in reponse.headers['Location']
    assert not _archive_existe()
    assert not fichier.exists()
    _deconnexion(client)


# ── Fiche mensuelle PDF : cas non couverts par tests/test_security.py ────────

def test_export_pdf_mensuel_non_connecte(client, app, db, sample_users):
    """Complète TestExportPdfMensuelAccessControl (tests/test_security.py) :
    sans session, la fiche RH nominative n'est pas servie."""
    with app.app_context():
        _verrouiller_fiche(db, sample_users['salarie_id'], mois=1, annee=2026)

    reponse = client.get(
        f"/export_pdf_mensuel?user_id={sample_users['salarie_id']}&mois=1&annee=2026",
        follow_redirects=False)

    _assert_redirige_vers_login(reponse)


def test_export_pdf_mensuel_responsable_hors_de_son_equipe(client, app, db, sample_users):
    """Second cas manquant : un responsable n'exporte que les fiches de son
    équipe (même secteur ou rattachement hiérarchique direct)."""
    from werkzeug.security import generate_password_hash

    with app.app_context():
        cur = db.execute("INSERT INTO secteurs (nom) VALUES (?)", ('Secteur Voisin',))
        secteur_voisin_id = cur.lastrowid
        cur = db.execute(
            "INSERT INTO users (nom, prenom, login, password, profil, secteur_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ('Petit', 'Luc', 'salarie_voisin', generate_password_hash('sal123'),
             'salarie', secteur_voisin_id)
        )
        salarie_voisin_id = cur.lastrowid
        db.commit()
        _verrouiller_fiche(db, salarie_voisin_id, mois=1, annee=2026)

    _connexion(client, 'resp_test', 'resp123')
    reponse = client.get(
        f'/export_pdf_mensuel?user_id={salarie_voisin_id}&mois=1&annee=2026',
        follow_redirects=False)

    assert reponse.status_code == 302
    assert '/vue_mensuelle' in reponse.headers['Location']
    _assert_aucun_document(reponse)

    # Contrôle positif : la fiche d'un salarié de son secteur reste exportable.
    with app.app_context():
        _verrouiller_fiche(db, sample_users['salarie_id'], mois=1, annee=2026)
    reponse = client.get(
        f"/export_pdf_mensuel?user_id={sample_users['salarie_id']}&mois=1&annee=2026")
    assert reponse.status_code == 200
    assert reponse.headers['Content-Type'] == 'application/pdf'
    _deconnexion(client)
