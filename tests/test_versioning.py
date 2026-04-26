from app_version import APP_VERSION


def test_inject_version_utilise_version_applicative_configuree(app):
    """La version applicative doit utiliser la valeur configurée."""
    import app as app_module

    app_module.invalidate_version_cache()

    with app.app_context():
        version_ctx = app_module.inject_version()

    assert version_ctx['app_version'] == APP_VERSION


def test_administration_affiche_version_1_1(admin_client):
    """La page administration doit afficher la version applicative configurée."""
    response = admin_client.get('/administration')

    assert response.status_code == 200
    assert APP_VERSION.encode() in response.data
