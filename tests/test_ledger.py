"""gltest direct-mode tests (mocked web and model I/O; not live consensus).

Same harness conventions as the reference registry: direct_vm / direct_deploy fixtures,
mock_web, mock_llm, run_validator. The SDK version is a single constant; set it to the
version your gltest installation targets.
"""
import json

SDK = "v0.6.0-rc5"
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


def llm(value) -> str:
    """The direct mock decodes once; the SDK then parses JSON text."""
    return json.dumps(json.dumps(value))


def verdict(c, a, u, cite=URL_A):
    return llm({"scores": {"coverage": c, "accuracy": a, "upkeep": u},
                "citations": {"coverage": cite, "accuracy": cite, "upkeep": cite}})


def deploy(direct_vm, direct_deploy, direct_owner):
    direct_vm.sender = direct_owner
    direct_vm.warp("2030-01-01T12:00:00Z")
    contract = direct_deploy("contracts/plumbline_ledger.py", sdk_version=SDK)
    contract.open_case("docs", "Example project docs", json.dumps(RUBRIC), json.dumps([URL_A, URL_B]))
    direct_vm.mock_web(r".*", {"status": 200, "body": "Project documentation page with release notes."})
    return contract


def test_pass_round_sets_standing_and_validator_accepts(direct_vm, direct_deploy, direct_owner):
    contract = deploy(direct_vm, direct_deploy, direct_owner)
    direct_vm.mock_llm(r"RUBRIC SCORING", verdict(9, 9, 9))
    record = contract.assess("docs", 0)
    assert record["band"] == "PASS" and record["effect"] == "SET" and record["weighted_score"] == 90
    assert contract.is_passing("docs") is True
    assert direct_vm.run_validator()


def test_validator_tolerates_small_score_drift_but_not_a_band_change(direct_vm, direct_deploy, direct_owner):
    contract = deploy(direct_vm, direct_deploy, direct_owner)
    direct_vm.mock_llm(r"RUBRIC SCORING", verdict(8, 8, 8))
    contract.assess("docs", 0)
    direct_vm.clear_mocks()
    direct_vm.mock_web(r".*", {"status": 200, "body": "Project documentation page with release notes."})
    direct_vm.mock_llm(r"RUBRIC SCORING", verdict(8, 9, 8))          # within tolerance, same band
    assert direct_vm.run_validator()
    direct_vm.clear_mocks()
    direct_vm.mock_web(r".*", {"status": 200, "body": "Project documentation page with release notes."})
    direct_vm.mock_llm(r"RUBRIC SCORING", verdict(7, 7, 7))          # within tolerance, BORDERLINE band
    assert not direct_vm.run_validator()


def test_two_decisive_failures_are_needed_to_flip(direct_vm, direct_deploy, direct_owner):
    contract = deploy(direct_vm, direct_deploy, direct_owner)
    direct_vm.mock_llm(r"RUBRIC SCORING", verdict(9, 9, 9))
    contract.assess("docs", 0)
    direct_vm.clear_mocks()
    direct_vm.mock_web(r".*", {"status": 200, "body": "Project documentation page with release notes."})
    direct_vm.mock_llm(r"RUBRIC SCORING", verdict(2, 2, 2))
    assert contract.assess("docs", 1)["effect"] == "FLIP_PENDING"
    assert contract.is_passing("docs") is True
    assert contract.assess("docs", 2)["effect"] == "FLIPPED"
    assert contract.get_standing("docs")["standing"] == "FAIL"


def test_unavailable_evidence_does_not_move_standing(direct_vm, direct_deploy, direct_owner):
    contract = deploy(direct_vm, direct_deploy, direct_owner)
    direct_vm.mock_llm(r"RUBRIC SCORING", verdict(9, 9, 9))
    contract.assess("docs", 0)
    direct_vm.clear_mocks()
    direct_vm.mock_web(r".*", {"status": 503, "body": b"service unavailable"})
    record = contract.assess("docs", 1)
    assert record["band"] == "NO_EVIDENCE" and record["effect"] == "NO_EVIDENCE"
    assert contract.is_passing("docs") is True


def test_only_owner_may_assess_and_stale_rounds_revert(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy(direct_vm, direct_deploy, direct_owner)
    direct_vm.mock_llm(r"RUBRIC SCORING", verdict(9, 9, 9))
    with direct_vm.prank(direct_alice):
        with direct_vm.expect_revert("only the case owner"):
            contract.assess("docs", 0)
    contract.assess("docs", 0)
    with direct_vm.expect_revert("round is stale"):
        contract.assess("docs", 0)


def test_fabricated_citation_fails_closed(direct_vm, direct_deploy, direct_owner):
    contract = deploy(direct_vm, direct_deploy, direct_owner)
    direct_vm.mock_llm(r"RUBRIC SCORING", verdict(9, 9, 9, cite="https://invented.example.org/proof"))
    with direct_vm.expect_revert("LLM_ERROR"):
        contract.assess("docs", 0)
    assert contract.get_case("docs")["round"] == 0
