# Plumbline

**A living verdict that resists noise.** Plumbline is a standalone GenLayer Intelligent Contract primitive for attestations that must stay true over time: "does this project still meet the bar?" It scores evidence against a frozen rubric, reaches consensus with a tolerance band instead of exact equality, and flips a standing verdict only after repeated decisive evidence.

## Why it exists

Most "AI decides X" contracts return one verdict once. Real obligations drift: documentation rots, an SLA slips, a grantee stops shipping. Re-asking an LLM every week produces flip-flopping, because model scores are noisy near any threshold. Plumbline separates the three things that are usually blended together:

| Concern | Who handles it |
|---|---|
| Reading messy evidence and scoring criteria 0-10 | Validators (non-deterministic, consensus-checked) |
| Weights, hard floors, pass threshold, bands | Deterministic contract code. **The model never sees these** |
| Whether the standing verdict changes | A hysteresis state machine in contract code |

## How consensus is used

`assess` calls `gl.vm.run_nondet_unsafe` with a custom validator. The leader fetches the evidence URLs and asks the model for one integer per criterion plus a citation. Each validator independently fetches and scores, then accepts the leader only if **all** hold:

1. Strict schema, with exact criterion IDs, integers in range, no extra fields, no invented citations, and no non-zero score without a citation.
2. The same evidence digest (same bytes read, same availability).
3. Every criterion is within the rubric's frozen `tolerance` (0-3 points).
4. The deterministic band computed from each side's scores is identical (PASS, BORDERLINE or FAIL, with floors applied).

It deliberately does not compare identical scores or identical cited URLs. Those are incidental. Near-threshold disagreement is an honest failure to agree, not something settled by noise. See [docs/CONSENSUS.md](docs/CONSENSUS.md).

## State design

```
case = { owner, rubric (frozen) + rubric_digest, evidence_refs, evidence_version,
         round, standing: UNSET|PASS|FAIL, streak: {toward, count}, last_effect }
round record = scores, citations, weighted_score, failed_gates, band, tolerance_used,
               effect, standing_after, input_digest, evidence_digest
```

Rubric fields: `criteria[{id, description, weight 1-10, floor 0-10}]` (2-6), `pass_score` 40-95, `margin` 1-20, `tolerance` 0-3, `flip_confirmations` 1-3. Weighted score is integer math: `sum(weight*score)*100 // (10*sum(weight))`. A score below any `floor` is a hard veto (FAIL) regardless of the weighted total.

Hysteresis: the first decisive band sets the standing. After that, a decisive opposite band must repeat `flip_confirmations` times in a row to flip. BORDERLINE resets the streak. A round with unavailable evidence is recorded but neither confirms nor resets anything.

## API

| Call | Who | Purpose |
|---|---|---|
| `open_case(case_id, subject_label, rubric_json, evidence_refs_json)` | anyone (becomes owner) | Freeze a rubric and register evidence |
| `update_evidence(case_id, expected_round, evidence_refs_json)` | owner | Point at new evidence; rubric stays frozen |
| `assess(case_id, expected_round)` | owner | Run one consensus scoring round |
| `get_case`, `get_round`, `get_standing`, `list_cases` | anyone | Read state |
| `is_passing(case_id)` | anyone / other contracts | Boolean gate |

Bounds: 24 cases, 12 rounds per case, 3 evidence URLs of at most 5,000 bytes each (strict UTF-8, public HTTPS hostnames only).

## Use it from another contract

Any contract can gate an action on a standing verdict without knowing the rubric: read `is_passing(case_id)` on the deployed ledger. Typical uses are milestone payouts that stay conditional on continued compliance, delegate or grantee conduct gates, SLA credits, and registry listings that must keep meeting criteria.

## Tests

```bash
pip install -r requirements.txt
python -m pytest                      # direct mode (mocked web and model) plus SDK-free logic tests
genvm-lint check contracts/plumbline_ledger.py
```

- `tests/test_ledger.py`: gltest direct-mode tests (mocked I/O).
- `tests/test_logic_sdkfree.py`: 32 cases that need only pytest, using `tests/sdk_stub.py`. The stub is not a consensus simulator; it runs the leader once and lets tests feed the validator forged or drifted results.

## Verification status (read before relying on this)

- The 32 SDK-free logic cases pass locally against the stub.
- `tests/test_ledger.py`, `genvm-lint`, ABI extraction and any deployment have **not** been run for this package. Run them in a GenLayer-enabled environment first.
- The `Depends` runner hash on line 1 was carried over from the reference project. Confirm it matches the runner your target network expects.
- Real model behaviour near band edges is untested. Tolerance and margin defaults are starting points to tune against live runs.

## Limits

- Evidence authenticity is not verified (no signatures, DNS pinning or freshness). Page text is untrusted prompt input; the strict schema and citation binding reduce, but do not eliminate, injection risk.
- If a page changes between leader and validator fetches, digests differ and the round fails. That is conservative by design.
- Only the case owner can assess, which prevents round-burning griefing but makes the owner a trust point. Swap in an allowlist or bonded assessors for adversarial settings.
- A passing standing describes registry state against the rubric, not truth or certification.
