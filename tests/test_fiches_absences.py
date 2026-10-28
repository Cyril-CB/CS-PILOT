"""Clôture automatique des fiches entièrement absentes : cas métier et sécurité."""
from datetime import date, datetime, timedelta

from fiches_absences import (cloturer_mois_absences_completes,
                            salarie_absent_a_date)
from tests.test_fiches_versions import client_role, fiche_complete


MOIS, ANNEE = 8, 2026


def _absence_mois(db, uid, fin='2026-08-31', debut='2026-08-01'):
    """Une absence enregistrée et effectivement projetée sur le calendrier."""
    cur = db.execute("""
        INSERT INTO absences (user_id, motif, date_debut, date_fin, jours_ouvres, saisi_par)
        VALUES (?, 'Arrêt maladie', ?, ?, 21, 1)
    """, (uid, debut, fin))
    absence_id = cur.lastrowid
    jour = date.fromisoformat(debut)
    while jour <= date.fromisoformat(fin):
        if jour.weekday() < 5:
            db.execute("""
                INSERT INTO heures_reelles
                    (user_id, date, declaration_conforme, type_saisie, commentaire)
                VALUES (?, ?, 1, 'absence', ?)
            """, (uid, jour.isoformat(), f"Absence #{absence_id} - Arrêt maladie"))
        jour += timedelta(days=1)
    db.commit()
    return absence_id


def _etat(db, uid):
    return db.execute("SELECT * FROM validations WHERE user_id=? AND mois=? AND annee=?",
                      (uid, MOIS, ANNEE)).fetchone()


def test_cloture_seulement_apres_fin_de_mois_et_idempotence(
        app, db, sample_users, sample_contrat, sample_planning):
    uid = sample_users['salarie_id']
    _absence_mois(db, uid)
    assert cloturer_mois_absences_completes(db, MOIS, ANNEE, date(2026, 8, 31)) == 0
    assert _etat(db, uid) is None
    assert cloturer_mois_absences_completes(db, MOIS, ANNEE, date(2026, 9, 1)) == 1
    db.commit()
    v = _etat(db, uid)
    assert v['bloque'] == 1
    assert v['circuit_version'] == 3
    assert v['version_courante_id'] is not None
    assert v['validation_salarie'] is None
    assert v['validation_responsable'] is None
    assert v['validation_directeur'] is None
    assert db.execute("""
        SELECT COUNT(*) FROM fiches_evenements WHERE user_id=? AND mois=?
          AND annee=? AND evenement='cloture_absence_complete'
    """, (uid, MOIS, ANNEE)).fetchone()[0] == 1
    assert cloturer_mois_absences_completes(db, MOIS, ANNEE, date(2026, 9, 2)) == 0
    assert db.execute("SELECT COUNT(*) FROM fiches_evenements WHERE evenement='cloture_absence_complete'").fetchone()[0] == 1


def test_une_seule_journee_travaillee_bloque_la_cloture(
        app, db, sample_users, sample_contrat, sample_planning):
    uid = sample_users['salarie_id']
    _absence_mois(db, uid)
    db.execute("""UPDATE heures_reelles SET type_saisie='normal',
                  declaration_conforme=1 WHERE user_id=? AND date='2026-08-03'""", (uid,))
    db.commit()
    assert cloturer_mois_absences_completes(db, MOIS, ANNEE, date(2026, 9, 1)) == 0
    assert _etat(db, uid) is None


def test_absence_partielle_ne_cloture_pas(
        app, db, sample_users, sample_contrat, sample_planning):
    uid = sample_users['salarie_id']
    _absence_mois(db, uid, fin='2026-08-14')
    assert cloturer_mois_absences_completes(db, MOIS, ANNEE, date(2026, 9, 1)) == 0
    assert _etat(db, uid) is None


def test_ne_pas_remplacer_une_validation_ou_recloturer_apres_reouverture(
        app, db, sample_users, sample_contrat, sample_planning):
    uid = sample_users['salarie_id']
    _absence_mois(db, uid)
    db.execute("INSERT INTO validations (user_id, mois, annee, validation_salarie) VALUES (?, ?, ?, 'Accord existant')",
               (uid, MOIS, ANNEE))
    db.commit()
    assert cloturer_mois_absences_completes(db, MOIS, ANNEE, date(2026, 9, 1)) == 0
    db.execute('DELETE FROM validations WHERE user_id=? AND mois=? AND annee=?',
               (uid, MOIS, ANNEE))
    db.execute("""INSERT INTO fiches_evenements
                (user_id, annee, mois, evenement, date_evenement, details)
                VALUES (?, ?, ?, 'reouverture', '2026-09-01', '{}')""",
               (uid, ANNEE, MOIS))
    db.commit()
    assert cloturer_mois_absences_completes(db, MOIS, ANNEE, date(2026, 9, 1)) == 0
    assert _etat(db, uid) is None


