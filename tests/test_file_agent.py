"""Scénarios de reprise et de coordination du pilote, sans effets externes."""

from copy import deepcopy
import json
import sys

import pytest

from scripts import file_agent as agent
from scripts.triage_agent import ROOT, evaluer, load_json


def ref(n):
    return f"{n:032x}"


def instantane_initial(d, reference):
    return {
        "version": 1, "version_precedente": None,
        "source_evenement": [reference], "date": "2026-01-02T10:00:00+00:00",
        "resume": "Besoin synthétique du formulaire",
        "exigences": [{"id_stable": "E1", "description": "Afficher la valeur saisie",
                      "statut": "incluse", "origine": [reference],
                      "criteres_recette": ["La valeur enregistrée est affichée après rechargement"],
                      "motif": "Besoin confirmé"}],
        "questions_ouvertes": [], "decision": deepcopy(d["decision"]),
        "impacts": {"ressources": deepcopy(d["ressources"]), "dependances": deepcopy(d["dependances"])},
    }


def synchroniser_instantanes_fixture(file):
    # Les scénarios construisent leur état initial avant d'exercer une transition.
    for d in file["dossiers"].values():
        p = d.get("perimetres", {}).get(str(d["version_perimetre"]))
        if p is not None:
            p["decision"] = deepcopy(d["decision"])
            p["impacts"] = {"ressources": deepcopy(d["ressources"]),
                            "dependances": deepcopy(d["dependances"])}


@pytest.fixture
def file():
    file = agent.nouvelle_file()
    file["actif"] = True
    evaluation = load_json(ROOT / "docs/agent-demandes/calibration-v1.json")["cas"][1]["evaluation"]
    for n in range(1, 6):
        file, _ = agent.enregistrer_proposition(file, ref(n), "a" * 64, True)
        d = file["dossiers"][ref(n)]
        d.update(etat="a_developper", ressources=[f"table:domaine{n}"],
                 decision={"version_perimetre": 1, "evaluation": deepcopy(evaluation),
                           **evaluer(evaluation)})
        d["perimetres"] = {"1": instantane_initial(d, ref(n))}
    return file



def constater_resultat(file, reference, execution, cle, etat, preuve):
    """Construire un résultat observé après la réservation de sa tentative."""
    if etat != "echec_certain" and file["dossiers"][reference]["effets"][cle]["etat"] == "intention":
        file = agent.verifier_effet_a_executer(file, reference, execution, cle)
    return agent.resultat_effet(file, reference, execution, cle, etat, preuve)


def demarrer(file, n):
    synchroniser_instantanes_fixture(file)
    file = agent.prendre_dossier(file, ref(n), f"execution-{n}")
    return agent.demarrer_developpement(file, ref(n), f"execution-{n}")


@pytest.mark.parametrize("action", ["demarrer", "migration", "branche", "pr",
                                    "correction", "revue", "mail_suivi", "mail_precisions"])
def test_reponse_persistee_bloque_action_sur_ancien_perimetre(file, action):
    file["dossiers"][ref(1)]["ressources"] = ["schema"]
    synchroniser_instantanes_fixture(file)
    if action == "demarrer":
        file = agent.prendre_dossier(file, ref(1), "execution-1")
    else:
        file = demarrer(file, 1)
        if action in {"correction", "revue"}:
            file["dossiers"][ref(1)]["pr"] = 101
            file["dossiers"][ref(1)]["etat"] = "pret_recette"
    file, _ = agent.ajouter_reponse(file, ref(1), "execution-1", "nouvelle-reponse")
    # Simule la publication puis la perte de toute mémoire hors du JSON.
    file = json.loads(json.dumps(file))
    file, etat = agent.ajouter_reponse(file, ref(1), "execution-1", "nouvelle-reponse")
    assert etat == "doublon"
    avant = deepcopy(file)
    with pytest.raises(ValueError, match="réponse.*analyser"):
        if action == "demarrer":
            agent.demarrer_developpement(file, ref(1), "execution-1")
        elif action == "migration":
            agent.reserver_migration(file, ref(1), "execution-1", ["0073"])
        else:
            agent.preparer_effet(file, ref(1), "execution-1", "action-v1", action)
    assert file == avant
    assert demarrer(file, 2)["dossiers"][ref(2)]["branche"]


def test_trois_developpements_et_analyse_non_bloquee(file):
    avant = deepcopy(file)
    for n in range(1, 4):
        file = demarrer(file, n)
    file = agent.prendre_dossier(file, ref(4), "execution-4")
    with pytest.raises(ValueError, match="développements"):
        agent.demarrer_developpement(file, ref(4), "execution-4")
    # La quatrième demande peut recevoir une précision sans créer de branche.
    file, etat = agent.ajouter_reponse(file, ref(4), "execution-4", "nouvelle-reponse")
    assert etat == "a_analyser"
    assert file["dossiers"][ref(4)]["branche"] is None
    assert avant["dossiers"][ref(1)]["branche"] is None  # opérations pures


@pytest.mark.parametrize("etat", ["en_revue", "pret_recette", "bloque_technique", "attente_precisions"])
def test_pr_non_integree_compte_encore_dans_le_plafond(file, etat):
    for n in range(1, 4):
        file = demarrer(file, n)
        file["dossiers"][ref(n)]["etat"] = etat
        file = agent.liberer_dossier(file, ref(n), f"execution-{n}")
    with pytest.raises(ValueError, match="développements"):
        demarrer(file, 4)


def test_integration_dev_libere_un_creneau_pas_une_livraison(file):
    for n in range(1, 4):
        file = demarrer(file, n)
    d = file["dossiers"][ref(1)]
    d.update(etat="integre_dev", fusion_dev="b" * 40, pr=101, verrou=None)
    file = demarrer(file, 4)
    assert file["dossiers"][ref(1)]["etat"] != "clos"
    assert file["dossiers"][ref(4)]["branche"]


@pytest.mark.parametrize("ressource", ["table:domaine1", "*", "schema"])
def test_demandes_liees_attendent_sans_bloquer_une_independante(file, ressource):
    file["dossiers"][ref(1)]["ressources"] = [ressource]
    file["dossiers"][ref(2)]["ressources"] = [ressource]
    file = demarrer(file, 1)
    with pytest.raises(ValueError, match="ressource commune"):
        demarrer(file, 2)
    if ressource != "*":
        assert demarrer(file, 3)["dossiers"][ref(3)]["branche"]


def test_dependance_doite_etre_integree(file):
    file["dossiers"][ref(2)]["dependances"] = [ref(1)]
    with pytest.raises(ValueError, match="Dépendance"):
        demarrer(file, 2)


def test_numero_migration_tient_compte_de_main_dev_et_reservations(file):
    file["dossiers"][ref(1)]["ressources"] = ["schema"]
    file = demarrer(file, 1)
    file, numero = agent.reserver_migration(file, ref(1), "execution-1", ["0073", "0074"])
    assert numero == "0075"
    with pytest.raises(ValueError, match="existante"):
        agent.reserver_migration(file, ref(1), "execution-1", ["0074"])


def test_migration_exige_le_creneau_schema(file):
    file = demarrer(file, 1)
    with pytest.raises(ValueError, match="schéma"):
        agent.reserver_migration(file, ref(1), "execution-1", ["0073"])


def test_aucun_vol_de_verrou_meme_par_le_meme_execution(file):
    file = agent.prendre_dossier(file, ref(1), "ancien")
    for execution in ("ancien", "nouveau"):
        with pytest.raises(ValueError, match="Verrou existant"):
            agent.prendre_dossier(file, ref(1), execution)
    with pytest.raises(ValueError, match="non détenu"):
        agent.liberer_dossier(file, ref(1), "nouveau")
    assert agent.prendre_dossier(file, ref(2), "nouveau")["dossiers"][ref(2)]["verrou"] == "nouveau"


