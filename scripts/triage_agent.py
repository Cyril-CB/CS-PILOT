#!/usr/bin/env python3
"""Décision déterministe sur une évaluation déjà justifiée par l'agent.

Ce script ne lit aucune boîte et ne classe pas le langage naturel. Il ne confère
aucune autorisation d'envoi, de développement ou d'accès à des données.
"""

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FLAGS = {"source_verifiee", "integrite_verifiee", "contenu_suspect",
         "doublon", "conflit_reference", "action_interdite", "acces_manquant",
         "besoin_complet", "preuves_completes"}
FIELDS = FLAGS | {"couverture", "risque", "notes"}


def load_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Clé JSON dupliquée : " + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique)


def evaluer(evaluation, grille=None):
    """Refuser les évaluations incomplètes plutôt que leur inventer des défauts."""
    grille = grille if grille is not None else load_json(
        ROOT / "docs/agent-demandes/grille-v1.json")
    if not isinstance(evaluation, dict) or set(evaluation) != FIELDS:
        raise ValueError("Champs d'évaluation manquants ou inconnus")
    if any(type(evaluation[k]) is not bool for k in FLAGS):
        raise ValueError("Les contrôles doivent être des booléens explicites")
    if evaluation["couverture"] not in {"complete", "partielle", "absente"}:
        raise ValueError("Couverture inconnue")
    if evaluation["risque"] not in {"faible", "modere", "eleve"}:
        raise ValueError("Risque inconnu")
    notes = evaluation["notes"]
    criteres = grille["criteres"]
    if not isinstance(notes, dict) or set(notes) != set(criteres):
        raise ValueError("Notes manquantes ou inconnues")
    if any(type(n) is not int or n not in range(5) for n in notes.values()):
        raise ValueError("Chaque note doit être un entier de 0 à 4")
    if sum(c["poids"] for c in criteres.values()) != 100:
        raise ValueError("Les poids doivent totaliser 100")
    score = sum(notes[k] * c["poids"] / 4 for k, c in criteres.items())
    e = evaluation
    if (not e["source_verifiee"] or not e["integrite_verifiee"]
            or e["contenu_suspect"] or e["conflit_reference"]):
        decision = "quarantaine"
    elif e["doublon"]:
        decision = "rattacher_doublon"
    elif e["action_interdite"]:
        decision = "refuser"
    elif e["acces_manquant"]:
        decision = "clarifier_acces"
    elif e["couverture"] == "complete":
        decision = "orienter_existant"
    elif not e["besoin_complet"] or not e["preuves_completes"]:
        decision = "clarifier"
    elif e["risque"] == "eleve":
        decision = "validation_humaine"
    elif score < grille["seuil_developpement"]:
        decision = "reporter"
    elif e["couverture"] == "partielle":
        decision = "ameliorer_existant"
    else:
        decision = "creer_module"
    return {"grille_version": grille["version"], "decision": decision,
            "score": score, "developpement_eligible": decision in {
                "ameliorer_existant", "creer_module"}}


def calibrer(path):
    cas = load_json(path)["cas"]
    erreurs = []
    for exemple in cas:
        resultat = evaluer(exemple["evaluation"])
        if resultat["decision"] != exemple["attendu"]:
            erreurs.append({"id": exemple["id"], "attendu": exemple["attendu"],
                            "obtenu": resultat["decision"]})
    return {"cas": len(cas), "erreurs": erreurs, "ok": not erreurs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--evaluation", type=Path)
    group.add_argument("--calibration", type=Path)
    args = parser.parse_args()
    try:
        result = (evaluer(load_json(args.evaluation)) if args.evaluation
                  else calibrer(args.calibration))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"ok": False, "erreur": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
