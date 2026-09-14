#!/usr/bin/env python3
"""Transitions pures de la file privée Work, sans réseau ni permission implicite.

Le résultat est un candidat : le coordinateur doit le publier dans Library avec
la version réellement lue (CAS) avant tout effet. Ce module ne fait aucun envoi,
ne lance aucun agent, ne fusionne aucune PR et ne garantit pas le CAS distant.
"""

import argparse
from copy import deepcopy
import json
import re

from scripts.triage_agent import evaluer, load_json


ETATS = {"recu", "quarantaine", "analyse", "attente_precisions",
         "attente_validation", "a_developper", "en_developpement", "en_revue",
         "a_corriger", "pret_recette", "integre_dev", "livre_main", "clos",
         "reporte", "refuse", "bloque_technique", "abandonne"}
TYPES_EFFETS = {"mail_precisions", "mail_suivi", "branche", "pr", "correction", "revue"}
ETATS_RESULTATS = {"confirme", "incertain", "echec_certain"}


def _texte_non_vide(value):
    return isinstance(value, str) and bool(value.strip())


def _valider_effets(effets):
    for cle, effet in effets.items():
        if (not _texte_non_vide(cle) or not isinstance(effet, dict)
                or not isinstance(effet.get("type"), str)
                or effet["type"] not in TYPES_EFFETS
                or not isinstance(effet.get("etat"), str)
                or effet["etat"] not in ETATS_RESULTATS | {"intention"}):
            raise ValueError("Effet invalide : clé, type ou état manquant/inconnu")
        if ((effet["etat"] != "intention" or "preuve" in effet)
                and not _texte_non_vide(effet.get("preuve"))):
            raise ValueError("Effet invalide : preuve absente ou vide")


def _hex(value, taille):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{%d}" % taille, value)


def nouvelle_file():
    return {"format": "cspilot.file-demandes", "version": 2,
            "actif": False, "maximum_developpements": 3,
            "dossiers": {}, "migrations_reservees": {}}


def occupe_creneau(dossier):
    # Une PR en attente de recette ou bloquée reste un développement en cours.
    return dossier["branche"] is not None and dossier["fusion_dev"] is None


def valider_file(file):
    if (not isinstance(file, dict) or file.get("format") != "cspilot.file-demandes"
            or type(file.get("version")) is not int or file["version"] != 2
            or type(file.get("actif")) is not bool
            or type(file.get("maximum_developpements")) is not int
            or not 1 <= file["maximum_developpements"] <= 3
            or not isinstance(file.get("dossiers"), dict)
            or not isinstance(file.get("migrations_reservees"), dict)):
        raise ValueError("File privée invalide")
    branches, prs = set(), set()
    for ref, d in file["dossiers"].items():
        if (not _hex(ref, 32) or not isinstance(d, dict)
                or not _hex(d.get("manifest_sha256"), 64)
                or d.get("etat") not in ETATS
                or type(d.get("version_perimetre")) is not int
                or d["version_perimetre"] < 1
                or type(d.get("source_verifiee")) is not bool
                or not isinstance(d.get("ressources"), list)
                or not d["ressources"]
                or any(not isinstance(r, str) or not r for r in d["ressources"])
                or not isinstance(d.get("dependances"), list)
                or any(r not in file["dossiers"] or r == ref for r in d["dependances"])
                or "verrou" not in d or "branche" not in d or "pr" not in d
                or "fusion_dev" not in d
                or not isinstance(d.get("evenements"), list)
                or any(not isinstance(e, str) or not e for e in d["evenements"])
                or not isinstance(d.get("effets"), dict)):
            raise ValueError("Dossier invalide : " + ref)
        _valider_effets(d["effets"])
        if d["verrou"] is not None and (not isinstance(d["verrou"], str) or not d["verrou"]):
            raise ValueError("Propriétaire de verrou invalide")
        if d["branche"] is not None:
            if d["branche"] != "feat/demande-" + ref or d["branche"] in branches:
                raise ValueError("Branche de dossier invalide ou dupliquée")
            branches.add(d["branche"])
        if d["pr"] is not None:
            if type(d["pr"]) is not int or d["pr"] < 1 or d["pr"] in prs or d["branche"] is None:
                raise ValueError("PR invalide ou partagée entre dossiers")
            prs.add(d["pr"])
        if d["fusion_dev"] is not None and (not _hex(d["fusion_dev"], 40) or d["pr"] is None):
            raise ValueError("Fusion dev sans preuve de PR")
        if d["fusion_dev"] is not None and d["etat"] not in {"integre_dev", "livre_main", "clos"}:
            raise ValueError("Fusion dev incompatible avec l'état du dossier")
        if d["etat"] in {"integre_dev", "livre_main"} and d["fusion_dev"] is None:
            raise ValueError("Intégration non démontrée")
    if sum(occupe_creneau(d) for d in file["dossiers"].values()) > file["maximum_developpements"]:
        raise ValueError("Plafond de développements dépassé")
    for numero, ref in file["migrations_reservees"].items():
        if not _hex(numero, 4) or not numero.isdigit() or ref not in file["dossiers"]:
            raise ValueError("Réservation de migration invalide")
    return file