def test_pause_et_version_de_perimetre_obsolete(file):
    file["actif"] = False
    with pytest.raises(ValueError, match="pause"):
        agent.prendre_dossier(file, ref(1), "x")
    file["actif"] = True
    file["dossiers"][ref(1)]["version_perimetre"] = 2
    with pytest.raises(ValueError, match="périmètre"):
        demarrer(file, 1)


@pytest.mark.parametrize("changement", [{"source_verifiee": False}, {"besoin_complet": False}, {"risque": "eleve"}])
def test_grille_recalculee_avant_reservation(file, changement):
    file["dossiers"][ref(1)]["decision"]["evaluation"].update(changement)
    with pytest.raises(ValueError, match="Grille"):
        demarrer(file, 1)


def test_reference_alteree_ne_remplace_pas_le_dossier(file):
    avant = deepcopy(file)
    identique, etat = agent.enregistrer_proposition(file, ref(1), "a" * 64)
    assert etat == "doublon" and identique == avant
    with pytest.raises(ValueError, match="Conflit"):
        agent.enregistrer_proposition(file, ref(1), "b" * 64)
    assert file == avant
    file = agent.prendre_dossier(file, ref(1), "x")
    file, etat = agent.ajouter_reponse(file, ref(1), "x", "reponse-1")
    assert etat == "a_analyser"
    assert agent.ajouter_reponse(file, ref(1), "x", "reponse-1")[1] == "doublon"
    assert agent.ajouter_reponse(file, ref(1), "x", "reponse-2")[1] == "a_analyser"


def source_inconnue():
    f = agent.nouvelle_file()
    f["actif"] = True
    f, _ = agent.enregistrer_proposition(f, ref(1), "a" * 64)
    return agent.prendre_dossier(f, ref(1), "execution-1")


def test_source_inconnue_verifiee_puis_developpement_apres_reprise(file):
    f = source_inconnue()
    double, statut = agent.enregistrer_proposition(f, ref(1), "a" * 64, True)
    assert statut == "doublon" and double == f  # un mail répété n'est pas une preuve Work
    avant = deepcopy(f)
    f = agent.confirmer_source(f, ref(1), "execution-1", "a" * 64, "work-verification", "Centre vérifié dans Work")
    assert avant["dossiers"][ref(1)]["source_verifiee"] is False
    f = json.loads(json.dumps(f))
    assert f["dossiers"][ref(1)]["etat"] == "recu"
    assert agent.confirmer_source(f, ref(1), "execution-1", "a" * 64, "work-verification", "Centre vérifié dans Work") == f
    p = deepcopy(file["dossiers"][ref(1)]["perimetres"]["1"])
    f = agent.enregistrer_perimetre_initial(f, ref(1), "execution-1", p)
    f = agent.demarrer_developpement(f, ref(1), "execution-1")
    assert f["dossiers"][ref(1)]["branche"]
    assert agent.enregistrer_proposition(f, ref(1), "a" * 64, False)[0] == f
    with pytest.raises(ValueError, match="déjà vérifiée"):
        agent.confirmer_source(f, ref(1), "execution-1", "a" * 64, "autre", "Autre preuve")


@pytest.mark.parametrize("besoin_complet", [True, False])
def test_verification_source_reevalue_decision_sans_effacer_quarantaine(file, besoin_complet):
    f = source_inconnue()
    p = deepcopy(file["dossiers"][ref(1)]["perimetres"]["1"])
    evaluation = deepcopy(p["decision"]["evaluation"])
    evaluation.update(source_verifiee=False, besoin_complet=besoin_complet)
    p["decision"] = {"version_perimetre": 1, "evaluation": evaluation, **evaluer(evaluation)}
    f = agent.enregistrer_perimetre_initial(f, ref(1), "execution-1", p)
    f = agent.confirmer_source(f, ref(1), "execution-1", "a" * 64, "work-verification", "Centre vérifié dans Work")
    f = json.loads(json.dumps(f))
    assert f["dossiers"][ref(1)]["perimetres"]["1"] == p
    assert agent.reponses_en_attente(f["dossiers"][ref(1)]) == ["work-verification"]
    with pytest.raises(ValueError, match="réponse.*analyser"):
        agent.demarrer_developpement(f, ref(1), "execution-1")
    evaluation = deepcopy(evaluation)
    evaluation["source_verifiee"] = True
    decision = {"version_perimetre": 2, "evaluation": evaluation, **evaluer(evaluation)}
    f = json.loads(json.dumps(integrer(f, decision=decision)))
    assert f["dossiers"][ref(1)]["perimetres"]["1"] == p
    assert f["dossiers"][ref(1)]["etat"] == ("a_developper" if besoin_complet else "attente_precisions")
    if besoin_complet:
        assert agent.demarrer_developpement(f, ref(1), "execution-1")
    else:
        with pytest.raises(ValueError, match="Grille"):
            agent.demarrer_developpement(f, ref(1), "execution-1")


@pytest.mark.parametrize("defaut", ["pause", "verrou", "empreinte", "preuve", "evenement", "collision"])
def test_verification_source_refuse_sans_preuve_et_verrou(defaut):
    f = source_inconnue()
    args = [f, ref(1), "execution-1", "a" * 64, "work-verification", "Centre vérifié dans Work"]
    if defaut == "pause":
        f["actif"] = False
    elif defaut == "verrou":
        args[2] = "autre"
    elif defaut == "empreinte":
        args[3] = "b" * 64
    elif defaut == "preuve":
        args[5] = " "
    elif defaut == "evenement":
        args[4] = " "
    else:
        f["dossiers"][ref(1)]["evenements"].append("work-verification")
    avant = deepcopy(f)
    with pytest.raises(ValueError):
        agent.confirmer_source(*args)
    assert f == avant


@pytest.mark.parametrize("champ", ["preuve", "manifest_sha256", "execution", "evenement_id", "analyse_requise"])
def test_preuve_source_malformee_refusee_au_rechargement(champ):
    f = agent.confirmer_source(source_inconnue(), ref(1), "execution-1", "a" * 64, "work-verification", "Centre vérifié dans Work")
    del f["dossiers"][ref(1)]["verification_source"][champ]
    with pytest.raises(ValueError, match="provenance"):
        agent.valider_file(json.loads(json.dumps(f)))


def test_effet_incertain_jamais_repete(file):
    file = agent.prendre_dossier(file, ref(1), "x")
    file = agent.preparer_effet(file, ref(1), "x", "question-v1", "mail_precisions")
    file = constater_resultat(file, ref(1), "x", "question-v1", "incertain", "Coupure réseau")
    with pytest.raises(ValueError, match="répéter"):
        agent.preparer_effet(file, ref(1), "x", "question-v1", "mail_precisions")
    with pytest.raises(ValueError, match="transition"):
        agent.resultat_effet(file, ref(1), "x", "question-v1", "confirme", "Non observé")


@pytest.mark.parametrize("type_effet,limite", [("mail_precisions", 2), ("correction", 3)])
def test_plafonds_par_dossier(file, type_effet, limite):
    if type_effet == "correction":
        for n in (1, 2):
            file = demarrer(file, n)
            file["dossiers"][ref(n)]["pr"] = 100 + n
            file = agent.liberer_dossier(file, ref(n), f"execution-{n}")
    file = agent.prendre_dossier(file, ref(1), "x")
    for n in range(limite):
        file = agent.preparer_effet(file, ref(1), "x", str(n), type_effet)
    with pytest.raises(ValueError, match="cycles"):
        agent.preparer_effet(file, ref(1), "x", "suivant", type_effet)
    file = agent.prendre_dossier(file, ref(2), "y")
    assert agent.preparer_effet(file, ref(2), "y", "premier", type_effet)


@pytest.mark.parametrize("type_effet", ["fusion", "deploiement", "reply_all"])
def test_effets_interdits(file, type_effet):
    file = agent.prendre_dossier(file, ref(1), "x")
    with pytest.raises(ValueError, match="non autorisé"):
        agent.preparer_effet(file, ref(1), "x", "interdit", type_effet)


