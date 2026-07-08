---
id: arbiter-l8-2026-07-04T0435-synapse-l4-adapter
repo: arbiter-l8
title: "First Real System-Under-Test: the Synapse-L4 HTTP Adapter"
date: 2026-07-04
phase: 3
tags: [adapter-pattern, respx, additive-observability]
files: [src/arbiter_l8/adapters/__init__.py, src/arbiter_l8/adapters/synapse_l4.py, tests/test_synapse_l4_adapter.py, README.md]
---

First real system-under-test wrapper: `make_synapse_l4_system_under_test()`
POSTs to Synapse-L4's `/ingest` and maps its Axiom response into
`EvalPrediction`. Everything up to this point had only ever run against
the hand-written fixture — this is the first adapter that could score real
traffic.

### Pattern: Adapter, reused and made concrete

The scaffold-phase `Adapter` pattern entry (Phase 2 journal) was written
against a hypothetical future wrapper. This is that wrapper: `raw_output`
carries the untouched Axiom dict, `label` carries Synapse's own vocabulary
(`status`) unmapped, and the harness (`run_eval`, `evaluate_item`) imports
nothing from `adapters/` — only the adapter imports `SystemUnderTest` from
`harness.py`, one-directional as designed.

### Decision: HTTP over direct import, decided in the plan step not here

This was resolved during planning (docs/journal entry for the config-module
step doesn't cover it, but the plan file does): Synapse-L4's `config.py`
instantiates a pydantic-settings singleton at import time requiring a
reachable Redis URL, its dependency set is heavy and service-specific, it
runs on Python 3.14 against arbiter-l8's pinned 3.12, and importing its
internals at all would violate the standalone-module ADR. HTTP sidesteps
all four at once. Recorded here as the concrete implementation of a
decision made one step earlier, not re-litigated.

### Decision: Raise on HTTP error rather than degrade to a null prediction

`SynapseL4Error` wraps Synapse-L4's structured error bodies (422
extraction_failed/judge_rejected, 502 emit_failed) and is raised, not
swallowed into some placeholder `EvalPrediction`. This means one bad
example currently aborts an entire `run_eval()` batch — acknowledged as a
real limitation in the adapter's docstring rather than silently accepted.
Fixing that is `run_eval()`'s job (per-example error handling), not
something to paper over inside one adapter.

### Challenge: No live verification this step

Synapse-L4 wasn't running locally when this adapter was built, so
verification is mocked-only (`respx`, four tests: success mapping, both
error paths, default base URL resolution). Per the Phase 2 precedent of
treating "instrumented" and "confirmed flowing" as separate claims: this
adapter is *tested against a faithful mock of the documented contract*,
not yet *confirmed against the real running service*. Flagged rather than
assumed — a live check against an actual Synapse-L4 process is still
outstanding.
