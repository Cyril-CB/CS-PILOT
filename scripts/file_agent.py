#!/usr/bin/env python3
"""Transitions pures de la file privée Work, sans réseau ni permission implicite.

Le résultat est un candidat : le coordinateur doit le publier dans Library avec
la version réellement lue (CAS) avant tout effet. Ce module ne fait aucun envoi,
ne lance aucun agent, ne fusionne aucune PR et ne garantit pas le CAS distant.
"""

import argparse
from copy import deepcopy
from datetime import datetime
import json
import re

from scripts.triage_agent import evaluer, load_json


ETATS = {"recu", "quarantaine", "analyse", "attente_precisions",
         "attente_validation", "a_developper", "en_developpement", "en_revue",
         "a_corriger", "pret_recette", "integre_dev", "livre_main", "clos",
         "reporte", "refuse", "bloque_technique", "abandonne"}
TYPES_EFFETS = {"mail_precisions", "mail_suivi", "branche", "pr", "correction", "revue"}
ETATS_RESULTATS = {"confirme", "incertain", "echec_certain"}
ETATS_A_RECONCILIER = {"tentative", "incertain"}
EFFETS_DEVELOPPEMENT = {"branche", "pr", "correction", "revue"}


def _texte_non_vide(value):
    return isinstance(value, str) and bool(value.strip())


def _valider_effets(effets):
    for cle, effet in effets.items():
        if (not _texte_non_vide(cle) or not isinstance(effet, dict)
                or not isinstance(effet.get("type"), str)
                or effet["type"] not in TYPES_EFFETS
                or not isinstance(effet.get("etat"), str)
                or effet["etat"] not in ETATS_RESULTATS | {"intention", "tentative"}):
            raise ValueError("Effet invalide : clé, type ou état manquant/inconnu")
        if ((effet["etat"] in ETATS_RESULTATS or "preuve" in effet)
                and not _texte_non_vide(effet.get("preuve"))):
            raise ValueError("Effet invalide : preuve absente ou vide")
        if ((effet["etat"] == "tentative" or "execution_tentative" in effet)
                and (not _texte_non_vide(effet.get("execution_tentative"))
                     or "version_perimetre" not in effet)):
            raise ValueError("Effet invalide : propriétaire ou périmètre de tentative absent")
        if effet["etat"] == "intention" and "execution_tentative" in effet:
            raise ValueError("Effet invalide : une tentative ne redevient pas intention")
        if "version_perimetre" in effet and (type(effet["version_perimetre"]) is not int
                                             or effet["version_perimetre"] < 1):
            raise ValueError("Effet invalide : version de périmètre incorrecte")
        historique = effet.get("historique", [])
        if (not isinstance(historique, list)
                or any(not isinstance(entree, dict)
                       or not isinstance(entree.get("etat"), str)
                       or entree.get("etat") not in ETATS_A_RECONCILIER
                       or not _texte_non_vide(entree.get("preuve"))
                       or (entree["etat"] == "tentative"
                           and not _texte_non_vide(effet.get("execution_tentative")))
                       for entree in historique)
                or historique and effet["etat"] not in {"confirme", "echec_certain"}):
            raise ValueError("Effet invalide : historique de réconciliation incorrect")


def _hex(value, taille):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{%d}" % taille, value)


def _liste_textes(valeur, non_vide=False):
    return (isinstance(valeur, list) and (bool(valeur) or not non_vide)
            and all(_texte_non_vide(v) for v in valeur))