def test_collision_de_reservation_cas_simule(file):
    # Modèle d'un serveur CAS, pas preuve d'une intégration Library exécutée.
    version = 17
    candidat_a = demarrer(file, 1)
    candidat_b = demarrer(file, 2)
    def publier(candidat, expected):
        nonlocal file, version
        if expected != version:
            raise ValueError("Conflit de version : aucun effet externe")
        file, version = candidat, version + 1
    publier(candidat_a, 17)
    with pytest.raises(ValueError, match="Conflit"):
        publier(candidat_b, 17)
    assert file["dossiers"][ref(2)]["branche"] is None


@pytest.mark.parametrize("valeur", [True, 0, 4, "3"])
def test_plafond_invalide_refuse(file, valeur):
    file["maximum_developpements"] = valeur
    with pytest.raises(ValueError):
        agent.valider_file(file)


def test_publication_ne_contourne_pas_la_reservation(file):
    file = agent.prendre_dossier(file, ref(1), "x")
    for type_effet in ("branche", "pr"):
        with pytest.raises(ValueError, match="non réservé"):
            agent.preparer_effet(file, ref(1), "x", type_effet, type_effet)


def test_marqueur_fusion_incoherent_ne_libere_pas_un_creneau(file):
    file = demarrer(file, 1)
    file["dossiers"][ref(1)].update(pr=101, fusion_dev="b" * 40)
    with pytest.raises(ValueError, match="incompatible"):
        demarrer(file, 2)


@pytest.mark.parametrize("effets", [
    {"mail-1": {}},
    {"mail-1": None},
    {"mail-1": []},
    {"mail-1": {"type": "mail_precisions"}},
    {"mail-1": {"etat": "intention"}},
    {"mail-1": {"type": "fusion", "etat": "intention"}},
    {"mail-1": {"type": [], "etat": "intention"}},
    {"mail-1": {"type": "mail_suivi", "etat": []}},
    {"mail-1": {"type": "mail_suivi", "etat": "inconnu"}},
    {"mail-1": {"type": "mail_suivi", "etat": "confirme"}},
    {"mail-1": {"type": "mail_suivi", "etat": "incertain", "preuve": ""}},
    {"mail-1": {"type": "pr", "etat": "echec_certain", "preuve": "  "}},
    {"mail-1": {"type": "mail_suivi", "etat": "confirme", "preuve": 42}},
    {"mail-1": {"type": "mail_suivi", "etat": "intention", "preuve": None}},
    {"": {"type": "mail_suivi", "etat": "intention"}},
    {"  ": {"type": "mail_suivi", "etat": "intention"}},
])
def test_verificateur_refuse_effet_inexploitable(file, effets, tmp_path, monkeypatch, capsys):
    file = agent.prendre_dossier(file, ref(1), "x")
    file["dossiers"][ref(1)]["effets"] = effets
    avant = deepcopy(file)
    chemin = tmp_path / "file.json"
    chemin.write_text(json.dumps(file), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["file_agent", "--verifier", str(chemin)])
    assert agent.main() == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False
    with pytest.raises(ValueError, match="Effet"):
        agent.preparer_effet(file, ref(1), "x", "nouveau", "mail_precisions")
    assert file == avant


@pytest.mark.parametrize("etat", ["intention", "confirme", "incertain", "echec_certain"])
def test_verificateur_accepte_historique_effets_valide(file, etat, tmp_path, monkeypatch, capsys):
    file = demarrer(file, 1)
    file = agent.preparer_effet(file, ref(1), "execution-1", "pr", "pr")
    file["dossiers"][ref(1)]["pr"] = 101
    for type_effet in ("mail_precisions", "mail_suivi", "branche", "correction", "revue"):
        file = agent.preparer_effet(file, ref(1), "execution-1", type_effet, type_effet)
    # Validation structurelle d'un historique déjà reçu ; ce test ne simule
    # pas l'exécution simultanée de ces effets.
    if etat != "intention":
        for effet in file["dossiers"][ref(1)]["effets"].values():
            effet.update(etat=etat, preuve="Preuve synthétique", execution_tentative="execution-1")
    chemin = tmp_path / "file.json"
    chemin.write_text(json.dumps(file), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["file_agent", "--verifier", str(chemin)])
    assert agent.main() == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_pr_enregistree_interdit_nouvelle_intention(file):
    file = demarrer(file, 1)
    file["dossiers"][ref(1)]["pr"] = 101
    avant = deepcopy(file)
    with pytest.raises(ValueError, match="PR déjà"):
        agent.preparer_effet(file, ref(1), "execution-1", "nouvelle-cle", "pr")
    assert file == avant


@pytest.mark.parametrize("etat", ["intention", "confirme", "incertain"])
def test_intention_pr_non_echouee_interdit_autre_cle(file, etat):
    file = demarrer(file, 1)
    file = agent.preparer_effet(file, ref(1), "execution-1", "pr-v1", "pr")
    if etat != "intention":
        file = constater_resultat(file, ref(1), "execution-1", "pr-v1", etat, "Preuve synthétique")
    avant = deepcopy(file)
    with pytest.raises(ValueError, match="PR déjà"):
        agent.preparer_effet(file, ref(1), "execution-1", "pr-v2", "pr")
    assert file == avant
    # Le refus n'empêche pas la première PR d'un dossier indépendant.
    autre = demarrer(file, 2)
    assert agent.preparer_effet(autre, ref(2), "execution-2", "pr-v1", "pr")


@pytest.mark.parametrize("type_effet", ["mail_precisions", "mail_suivi", "branche", "pr", "correction", "revue"])
def test_mail_incertain_bloque_toute_nouvelle_action_du_dossier(file, type_effet):
    file = demarrer(file, 1)
    if type_effet in {"correction", "revue"}:
        file["dossiers"][ref(1)]["pr"] = 101
    file = agent.preparer_effet(file, ref(1), "execution-1", "mail-v1", "mail_precisions")
    file = constater_resultat(file, ref(1), "execution-1", "mail-v1", "incertain", "Coupure réseau")
    avant = deepcopy(file)
    with pytest.raises(ValueError, match="incertain"):
        agent.preparer_effet(file, ref(1), "execution-1", "autre-cle-v2", type_effet)
    assert file == avant
    # On peut toujours lire une réponse pour éclaircir l'issue du dossier.
    file, etat = agent.ajouter_reponse(file, ref(1), "execution-1", "reponse-nouvelle")
    assert etat == "a_analyser"
    assert file["dossiers"][ref(1)]["effets"]["mail-v1"]["etat"] == "incertain"
    # Le blocage est propre au dossier ; les autres demandes restent actives.
    autre = demarrer(file, 2)
    autre = agent.preparer_effet(autre, ref(2), "execution-2", "premier-mail", "mail_precisions")
    assert autre["dossiers"][ref(2)]["effets"]["premier-mail"]["etat"] == "intention"


@pytest.mark.parametrize("type_initial", ["mail_precisions", "mail_suivi", "branche", "pr", "correction", "revue"])
def test_tout_type_de_resultat_incertain_bloque_un_nouvel_effet(file, type_initial):
    file = demarrer(file, 1)
    if type_initial in {"correction", "revue"}:
        file["dossiers"][ref(1)]["pr"] = 101
    file = agent.preparer_effet(file, ref(1), "execution-1", "initial", type_initial)
    file = constater_resultat(file, ref(1), "execution-1", "initial", "incertain", "Résultat non déterminé")
    avant = deepcopy(file)
    with pytest.raises(ValueError, match="incertain"):
        agent.preparer_effet(file, ref(1), "execution-1", "suivi", "mail_suivi")
    assert file == avant


