"""Logic tests that need only pytest. They use tests/sdk_stub.py, not real consensus."""
import copy
import json
import types
from pathlib import Path

import pytest

from sdk_stub import load_contract

ROOT = Path(__file__).resolve().parent.parent
URL_A = "https://project.example.org/docs"
URL_B = "https://project.example.org/changelog"

RUBRIC = {
    "criteria": [
        {"id": "coverage", "description": "Documentation covers every public feature.", "weight": 4, "floor": 0},
        {"id": "accuracy", "description": "Documented behaviour matches the shipped release.", "weight": 4, "floor": 5},
        {"id": "upkeep", "description": "Docs were updated alongside recent releases.", "weight": 2, "floor": 0},
    ],
    "pass_score": 70, "margin": 10, "tolerance": 1, "flip_confirmations": 2,
}


@pytest.fixture
def world():
    module, rt = load_contract(ROOT / "contracts" / "plumbline_ledger.py")
    contract = module.PlumblineLedger()
    rt.web = lambda url: types.SimpleNamespace(status=200, body=f"Evidence page for {url}".encode())
    return module, rt, contract


def scores(c, a, u):
    return {"scores": {"coverage": c, "accuracy": a, "upkeep": u},
            "citations": {k: (URL_A if v else "") for k, v in zip(("coverage", "accuracy", "upkeep"), (c, a, u))}}


def open_case(contract, rubric=RUBRIC, case_id="case-1"):
    return contract.open_case(case_id, "Example project docs", json.dumps(rubric), json.dumps([URL_A, URL_B]))


# ---------------------------------------------------------------- pure scoring

def test_weighted_score_and_bands(world):
    module, _, _ = world
    rubric = module._rubric(json.dumps(RUBRIC))
    assert module._band(rubric, {"coverage": 9, "accuracy": 9, "upkeep": 9})[:2] == (90, "PASS")
    assert module._band(rubric, {"coverage": 3, "accuracy": 3, "upkeep": 3})[1] == "FAIL"
    assert module._band(rubric, {"coverage": 7, "accuracy": 7, "upkeep": 7})[:2] == (70, "BORDERLINE")


def test_hard_gate_vetoes_a_high_weighted_score(world):
    module, _, _ = world
    rubric = module._rubric(json.dumps(RUBRIC))
    weighted, band, gates = module._band(rubric, {"coverage": 10, "accuracy": 4, "upkeep": 10})
    assert weighted == 76 and band == "FAIL" and gates == ["accuracy"]


def test_hysteresis_state_machine(world):
    module, _, _ = world
    idle = {"toward": "", "count": 0}
    s, st, e = module._advance("UNSET", idle, "PASS", 2)
    assert (s, e) == ("PASS", "SET")
    s, st, e = module._advance(s, st, "FAIL", 2)
    assert (s, e, st["count"]) == ("PASS", "FLIP_PENDING", 1)
    s, st, e = module._advance(s, st, "BORDERLINE", 2)          # noise resets the streak
    assert (s, e, st["count"]) == ("PASS", "HELD_BORDERLINE", 0)
    s, st, e = module._advance(s, st, "FAIL", 2)
    s, st, e = module._advance(s, st, "NO_EVIDENCE", 2)          # a gap neither confirms nor resets
    assert (e, st["count"]) == ("NO_EVIDENCE", 1)
    s, st, e = module._advance(s, st, "FAIL", 2)
    assert (s, e) == ("FAIL", "FLIPPED")


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(tolerance=4),
    lambda r: r.update(pass_score=95, margin=10),
    lambda r: r.update(margin=0),
    lambda r: r.update(flip_confirmations=0),
    lambda r: r.update(extra=1),
    lambda r: r["criteria"].__delitem__(slice(1, None)),
    lambda r: r["criteria"][0].update(weight=11),
    lambda r: r["criteria"][1].update(id="coverage"),
    lambda r: r["criteria"][0].update(weight=True),
])
def test_invalid_rubrics_are_rejected(world, mutate):
    module, _, contract = world
    bad = copy.deepcopy(RUBRIC)
    mutate(bad)
    with pytest.raises(module.gl.vm.UserError):
        open_case(contract, bad)


@pytest.mark.parametrize("refs", [
    ["http://project.example.org/a"], ["https://localhost/a"], ["https://user@project.example.org/a"],
    ["https://project.example.org:8443/a"], ["https://10.0.0.1/a"], [URL_A, URL_A], [],
])
def test_invalid_evidence_urls_are_rejected(world, refs):
    module, _, contract = world
    with pytest.raises(module.gl.vm.UserError):
        contract.open_case("c", "x subject", json.dumps(RUBRIC), json.dumps(refs))


# ------------------------------------------------------------------ end to end

def test_first_pass_sets_standing_and_model_never_sees_thresholds(world):
    module, rt, contract = world
    open_case(contract)
    rt.model = lambda prompt, **kw: scores(9, 9, 9)
    record = contract.assess("case-1", 0)
    assert (record["band"], record["effect"], record["weighted_score"]) == ("PASS", "SET", 90)
    assert contract.is_passing("case-1") is True
    assert rt.validate()
    prompt = rt.prompts[-1]
    assert "pass_score" not in prompt and "weight" not in prompt and "floor" not in prompt
    assert "UNSET" not in prompt and "standing" not in prompt