def _valider_instantane(p):
    """Contrat structurel de evolutions-v2 ; la vérité métier reste vérifiée en amont."""
    requis = {"version", "version_precedente", "source_evenement", "date", "resume",
              "exigences", "questions_ouvertes", "decision", "impacts"}
    if (not isinstance(p, dict) or not requis <= p.keys()
            or type(p["version"]) is not int or p["version"] < 1
            or not _liste_textes(p["source_evenement"], non_vide=True)
            or len(set(p["source_evenement"])) != len(p["source_evenement"])
            or not _texte_non_vide(p["resume"]) or not _texte_non_vide(p["date"])
            or not isinstance(p["exigences"], list)
            or not _liste_textes(p["questions_ouvertes"])
            or not isinstance(p["impacts"], dict)
            or not _liste_textes(p["impacts"].get("ressources"), non_vide=True)
            or not _liste_textes(p["impacts"].get("dependances"))):
        raise ValueError("Instantané du périmètre incomplet ou invalide")
    precedente = p["version_precedente"]
    if ((p["version"] == 1 and precedente is not None)
            or (p["version"] > 1 and (type(precedente) is not int
                                     or precedente != p["version"] - 1))):
        raise ValueError("Instantané : version précédente incorrecte")
    try:
        date = datetime.fromisoformat(p["date"])
    except ValueError:
        raise ValueError("Instantané : date incorrecte") from None
    if date.tzinfo is None:
        raise ValueError("Instantané : date sans fuseau")
    ids = set()
    for e in p["exigences"]:
        if (not isinstance(e, dict)
                or not _texte_non_vide(e.get("id_stable"))
                or e["id_stable"] in ids or not _texte_non_vide(e.get("description"))
                or not isinstance(e.get("statut"), str)
                or e["statut"] not in {"incluse", "proposee", "a_preciser", "differee", "retiree"}
                or not _liste_textes(e.get("origine"), non_vide=True)
                or not _liste_textes(e.get("criteres_recette"), non_vide=e["statut"] == "incluse")
                or not isinstance(e.get("motif"), str)
                or (e["statut"] in {"differee", "retiree"} and not _texte_non_vide(e["motif"]))):
            raise ValueError("Instantané : exigence, origine ou critères invalides")
        ids.add(e["id_stable"])
    calculee = _evaluation_decision(p["decision"], p["version"])
    if calculee["developpement_eligible"] and (
            p["questions_ouvertes"] or not any(e["statut"] == "incluse" for e in p["exigences"])):
        raise ValueError("Instantané : critères absents ou question ouverte avant développement")
    return p


def _instantane_correspond(d, p):
    return (p["version"] == d["version_perimetre"] and p["decision"] == d["decision"]
            and p["impacts"]["ressources"] == d["ressources"]
            and p["impacts"]["dependances"] == d["dependances"])


def _valider_evolution(precedent, courant):
    exigences = {e["id_stable"]: e for e in courant["exigences"]}
    for ancienne in precedent["exigences"]:
        actuelle = exigences.get(ancienne["id_stable"])
        if actuelle is None:
            raise ValueError("Instantané : exigence antérieure disparue, conserver son ID stable")
        if (actuelle["description"] != ancienne["description"]
                or not set(ancienne["criteres_recette"]) <= set(actuelle["criteres_recette"])
                or not set(ancienne["origine"]) <= set(actuelle["origine"])):
            raise ValueError("Instantané : identité d'exigence remplacée, retirer l'ancienne et créer un nouvel ID")
        if (ancienne["statut"] == "incluse"
                and actuelle["statut"] not in {"incluse", "retiree", "differee"}):
            raise ValueError("Instantané : retrait d'une exigence incluse à expliciter avec motif")