@pytest.mark.parametrize("etat_final", ["confirme", "echec_certain"])
def test_reconcilier_effet_incertain_preserve_ambiguite_et_reprend(file, etat_final):
    file = demarrer(file, 1)
    file = agent.preparer_effet(file, ref(1), "execution-1", "mail-v1", "mail_suivi")
    file = constater_resultat(file, ref(1), "execution-1", "mail-v1", "incertain",
                               "Coupure avant réception de la réponse")
    with pytest.raises(ValueError, match="transition"):
        agent.resultat_effet(file, ref(1), "execution-1", "mail-v1", etat_final,
                             "Vérification distante")
    file = agent.reconcilier_effet(file, ref(1), "execution-1", "mail-v1", etat_final,
                                   "Vérification distante concluante")
    effet = file["dossiers"][ref(1)]["effets"]["mail-v1"]
    assert effet == {
        "type": "mail_suivi",
        "execution_tentative": "execution-1",
        "version_perimetre": 1,
        "etat": etat_final,
        "preuve": "Vérification distante concluante",
        "historique": [{"etat": "incertain", "preuve": "Coupure avant réception de la réponse"}],
    }
    reprise = agent.preparer_effet(file, ref(1), "execution-1", "mail-v2", "mail_suivi")
    assert reprise["dossiers"][ref(1)]["effets"]["mail-v2"]["etat"] == "intention"


@pytest.mark.parametrize("etat_depart,etat_final,preuve", [
    ("intention", "confirme", "Trouvé"),
    ("confirme", "echec_certain", "Absent"),
    ("incertain", "incertain", "Encore ambigu"),
    ("incertain", "intention", "Rejouer"),
    ("incertain", "confirme", ""),
    ("incertain", "echec_certain", "  "),
    ("incertain", [], "Conclusion"),
    ("incertain", "confirme", 42),
])
def test_reconciliation_refuse_transition_ou_preuve_invalide(file, etat_depart, etat_final, preuve):
    file = demarrer(file, 1)
    file = agent.preparer_effet(file, ref(1), "execution-1", "mail-v1", "mail_suivi")
    if etat_depart != "intention":
        file = constater_resultat(file, ref(1), "execution-1", "mail-v1", etat_depart,
                                   "Preuve initiale")
    avant = deepcopy(file)
    with pytest.raises(ValueError, match="réconciliation"):
        agent.reconcilier_effet(file, ref(1), "execution-1", "mail-v1", etat_final, preuve)
    assert file == avant


@pytest.mark.parametrize("historique", [
    {}, [None], [{}], [{"etat": "confirme", "preuve": "Ancien"}],
    [{"etat": "incertain"}], [{"etat": "incertain", "preuve": ""}],
])
def test_verificateur_refuse_historique_reconciliation_invalide(file, historique):
    file = demarrer(file, 1)
    file = agent.preparer_effet(file, ref(1), "execution-1", "mail-v1", "mail_suivi")
    file = constater_resultat(file, ref(1), "execution-1", "mail-v1", "confirme", "Trouvé")
    file["dossiers"][ref(1)]["effets"]["mail-v1"]["historique"] = historique
    avec_erreur = deepcopy(file)
    with pytest.raises(ValueError, match="historique"):
        agent.valider_file(file)
    assert file == avec_erreur


def test_nouvelle_intention_pr_apres_echec_certain_uniquement(file):
    file = demarrer(file, 1)
    file = agent.preparer_effet(file, ref(1), "execution-1", "pr-v1", "pr")
    file = constater_resultat(file, ref(1), "execution-1", "pr-v1", "echec_certain",
                               "Refus explicite du service ; aucune PR créée")
    with pytest.raises(ValueError, match="répéter"):
        agent.preparer_effet(file, ref(1), "execution-1", "pr-v1", "pr")
    reprise = agent.preparer_effet(file, ref(1), "execution-1", "pr-v2", "pr")
    assert reprise["dossiers"][ref(1)]["effets"]["pr-v1"]["etat"] == "echec_certain"
    assert reprise["dossiers"][ref(1)]["effets"]["pr-v2"]["etat"] == "intention"
    # Une PR retrouvée à distance interdit la reprise, même avec cet historique.
    file["dossiers"][ref(1)]["pr"] = 101
    with pytest.raises(ValueError, match="PR déjà"):
        agent.preparer_effet(file, ref(1), "execution-1", "pr-v2", "pr")

def integrer(file, *, modifie=True, messages=None, **changements):
    d = file["dossiers"][ref(1)]
    version = d["version_perimetre"] + int(modifie)
    decision = deepcopy(d["decision"])
    decision["version_perimetre"] = version
    analyse = dict(perimetre_modifie=modifie, version_perimetre=version,
                   decision=decision, ressources=deepcopy(d["ressources"]),
                   dependances=deepcopy(d["dependances"]),
                   preuve="Analyse synthétique et critères conservés dans l'instantané privé")
    analyse.update(changements)
    messages = messages if messages is not None else agent.reponses_en_attente(d)
    instantane = deepcopy(d["perimetres"][str(d["version_perimetre"])])
    if modifie:
        instantane.update(version=analyse["version_perimetre"],
                          version_precedente=d["version_perimetre"],
                          source_evenement=messages, resume="Besoin synthétique actualisé")
    instantane["decision"] = deepcopy(analyse["decision"])
    instantane["impacts"] = {"ressources": deepcopy(analyse["ressources"]),
                             "dependances": deepcopy(analyse["dependances"])}
    analyse.setdefault("instantane", instantane)
    return agent.integrer_reponses(
        file, ref(1), "execution-1", messages, **analyse)


def recevoir(file, message="reponse-1"):
    return agent.ajouter_reponse(file, ref(1), "execution-1", message)[0]


def test_integration_refuse_de_solder_reponse_sans_instantane(file):
    file = agent.prendre_dossier(file, ref(1), "execution-1")
    file = recevoir(file)
    d = file["dossiers"][ref(1)]
    decision = {**deepcopy(d["decision"]), "version_perimetre": 2}
    avant = deepcopy(file)
    with pytest.raises(ValueError, match="Instantané"):
        agent.integrer_reponses(
            file, ref(1), "execution-1", ["reponse-1"], perimetre_modifie=True,
            version_perimetre=2, decision=decision, ressources=d["ressources"],
            dependances=[], preuve="Texte libre sans instantané")
    assert file == avant


def test_reprise_reconstruit_exigences_criteres_et_sources_depuis_json(file):
    file = agent.prendre_dossier(file, ref(1), "execution-1")
    original = deepcopy(file["dossiers"][ref(1)]["perimetres"]["1"])
    file = recevoir(recevoir(file), "reponse-2")
    file = json.loads(json.dumps(integrer(file)))
    d = file["dossiers"][ref(1)]
    version = d["analyses_reponses"]["reponse-2"]["version_perimetre"]
    p = d["perimetres"][str(version)]
    assert p["version"] == 2 and p["version_precedente"] == 1
    assert p["source_evenement"] == ["reponse-1", "reponse-2"]
    assert p["exigences"][0]["description"] == original["exigences"][0]["description"]
    assert p["exigences"][0]["criteres_recette"]
    assert p["exigences"][0]["origine"] == [ref(1)]
    assert p["questions_ouvertes"] == []
    assert p["decision"] == d["decision"]
    assert p["impacts"]["ressources"] == d["ressources"]
    assert d["perimetres"]["1"] == original
    assert agent.demarrer_developpement(file, ref(1), "execution-1")
    # L'effacement de l'instantané n'est pas une reprise valide.
    del d["perimetres"]["2"]
    with pytest.raises(ValueError, match="Instantané"):
        agent.valider_file(file)


@pytest.mark.parametrize("champ", ["version", "version_precedente", "source_evenement", "date",
                                  "resume", "exigences", "questions_ouvertes", "decision", "impacts"])
def test_instantane_incomplet_refuse_avant_acquittement(file, champ):
    file = agent.prendre_dossier(file, ref(1), "execution-1")
    file = recevoir(file)
    p = deepcopy(file["dossiers"][ref(1)]["perimetres"]["1"])
    del p[champ]
    avant = deepcopy(file)
    with pytest.raises(ValueError, match="Instantané"):
        integrer(file, instantane=p)
    assert file == avant
    assert agent.reponses_en_attente(file["dossiers"][ref(1)]) == ["reponse-1"]


