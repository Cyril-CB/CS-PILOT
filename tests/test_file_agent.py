"""Scénarios de reprise et de coordination du pilote, sans effets externes."""

from copy import deepcopy

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