def _exiger_instantane_courant(d):
    p = d.get("perimetres", {}).get(str(d["version_perimetre"]))
    if p is None or not _instantane_correspond(d, p):
        raise ValueError("Instantané du périmètre courant absent ou incohérent")
    return p


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
        if type(d.get("source_verifiee_initialement")) is not bool:
            raise ValueError("Provenance initiale absente : retrouver la source, ne pas la supposer")
        verification = d.get("verification_source")
        if d["source_verifiee"] and not d["source_verifiee_initialement"] and verification is None:
            raise ValueError("Preuve de vérification de provenance absente")
        if verification is not None and (
                not isinstance(verification, dict) or not d["source_verifiee"]
                or verification.get("manifest_sha256") != d["manifest_sha256"]
                or any(not _texte_non_vide(verification.get(k))
                       for k in ("evenement_id", "preuve", "execution"))
                or type(verification.get("analyse_requise")) is not bool
                or (verification["analyse_requise"]
                    and verification["evenement_id"] not in d["evenements"])):
            raise ValueError("Preuve de vérification de provenance invalide")
        perimetres = d.get("perimetres", {})
        if not isinstance(perimetres, dict):
            raise ValueError("Instantanés des périmètres invalides")
        for version, p in perimetres.items():
            _valider_instantane(p)
            if (version != str(p["version"]) or p["version"] > d["version_perimetre"]
                    or (p["version_precedente"] is not None
                        and str(p["version_precedente"]) not in perimetres)):
                raise ValueError("Instantané : historique des versions incomplet")
        if perimetres:
            _exiger_instantane_courant(d)
        for p in perimetres.values():
            if p["version_precedente"] is not None:
                _valider_evolution(perimetres[str(p["version_precedente"])], p)
        for effet in d["effets"].values():
            version = effet.get("version_perimetre")
            if version is not None and (version > d["version_perimetre"]
                                        or str(version) not in perimetres):
                raise ValueError("Effet : périmètre futur ou instantané absent")
        analyses = d.get("analyses_reponses", {})
        if (len(set(d["evenements"])) != len(d["evenements"])
                or not isinstance(analyses, dict)
                or any(message not in d["evenements"] or not isinstance(a, dict)
                       or type(a.get("version_perimetre")) is not int
                       or not 1 <= a["version_perimetre"] <= d["version_perimetre"]
                       or str(a["version_perimetre"]) not in perimetres
                       or type(a.get("perimetre_modifie")) is not bool
                       or (a["perimetre_modifie"] and message not in
                           perimetres[str(a["version_perimetre"])]["source_evenement"])
                       or not _texte_non_vide(a.get("preuve"))
                       for message, a in analyses.items())):
            raise ValueError("Historique d'analyse des réponses invalide")
        for p in perimetres.values():
            if p["version_precedente"] is not None and any(
                    message not in d["evenements"] or message not in analyses
                    or analyses[message]["version_perimetre"] != p["version"]
                    or not analyses[message]["perimetre_modifie"]
                    for message in p["source_evenement"]):
                raise ValueError("Instantané : réponse source sans réception et analyse correspondantes")
        if not isinstance(d.get("historique_perimetres", []), list):
            raise ValueError("Historique des périmètres invalide")
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
        "source_verifiee_initialement": source_verifiee,
        "etat": "recu" if source_verifiee else "quarantaine",
        "version_perimetre": 1, "decision": None, "ressources": ["a_analyser"],
        "dependances": [], "verrou": None, "branche": None, "pr": None,
        "fusion_dev": None, "evenements": [], "effets": {},
        "analyses_reponses": {}, "historique_perimetres": [],
        "perimetres": {},
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


def confirmer_source(file, reference, execution, empreinte, evenement_id, preuve):
    """Consigner la vérification Work, sans la déduire d'une retransmission.

    Le coordinateur vérifie la preuve puis publie ce candidat sous CAS. Si une
    décision existe, l'événement Work rejoint les éléments à réévaluer dans un
    nouvel instantané ; aucune décision passée n'est réécrite ici.
    """
    resultat, d = _detenir(file, reference, execution)
    if (not _hex(empreinte, 64) or empreinte != d["manifest_sha256"]
            or not _texte_non_vide(evenement_id) or not _texte_non_vide(preuve)):
        raise ValueError("Vérification de provenance : empreinte ou preuve invalide")
    precedente = d.get("verification_source")
    if d["source_verifiee"]:
        if (precedente and precedente["evenement_id"] == evenement_id
                and precedente["preuve"] == preuve):
            return resultat
        raise ValueError("Source déjà vérifiée : ne pas remplacer sa preuve")
    if d["etat"] != "quarantaine" or evenement_id in d["evenements"]:
        raise ValueError("Vérification de provenance : état ou événement incompatible")
    analyse_requise = d["decision"] is not None
    if analyse_requise:
        _exiger_instantane_courant(d)
        d["evenements"].append(evenement_id)
    else:
        d["etat"] = "recu"
    d["source_verifiee"] = True
    d["verification_source"] = {
        "manifest_sha256": empreinte, "evenement_id": evenement_id,
        "preuve": preuve, "execution": execution, "analyse_requise": analyse_requise,
    }
    return valider_file(resultat)


