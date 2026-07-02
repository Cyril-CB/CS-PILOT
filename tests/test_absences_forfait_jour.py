"""
Report des absences (arrêt maladie / congés) sur le calendrier forfait jours
de la direction.

La direction (forfait jours) tient son calendrier et son décompte dans
`presence_forfait_jour`, et non dans `heures_reelles` / les compteurs de congés
salariés. Une absence saisie pour un directeur doit donc :
- marquer les jours ouvrés concernés du bon type (maladie, conge_paye…) ;
- ajuster automatiquement le décompte (jours travaillés −, soldes CP/maladie +) ;
- ne PAS toucher aux tables/compteurs salariés.

Le comportement salarié doit rester strictement inchangé.
"""
from datetime import datetime, timedelta

import utils
import database


def _un_jour_ouvre(annee, mois, decalage=0):
    """(1 + decalage)-ième jour ouvré (lun-ven) du mois, format YYYY-MM-DD."""
    jour = datetime(annee, mois, 1)
    trouves = 0
    while True:
        if jour.weekday() < 5:
            if trouves == decalage:
                return jour.strftime('%Y-%m-%d')
            trouves += 1
        jour += timedelta(days=1)


def _jours_ouvres_attendus(annee):
    """Nombre de jours lun-ven de l'année (aucun férié dans la base de test)."""
    n = 0
    jour = datetime(annee, 1, 1)
    fin = datetime(annee, 12, 31)
    while jour <= fin:
        if jour.weekday() < 5:
            n += 1
        jour += timedelta(days=1)
    return n


def _type_du_jour(app, user_id, date):
    with app.app_context():
        conn = database.get_db()
        row = conn.execute(
            "SELECT type_journee FROM presence_forfait_jour WHERE user_id = ? AND date = ?",
            (user_id, date)
        ).fetchone()
        conn.close()
    return row['type_journee'] if row else None


def _compte(app, table, user_id, date=None):
    with app.app_context():
        conn = database.get_db()
        if date is None:
            row = conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE user_id = ?", (user_id,)).fetchone()
        else:
            row = conn.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE user_id = ? AND date = ?", (user_id, date)
            ).fetchone()
        conn.close()
    return row['n']


def test_arret_maladie_directeur_reporte_sur_forfait(app, admin_client, sample_users):
    """Un arrêt maladie saisi pour un directeur apparaît sur son forfait jours et
    ajuste le décompte, sans écrire dans heures_reelles."""
    annee = 2026
    jour = _un_jour_ouvre(annee, 3)
    uid = sample_users['directeur_id']

    resp = admin_client.post('/absences', data={
        'user_id': uid, 'motif': 'Arrêt maladie',
        'date_debut': jour, 'date_fin': jour,
    }, follow_redirects=True)
    assert resp.status_code == 200

    # Marqué 'maladie' sur le calendrier forfait
    assert _type_du_jour(app, uid, jour) == 'maladie'

    # Décompte ajusté : 1 jour maladie, 1 jour travaillé de moins
    with app.app_context():
        stats = utils.calculer_stats_forfait_jour(uid, annee)
    assert stats['maladie'] == 1
    assert stats['travaille'] == _jours_ouvres_attendus(annee) - 1

    # Rien dans heures_reelles (table des salariés)
    assert _compte(app, 'heures_reelles', uid, jour) == 0


def test_conge_paye_directeur_reporte_sans_toucher_compteurs_salaries(app, admin_client, db, sample_users):
    """Un congé payé pour un directeur marque le forfait (conge_paye) et décrémente
    le solde CP du décompte, sans toucher aux compteurs de congés salariés."""
    annee = 2026
    jour = _un_jour_ouvre(annee, 4)
    uid = sample_users['directeur_id']

    cp_avant = db.execute("SELECT cp_pris FROM users WHERE id = ?", (uid,)).fetchone()['cp_pris']

    admin_client.post('/absences', data={
        'user_id': uid, 'motif': 'Congé payé',
        'date_debut': jour, 'date_fin': jour,
    }, follow_redirects=True)

    assert _type_du_jour(app, uid, jour) == 'conge_paye'

    with app.app_context():
        stats = utils.calculer_stats_forfait_jour(uid, annee)
    assert stats['conge_paye'] == 1
    assert stats['soldes']['conges_payes_restants'] == 25 - 1

    # Les compteurs de congés salariés du directeur n'ont pas bougé
    cp_apres = db.execute("SELECT cp_pris FROM users WHERE id = ?", (uid,)).fetchone()['cp_pris']
    assert (cp_apres or 0) == (cp_avant or 0)


def test_suppression_absence_directeur_repasse_en_travaille(app, admin_client, db, sample_users):
    """Supprimer l'absence d'un directeur repasse les jours concernés en travaillé."""
    annee = 2026
    jour = _un_jour_ouvre(annee, 5)
    uid = sample_users['directeur_id']

    admin_client.post('/absences', data={
        'user_id': uid, 'motif': 'Arrêt maladie',
        'date_debut': jour, 'date_fin': jour,
    }, follow_redirects=True)
    assert _type_du_jour(app, uid, jour) == 'maladie'

    absence_id = db.execute(
        "SELECT id FROM absences WHERE user_id = ? ORDER BY id DESC LIMIT 1", (uid,)
    ).fetchone()['id']
    resp = admin_client.post(f'/absences/supprimer/{absence_id}', follow_redirects=True)
    assert resp.status_code == 200

    # Le jour est de nouveau 'travaille', et le décompte maladie est revenu à 0
    assert _type_du_jour(app, uid, jour) == 'travaille'
    with app.app_context():
        stats = utils.calculer_stats_forfait_jour(uid, annee)
    assert stats['maladie'] == 0
    assert stats['travaille'] == _jours_ouvres_attendus(annee)


def test_arret_maladie_salarie_reste_sur_heures_reelles(app, admin_client, sample_users):
    """Le comportement salarié est inchangé : l'absence va sur heures_reelles et
    RIEN n'est écrit sur le calendrier forfait jours."""
    jour = _un_jour_ouvre(2026, 6)
    uid = sample_users['salarie_id']

    admin_client.post('/absences', data={
        'user_id': uid, 'motif': 'Arrêt maladie',
        'date_debut': jour, 'date_fin': jour,
    }, follow_redirects=True)

    with app.app_context():
        conn = database.get_db()
        row = conn.execute(
            "SELECT type_saisie FROM heures_reelles WHERE user_id = ? AND date = ?", (uid, jour)
        ).fetchone()
        conn.close()
    assert row is not None and row['type_saisie'] == 'absence'

    # Aucun report sur le forfait jours pour un salarié
    assert _compte(app, 'presence_forfait_jour', uid) == 0
