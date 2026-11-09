"""Tests PDF des plannings théoriques actifs : accès et versions remplacées."""
from datetime import datetime
from io import BytesIO

import pdfplumber

from tests.test_planning import _creer_salarie_autre_secteur
from blueprints.planning import _selectionner_plannings_en_vigueur


def _ajouter_planning(db, uid, periode, alternance, date_debut, debut):
    cur = db.execute("""INSERT INTO planning_theorique
        (user_id,type_periode,type_alternance,date_debut_validite,
         lundi_matin_debut,lundi_matin_fin,total_hebdo)
        VALUES(?,?,?,?,?,'12:00',3)""",
        (uid,periode,alternance,date_debut,debut))
    db.commit()
    return cur.lastrowid


def test_export_pdf_refuse_aux_anonymes(client, sample_users):
    r = client.get(f"/planning_theorique/pdf?user_id={sample_users['salarie_id']}")
    assert r.status_code == 302
    assert '/login' in r.headers['Location']


def test_export_pdf_refuse_a_un_salarie_pour_un_collegue(auth_client, sample_users):
    r = auth_client.get(f"/planning_theorique/pdf?user_id={sample_users['responsable_id']}")
    assert r.status_code == 403


def test_export_pdf_refuse_a_un_responsable_hors_secteur(resp_client, db):
    uid = _creer_salarie_autre_secteur(db)
    r = resp_client.get(f'/planning_theorique/pdf?user_id={uid}')
    assert r.status_code == 403


def test_export_pdf_autorise_pour_soi(auth_client, db, sample_users):
    uid = sample_users['salarie_id']
    _ajouter_planning(db,uid,'periode_scolaire','fixe','2024-01-01','07:00')
    r = auth_client.get(f'/planning_theorique/pdf?user_id={uid}')
    assert r.status_code == 200
    assert r.data.startswith(b'%PDF')
    assert r.mimetype == 'application/pdf'


def test_export_pdf_autorise_pour_direction(admin_client, db, sample_users):
    uid = sample_users['salarie_id']
    _ajouter_planning(db,uid,'periode_scolaire','fixe','2024-01-01','07:00')
    r = admin_client.get(f'/planning_theorique/pdf?user_id={uid}')
    assert r.status_code == 200
    assert r.data.startswith(b'%PDF')


def test_export_ne_reprend_ni_anciennes_ni_futures_versions(auth_client, db, sample_users):
    uid = sample_users['salarie_id']
    _ajouter_planning(db,uid,'periode_scolaire','fixe','2024-01-01','07:00')
    _ajouter_planning(db,uid,'periode_scolaire','fixe','2025-01-01','08:00')
    _ajouter_planning(db,uid,'periode_scolaire','fixe','2099-01-01','09:00')
    pdf = auth_client.get(f'/planning_theorique/pdf?user_id={uid}')
    assert pdf.status_code == 200
    with pdfplumber.open(BytesIO(pdf.data)) as document:
        contenu = '\n'.join(page.extract_text() or '' for page in document.pages)
    assert '08:00' in contenu
    assert '07:00' not in contenu
    assert '09:00' not in contenu


def test_alternance_par_periode_ne_ressort_pas_un_ancien_scolaire(db, sample_users):
    uid = sample_users['salarie_id']
    db.execute("""INSERT INTO alternance_reference
        (user_id,date_reference,date_debut_validite) VALUES(?, '2025-01-06','2025-01-06')""",
        (uid,))
    _ajouter_planning(db,uid,'periode_scolaire','semaine_1','2025-01-06','07:00')
    _ajouter_planning(db,uid,'periode_scolaire','semaine_2','2025-01-06','08:00')
    _ajouter_planning(db,uid,'vacances','semaine_1','2025-01-06','09:00')
    _ajouter_planning(db,uid,'vacances','semaine_2','2025-01-06','10:00')
    nouveau = _ajouter_planning(db,uid,'periode_scolaire','fixe','2026-01-01','11:00')
    actifs = _selectionner_plannings_en_vigueur(db,uid,datetime.now().date().isoformat())
    scolaires = [p for p in actifs if p['type_periode']=='periode_scolaire']
    vacances = [p for p in actifs if p['type_periode']=='vacances']
    assert [p['id'] for p in scolaires] == [nouveau]
    assert {p['type_alternance'] for p in vacances} == {'semaine_1','semaine_2'}