@pytest.mark.parametrize("defaut", [
    "criteres", "origine", "statut", "ids_doubles", "sans_exigence",
    "question_bloquante", "date", "precedente", "sources", "decision", "impacts",
])
def test_instantane_malforme_ou_desaccord_refuse(file, defaut):
    file = agent.prendre_dossier(file, ref(1), "execution-1")
    file = recevoir(file)
    p = deepcopy(integrer(file)["dossiers"][ref(1)]["perimetres"]["2"])
    if defaut == "criteres":
        p["exigences"][0]["criteres_recette"] = []
    elif defaut == "origine":
        p["exigences"][0]["origine"] = []
    elif defaut == "statut":
        p["exigences"][0]["statut"] = "inventé"
    elif defaut == "ids_doubles":
        p["exigences"].append(deepcopy(p["exigences"][0]))
    elif defaut == "sans_exigence":
        p["exigences"] = []
    elif defaut == "question_bloquante":
        p["questions_ouvertes"] = ["Droit de modification inconnu"]
    elif defaut == "date":
        p["date"] = "date inconnue"
    elif defaut == "precedente":
        p["version_precedente"] = 2
    elif defaut == "sources":
        p["source_evenement"] = ["autre-message"]
    elif defaut == "decision":
        p["decision"]["motif"] = "Autre décision"
    else:
        p["impacts"]["ressources"] = ["table:autre"]
    avant = deepcopy(file)
    with pytest.raises(ValueError, match="Instantané"):
        integrer(file, instantane=p)
    assert file == avant


def test_meme_version_ne_peut_pas_modifier_criteres(file):
    file = agent.prendre_dossier(file, ref(1), "execution-1")
    file = recevoir(file)
    p = deepcopy(file["dossiers"][ref(1)]["perimetres"]["1"])
    p["exigences"][0]["criteres_recette"] = ["Un autre résultat"]
    with pytest.raises(ValueError, match="nouveau périmètre"):
        integrer(file, modifie=False, instantane=p)


@pytest.mark.parametrize("defaut", ["version_absente", "source_incoherente", "decision_divergente"])
def test_journal_refuse_lien_analyse_instantane_incoherent(file, defaut):
    file = agent.prendre_dossier(file, ref(1), "execution-1")
    file = integrer(recevoir(file))
    d = file["dossiers"][ref(1)]
    if defaut == "version_absente":
        d["analyses_reponses"]["reponse-1"]["version_perimetre"] = 3
    elif defaut == "source_incoherente":
        d["analyses_reponses"]["reponse-1"]["version_perimetre"] = 1
    else:
        d["decision"]["motif"] = "Modification hors de l'instantané"
    with pytest.raises(ValueError):
        agent.valider_file(json.loads(json.dumps(file)))


def test_questions_ouvertes_retrouvees_apres_reprise(file):
    file = agent.prendre_dossier(file, ref(1), "execution-1")
    file = recevoir(file)
    evaluation = deepcopy(file["dossiers"][ref(1)]["decision"]["evaluation"])
    evaluation["besoin_complet"] = False
    decision = {"version_perimetre": 2, "evaluation": evaluation, **evaluer(evaluation)}
    p = deepcopy(file["dossiers"][ref(1)]["perimetres"]["1"])
    p.update(version=2, version_precedente=1, source_evenement=["reponse-1"],
             decision=decision, questions_ouvertes=["Quel profil peut modifier la valeur ?"])
    file = json.loads(json.dumps(integrer(file, decision=decision, instantane=p)))
    d = file["dossiers"][ref(1)]
    assert d["etat"] == "attente_precisions"
    assert d["perimetres"]["2"]["questions_ouvertes"] == ["Quel profil peut modifier la valeur ?"]
    assert agent.reponses_en_attente(d) == []
    with pytest.raises(ValueError, match="Grille"):
        agent.demarrer_developpement(file, ref(1), "execution-1")



def test_instantane_incomplet_refuse_aussi_par_cli(file, tmp_path, monkeypatch, capsys):
    file = agent.prendre_dossier(file, ref(1), "execution-1")
    file = integrer(recevoir(file))
    del file["dossiers"][ref(1)]["perimetres"]["2"]["exigences"]
    chemin = tmp_path / "file.json"
    chemin.write_text(json.dumps(file), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["file_agent", "--verifier", str(chemin)])
    assert agent.main() == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_instantane_initial_persiste_avant_premier_developpement(file):
    neuf = agent.nouvelle_file()
    neuf["actif"] = True
    neuf, _ = agent.enregistrer_proposition(neuf, ref(1), "a" * 64, True)
    neuf = agent.prendre_dossier(neuf, ref(1), "execution-1")
    p = deepcopy(file["dossiers"][ref(1)]["perimetres"]["1"])
    neuf = agent.enregistrer_perimetre_initial(neuf, ref(1), "execution-1", p)
    p["exigences"][0]["description"] = "Altération du paramètre après appel"
    neuf = json.loads(json.dumps(neuf))
    assert neuf["dossiers"][ref(1)]["perimetres"]["1"]["exigences"][0]["description"] != p["exigences"][0]["description"]
    assert agent.demarrer_developpement(neuf, ref(1), "execution-1")
    with pytest.raises(ValueError, match="déjà établi"):
        agent.enregistrer_perimetre_initial(neuf, ref(1), "execution-1", p)


def test_initialisation_ancien_journal_exige_reconstruction_explicite(file):
    file = agent.prendre_dossier(file, ref(1), "execution-1")
    p = file["dossiers"][ref(1)].pop("perimetres")["1"]
    with pytest.raises(ValueError, match="Instantané"):
        agent.demarrer_developpement(file, ref(1), "execution-1")
    file = agent.enregistrer_perimetre_initial(file, ref(1), "execution-1", p)
    assert agent.demarrer_developpement(file, ref(1), "execution-1")


@pytest.mark.parametrize("defaut", ["id_remplace", "retrograde", "retrait_sans_motif"])
def test_evolution_conserve_exigences_acquises(file, defaut):
    file = recevoir(demarrer(file, 1))
    p = deepcopy(integrer(file)["dossiers"][ref(1)]["perimetres"]["2"])
    e = p["exigences"][0]
    if defaut == "id_remplace":
        e["id_stable"] = "E2"
    elif defaut == "retrograde":
        e["statut"] = "proposee"
    else:
        e.update(statut="retiree", motif="")
        p["exigences"].append({**deepcopy(e), "id_stable": "E2", "statut": "incluse"})
    avant = deepcopy(file)
    with pytest.raises(ValueError, match="Instantané"):
        integrer(file, instantane=p)
    assert file == avant
    # Même défaut injecté dans un journal publié : la reprise le refuse.
    invalide = integrer(file)
    invalide["dossiers"][ref(1)]["perimetres"]["2"] = p
    with pytest.raises(ValueError, match="Instantané"):
        agent.reprendre_developpement(json.loads(json.dumps(invalide)), ref(1), "execution-1")


@pytest.mark.parametrize("statut", ["retiree", "differee"])
def test_retrait_explicite_preserve_identite_et_ancien_critere(file, statut):
    file = recevoir(demarrer(file, 1))
    p = deepcopy(integrer(file)["dossiers"][ref(1)]["perimetres"]["2"])
    p["exigences"].append({**deepcopy(p["exigences"][0]), "id_stable": "E2"})
    p["exigences"][0].update(statut=statut, motif="Retrait confirmé dans la réponse")
    file = json.loads(json.dumps(integrer(file, instantane=p)))
    file = integrer(recevoir(file, "reponse-2"))
    d = file["dossiers"][ref(1)]
    assert d["perimetres"]["1"]["exigences"][0]["statut"] == "incluse"
    assert d["perimetres"]["3"]["exigences"][0]["statut"] == statut
    assert agent.reprendre_developpement(file, ref(1), "execution-1")


