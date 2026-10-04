# Plumbline: submission draft (Intelligent Contracts)

**Primitive:** tolerance-band rubric attestations with hysteresis for living obligations.

**Not a thin LLM wrapper:** the model only emits per-criterion integers with citations. Weights, hard floors, thresholds, bands and the standing verdict are deterministic and hidden from the model.

**Consensus:** custom validator via `gl.vm.run_nondet_unsafe`. Acceptance requires matching evidence digest, per-criterion scores within a frozen tolerance, and an identical deterministic band. Identical scores and citation choices are intentionally not required.

**State design:** frozen rubric plus digest, evidence versioning, bounded round records, standing verdict with a flip streak. `is_passing` makes it composable by other contracts.

**Documentation and tests:** README, `docs/CONSENSUS.md` (equivalence rules and threat table), 32 SDK-free logic tests, and gltest direct-mode tests.

**Honest status:** not deployed; direct-mode tests, lint and ABI extraction pending in a GenLayer environment (see README, Verification status).