def _copie_active(file):
    valider_file(file)
    if not file["actif"]:
        raise ValueError("File en pause")
    return deepcopy(file)


def enregistrer_proposition(file, reference, empreinte, source_verifiee=False):
    """Même référence/hash : doublon ; référence altérée : aucun écrasement."""
    resultat = _copie_active(file)
    if not _hex(reference, 32) or not _hex(empreinte, 64) or type(source_verifiee) is not bool:
        raise ValueError("Proposition invalide")
    precedent = resultat["dossiers"].get(reference)
    if precedent:
        if precedent["manifest_sha256"] != empreinte:
            raise ValueError("Conflit de référence : isoler le nouvel événement en quarantaine")
        return resultat, "doublon"
    resultat["dossiers"][reference] = {
        "manifest_sha256": empreinte, "source_verifiee": source_verifiee,
        "etat": "recu" if source_verifiee else "quarantaine",
        "version_perimetre": 1, "decision": None, "ressources": ["a_analyser"],
        "dependances": [], "verrou": None, "branche": None, "pr": None,
        "fusion_dev": None, "evenements": [], "effets": {},
    }
    return valider_file(resultat), "nouveau"


def prendre_dossier(file, reference, execution):
    resultat = _copie_active(file)
    if not isinstance(execution, str) or not execution:
        raise ValueError("Exécution non identifiée")
    d = resultat["dossiers"][reference]
    if d["verrou"] is not None:
        raise ValueError("Verrou existant : aucune reprise automatique")
    d["verrou"] = execution
    return resultat


def _detenir(file, reference, execution):
    resultat = _copie_active(file)
    d = resultat["dossiers"][reference]
    if not execution or d["verrou"] != execution:
        raise ValueError("Verrou du dossier non détenu")
    return resultat, d


def liberer_dossier(file, reference, execution):
    resultat, d = _detenir(file, reference, execution)
    d["verrou"] = None
    return resultat


def ajouter_reponse(file, reference, execution, message_id):
    resultat, d = _detenir(file, reference, execution)
    if not isinstance(message_id, str) or not message_id:
        raise ValueError("Identifiant de réponse absent")
    if message_id in d["evenements"]:
        return resultat, "doublon"
    d["evenements"].append(message_id)
    # La même référence n'est pas un doublon de réponse. Le coordinateur doit
    # encore analyser le texte nouveau et versionner les exigences si nécessaire.
    return resultat, "a_analyser"


def _conflit_ressources(a, b):
    for gauche in a:
        for droite in b:
            if (gauche == droite or gauche == "*" or droite == "*"
                    or gauche.startswith(droite.rstrip("/") + "/")
                    or droite.startswith(gauche.rstrip("/") + "/")):
                return True
    return False


