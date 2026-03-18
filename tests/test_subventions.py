import re


def test_subventions_affiche_benevoles_par_id_exact(admin_client, app, db):
    with app.app_context():
        db.execute(
            "INSERT INTO benevoles (id, nom, groupe) VALUES (?, ?, ?)",
            (1, 'BenOne', 'nouveau')
        )
        db.execute(
            "INSERT INTO benevoles (id, nom, groupe) VALUES (?, ?, ?)",
            (10, 'BenTen', 'nouveau')
        )
        db.execute(
            "INSERT INTO subventions (nom, benevoles_ids) VALUES (?, ?)",
            ('Subvention Test', '[10]')
        )
        db.commit()

    response = admin_client.get('/subventions')
    assert response.status_code == 200

    html = response.get_data(as_text=True)
    match = re.search(
        r'<span class="sv-benevoles-display" data-ids="\[10\]">(.*?)</span>\s*</td>',
        html,
        re.DOTALL
    )
    assert match is not None

    benevoles_cell = match.group(1)
    assert 'BenTen' in benevoles_cell
    assert 'BenOne' not in benevoles_cell
