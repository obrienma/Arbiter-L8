---
id: arbiter-l8-2026-07-06T1853-synapse-l4-ground-truth-fixture
repo: arbiter-l8
title: "A Synapse-L4-Shaped Ground-Truth Fixture, Scoped to What's Actually Solvable"
date: 2026-07-06
phase: 3
tags: [ground-truth, fail-fast, live-verification, validator-as-judge]
files: [tests/fixtures/synapse_l4_ground_truth.json, README.md, docs/DEV_GETTING_STARTED.md]
---

Third item off the punch list. ADR-0001 explicitly defers "the harder
question of what ground truth looks like for Synapse-L4's Axiom
extraction" as unsolved, out-of-scope follow-up — this entry solves the
narrower, honestly-scoped slice of that problem rather than pretending to
close the whole gap.

### Decision: Ground Truth for the Deterministic Fast Path, Not the LLM Path

Sentinel-L7's ground truth comes from `TransactionStreamService`'s pre-AI
`is_threat` label — a value known correct *before* any AI runs. Synapse-L4
has no equivalent generator, and manufacturing labels for genuine
LLM-driven extraction would just be guessing, not ground truth. But
`extract()`'s "EventHorizon raw document" fast path
(`_try_direct_extraction`, Shape 2) is itself a fixed, documented,
deterministic mapping (`raw.payload.status`/`processed.classification` →
`status`/`anomaly_score`) that runs with **no LLM involved** — Synapse-L4
trusts this mapping as authoritative by design (that's the whole point of
a fast path). Computing `expected_label` for each fixture example directly
from that mapping table is not a guess; it's applying the same
specification the code itself implements. This is real, non-circular
ground truth for exactly the slice of "extraction correctness" that's
actually deterministic — not the harder LLM-driven slice ADR-0001 still
flags as unsolved.

### Decision: Verify the Hand Computation Against the Real Server, Not Just the Read Code

All 12 examples' `expected_label` values were computed by hand from
reading `_try_direct_extraction`, then run against a real local
Synapse-L4 instance before being committed as fact — `12/12 (100.0%)`.
Reading the code and being right about it are different claims; this
repo's whole live-verification practice this session has been about not
conflating them.

### Pattern: Discovered a Real Contradiction Trap, Deterministically

While hand-computing expected values, noticed `status` and `anomaly_score`
are derived by two *independent* branches in the same function: `status`
prioritizes `raw.payload.status` (`passed`/`success`/`failed`/`error`)
over `processed.classification`, but `anomaly_score` is driven by
`classification` alone, unconditionally. So `status: "passed"` +
`classification: "critical"` produces `status: "nominal"` +
`anomaly_score: 0.9` — the exact "Silent Contradiction"
`rule_anomaly_score_status_consistency` exists to catch, except reproduced
by Synapse-L4's own deterministic code, not an LLM. Confirmed live:
real `422 judge_rejected`. Every fixture example was deliberately chosen
to avoid this combination (verified by hand against the safe/unsafe
matrix, not by trial and error) — the fixture demonstrates the fast path
working correctly, and a companion one-off example (documented in
`docs/DEV_GETTING_STARTED.md`) demonstrates the trap on demand.

### Decision: Documented, Not Fixed

The contradiction trap is Synapse-L4's own code, not arbiter-l8's —
fixing it would mean changing another repo's extraction logic, which is
out of scope for "add a fixture" and wasn't asked for. Added as a new
README Known Issue instead, matching how the CLI's `SynapseL4Error` gap
was fixed here (arbiter-l8's own code) while Sentinel-L7's semantic
cache amplification (Sentinel-L7's own code) is only ever documented, not
patched, in this repo.

### Decision: No Automated Test Uses This Fixture

Checked `sentinel_l7_ground_truth.json` first: it's never loaded by
`pytest`, only referenced in CLI help text — it's a live-verification
fixture, not a CI fixture (that role belongs to `compliance_dataset.json`,
which is mocked in `tests/`). `synapse_l4_ground_truth.json` follows the
same precedent rather than inventing a new one.