def ajouter_reponse(file, reference, execution, message_id):
    resultat, d = _detenir(file, reference, execution)
    if not isinstance(message_id, str) or not message_id:
        raise ValueError("Identifiant de réponse absent")
    if message_id in d["evenements"]:
        return resultat, "doublon"
    d["evenements"].append(message_id)
    # L'absence d'analyse associée est durable, même si le retour a_analyser est
    # perdu. Un doublon reçu ne retire jamais cette obligation du journal.
    return resultat, "a_analyser"


def reponses_en_attente(dossier):
    """Les anciennes réponses sans preuve d'analyse restent à examiner."""
    return [message for message in dossier["evenements"]
            if message not in dossier.get("analyses_reponses", {})]


def _exiger_reponses_analysees(dossier):
    if reponses_en_attente(dossier):
        raise ValueError("Une réponse reste à analyser avant de poursuivre ce dossier")


def _evaluation_decision(decision, version):
    if (not isinstance(decision, dict)
            or type(decision.get("version_perimetre")) is not int
            or decision["version_perimetre"] != version):
        raise ValueError("Décision absente ou liée à un ancien périmètre")
    calculee = evaluer(decision.get("evaluation", {}))
    if (decision.get("decision") != calculee["decision"]
            or decision.get("score") != calculee["score"]):
        raise ValueError("Grille non favorable ou décision incohérente")
    return calculee


def enregistrer_perimetre_initial(file, reference, execution, instantane):
    """Établir le premier instantané à partir des sources, sans supposer un historique."""
    resultat, d = _detenir(file, reference, execution)
    _valider_instantane(instantane)
    if (d.get("perimetres") or d.get("analyses_reponses")
            or d["version_perimetre"] != 1 or instantane["version"] != 1):
        raise ValueError("Instantané initial déjà établi ou historique à reconstituer")
    if d["decision"] is not None and not _instantane_correspond(d, instantane):
        raise ValueError("Instantané initial incompatible avec la décision conservée")
    if d["decision"] is None:
        d.update(decision=deepcopy(instantane["decision"]),
                 ressources=deepcopy(instantane["impacts"]["ressources"]),
                 dependances=deepcopy(instantane["impacts"]["dependances"]))
        calculee = _evaluation_decision(d["decision"], 1)
        if d["source_verifiee"] and calculee["developpement_eligible"]:
            d["etat"] = "a_developper"
        elif not d["source_verifiee"] or calculee["decision"] == "quarantaine":
            d["etat"] = "quarantaine"
        else:
            d["etat"] = {"clarifier": "attente_precisions",
                         "clarifier_acces": "attente_precisions",
                         "validation_humaine": "attente_validation",
                         "reporter": "reporte", "refuser": "refuse"}.get(calculee["decision"], "analyse")
    d["perimetres"] = {"1": deepcopy(instantane)}
    return valider_file(resultat)