@pytest.mark.parametrize("defaut", ["deux_traces", "analyse", "reception", "version", "sans_changement"])
def test_source_evolution_exige_reception_et_analyse(file, defaut):
    file = integrer(recevoir(demarrer(file, 1)))
    file = integrer(recevoir(file, "reponse-2"))
    d = file["dossiers"][ref(1)]
    # Vérifier aussi une source historique, pas seulement celle de v3.
    if defaut in {"deux_traces", "reception"}:
        d["evenements"].remove("reponse-1")
    if defaut in {"deux_traces", "analyse"}:
        del d["analyses_reponses"]["reponse-1"]
    elif defaut == "version":
        d["analyses_reponses"]["reponse-1"]["version_perimetre"] = 1
        d["analyses_reponses"]["reponse-1"]["perimetre_modifie"] = False
    else:
        d["analyses_reponses"]["reponse-1"]["perimetre_modifie"] = False
    with pytest.raises(ValueError):
        agent.reprendre_developpement(json.loads(json.dumps(file)), ref(1), "execution-1")


@pytest.mark.parametrize("etat", ["intention", "confirme", "incertain", "echec_certain"])
@pytest.mark.parametrize("defaut", ["future", "sans_instantane"])
def test_effet_exige_version_existante_des_la_lecture(file, etat, defaut):
    file = demarrer(file, 1)
    file = agent.preparer_effet(file, ref(1), "execution-1", "effet-v1", "pr")
    if etat != "intention":
        file = constater_resultat(file, ref(1), "execution-1", "effet-v1", etat, "Preuve synthétique")
    d = file["dossiers"][ref(1)]
    if defaut == "future":
        d["effets"]["effet-v1"]["version_perimetre"] = 2
    else:
        d["perimetres"] = {}
    avant = deepcopy(file)
    with pytest.raises(ValueError, match="Effet"):
        agent.valider_file(json.loads(json.dumps(file)))
    # Une réponse légitime ne peut rendre valable une intention future.
    with pytest.raises(ValueError, match="Effet"):
        recevoir(file)
    assert file == avant


def test_effet_ancien_reste_historique_sans_redevenir_executable(file):
    file = demarrer(file, 1)
    file = agent.preparer_effet(file, ref(1), "execution-1", "effet-v1", "pr")
    file = integrer(recevoir(file))
    assert agent.valider_file(json.loads(json.dumps(file)))
    with pytest.raises(ValueError, match="ancien périmètre"):
        agent.verifier_effet_a_executer(file, ref(1), "execution-1", "effet-v1")
    file = constater_resultat(file, ref(1), "execution-1", "effet-v1", "echec_certain", "Appel non effectué")
    assert agent.preparer_effet(file, ref(1), "execution-1", "effet-v2", "pr")


def test_mail_exige_aussi_instantane_initial(file):
    file = agent.prendre_dossier(file, ref(1), "execution-1")
    del file["dossiers"][ref(1)]["perimetres"]
    with pytest.raises(ValueError, match="Instantané"):
        agent.preparer_effet(file, ref(1), "execution-1", "clarification", "mail_precisions")


@pytest.mark.parametrize("type_effet", sorted(agent.TYPES_EFFETS))
def test_tentative_publiee_interdit_rejeu_apres_interruption(file, type_effet):
    file = demarrer(file, 1)
    if type_effet in {"correction", "revue"}:
        file["dossiers"][ref(1)]["pr"] = 101
    file = agent.preparer_effet(file, ref(1), "execution-1", "action", type_effet)
    avant = deepcopy(file)
    candidat = agent.verifier_effet_a_executer(file, ref(1), "execution-1", "action")
    assert file == avant  # Rien n'est exécuté avant publication du candidat.
    persiste = json.loads(json.dumps(candidat))
    effet = persiste["dossiers"][ref(1)]["effets"]["action"]
    assert effet["etat"] == "tentative" and effet["execution_tentative"] == "execution-1"
    with pytest.raises(ValueError, match="déjà traitée"):
        agent.verifier_effet_a_executer(persiste, ref(1), "execution-1", "action")
    with pytest.raises(ValueError, match="incertain"):
        agent.preparer_effet(persiste, ref(1), "execution-1", "autre", "mail_suivi")
    assert agent.resultat_effet(persiste, ref(1), "execution-1", "action", "confirme", "Résultat réellement observé")


@pytest.mark.parametrize("appel_effectue", [False, True])
@pytest.mark.parametrize("issue", ["confirme", "echec_certain"])
def test_coupure_apres_cas_exige_reconciliation_sans_second_appel(file, appel_effectue, issue):
    file = demarrer(file, 1)
    file = agent.preparer_effet(file, ref(1), "execution-1", "mail", "mail_suivi")
    file = agent.verifier_effet_a_executer(file, ref(1), "execution-1", "mail")
    appels = ["envoi"] if appel_effectue else []
    file = json.loads(json.dumps(file))  # Coupure avant ou après l'appel, sans résultat.
    with pytest.raises(ValueError):
        agent.verifier_effet_a_executer(file, ref(1), "execution-1", "mail")
    # L'issue fournie vient d'une vérification externe, pas de la seule tentative.
    file = agent.reconcilier_effet(file, ref(1), "execution-1", "mail", issue, "Vérification distante de l'issue")
    e = file["dossiers"][ref(1)]["effets"]["mail"]
    assert e["historique"][0]["etat"] == "tentative"
    assert e["execution_tentative"] == "execution-1" and len(appels) == int(appel_effectue)
    with pytest.raises(ValueError):
        agent.verifier_effet_a_executer(file, ref(1), "execution-1", "mail")


def test_cas_de_tentative_un_seul_gagnant_peut_appeler(file):
    file = demarrer(file, 1)
    file = agent.preparer_effet(file, ref(1), "execution-1", "mail", "mail_suivi")
    # Deux lectures de la même version : les candidats seuls n'autorisent pas l'appel.
    candidats = [agent.verifier_effet_a_executer(file, ref(1), "execution-1", "mail") for _ in range(2)]
    version = 1
    appels = []
    for candidat in candidats:
        if version != 1:  # Le stockage rejette le second CAS ; aucun effet perdant.
            continue
        file = json.loads(json.dumps(candidat))
        version += 1
        appels.append("appel après CAS confirmé")
    assert len(appels) == 1
    with pytest.raises(ValueError):
        agent.verifier_effet_a_executer(file, ref(1), "execution-1", "mail")


@pytest.mark.parametrize("etat", ["confirme", "incertain"])
def test_resultat_observe_exige_tentative_precedente(file, etat):
    file = demarrer(file, 1)
    file = agent.preparer_effet(file, ref(1), "execution-1", "mail", "mail_suivi")
    with pytest.raises(ValueError, match="transition"):
        agent.resultat_effet(file, ref(1), "execution-1", "mail", etat, "Preuve")


@pytest.mark.parametrize("defaut", ["proprietaire_absent", "proprietaire_vide", "perimetre_absent", "retour_intention"])
def test_tentative_malformee_refusee_a_la_relecture(file, defaut):
    file = demarrer(file, 1)
    file = agent.preparer_effet(file, ref(1), "execution-1", "mail", "mail_suivi")
    file = agent.verifier_effet_a_executer(file, ref(1), "execution-1", "mail")
    e = file["dossiers"][ref(1)]["effets"]["mail"]
    if defaut == "proprietaire_absent":
        del e["execution_tentative"]
    elif defaut == "proprietaire_vide":
        e["execution_tentative"] = ""
    elif defaut == "perimetre_absent":
        del e["version_perimetre"]
    else:
        e["etat"] = "intention"
    with pytest.raises(ValueError, match="Effet"):
        agent.valider_file(json.loads(json.dumps(file)))


