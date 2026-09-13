#!/usr/bin/env python3
"""Valider le catalogue sans importer Flask, ouvrir une base ou lire les données.

Usage : python scripts/validate_feature_catalogue.py [--root CHEMIN_DEPOT]

Le schéma JSON décrit les fichiers de domaine ; ce contrôle sans dépendance en
vérifie les formes puis les références au dépôt. L'analyse statique des routes
reconnaît Blueprint('nom') et les décorateurs route/get/post/put/patch/delete.
Chaque endpoint ainsi découvert doit figurer dans les entry_points d'une fiche,
même si son fichier est déjà référencé ailleurs dans le catalogue.
Les tables sont des noms déclarés par CREATE TABLE/VIEW dans database.py, les
migrations et les helpers Python racine (schémas délégués). Ce n'est ni une
preuve du schéma déployé ni une validation des règles métier et permissions.
"""

import argparse
import ast
import json
from pathlib import Path, PurePosixPath
import re
import sys


DOMAINS = {"interface", "temps", "rh", "finances", "association", "administration"}
FEATURE_FIELDS = {
    "id", "title", "purpose", "example_requests", "capabilities", "entry_points",
    "implementation", "access", "invariants", "extension_points", "related_features",
    "limitations",
}
IMPLEMENTATION_FIELDS = {"route_files", "service_files", "templates", "tables", "tests", "docs"}
ACCESS_FIELDS = {"summary", "scope", "conditions", "sources"}
FEATURE_ID = re.compile(
    r"(?:interface|temps|rh|finances|association|administration)\.[a-z][a-z0-9]*(?:_[a-z0-9]+)*\Z"
)
ENDPOINT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\Z")
TABLE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
CREATE_TABLE = re.compile(
    r"\bCREATE\s+(?:(?:TEMP(?:ORARY)?|VIRTUAL)\s+)?(?:TABLE|VIEW)\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?[\"`\[]?([A-Za-z_][A-Za-z0-9_]*)[\"`\]]?\s*(?:\(|AS\b)",
    re.IGNORECASE,
)
ROUTE_METHODS = {"route", "get", "post", "put", "patch", "delete", "head", "options"}


def reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("clé JSON dupliquée : " + key)
        result[key] = value
    return result


def read_json(path, errors):
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys)
    except (OSError, UnicodeError, ValueError) as exc:
        errors.append("{} : {}".format(path, exc))
        return None


def object_fields(value, expected, label, errors):
    if not isinstance(value, dict):
        errors.append(label + " : objet attendu")
        return False
    missing, extra = expected - value.keys(), value.keys() - expected
    if missing:
        errors.append(label + " : champs manquants " + ", ".join(sorted(missing)))
    if extra:
        errors.append(label + " : champs inconnus " + ", ".join(sorted(extra)))
    return not missing and not extra


def text_value(value, label, errors):
    if not isinstance(value, str) or not value.strip():
        errors.append(label + " : chaîne non vide attendue")
        return False
    return True


def text_list(value, label, errors, pattern=None):
    if not isinstance(value, list):
        errors.append(label + " : liste attendue")
        return []
    result = []
    for index, item in enumerate(value):
        item_label = "{}[{}]".format(label, index)
        if not text_value(item, item_label, errors):
            continue
        if item in result:
            errors.append(item_label + " : valeur dupliquée " + item)
        if pattern and not pattern.fullmatch(item):
            errors.append(item_label + " : format invalide " + item)
        result.append(item)
    return result


def repository_file(root, value, label, errors):
    if not text_value(value, label, errors):
        return None
    parts = value.split("/")
    if (PurePosixPath(value).is_absolute() or any(p in {"", ".", ".."} for p in parts)
            or any(char in value for char in "\\*?[]:") or value != value.strip()):
        errors.append(label + " : chemin relatif exact requis : " + value)
        return None
    try:
        path = (root / value).resolve()
        path.relative_to(root)
        if not path.is_file():
            errors.append(label + " : fichier absent : " + value)
            return None
        return path
    except (OSError, RuntimeError, ValueError):
        errors.append(label + " : chemin hors dépôt ou invalide : " + value)
        return None


def path_list(root, value, label, errors, category=None):
    paths = text_list(value, label, errors)
    for item in paths:
        path = repository_file(root, item, label, errors)
        if path is None:
            continue
        parts = PurePosixPath(item).parts
        valid = True
        if category == "route_files":
            valid = path.suffix == ".py"
        elif category == "templates":
            valid = parts[0] == "templates"
        elif category == "tests":
            valid = parts[0] == "tests" and path.suffix in {".py", ".js", ".cjs", ".mjs"}
        elif category == "docs":
            valid = parts[0] == "docs" or (len(parts) == 1 and path.suffix in {".md", ".rst", ".txt"})
        if not valid:
            errors.append(label + " : fichier mal classé : " + item)
    return paths


def parse_python(path, errors):
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        errors.append("{} : analyse Python impossible : {}".format(path, exc))
        return None


