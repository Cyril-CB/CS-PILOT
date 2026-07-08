"""
Fiche salarié (infos_salaries) : édition de la pesée et des points de compétence.

Les points de compétence peuvent comporter des décimales (ex. 4,25) : la
saisie ne doit plus être bloquée à un entier ni tronquée à l'enregistrement.
"""


def test_competence_accepte_les_decimales(admin_client, db, sample_users):
    uid = sample_users['salarie_id']
    admin_client.post('/infos_salaries/pesee', data={
        'user_id': uid, 'pesee': '100', 'competence': '4.25', 'maintien': '0',
    }, follow_redirects=True)
    row = db.execute("SELECT competence FROM users WHERE id = ?", (uid,)).fetchone()
    assert row['competence'] == 4.25


def test_competence_entiere_reste_valide(admin_client, db, sample_users):
    uid = sample_users['salarie_id']
    admin_client.post('/infos_salaries/pesee', data={
        'user_id': uid, 'pesee': '100', 'competence': '6', 'maintien': '0',
    }, follow_redirects=True)
    row = db.execute("SELECT competence FROM users WHERE id = ?", (uid,)).fetchone()
    assert row['competence'] == 6


def test_competence_vide_remet_a_null(admin_client, db, sample_users):
    uid = sample_users['salarie_id']
    db.execute("UPDATE users SET competence = 5 WHERE id = ?", (uid,))
    db.commit()
    admin_client.post('/infos_salaries/pesee', data={
        'user_id': uid, 'pesee': '100', 'competence': '', 'maintien': '0',
    }, follow_redirects=True)
    row = db.execute("SELECT competence FROM users WHERE id = ?", (uid,)).fetchone()
    assert row['competence'] is None
