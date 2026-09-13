"""La priorité ne doit jamais neutraliser une barrière du pilote."""

from copy import deepcopy

import pytest

from scripts.triage_agent import ROOT, calibrer, evaluer, load_json


@pytest.fixture
def evaluation():
    return deepcopy(load_json(ROOT / "docs/agent-demandes/calibration-v1.json")
                    ["cas"][1]["evaluation"])


def test_calibration():
    resultat = calibrer(ROOT / "docs/agent-demandes/calibration-v1.json")
    assert resultat == {"cas": 15, "erreurs": [], "ok": True}


@pytest.mark.parametrize("changement,attendu", [
    ({"source_verifiee": False}, "quarantaine"),
    ({"integrite_verifiee": False}, "quarantaine"),
    ({"contenu_suspect": True}, "quarantaine"),
    ({"doublon": True, "conflit_reference": True}, "quarantaine"),
    ({"action_interdite": True}, "refuser"),
    ({"acces_manquant": True, "couverture": "complete"}, "clarifier_acces"),
    ({"besoin_complet": False}, "clarifier"),
    ({"preuves_completes": False}, "clarifier"),
    ({"risque": "eleve"}, "validation_humaine"),
])
def test_score_maximal_ne_contourne_pas_les_barrieres(evaluation, changement, attendu):
    evaluation["notes"] = dict.fromkeys(evaluation["notes"], 4)
    evaluation.update(changement)
    resultat = evaluer(evaluation)
    assert resultat["score"] == 100
    assert resultat["decision"] == attendu
    assert resultat["developpement_eligible"] is False


def test_seuil_et_capacite_existante(evaluation):
    assert evaluer(evaluation)["score"] == 70
    assert evaluer(evaluation)["decision"] == "creer_module"
    evaluation["notes"]["frequence"] = 0
    assert evaluer(evaluation)["decision"] == "reporter"
    evaluation["couverture"] = "complete"
    assert evaluer(evaluation)["decision"] == "orienter_existant"


@pytest.mark.parametrize("cle,valeur", [
    ("source_verifiee", "false"), ("source_verifiee", 1),
    ("couverture", "inconnue"), ("risque", "inconnu"),
    ("notes", {}), ("notes", None),
])
def test_evaluation_invalide_echoue(evaluation, cle, valeur):
    evaluation[cle] = valeur
    with pytest.raises(ValueError):
        evaluer(evaluation)


@pytest.mark.parametrize("valeur", [True, -1, 5, 2.5, "4"])
def test_notes_invalides(evaluation, valeur):
    evaluation["notes"]["valeur"] = valeur
    with pytest.raises(ValueError):
        evaluer(evaluation)


def test_champ_absent_ou_inconnu(evaluation):
    absent = deepcopy(evaluation)
    del absent["source_verifiee"]
    with pytest.raises(ValueError):
        evaluer(absent)
    evaluation["autorisation"] = True
    with pytest.raises(ValueError):
        evaluer(evaluation)


def test_cles_json_dupliquees_refusees(tmp_path):
    path = tmp_path / "evaluation.json"
    path.write_text('{"source_verifiee":false,"source_verifiee":true}')
    with pytest.raises(ValueError, match="dupliquée"):
        load_json(path)


def test_decision_exige_la_version_du_perimetre():
    schema = load_json(ROOT / "docs/agent-demandes/decision-v1.schema.json")
    assert "version_perimetre" in schema["required"]
    regle = schema["properties"]["version_perimetre"]
    assert regle["type"] == "integer"
    assert regle["minimum"] == 1
    assert "default" not in regle  # Ne jamais inventer l'instantané analysé.
    assert schema["additionalProperties"] is False