def integrer_reponses(file, reference, execution, messages, *, perimetre_modifie,
                     version_perimetre, decision, ressources, dependances, preuve,
                     instantane=None):
    """Publier ensemble analyse, décision et impacts, puis autoriser la reprise.

    L'instantané complet est validé et conservé dans le même candidat que les
    acquittements. Une preuve libre ne remplace pas exigences, critères et sources.
    """
    resultat, d = _detenir(file, reference, execution)
    attente = reponses_en_attente(d)
    if (not attente or not isinstance(messages, list) or messages != attente
            or type(perimetre_modifie) is not bool or not _texte_non_vide(preuve)):
        raise ValueError("Analyse incomplète ou périmée : reprendre les réponses en attente")
    version_attendue = d["version_perimetre"] + int(perimetre_modifie)
    if type(version_perimetre) is not int or version_perimetre != version_attendue:
        raise ValueError("Version de périmètre incorrecte pour cette analyse")
    calculee = _evaluation_decision(decision, version_perimetre)
    _valider_instantane(instantane)
    precedent = _exiger_instantane_courant(d)
    if (instantane["version"] != version_perimetre or instantane["decision"] != decision
            or instantane["impacts"]["ressources"] != ressources
            or instantane["impacts"]["dependances"] != dependances):
        raise ValueError("Instantané incohérent avec la décision ou les impacts")
    if perimetre_modifie and instantane["source_evenement"] != messages:
        raise ValueError("Instantané : réponses sources incomplètes ou périmées")
    if not perimetre_modifie and (decision != d["decision"]
                                 or ressources != d["ressources"]
                                 or dependances != d["dependances"]):
        raise ValueError("Une décision ou des impacts modifiés imposent un nouveau périmètre")
    if not perimetre_modifie and instantane != precedent:
        raise ValueError("Un instantané modifié impose un nouveau périmètre")
    if perimetre_modifie:
        if d["fusion_dev"] is not None or d["etat"] in {"clos", "abandonne"}:
            raise ValueError("Évolution après clôture ou intégration : arbitrer un dossier lié")
        ancien = {k: deepcopy(d[k]) for k in
                  ("version_perimetre", "decision", "ressources", "dependances")}
        d.setdefault("historique_perimetres", []).append(ancien)
        d.update(version_perimetre=version_perimetre, decision=deepcopy(decision),
                 ressources=deepcopy(ressources), dependances=deepcopy(dependances))
        d["perimetres"][str(version_perimetre)] = deepcopy(instantane)
        if not d["source_verifiee"] or calculee["decision"] == "quarantaine":
            d["etat"] = "quarantaine"
        elif calculee["developpement_eligible"]:
            d["etat"] = ("a_corriger" if d["pr"] else "en_developpement") if d["branche"] else "a_developper"
        else:
            d["etat"] = {"clarifier": "attente_precisions", "clarifier_acces": "attente_precisions",
                         "validation_humaine": "attente_validation", "reporter": "reporte",
                         "refuser": "refuse"}.get(calculee["decision"], "analyse")
    for message in messages:
        d.setdefault("analyses_reponses", {})[message] = {
            "version_perimetre": version_perimetre,
            "perimetre_modifie": perimetre_modifie, "preuve": preuve}
    return valider_file(resultat)


def _conflit_ressources(a, b):
    for gauche in a:
        for droite in b:
            if (gauche == droite or gauche == "*" or droite == "*"
                    or gauche.startswith(droite.rstrip("/") + "/")
                    or droite.startswith(gauche.rstrip("/") + "/")):
                return True
    return False


def _verifier_developpement(file, reference, d):
    _exiger_reponses_analysees(d)
    _exiger_instantane_courant(d)
    if not d["source_verifiee"]:
        raise ValueError("Dossier non éligible")
    if not _evaluation_decision(d.get("decision"), d["version_perimetre"])["developpement_eligible"]:
        raise ValueError("Grille non favorable ou décision incohérente")
    if "a_analyser" in d["ressources"]:
        raise ValueError("Impacts non analysés")
    if any(file["dossiers"][r]["fusion_dev"] is None for r in d["dependances"]):
        raise ValueError("Dépendance non intégrée à dev")
    actifs = [v for k, v in file["dossiers"].items() if k != reference and occupe_creneau(v)]
    if any(_conflit_ressources(d["ressources"], autre["ressources"]) for autre in actifs):
        raise ValueError("Dépendance ou ressource commune : séquencer les développements")
    return actifs


def demarrer_developpement(file, reference, execution):
    resultat, d = _detenir(file, reference, execution)
    actifs = _verifier_developpement(resultat, reference, d)
    if d["etat"] != "a_developper" or d["branche"] is not None:
        raise ValueError("Dossier non éligible ou développement déjà réservé")
    if len(actifs) >= resultat["maximum_developpements"]:
        raise ValueError("Trois développements sont déjà en cours")
    d["branche"] = "feat/demande-" + reference
    d["etat"] = "en_developpement"
    return valider_file(resultat)


def reprendre_developpement(file, reference, execution):
    """Revalider aussi un travail déjà réservé, sans consommer un autre créneau."""
    resultat, d = _detenir(file, reference, execution)
    _verifier_developpement(resultat, reference, d)
    if not occupe_creneau(d) or d["etat"] not in {"en_developpement", "a_corriger"}:
        raise ValueError("Développement non disponible pour reprise")
    return resultat