@pytest.mark.parametrize("champ", ["description", "criteres_recette", "origine"])
def test_identite_exigence_ne_se_remplace_pas_sous_meme_id(file, champ):
    file = recevoir(demarrer(file, 1))
    p = deepcopy(integrer(file)["dossiers"][ref(1)]["perimetres"]["2"])
    p["exigences"][0][champ] = "Autre besoin" if champ == "description" else ["Autre contenu"]
    with pytest.raises(ValueError, match="identité"):
        integrer(file, instantane=p)
    invalide = integrer(file)
    invalide["dossiers"][ref(1)]["perimetres"]["2"] = p
    with pytest.raises(ValueError, match="identité"):
        agent.valider_file(json.loads(json.dumps(invalide)))


def test_enrichissement_conserve_criteres_et_sources_anterieurs(file):
    file = recevoir(demarrer(file, 1))
    p = deepcopy(integrer(file)["dossiers"][ref(1)]["perimetres"]["2"])
    p["exigences"][0]["criteres_recette"].append("Le résultat est également consultable au clavier")
    p["exigences"][0]["origine"].append("reponse-1")
    file = integrer(file, instantane=p)
    assert agent.reprendre_developpement(json.loads(json.dumps(file)), ref(1), "execution-1")


def test_remplacement_explicitement_relie_a_un_nouvel_id(file):
    file = recevoir(demarrer(file, 1))
    p = deepcopy(integrer(file)["dossiers"][ref(1)]["perimetres"]["2"])
    p["exigences"][0].update(statut="retiree", motif="Remplacée par E2 selon la réponse")
    p["exigences"].append({"id_stable": "E2", "description": "Nouveau besoin confirmé",
                         "criteres_recette": ["Nouveau résultat mesurable"], "origine": ["reponse-1"],
                         "statut": "incluse", "motif": "Remplace E1"})
    file = integrer(file, instantane=p)
    assert agent.reprendre_developpement(json.loads(json.dumps(file)), ref(1), "execution-1")



def test_analyse_persistante_reprise_complete_et_historique(file):
    file = agent.prendre_dossier(file, ref(1), "execution-1")
    ancienne = deepcopy(file["dossiers"][ref(1)]["decision"])
    file = recevoir(file)
    avant = deepcopy(file)
    candidat = integrer(file, ressources=["table:nouveau_domaine"])
    # Coupure avant publication : l'ancien JSON reste bloqué.
    assert file == avant
    with pytest.raises(ValueError, match="réponse.*analyser"):
        agent.demarrer_developpement(json.loads(json.dumps(file)), ref(1), "execution-1")
    # Coupure après publication : analyse, décision et ressources sont ensemble.
    file = json.loads(json.dumps(candidat))
    d = file["dossiers"][ref(1)]
    assert agent.reponses_en_attente(d) == []
    assert d["analyses_reponses"]["reponse-1"]["version_perimetre"] == 2
    assert d["decision"]["version_perimetre"] == d["version_perimetre"] == 2
    assert d["ressources"] == ["table:nouveau_domaine"]
    assert d["historique_perimetres"][0]["decision"] == ancienne
    assert d["historique_perimetres"][0]["version_perimetre"] == 1
    assert agent.demarrer_developpement(file, ref(1), "execution-1")["dossiers"][ref(1)]["branche"]
    assert agent.ajouter_reponse(file, ref(1), "execution-1", "reponse-1") == (file, "doublon")


def test_seconde_reponse_invalide_analyse_en_cours_sans_perte(file):
    file = agent.prendre_dossier(file, ref(1), "execution-1")
    file = recevoir(file)
    file = recevoir(file, "reponse-2")
    avant = deepcopy(file)
    with pytest.raises(ValueError, match="périmée"):
        integrer(file, messages=["reponse-1"])
    assert file == avant
    assert agent.reponses_en_attente(file["dossiers"][ref(1)]) == ["reponse-1", "reponse-2"]
    file = json.loads(json.dumps(integrer(file)))
    assert set(file["dossiers"][ref(1)]["analyses_reponses"]) == {"reponse-1", "reponse-2"}
    file = recevoir(file, "reponse-3")
    assert agent.reponses_en_attente(file["dossiers"][ref(1)]) == ["reponse-3"]
    with pytest.raises(ValueError, match="réponse.*analyser"):
        agent.demarrer_developpement(file, ref(1), "execution-1")


@pytest.mark.parametrize("etat", ["en_developpement", "en_revue", "pret_recette"])
def test_reponse_apres_debut_conserve_creneau_et_invalide_jalon(file, etat):
    for n in (1, 2, 3):
        file = demarrer(file, n)
    file["dossiers"][ref(1)].update(pr=101, etat=etat)
    file = recevoir(file)
    with pytest.raises(ValueError, match="réponse.*analyser"):
        agent.reprendre_developpement(file, ref(1), "execution-1")
    with pytest.raises(ValueError, match="développements"):
        demarrer(file, 4)
    file = integrer(file)
    d = file["dossiers"][ref(1)]
    assert d["etat"] == "a_corriger"
    assert d["pr"] == 101 and d["branche"] == "feat/demande-" + ref(1)
    assert agent.reprendre_developpement(file, ref(1), "execution-1") == file


def test_courtoisie_sans_modification_preserve_perimetre_et_recette(file):
    file = demarrer(file, 1)
    file["dossiers"][ref(1)].update(pr=101, etat="pret_recette")
    ancienne = deepcopy(file["dossiers"][ref(1)])
    file = recevoir(file)
    file = integrer(file, modifie=False)
    d = file["dossiers"][ref(1)]
    assert d["etat"] == "pret_recette" and d["version_perimetre"] == 1
    assert d["decision"] == ancienne["decision"]
    assert d["historique_perimetres"] == []
    assert d["analyses_reponses"]["reponse-1"]["preuve"]
    # Une deuxième conclusion n'est pas un deuxième traitement.
    with pytest.raises(ValueError, match="Analyse incomplète"):
        integrer(file, modifie=False)


@pytest.mark.parametrize("modification", ["ressources", "dependances", "decision"])
def test_impacts_modifies_ne_peuvent_pas_garder_ancienne_version(file, modification):
    file = agent.prendre_dossier(file, ref(1), "execution-1")
    file = recevoir(file)
    changements = {"ressources": ["table:autre"], "dependances": [ref(2)],
                   "decision": {**file["dossiers"][ref(1)]["decision"], "motif": "ajout"}}
    with pytest.raises(ValueError, match="nouveau périmètre"):
        integrer(file, modifie=False, **{modification: changements[modification]})


@pytest.mark.parametrize("version", [1, 3, True, "2"])
def test_version_d_analyse_invalide_refusee_sans_mutation(file, version):
    file = agent.prendre_dossier(file, ref(1), "execution-1")
    file = recevoir(file)
    avant = deepcopy(file)
    with pytest.raises(ValueError, match="Version"):
        integrer(file, version_perimetre=version)
    assert file == avant


@pytest.mark.parametrize("preuve", ["", " ", None, 42])
def test_analyse_sans_preuve_refusee(file, preuve):
    file = agent.prendre_dossier(file, ref(1), "execution-1")
    file = recevoir(file)
    avant = deepcopy(file)
    with pytest.raises(ValueError, match="Analyse"):
        integrer(file, preuve=preuve)
    assert file == avant


def test_decision_obsolete_ne_solde_pas_analyse(file):
    file = agent.prendre_dossier(file, ref(1), "execution-1")
    file = recevoir(file)
    avant = deepcopy(file)
    with pytest.raises(ValueError, match="ancien périmètre"):
        integrer(file, decision=deepcopy(file["dossiers"][ref(1)]["decision"]))
    assert file == avant


