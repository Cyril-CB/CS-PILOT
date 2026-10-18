"""Comparatifs réservés aux PDF de l'initial, sur données synthétiques."""
import io

import pdfplumber
import pytest


def lignes_pdf(data):
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return [row for page in pdf.pages for table in page.extract_tables() for row in table]


def montants(data, compte):
    return next(row[2:] for row in lignes_pdf(data) if row[0] == compte)


def saisir(db, secteur, annee, typ, compte, valeur):
    db.execute('''INSERT INTO budget_prev_saisies
        (type_budget, annee, secteur_id, compte_num, valeur_temp, valeur_def)
        VALUES (?, ?, ?, ?, 987654, ?)''', (typ, annee, secteur, compte, valeur))


@pytest.mark.parametrize('global_mode', [False, True])
def test_pdf_initial_comparatifs_et_aucune_mutation(db, admin_client, sample_users, global_mode):
    sid = sample_users['secteur_id']
    db.execute("INSERT INTO budget_prev_config_codes (code_analytique, secteur_id) VALUES ('PDF', ?)", (sid,))
    imp = db.execute("INSERT INTO bilan_fec_imports (fichier_nom, annee, nb_ecritures) VALUES ('synthetique.txt', 2025, 2)").lastrowid
    for compte, valeur in [('606000', 123), ('706000', 0)]:
        db.execute('''INSERT INTO bilan_fec_donnees
            (compte_num, libelle, code_analytique, annee, mois, montant, import_id)
            VALUES (?, ?, 'PDF', 2025, 12, ?, ?)''', (compte, compte, valeur, imp))
    for compte, initial_n1, actualise_n1, initial_n in [
        ('606000', 200, 250, 300), ('706000', 500, 450, 400),
        ('611000', 0, 0, 0), ('612000', None, 75, 100),
    ]:
        saisir(db, sid, 2026, 'initial', compte, initial_n1)
        saisir(db, sid, 2026, 'actualise', compte, actualise_n1)
        saisir(db, sid, 2027, 'initial', compte, initial_n)
    # Comptes présents seulement dans l'historique et initial N non saisi.
    saisir(db, sid, 2026, 'initial', '613000', 40)
    saisir(db, sid, 2026, 'actualise', '614000', 60)
    saisir(db, sid, 2027, 'initial', '615000', None)
    db.commit()
    avant = list(db.iterdump())
    scope = 'global=1' if global_mode else f'secteur_id={sid}'
    api = f'/api/budget-previsionnel/donnees?type_budget=initial&annee=2027&{scope}'
    ecran_avant = admin_client.get(api).get_json()
    r = admin_client.get(f'/api/budget-previsionnel/export-pdf?type_budget=initial&annee=2027&{scope}')
    assert r.status_code == 200 and r.mimetype == 'application/pdf'
    assert lignes_pdf(r.data)[0][2:] == [
        'N-2\n2025', 'N-1 initial\n2026', 'N-1 actualisé\n2026',
        'Initial N\n2027', 'Différence\ninitial N - N-1',
    ]
    assert montants(r.data, '606000') == ['123.00', '200.00', '250.00', '300.00', '+100.00']
    assert montants(r.data, '706000') == ['0.00', '500.00', '450.00', '400.00', '-100.00']
    assert montants(r.data, '611000') == ['0.00', '0.00', '0.00', '0.00', '+0.00']
    assert montants(r.data, '612000') == ['0.00', '0.00', '75.00', '100.00', '+100.00']
    assert montants(r.data, '613000') == ['0.00', '40.00', '0.00', '0.00', '-40.00']
    assert montants(r.data, '614000') == ['0.00', '0.00', '60.00', '0.00', '+0.00']
    assert montants(r.data, '615000') == ['0.00', '0.00', '0.00', '0.00', '+0.00']
    assert montants(r.data, 'Sous-total 60xxxx') == ['123.00', '200.00', '250.00', '300.00', '+100.00']
    assert montants(r.data, 'TOTAL CHARGES') == ['123.00', '240.00', '385.00', '400.00', '+160.00']
    assert montants(r.data, 'TOTAL PRODUITS') == ['0.00', '500.00', '450.00', '400.00', '-100.00']
    assert admin_client.get(api).get_json() == ecran_avant
    assert list(db.iterdump()) == avant


@pytest.mark.parametrize('valeur_autre', [None, 0, 50])
def test_pdf_initial_global_additionne_les_montants_et_remplace_les_absences_par_zero(db, admin_client, sample_users, valeur_autre):
    sid = sample_users['secteur_id']
    autre = db.execute("INSERT INTO secteurs (nom) VALUES ('Autre secteur PDF')").lastrowid
    for secteur, valeur in [(sid, 100), (autre, valeur_autre)]:
        for annee, typ in [(2026, 'initial'), (2026, 'actualise'), (2027, 'initial')]:
            saisir(db, secteur, annee, typ, '606000',
                   valeur * 2 if annee == 2027 and valeur is not None else valeur)
    db.commit()
    url = '/api/budget-previsionnel/export-pdf?type_budget=initial&annee=2027&'
    secteur_pdf = admin_client.get(url + f'secteur_id={sid}').data
    assert montants(secteur_pdf, '606000') == ['0.00', '100.00', '100.00', '200.00', '+100.00']
    global_pdf = admin_client.get(url + 'global=1').data
    total_n1 = 100 + (valeur_autre or 0)
    attendu = ['0.00', f'{total_n1:.2f}', f'{total_n1:.2f}',
               f'{total_n1 * 2:.2f}', f'{total_n1:+.2f}']
    assert montants(global_pdf, '606000') == attendu
    assert montants(global_pdf, 'TOTAL CHARGES') == attendu


def test_pdf_initial_responsable_limite_a_son_secteur(db, resp_client, sample_users):
    from app_options import set_option_bool
    set_option_bool('budget_previsionnel_responsable_autorise', True)
    sid = sample_users['secteur_id']
    autre = db.execute("INSERT INTO secteurs (nom) VALUES ('Secteur confidentiel PDF')").lastrowid
    for secteur, montant in [(sid, 100), (autre, 999)]:
        for annee, typ in [(2026, 'initial'), (2026, 'actualise'), (2027, 'initial')]:
            saisir(db, secteur, annee, typ, '606000', montant)
    db.commit()
    url = '/api/budget-previsionnel/export-pdf?type_budget=initial&annee=2027&'
    r = resp_client.get(url + f'secteur_id={autre}')
    assert r.status_code == 200
    assert montants(r.data, '606000') == ['0.00', '100.00', '100.00', '100.00', '+0.00']
    assert resp_client.get(url + 'global=1').status_code == 403