def reserver_migration(file, reference, execution, versions_observees):
    resultat, d = _detenir(file, reference, execution)
    _verifier_developpement(resultat, reference, d)
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
    _exiger_reponses_analysees(d)
    _exiger_instantane_courant(d)
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
    if any(e["etat"] in ETATS_A_RECONCILIER for e in d["effets"].values()):
        raise ValueError("Résultat incertain dans ce dossier : réconcilier avant tout nouvel effet")
    if type_effet in {"correction", "revue"} and d["pr"] is None:
        raise ValueError("PR absente")
    plafond = {"mail_precisions": 2, "correction": 3}.get(type_effet)
    if plafond is not None and sum(e["type"] == type_effet for e in d["effets"].values()) >= plafond:
        raise ValueError("Plafond de cycles atteint")
    if type_effet in EFFETS_DEVELOPPEMENT:
        _verifier_developpement(resultat, reference, d)
    d["effets"][cle] = {"type": type_effet, "etat": "intention",
                        "version_perimetre": d["version_perimetre"]}
    return resultat


def verifier_effet_a_executer(file, reference, execution, cle):
    """Réserver durablement la tentative sur une lecture fraîche avant l'appel.

    Retourne le candidat FILE à publier sous CAS, et non une autorisation nue.
    Seul le gagnant du CAS peut appeler une fois le service dans cette continuité.
    Une reprise qui lit « tentative » doit réconcilier ; elle ne rejoue pas l'appel.
    Aucun réseau ici. Les résultats dus restent enregistrables après une réponse.
    """
    resultat, d = _detenir(file, reference, execution)
    _exiger_reponses_analysees(d)
    effet = d["effets"].get(cle)
    if (not isinstance(effet, dict) or effet["etat"] != "intention"
            or effet.get("version_perimetre") != d["version_perimetre"]):
        raise ValueError("Intention absente, déjà traitée ou liée à un ancien périmètre")
    if not d["source_verifiee"] or d["etat"] == "quarantaine":
        raise ValueError("Provenance non vérifiée")
    if any(e["etat"] in ETATS_A_RECONCILIER for e in d["effets"].values()):
        raise ValueError("Résultat incertain à réconcilier")
    if effet["type"] == "pr" and (d["pr"] is not None or any(
            k != cle and e["type"] == "pr" and e["etat"] != "echec_certain"
            for k, e in d["effets"].items())):
        raise ValueError("PR déjà enregistrée ou autre création à réconcilier")
    if effet["type"] in {"correction", "revue"} and d["pr"] is None:
        raise ValueError("PR absente")
    if effet["type"] in EFFETS_DEVELOPPEMENT:
        _verifier_developpement(resultat, reference, d)
        if not occupe_creneau(d):
            raise ValueError("Créneau de développement non réservé")
    effet.update(etat="tentative", execution_tentative=execution)
    return valider_file(resultat)


def resultat_effet(file, reference, execution, cle, etat, preuve):
    resultat, d = _detenir(file, reference, execution)
    effet = d["effets"][cle]
    if (not isinstance(etat, str) or etat not in ETATS_RESULTATS
            or not (effet["etat"] == "tentative"
                    or (effet["etat"] == "intention" and etat == "echec_certain"))
            or not _texte_non_vide(preuve)):
        raise ValueError("Résultat ou transition d'effet invalide")
    effet.update(etat=etat, preuve=preuve)
    return resultat


def reconcilier_effet(file, reference, execution, cle, etat, preuve):
    """Conclut une issue incertaine sans supprimer la preuve de l'ambiguïté."""
    resultat, d = _detenir(file, reference, execution)
    effet = d["effets"].get(cle)
    if (not isinstance(effet, dict) or effet.get("etat") not in ETATS_A_RECONCILIER
            or not isinstance(etat, str) or etat not in {"confirme", "echec_certain"}
            or not _texte_non_vide(preuve)):
        raise ValueError("Transition de réconciliation invalide")
    historique = list(effet.get("historique", []))
    historique.append({"etat": effet["etat"], "preuve": effet.get("preuve") or
                       "Tentative réservée avant appel ; résultat absent"})
    effet.update(etat=etat, preuve=preuve, historique=historique)
    return valider_file(resultat)


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
