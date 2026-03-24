def test_inject_version_utilise_prefix_1_1(app, monkeypatch):
    """La version applicative doit utiliser le préfixe 1.1."""
    import app as app_module
    import migration_manager

    app_module.invalidate_version_cache()
    monkeypatch.setattr(migration_manager, 'get_version_actuelle', lambda: '1234')

    with app.app_context():
        version_ctx = app_module.inject_version()

    assert version_ctx['app_version'] == '1.1.1234'


def test_administration_affiche_version_1_1(admin_client):
    """La page administration doit afficher une version 1.1.xxxx."""
    response = admin_client.get('/administration')

    assert response.status_code == 200
    assert b'1.1.' in response.data