def string_constant(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def module_symbols(tree):
    """Noms liés dans le module, sans confondre avec les variables des fonctions."""
    symbols = set()

    def visit(node):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.add(node.name)
            return
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            symbols.add(node.id)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name != "*":
                    symbols.add(alias.asname or alias.name.split(".")[0])
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)
    return symbols


def validate_manifest_references(root, manifest, errors):
    """Contrôler les points de lecture optionnels du manifeste, pas leur sémantique."""
    if "format" in manifest:
        format_info = manifest["format"]
        if not isinstance(format_info, dict):
            errors.append("catalogue.json.format : objet attendu")
        else:
            path = repository_file(root, format_info.get("domain_schema"), "catalogue.json.format.domain_schema", errors)
            if path is not None and not isinstance(read_json(path, errors), dict):
                errors.append("catalogue.json.format.domain_schema : objet JSON attendu")
    if "search_contract" in manifest:
        search = manifest["search_contract"]
        if not isinstance(search, dict):
            errors.append("catalogue.json.search_contract : objet attendu")
        else:
            path_list(root, search.get("tests"), "catalogue.json.search_contract.tests", errors, "tests")
            sources = search.get("sources")
            if not isinstance(sources, list):
                errors.append("catalogue.json.search_contract.sources : liste attendue")
            else:
                for index, source in enumerate(sources):
                    label = "catalogue.json.search_contract.sources[{}]".format(index)
                    if not isinstance(source, dict):
                        errors.append(label + " : objet attendu")
                        continue
                    path = repository_file(root, source.get("path"), label + ".path", errors)
                    symbols = text_list(source.get("symbols", []), label + ".symbols", errors)
                    if path is not None and symbols:
                        if path.suffix != ".py":
                            errors.append(label + " : symbols vérifiables uniquement pour une source Python")
                            continue
                        tree = parse_python(path, errors)
                        if tree is not None:
                            for missing in sorted(set(symbols) - module_symbols(tree)):
                                errors.append(label + " : symbole Python absent : " + missing)
    if "cross_cutting_sources" in manifest:
        sources = manifest["cross_cutting_sources"]
        if not isinstance(sources, list):
            errors.append("catalogue.json.cross_cutting_sources : liste attendue")
        else:
            for index, source in enumerate(sources):
                label = "catalogue.json.cross_cutting_sources[{}]".format(index)
                if not isinstance(source, dict):
                    errors.append(label + " : objet attendu")
                else:
                    path_list(root, source.get("paths"), label + ".paths", errors)


def route_endpoints(tree):
    """Associer le nom de variable au nom réel du Blueprint, sans importer."""
    blueprints, endpoints = {}, set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        name = call.func.id if isinstance(call.func, ast.Name) else getattr(call.func, "attr", None)
        if name != "Blueprint":
            continue
        blueprint_name = string_constant(call.args[0]) if call.args else next(
            (string_constant(k.value) for k in call.keywords if k.arg == "name"), None
        )
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if blueprint_name:
            for target in targets:
                if isinstance(target, ast.Name):
                    blueprints[target.id] = blueprint_name
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            owner = decorator.func.value
            if (decorator.func.attr not in ROUTE_METHODS or not isinstance(owner, ast.Name)
                    or owner.id not in blueprints):
                continue
            explicit = next((k.value for k in decorator.keywords if k.arg == "endpoint"), None)
            endpoint = string_constant(explicit) if explicit is not None else node.name
            if endpoint:
                endpoints.add(blueprints[owner.id] + "." + endpoint)
    return endpoints


def source_inventory(root, errors):
    blueprint_paths = sorted((root / "blueprints").glob("*.py"))
    if not blueprint_paths:
        errors.append("blueprints/ : aucun fichier Python trouvé")
    sources = set(blueprint_paths) | set(root.glob("*.py")) | set((root / "migrations").glob("*.py"))
    if not (root / "database.py").is_file():
        errors.append("database.py : fichier absent")
    endpoints, tables = {}, set()
    for path in sorted(sources):
        relative = path.relative_to(root).as_posix()
        if repository_file(root, relative, "source", errors) is None:
            continue
        tree = parse_python(path, errors)
        if tree is None:
            continue
        endpoints[relative] = route_endpoints(tree)
        if path.parent == root / "blueprints":
            continue
        # Seulement les littéraux Python : ne pas reconnaître une mention en commentaire.
        for node in ast.walk(tree):
            text = string_constant(node)
            if text:
                tables.update(match.group(1) for match in CREATE_TABLE.finditer(text))
    expected = {p.relative_to(root).as_posix() for p in blueprint_paths if p.name != "__init__.py"}
    return endpoints, tables, expected


