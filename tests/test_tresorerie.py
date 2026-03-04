"""Tests ciblés pour le module trésorerie."""
import io


def test_import_fec_filtre_tout_journal_an(admin_client, db):
    """Les écritures du journal AN sont ignorées, y compris en janvier."""
    fec_content = (
        "JournalCode\tJournalLib\tEcritureNum\tEcritureDate\tCompteNum\tCompteLib\tCompAuxNum\t"
        "CompAuxLib\tPieceRef\tEcritureLib\tDebit\tCredit\n"
        "AN\tA nouveaux\t1\t20250101\t120000\tRésultat\t\t\tAN-1\tA nouveaux\t0\t1000\n"
        "AN\tA nouveaux\t2\t20250101\t280000\tAmortissements\t\t\tAN-2\tA nouveaux\t500\t0\n"
        "AN\tA nouveaux\t3\t20250101\t701000\tReport produits\t\t\tAN-3\tA nouveaux\t0\t200\n"
        "AC\tAchats\t4\t20250115\t601000\tAchats\t\t\tFAC-1\tFacture achat\t300\t0\n"
    )
    data = {'fichier': (io.BytesIO(fec_content.encode('utf-8')), 'fec.txt')}

    resp = admin_client.post('/api/tresorerie/import_fec',
                             data=data, content_type='multipart/form-data')
    result = resp.get_json()

    assert resp.status_code == 200
    assert result['success'] is True
    assert result['nb_ecritures'] == 1

    rows = db.execute("SELECT compte_num FROM tresorerie_donnees ORDER BY compte_num").fetchall()
    comptes = [r['compte_num'] for r in rows]
    assert comptes == ['601000']


def test_supprimer_tous_comptes_tresorerie_n_efface_pas_autres_modules(admin_client, db):
    """La purge des comptes trésorerie n'efface ni les données trésorerie ni les autres modules."""
    db.execute("""
        INSERT INTO tresorerie_comptes (compte_num, libelle_original, libelle_affiche, type_compte, actif)
        VALUES ('601000', 'Achats', 'Achats', 'charge', 1)
    """)
    db.execute("""
        INSERT INTO tresorerie_comptes (compte_num, libelle_original, libelle_affiche, type_compte, actif)
        VALUES ('701000', 'Ventes', 'Ventes', 'produit', 1)
    """)
    db.execute("""
        INSERT INTO tresorerie_donnees (compte_num, annee, mois, montant)
        VALUES ('601000', 2025, 1, 123.45)
    """)
    db.execute("""
        INSERT INTO plan_comptable_general (compte_num, libelle)
        VALUES ('411000', 'Clients')
    """)
    db.commit()

    resp = admin_client.post('/api/tresorerie/comptes/supprimer_tous')
    result = resp.get_json()

    assert resp.status_code == 200
    assert result['success'] is True
    assert result['nb_supprimes'] == 2

    nb_comptes_treso = db.execute(
        "SELECT COUNT(*) AS n FROM tresorerie_comptes"
    ).fetchone()['n']
    nb_donnees_treso = db.execute(
        "SELECT COUNT(*) AS n FROM tresorerie_donnees"
    ).fetchone()['n']
    nb_pcg = db.execute(
        "SELECT COUNT(*) AS n FROM plan_comptable_general"
    ).fetchone()['n']

    assert nb_comptes_treso == 0
    assert nb_donnees_treso == 1
    assert nb_pcg == 1
