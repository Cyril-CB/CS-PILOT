from app_version import APP_VERSION


def test_inject_version_utilise_version_applicative_configuree(app):
    """La version applicative doit utiliser la valeur configurée."""
    import app as app_module

    app_module.invalidate_version_cache()

    with app.app_context():
        version_ctx = app_module.inject_version()

    assert version_ctx['app_version'] == APP_VERSION


def test_invalidate_version_cache_recharge_la_version(app, monkeypatch):
    """Le cache de version doit être rechargé après invalidation."""
    import app as app_module

    app_module.invalidate_version_cache()
    monkeypatch.setattr(app_module, 'APP_VERSION', '1.1.502')

    with app.app_context():
        assert app_module.inject_version()['app_version'] == '1.1.502'

    monkeypatch.setattr(app_module, 'APP_VERSION', '1.1.503')

    with app.app_context():
        assert app_module.inject_version()['app_version'] == '1.1.502'

    app_module.invalidate_version_cache()

    with app.app_context():
        assert app_module.inject_version()['app_version'] == '1.1.503'


def test_administration_affiche_version_1_1(admin_client):
    """La page administration doit afficher la version applicative configurée."""
    response = admin_client.get('/administration')

    assert response.status_code == 200
    assert APP_VERSION.encode() in response.data
