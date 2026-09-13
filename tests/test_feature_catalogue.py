"""Contrôles du catalogue sur un dépôt factice, sans importer l'application."""

import json

import pytest

from scripts.validate_feature_catalogue import validate


DOMAINS = ("interface", "temps", "rh", "finances", "association", "administration")


def _write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _feature(domain):
    return {
        "id": domain + ".exemple",
        "title": "Fonctionnalité de test",
        "purpose": "Vérifier le rattachement des routes au catalogue.",
        "example_requests": [],
        "capabilities": [],
        "entry_points": [],
        "implementation": {
            "route_files": [],
            "service_files": [],
            "templates": [],
            "tables": [],
            "tests": [],
            "docs": [],
        },
        "access": {
            "summary": "Accès factice.",
            "scope": "Dépôt temporaire.",
            "conditions": [],
            "sources": [],
        },
        "invariants": [],
        "extension_points": [],
        "related_features": [],
        "limitations": [],
    }


@pytest.fixture
def catalogue_repo(tmp_path):
    """Six domaines valides et un blueprint dont toutes les routes sont décrites."""
    catalogue = tmp_path / "docs/agent-catalogue"
    catalogue.mkdir(parents=True)
    blueprints = tmp_path / "blueprints"
    blueprints.mkdir()
    # Ces garde-fous échoueraient si le validateur importait les sources.
    (tmp_path / "database.py").write_text(
        "raise RuntimeError('Ne pas importer la base factice')\n", encoding="utf-8"
    )
    (blueprints / "demo.py").write_text(
        "raise RuntimeError('Ne pas importer le blueprint factice')\n"
        "from flask import Blueprint\n"
        "demo = Blueprint('catalogue_test', __name__)\n"
        "@demo.route('/')\n"
        "def index():\n"
        "    return 'Index'\n"
        "@demo.post('/enregistrer', endpoint='enregistrer')\n"
        "def sauvegarder():\n"
        "    return 'Enregistré'\n",
        encoding="utf-8",
    )
    manifest = {"domains": []}
    for domain in DOMAINS:
        feature = _feature(domain)
        if domain == "interface":
            feature["implementation"]["route_files"] = ["blueprints/demo.py"]
            feature["entry_points"] = [
                "catalogue_test.index", "catalogue_test.enregistrer"
            ]
        path = "docs/agent-catalogue/" + domain + ".json"
        manifest["domains"].append({"id": domain, "path": path})
        _write_json(tmp_path / path, {
            "schema_version": 1, "domain": domain, "features": [feature]
        })
    _write_json(catalogue / "catalogue.json", manifest)
    return tmp_path


def _add_route(root, decorator="get"):
    with (root / "blueprints/demo.py").open("a", encoding="utf-8") as source:
        source.write(
            "@demo." + decorator + "('/exporter')\n"
            "def exporter():\n"
            "    return 'Export'\n"
        )


def test_catalogue_accepte_toutes_les_routes_documentees(catalogue_repo):
    # L'endpoint explicite diffère du nom de fonction Python sauvegarder.
    errors, count, blueprint_count = validate(catalogue_repo)

    assert errors == []
    assert count == 6
    assert blueprint_count == 1


@pytest.mark.parametrize("decorator", ["route", "get"])
def test_catalogue_refuse_nouvelle_route_dans_fichier_deja_couvert(
    catalogue_repo, decorator
):
    assert validate(catalogue_repo)[0] == []
    _add_route(catalogue_repo, decorator)

    errors, _, _ = validate(catalogue_repo)

    assert errors == [
        "endpoint sans fiche (entry_points) : catalogue_test.exporter"
    ]


def test_catalogue_refuse_route_ajoutee_dans_service_deja_reference(catalogue_repo):
    service = catalogue_repo / "blueprints/service.py"
    service.write_text("def calculer():\n    return 1\n", encoding="utf-8")
    path = catalogue_repo / "docs/agent-catalogue/administration.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["features"][0]["implementation"]["service_files"] = ["blueprints/service.py"]
    _write_json(path, data)
    assert validate(catalogue_repo)[0] == []

    with service.open("a", encoding="utf-8") as source:
        source.write(
            "from flask import Blueprint\n"
            "service = Blueprint('service_test', __name__)\n"
            "@service.get('/diagnostic')\n"
            "def diagnostic():\n"
            "    return 'Diagnostic'\n"
        )

    errors, _, _ = validate(catalogue_repo)

    assert errors == [
        "endpoint sans fiche (entry_points) : service_test.diagnostic"
    ]


def test_catalogue_accepte_nouvelle_route_rattachee_a_fiche_existante(catalogue_repo):
    _add_route(catalogue_repo)
    path = catalogue_repo / "docs/agent-catalogue/interface.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["features"][0]["entry_points"].append("catalogue_test.exporter")
    _write_json(path, data)

    errors, count, blueprint_count = validate(catalogue_repo)

    assert errors == []
    assert count == 6
    assert blueprint_count == 1
