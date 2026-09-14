"""Scénarios de reprise et de coordination du pilote, sans effets externes."""

from copy import deepcopy
import json
import sys

import pytest

from scripts import file_agent as agent
from scripts.triage_agent import ROOT, evaluer, load_json


def ref(n):
    return f"{n:032x}"


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
    return file


def demarrer(file, n):
    file = agent.prendre_dossier(file, ref(n), f"execution-{n}")
    return agent.demarrer_developpement(file, ref(n), f"execution-{n}")


@pytest.mark.parametrize("action", ["demarrer", "migration", "branche", "pr",
                                    "correction", "revue", "mail_suivi", "mail_precisions"])
def test_reponse_persistee_bloque_action_sur_ancien_perimetre(file, action):
    file["dossiers"][ref(1)]["ressources"] = ["schema"]
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


def test_effet_incertain_jamais_repete(file):
    file = agent.prendre_dossier(file, ref(1), "x")
    file = agent.preparer_effet(file, ref(1), "x", "question-v1", "mail_precisions")
    file = agent.resultat_effet(file, ref(1), "x", "question-v1", "incertain", "Coupure réseau")
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
    # Les intentions précèdent les résultats : l'incertitude doit empêcher
    # toute nouvelle intention, pas l'enregistrement des résultats déjà dus.
    if etat != "intention":
        for cle in file["dossiers"][ref(1)]["effets"]:
            file = agent.resultat_effet(file, ref(1), "execution-1", cle, etat, "Preuve synthétique")
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
        file = agent.resultat_effet(file, ref(1), "execution-1", "pr-v1", etat, "Preuve synthétique")
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
    file = agent.resultat_effet(file, ref(1), "execution-1", "mail-v1", "incertain", "Coupure réseau")
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
    file = agent.resultat_effet(file, ref(1), "execution-1", "initial", "incertain", "Résultat non déterminé")
    avant = deepcopy(file)
    with pytest.raises(ValueError, match="incertain"):
        agent.preparer_effet(file, ref(1), "execution-1", "suivi", "mail_suivi")
    assert file == avant


@pytest.mark.parametrize("etat_final", ["confirme", "echec_certain"])
def test_reconcilier_effet_incertain_preserve_ambiguite_et_reprend(file, etat_final):
    file = demarrer(file, 1)
    file = agent.preparer_effet(file, ref(1), "execution-1", "mail-v1", "mail_suivi")
    file = agent.resultat_effet(file, ref(1), "execution-1", "mail-v1", "incertain",
                               "Coupure avant réception de la réponse")
    with pytest.raises(ValueError, match="transition"):
        agent.resultat_effet(file, ref(1), "execution-1", "mail-v1", etat_final,
                             "Vérification distante")
    file = agent.reconcilier_effet(file, ref(1), "execution-1", "mail-v1", etat_final,
                                   "Vérification distante concluante")
    effet = file["dossiers"][ref(1)]["effets"]["mail-v1"]
    assert effet == {
        "type": "mail_suivi",
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
        file = agent.resultat_effet(file, ref(1), "execution-1", "mail-v1", etat_depart,
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
    file = agent.resultat_effet(file, ref(1), "execution-1", "mail-v1", "confirme", "Trouvé")
    file["dossiers"][ref(1)]["effets"]["mail-v1"]["historique"] = historique
    avec_erreur = deepcopy(file)
    with pytest.raises(ValueError, match="historique"):
        agent.valider_file(file)
    assert file == avec_erreur


def test_nouvelle_intention_pr_apres_echec_certain_uniquement(file):
    file = demarrer(file, 1)
    file = agent.preparer_effet(file, ref(1), "execution-1", "pr-v1", "pr")
    file = agent.resultat_effet(file, ref(1), "execution-1", "pr-v1", "echec_certain",
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
    return agent.integrer_reponses(
        file, ref(1), "execution-1",
        messages if messages is not None else agent.reponses_en_attente(d), **analyse)


def recevoir(file, message="reponse-1"):
    return agent.ajouter_reponse(file, ref(1), "execution-1", message)[0]


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
    assert agent.verifier_effet_a_executer(file, ref(1), "execution-1", "pr-v1")["version_perimetre"] == 1
    file = recevoir(file)
    with pytest.raises(ValueError, match="réponse.*analyser"):
        agent.verifier_effet_a_executer(file, ref(1), "execution-1", "pr-v1")
    file = integrer(file)
    with pytest.raises(ValueError, match="ancien périmètre"):
        agent.verifier_effet_a_executer(file, ref(1), "execution-1", "pr-v1")
    # Le résultat d'une action déjà tentée doit pouvoir être consigné.
    file = agent.resultat_effet(file, ref(1), "execution-1", "pr-v1", "incertain", "Réseau interrompu")
    file = recevoir(file, "reponse-2")
    file = agent.reconcilier_effet(file, ref(1), "execution-1", "pr-v1", "echec_certain", "Absence vérifiée")
    file = integrer(file)
    file = agent.preparer_effet(file, ref(1), "execution-1", "pr-v3", "pr")
    assert agent.verifier_effet_a_executer(file, ref(1), "execution-1", "pr-v3")["version_perimetre"] == 3


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