def test_ouverture_suivi_declenche_cloture(
        app, db, sample_users, sample_contrat, sample_planning):
    uid = sample_users['salarie_id']
    _absence_mois(db, uid)
    direction = client_role(app, sample_users, 'directeur')
    response = direction.get('/vue_ensemble_validation?mois=8&annee=2026')
    assert response.status_code == 200
    assert _etat(db, uid)['circuit_version'] == 3
    assert 'Clôturée — absence complète'.encode() in response.data


def test_suspend_reprise_relances_pendant_absence(
        app, db, sample_users, fiche_complete, monkeypatch):
    import email_service
    uid = sample_users['salarie_id']
    db.execute("UPDATE users SET email='test@example.invalid', email_notifications_enabled=1 WHERE id=?", (uid,))
    db.commit()
    direction = client_role(app, sample_users, 'directeur')
    monkeypatch.setattr('utils.maintenant', lambda: datetime(2026, 10, 27, 13))
    monkeypatch.setattr('blueprints.notifications.is_email_configured', lambda: True)
    monkeypatch.setattr(email_service, 'peut_envoyer_email', lambda actor_id: (True, 'test@example.invalid'))
    envois = []
    monkeypatch.setattr(email_service, 'notifier_relance_fiche',
                        lambda *args, **kwargs: (envois.append(args) or True, 'Test'))
    data = {'mois': MOIS, 'annee': ANNEE}
    assert direction.post('/api/email/relance_validation', json=data).status_code == 200
    assert any(a[-2] == uid for a in envois)
    envois.clear()
    absence_id = _absence_mois(db, uid, debut='2026-10-27', fin='2026-10-27')
    assert salarie_absent_a_date(db, uid, date(2026, 10, 27))
    assert direction.post('/api/email/relance_validation', json=data).status_code == 200
    assert not any(a[-2] == uid for a in envois)
    db.execute('DELETE FROM heures_reelles WHERE user_id=? AND date=?', (uid, '2026-10-27'))
    db.execute('DELETE FROM absences WHERE id=?', (absence_id,))
    db.commit()
    envois.clear()
    assert direction.post('/api/email/relance_validation', json=data).status_code == 200
    assert any(a[-2] == uid for a in envois)


def test_pdf_cloture_absence_complete_ne_simule_pas_des_signatures(
        app, db, sample_users, sample_contrat, sample_planning):
    from tests.test_export_pdf_mensuel import _texte_pdf
    uid = sample_users['salarie_id']
    _absence_mois(db, uid)
    assert cloturer_mois_absences_completes(db, MOIS, ANNEE, date(2026, 9, 1)) == 1
    db.commit()
    direction = client_role(app, sample_users, 'directeur')
    response = direction.get(
        f'/export_pdf_mensuel?user_id={uid}&mois={MOIS}&annee={ANNEE}'
    )
    assert response.status_code == 200
    assert response.headers['Content-Type'] == 'application/pdf'
    contenu = _texte_pdf(response.data)
    assert 'administrative automatique' in contenu
    # ReportLab peut répartir un paragraphe sur plusieurs objets Tj.
    from tests.test_export_pdf_mensuel import _cellules
    assert 'Aucune signature' in ' '.join(_cellules(contenu))
    assert 'Signature Salari' not in contenu
    assert 'Circuit : Salari' not in contenu


def test_pdf_circuit_ordinaire_conserve_zones_de_signature(
        app, db, sample_users, fiche_complete):
    from tests.test_export_pdf_mensuel import _texte_pdf
    from tests.test_fiches_versions import signer
    uid = sample_users['salarie_id']
    for role in ('salarie', 'responsable', 'directeur'):
        response = signer(client_role(app, sample_users, role), uid)
        assert response.status_code == 302
    direction = client_role(app, sample_users, 'directeur')
    response = direction.get(
        f'/export_pdf_mensuel?user_id={uid}&mois={MOIS}&annee={ANNEE}'
    )
    assert response.status_code == 200
    contenu = _texte_pdf(response.data)
    assert 'Signature Salari' in contenu
    assert 'Circuit : Salari' in contenu
    assert 'administrative automatique' not in contenu