@pytest.mark.parametrize("changement,etat", [
    ({"besoin_complet": False}, "attente_precisions"),
    ({"risque": "eleve"}, "attente_validation"),
    ({"action_interdite": True}, "refuse"),
])
def test_analyse_peut_retirer_eligibilite_sans_bloquer_ses_precisions(file, changement, etat):
    file = demarrer(file, 1)
    file = recevoir(file)
    evaluation = deepcopy(file["dossiers"][ref(1)]["decision"]["evaluation"])
    evaluation.update(changement)
    decision = {"version_perimetre": 2, "evaluation": evaluation, **evaluer(evaluation)}
    file = integrer(file, decision=decision)
    assert file["dossiers"][ref(1)]["etat"] == etat
    assert agent.occupe_creneau(file["dossiers"][ref(1)])
    with pytest.raises(ValueError, match="Grille"):
        agent.reprendre_developpement(file, ref(1), "execution-1")
    assert agent.preparer_effet(file, ref(1), "execution-1", "precision-v2", "mail_precisions")


@pytest.mark.parametrize("conflit", ["ressources", "dependances"])
def test_reanalyse_recontrole_conflits_et_dependances_sur_branche_existante(file, conflit):
    file = demarrer(demarrer(file, 1), 2)
    file = recevoir(file)
    changement = {"ressources": ["table:domaine2"]} if conflit == "ressources" else {"dependances": [ref(2)]}
    file = integrer(file, **changement)
    for action in (
        lambda: agent.reprendre_developpement(file, ref(1), "execution-1"),
        lambda: agent.preparer_effet(file, ref(1), "execution-1", "pr-v2", "pr"),
    ):
        with pytest.raises(ValueError, match="Dépendance"):
            action()
    assert demarrer(file, 3)["dossiers"][ref(3)]["branche"]


def test_ancienne_intention_revalidee_avant_execution_et_resultat_du_preserve(file):
    file = demarrer(file, 1)
    file = agent.preparer_effet(file, ref(1), "execution-1", "pr-v1", "pr")
    file = agent.verifier_effet_a_executer(file, ref(1), "execution-1", "pr-v1")
    assert file["dossiers"][ref(1)]["effets"]["pr-v1"]["version_perimetre"] == 1
    file = recevoir(file)
    with pytest.raises(ValueError, match="réponse.*analyser"):
        agent.verifier_effet_a_executer(file, ref(1), "execution-1", "pr-v1")
    file = integrer(file)
    with pytest.raises(ValueError, match="ancien périmètre"):
        agent.verifier_effet_a_executer(file, ref(1), "execution-1", "pr-v1")
    # Le résultat d'une action déjà tentée doit pouvoir être consigné.
    file = constater_resultat(file, ref(1), "execution-1", "pr-v1", "incertain", "Réseau interrompu")
    file = recevoir(file, "reponse-2")
    file = agent.reconcilier_effet(file, ref(1), "execution-1", "pr-v1", "echec_certain", "Absence vérifiée")
    file = integrer(file)
    file = agent.preparer_effet(file, ref(1), "execution-1", "pr-v3", "pr")
    candidat = agent.verifier_effet_a_executer(file, ref(1), "execution-1", "pr-v3")
    assert candidat["dossiers"][ref(1)]["effets"]["pr-v3"]["version_perimetre"] == 3


def test_journal_ancien_ne_presume_pas_que_reponses_sont_analysees(file):
    file = agent.prendre_dossier(file, ref(1), "execution-1")
    d = file["dossiers"][ref(1)]
    d.pop("analyses_reponses")
    d.pop("historique_perimetres")
    d["evenements"] = ["reponse-ancienne"]
    assert agent.valider_file(file) == file
    assert agent.reponses_en_attente(d) == ["reponse-ancienne"]
    with pytest.raises(ValueError, match="réponse.*analyser"):
        agent.demarrer_developpement(file, ref(1), "execution-1")
    file = integrer(file, modifie=False)
    assert agent.demarrer_developpement(file, ref(1), "execution-1")


@pytest.mark.parametrize("analyse", [None, [], {"inconnue": {"version_perimetre": 1, "preuve": "x"}},
                                    {"reponse-1": {}},
                                    {"reponse-1": {"version_perimetre": 2, "preuve": "x"}},
                                    {"reponse-1": {"version_perimetre": True, "preuve": "x"}},
                                    {"reponse-1": {"version_perimetre": 1, "preuve": ""}}])
def test_historique_analyse_malforme_refuse_en_cli(file, analyse, tmp_path, monkeypatch, capsys):
    file = agent.prendre_dossier(file, ref(1), "execution-1")
    file = recevoir(file)
    file["dossiers"][ref(1)]["analyses_reponses"] = analyse
    chemin = tmp_path / "file.json"
    chemin.write_text(json.dumps(file), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["file_agent", "--verifier", str(chemin)])
    assert agent.main() == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False


@pytest.mark.parametrize("situation", ["pause", "autre_verrou", "integration"])
def test_analyse_respecte_pause_verrou_et_integration(file, situation):
    file = demarrer(file, 1)
    file = recevoir(file)
    if situation == "pause":
        file["actif"] = False
    elif situation == "autre_verrou":
        file["dossiers"][ref(1)]["verrou"] = "autre-execution"
    else:
        file["dossiers"][ref(1)].update(pr=101, fusion_dev="b" * 40, etat="integre_dev")
    avant = deepcopy(file)
    with pytest.raises(ValueError):
        integrer(file)
    assert file == avant


@pytest.mark.parametrize("autre", ["pr_enregistree", "autre_intention", "creation_confirmee"])
def test_intention_prete_ne_peut_pas_creer_seconde_pr(file, autre):
    file = demarrer(file, 1)
    file = agent.preparer_effet(file, ref(1), "execution-1", "pr", "pr")
    d = file["dossiers"][ref(1)]
    if autre == "pr_enregistree":
        d["pr"] = 101
    else:
        d["effets"]["autre"] = {"type": "pr", "etat": "intention"}
        if autre == "creation_confirmee":
            d["effets"]["autre"].update(etat="confirme", preuve="PR retrouvée")
    avant = deepcopy(file)
    with pytest.raises(ValueError, match="PR déjà"):
        agent.verifier_effet_a_executer(file, ref(1), "execution-1", "pr")
    assert file == avant


@pytest.mark.parametrize("type_effet", ["correction", "revue"])
def test_intention_prete_recontrole_presence_pr(file, type_effet):
    file = demarrer(file, 1)
    file["dossiers"][ref(1)]["pr"] = 101
    file = agent.preparer_effet(file, ref(1), "execution-1", "action", type_effet)
    file["dossiers"][ref(1)]["pr"] = None
    with pytest.raises(ValueError, match="PR absente"):
        agent.verifier_effet_a_executer(file, ref(1), "execution-1", "action")



def test_ancien_effet_sans_version_conserve_mais_jamais_execute(file):
    file = demarrer(file, 1)
    file["dossiers"][ref(1)]["effets"]["ancien"] = {"type": "mail_suivi", "etat": "intention"}
    assert agent.valider_file(file) == file
    with pytest.raises(ValueError, match="ancien périmètre"):
        agent.verifier_effet_a_executer(file, ref(1), "execution-1", "ancien")
    assert agent.resultat_effet(file, ref(1), "execution-1", "ancien", "echec_certain", "Aucun envoi vérifié")


def test_resultat_cas_perdant_ne_solde_pas_seconde_reponse(file):
    file = agent.prendre_dossier(file, ref(1), "execution-1")
    file = recevoir(file)
    candidat = integrer(file)
    # Entre lecture et CAS, un événement est arrivé : le candidat est périmé.
    serveur = recevoir(file, "reponse-2")
    version_lue, version_serveur = 20, 21
    with pytest.raises(ValueError, match="Conflit"):
        if version_lue != version_serveur:
            raise ValueError("Conflit CAS : candidat non publié")
        serveur = candidat
    assert agent.reponses_en_attente(serveur["dossiers"][ref(1)]) == ["reponse-1", "reponse-2"]
    with pytest.raises(ValueError, match="réponse.*analyser"):
        agent.demarrer_developpement(serveur, ref(1), "execution-1")