def demarrer_developpement(file, reference, execution):
    resultat, d = _detenir(file, reference, execution)
    if d["etat"] != "a_developper" or not d["source_verifiee"]:
        raise ValueError("Dossier non éligible")
    decision = d.get("decision")
    if (not isinstance(decision, dict)
            or type(decision.get("version_perimetre")) is not int
            or decision["version_perimetre"] != d["version_perimetre"]):
        raise ValueError("Décision absente ou liée à un ancien périmètre")
    evaluation = decision.get("evaluation", {})
    calculee = evaluer(evaluation)
    if (not calculee["developpement_eligible"]
            or decision.get("decision") != calculee["decision"]
            or decision.get("score") != calculee["score"]):
        raise ValueError("Grille non favorable ou décision incohérente")
    if d["branche"] is not None or "a_analyser" in d["ressources"]:
        raise ValueError("Développement déjà réservé ou impacts non analysés")
    if any(resultat["dossiers"][r]["fusion_dev"] is None for r in d["dependances"]):
        raise ValueError("Dépendance non intégrée à dev")
    actifs = [v for k, v in resultat["dossiers"].items() if k != reference and occupe_creneau(v)]
    if len(actifs) >= resultat["maximum_developpements"]:
        raise ValueError("Trois développements sont déjà en cours")
    if any(_conflit_ressources(d["ressources"], autre["ressources"]) for autre in actifs):
        raise ValueError("Dépendance ou ressource commune : séquencer les développements")
    d["branche"] = "feat/demande-" + reference
    d["etat"] = "en_developpement"
    return valider_file(resultat)


def reserver_migration(file, reference, execution, versions_observees):
    resultat, d = _detenir(file, reference, execution)
    if not occupe_creneau(d) or "schema" not in d["ressources"]:
        raise ValueError("Le créneau exclusif de schéma est requis")
    # Le caller doit fournir main + dev + toutes les PR ouvertes fraîchement lus.
    if (not isinstance(versions_observees, list) or not versions_observees
            or any(not isinstance(v, str) or not re.fullmatch(r"[0-9]{4}", v) for v in versions_observees)):
        raise ValueError("Inventaire des migrations invalide")
    existante = [n for n, ref in resultat["migrations_reservees"].items() if ref == reference]
    if existante:
        raise ValueError("Réservation existante : vérifier sa reprise, ne pas en créer une autre")
    numero = max(map(int, versions_observees + list(resultat["migrations_reservees"]))) + 1
    if numero > 9999:
        raise ValueError("Numérotation épuisée")
    resultat["migrations_reservees"][f"{numero:04d}"] = reference
    return valider_file(resultat), f"{numero:04d}"


def preparer_effet(file, reference, execution, cle, type_effet):
    resultat, d = _detenir(file, reference, execution)
    if not d["source_verifiee"] or d["etat"] == "quarantaine":
        raise ValueError("Provenance non vérifiée")
    if not isinstance(type_effet, str) or type_effet not in TYPES_EFFETS:
        raise ValueError("Effet non autorisé")
    if not _texte_non_vide(cle) or cle in d["effets"]:
        raise ValueError("Effet déjà enregistré : réconcilier, ne pas répéter")
    if type_effet in {"branche", "pr"} and not occupe_creneau(d):
        raise ValueError("Créneau de développement non réservé")
    if type_effet == "pr" and (d["pr"] is not None or any(
            e["type"] == "pr" and e["etat"] != "echec_certain" for e in d["effets"].values())):
        raise ValueError("PR déjà enregistrée ou création à réconcilier")
    if type_effet in {"correction", "revue"} and d["pr"] is None:
        raise ValueError("PR absente")
    plafond = {"mail_precisions": 2, "correction": 3}.get(type_effet)
    if plafond is not None and sum(e["type"] == type_effet for e in d["effets"].values()) >= plafond:
        raise ValueError("Plafond de cycles atteint")
    d["effets"][cle] = {"type": type_effet, "etat": "intention"}
    return resultat


def resultat_effet(file, reference, execution, cle, etat, preuve):
    resultat, d = _detenir(file, reference, execution)
    effet = d["effets"][cle]
    if (effet["etat"] != "intention" or not isinstance(etat, str) or etat not in ETATS_RESULTATS
            or not _texte_non_vide(preuve)):
        raise ValueError("Résultat ou transition d'effet invalide")
    effet.update(etat=etat, preuve=preuve)
    return resultat


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verifier", required=True)
    args = parser.parse_args()
    try:
        file = valider_file(load_json(args.verifier))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({"ok": False, "erreur": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, "dossiers": len(file["dossiers"]),
                      "developpements": sum(occupe_creneau(d) for d in file["dossiers"].values())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
