"""Tests UI minimaux pour la page salles."""


def test_gestion_salles_utilise_toggle_dedie(admin_client, db):
    """Le formulaire admin des salles doit utiliser le toggle dédié à la page."""
    db.execute(
        "INSERT INTO salles (nom, capacite, description, couleur, active) VALUES (?, ?, ?, ?, ?)",
        ('Salle Polyvalente', 30, 'Test', '#2563eb', 1)
    )
    db.commit()

    resp = admin_client.get('/salles')
    html = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert "onclick=\"toggleSallesSection('section-salles')\"" in html
    assert "onclick=\"toggleSallesSection('section-resa')\"" in html
    assert "onclick=\"toggleSallesSection('section-rec')\"" in html
    assert "function toggleSallesSection(id)" in html