def test_flip_needs_two_consecutive_decisive_failures(world):
    module, rt, contract = world
    open_case(contract)
    rt.model = lambda prompt, **kw: scores(9, 9, 9)
    contract.assess("case-1", 0)
    rt.model = lambda prompt, **kw: scores(2, 2, 2)
    assert contract.assess("case-1", 1)["effect"] == "FLIP_PENDING"
    assert contract.get_standing("case-1")["passing"] is True
    rt.model = lambda prompt, **kw: scores(7, 7, 7)
    assert contract.assess("case-1", 2)["effect"] == "HELD_BORDERLINE"
    rt.model = lambda prompt, **kw: scores(2, 2, 2)
    contract.assess("case-1", 3)
    assert contract.assess("case-1", 4)["effect"] == "FLIPPED"
    assert contract.get_standing("case-1")["standing"] == "FAIL"
    assert contract.get_round("case-1", 5)["standing_after"] == "FAIL"


def test_unavailable_evidence_records_a_round_without_moving_standing(world):
    module, rt, contract = world
    open_case(contract)
    rt.model = lambda prompt, **kw: scores(9, 9, 9)
    contract.assess("case-1", 0)
    rt.web = lambda url: types.SimpleNamespace(status=503, body=b"down")
    record = contract.assess("case-1", 1)
    assert (record["band"], record["effect"], record["scores"]) == ("NO_EVIDENCE", "NO_EVIDENCE", {})
    assert contract.is_passing("case-1") is True
    assert rt.validate()


def test_owner_stale_round_and_round_limit(world):
    module, rt, contract = world
    open_case(contract)
    rt.model = lambda prompt, **kw: scores(9, 9, 9)
    rt.gl.message.sender_address = "0xintruder"
    with pytest.raises(module.gl.vm.UserError, match="only the case owner"):
        contract.assess("case-1", 0)
    rt.gl.message.sender_address = "0xowner"
    contract.assess("case-1", 0)
    with pytest.raises(module.gl.vm.UserError, match="stale"):
        contract.assess("case-1", 0)
    for n in range(1, module.MAX_ROUNDS):
        contract.assess("case-1", n)
    with pytest.raises(module.gl.vm.UserError, match="LIMIT"):
        contract.assess("case-1", module.MAX_ROUNDS)


def test_update_evidence_changes_the_snapshot_not_the_rubric(world):
    module, rt, contract = world
    case = open_case(contract)
    updated = contract.update_evidence("case-1", 0, json.dumps([URL_B]))
    assert updated["evidence_version"] == 2 and updated["evidence_refs"] == [URL_B]
    assert updated["rubric_digest"] == case["rubric_digest"]


# ------------------------------------------------- validator equivalence rules

def agree_with(world, validator_scores):
    module, rt, contract = world
    open_case(contract)
    rt.model = lambda prompt, **kw: scores(9, 9, 9)
    contract.assess("case-1", 0)
    rt.model = lambda prompt, **kw: validator_scores
    return rt.validate()


def test_validator_accepts_scores_within_tolerance_and_same_band(world):
    assert agree_with(world, scores(8, 9, 10))


def test_validator_accepts_a_different_but_valid_citation(world):
    other = scores(9, 9, 9)
    other["citations"] = {k: URL_B for k in other["citations"]}
    assert agree_with(world, other)


def test_validator_rejects_a_score_outside_tolerance(world):
    assert not agree_with(world, scores(7, 9, 9))


def test_validator_rejects_same_tolerance_but_different_band(world):
    module, rt, contract = world
    open_case(contract)
    rt.model = lambda prompt, **kw: scores(8, 8, 8)               # 80 -> PASS
    contract.assess("case-1", 0)
    rt.model = lambda prompt, **kw: scores(7, 7, 7)               # 70 -> BORDERLINE, each within 1
    assert not rt.validate()


def test_validator_rejects_a_gate_that_only_the_leader_missed(world):
    module, rt, contract = world
    open_case(contract)
    rt.model = lambda prompt, **kw: scores(9, 5, 9)
    contract.assess("case-1", 0)
    rt.model = lambda prompt, **kw: scores(9, 4, 9)               # within tolerance, but trips the floor
    assert not rt.validate()


def test_validator_rejects_different_evidence(world):
    module, rt, contract = world
    open_case(contract)
    rt.model = lambda prompt, **kw: scores(9, 9, 9)
    contract.assess("case-1", 0)
    rt.web = lambda url: types.SimpleNamespace(status=200, body=b"The page changed after the leader read it")
    assert not rt.validate()


def test_validator_rejects_forged_leader_results(world):
    module, rt, contract = world
    open_case(contract)
    rt.model = lambda prompt, **kw: scores(9, 9, 9)
    contract.assess("case-1", 0)
    honest = rt.captured[-1][0]
    forged_digest = dict(honest, input_digest="sha256:" + "0" * 64)
    extra_field = dict(honest, bonus=1)
    invented = dict(honest, citations={**honest["citations"], "coverage": "https://invented.example.org/x"})
    inflated = dict(honest, scores={**honest["scores"], "coverage": 11})
    unsupported = dict(honest, citations={**honest["citations"], "upkeep": ""})
    for forged in (forged_digest, extra_field, invented, inflated, unsupported):
        assert not rt.validate(forged)


def test_malformed_model_output_fails_closed(world):
    module, rt, contract = world
    open_case(contract)
    for bad in ({"scores": {"coverage": 9}, "citations": {}}, {"scores": {}, "citations": {}, "note": "x"}, "not json"):
        rt.model = lambda prompt, bad=bad, **kw: bad
        with pytest.raises(module.gl.vm.UserError, match="LLM_ERROR"):
            contract.assess("case-1", 0)
    assert contract.get_case("case-1")["round"] == 0
