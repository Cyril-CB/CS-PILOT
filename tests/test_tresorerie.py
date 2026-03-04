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