def validate_feature(root, feature, domain, label, errors, endpoints, tables):
    if not object_fields(feature, FEATURE_FIELDS, label, errors):
        return None, set(), [], []
    feature_id = feature["id"]
    if text_value(feature_id, label + ".id", errors):
        if not FEATURE_ID.fullmatch(feature_id) or not feature_id.startswith(domain + "."):
            errors.append(label + ".id : identifiant invalide pour le domaine " + domain)
    else:
        feature_id = None
    for field in ("title", "purpose"):
        text_value(feature[field], label + "." + field, errors)
    for field in ("example_requests", "capabilities", "invariants", "extension_points", "limitations"):
        text_list(feature[field], label + "." + field, errors)
    entries = text_list(feature["entry_points"], label + ".entry_points", errors, ENDPOINT)
    related = text_list(feature["related_features"], label + ".related_features", errors, FEATURE_ID)
    implementation = feature["implementation"]
    covered, route_files = set(), []
    if object_fields(implementation, IMPLEMENTATION_FIELDS, label + ".implementation", errors):
        for field in sorted(IMPLEMENTATION_FIELDS - {"tables"}):
            paths = path_list(root, implementation[field], label + ".implementation." + field, errors, field)
            if field in {"route_files", "service_files"}:
                covered.update(paths)
            if field == "route_files":
                route_files = paths
        for table in text_list(implementation["tables"], label + ".implementation.tables", errors, TABLE_NAME):
            if table not in tables:
                errors.append(label + " : table/vue sans déclaration CREATE vérifiée : " + table)
        available = set().union(*(endpoints.get(path, set()) for path in route_files))
        for entry in entries:
            if entry not in available:
                errors.append(label + " : endpoint absent des route_files : " + entry)
    access = feature["access"]
    if object_fields(access, ACCESS_FIELDS, label + ".access", errors):
        for field in ("summary", "scope"):
            text_value(access[field], label + ".access." + field, errors)
        text_list(access["conditions"], label + ".access.conditions", errors)
        path_list(root, access["sources"], label + ".access.sources", errors)
    return feature_id, covered, related, entries


def validate(root):
    errors = []
    manifest = read_json(root / "docs/agent-catalogue/catalogue.json", errors)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("domains"), list):
        errors.append("catalogue.json : objet avec liste domains attendu")
        return errors, 0, 0
    validate_manifest_references(root, manifest, errors)
    endpoints, tables, expected = source_inventory(root, errors)
    seen_domains, seen_paths, feature_ids, covered, relationships = set(), set(), set(), set(), []
    catalogued_endpoints = set()
    for index, domain_entry in enumerate(manifest["domains"]):
        label = "catalogue.json.domains[{}]".format(index)
        if not isinstance(domain_entry, dict):
            errors.append(label + " : objet attendu")
            continue
        domain = domain_entry.get("id")
        if not isinstance(domain, str) or domain not in DOMAINS:
            errors.append(label + " : domaine inconnu")
            continue
        if domain in seen_domains:
            errors.append(label + " : domaine dupliqué : " + domain)
        seen_domains.add(domain)
        path = repository_file(root, domain_entry.get("path"), label + ".path", errors)
        if path is None:
            continue
        if path in seen_paths:
            errors.append(label + " : fichier de domaine dupliqué")
        seen_paths.add(path)
        data = read_json(path, errors)
        if not object_fields(data, {"schema_version", "domain", "features"}, str(path), errors):
            continue
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            errors.append(str(path) + " : schema_version doit valoir 1")
        if data["domain"] != domain:
            errors.append(str(path) + " : domain ne correspond pas au manifeste")
        if not isinstance(data["features"], list) or not data["features"]:
            errors.append(str(path) + " : features doit être une liste non vide")
            continue
        for number, feature in enumerate(data["features"]):
            label = "{}.features[{}]".format(path.relative_to(root), number)
            feature_id, paths, related, entries = validate_feature(root, feature, domain, label, errors, endpoints, tables)
            covered.update(paths)
            catalogued_endpoints.update(entries)
            if feature_id:
                if feature_id in feature_ids:
                    errors.append(label + " : ID dupliqué : " + feature_id)
                feature_ids.add(feature_id)
                relationships.append((feature_id, related))
    for missing in sorted(DOMAINS - seen_domains):
        errors.append("catalogue.json : domaine manquant : " + missing)
    for feature_id, related in relationships:
        for target in related:
            if target not in feature_ids:
                errors.append(feature_id + " : related_features inconnu : " + target)
    for missing in sorted(expected - covered):
        errors.append("blueprint sans fiche (route_files/service_files) : " + missing)
    discovered_endpoints = set().union(*endpoints.values())
    for missing in sorted(discovered_endpoints - catalogued_endpoints):
        errors.append("endpoint sans fiche (entry_points) : " + missing)
    return errors, len(feature_ids), len(expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="racine du dépôt")
    args = parser.parse_args()
    errors, count, blueprint_count = validate(args.root.resolve())
    if errors:
        print("Catalogue invalide : {} erreur(s).".format(len(errors)), file=sys.stderr)
        for error in errors:
            print("- " + error, file=sys.stderr)
        return 1
    print("Catalogue valide : {} fonctionnalités, {} domaines, {} fichiers blueprints couverts.".format(
        count, len(DOMAINS), blueprint_count
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
