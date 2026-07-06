---
id: sentinel-eval-2026-07-06T0245-synapse-l4-live-verification
repo: sentinel-eval
title: "Synapse-L4 Adapter: Live-Verified Against a Real Running Instance"
date: 2026-07-06
phase: 3
tags: [live-verification, validator-as-judge, silent-contradiction, redis-streams, structured-generation]
files: [src/sentinel_eval/adapters/synapse_l4.py]
---

Closes the gap flagged in the Synapse-L4 adapter entry
(`sentinel-eval-2026-07-04T0435-synapse-l4-adapter.md`, "Challenge: No live
verification this step"): that entry was tested only against a faithful
`respx` mock of the documented `/ingest` contract, never against an actual
running Synapse-L4 process. No adapter code changed this session — this is
a verification-only entry.

### Pattern: "Instrumented" and "Confirmed Flowing" Are Still Separate Claims

Same distinction the Phase 2 OTel entry drew for telemetry, applied here to
the adapter itself: a passing mocked test proves the adapter speaks the
*documented* contract; it doesn't prove the adapter speaks the *real*
service's contract. Started a local Synapse-L4 instance (`uv run fastapi
dev main.py`), confirmed `/health`, ran
`make_synapse_l4_system_under_test()` against it for real, then stopped
the process — the same start/verify/stop shape used for Sentinel-L7's own
live verification (step 3) rather than a new pattern invented for this repo.

### Pattern: Validator-as-Judge Catching a Genuine Silent Contradiction

Ran three real cases through the full Extract → Judge → Emit pipeline, not
just the happy path — consistent with treating disagreement/rejection
outcomes as stronger verification than an all-success run (established in
the disagreement-layer and ground-truth entries). The interesting result
came from the third case: the real Ollama call (`qwen3.5:9b-q4_K_M` over
Tailscale, 13.9s) extracted a genuinely self-contradictory `AxiomDraft` —
`anomaly_score: 0.87` (above Synapse-L4's own 0.8 critical threshold) paired
with `status: "degraded"` instead of `"critical"`. The real, code-level
Judge stage (not another LLM call) caught this and returned a real `422
judge_rejected`. This is Synapse-L4's own documented anti-pattern —
**Silent Contradiction**, an Axiom whose `anomaly_score` "screams critical"
while `status` disagrees — reproduced by a real model, not constructed as a
test fixture, and caught by the real rule rather than assumed to work from
reading the code.

### Decision: Bumped the Adapter's Timeout Only for the LLM-Path Case

The adapter's default `timeout=10.0` was too tight for the real Ollama round
trip and the first attempt raised `httpx.ReadTimeout` — consistent with the
~8-9s latency already observed against this same host during the CLI
entrypoint step's live verification. Re-ran that one case with
`timeout=60.0` rather than treating the timeout as a pass/fail result to
discard: the real call completed in 13.9s. The fast-path and judge-rejection
cases both completed well inside the default 10s and needed no change.

### Decision: Left the Real Redis Write in Place

The fast-path success case really appended an entry to the shared
`synapse:axioms` Upstash Redis stream (`SentinelClient.post_axiom`'s `XADD`,
per ADR-0016) — Sentinel-L7's actual downstream stream, not a test double.
Confirmed beforehand via `ps aux` that no `sentinel:watch-axioms` consumer
was running locally, so nothing downstream processed it. Left the entry in
place rather than attempting cleanup: XADD has no "undo," and prior live
verification steps (embedding-consistency, ground-truth validation) already
established the precedent of accepting real writes to shared Upstash state
as the cost of a genuine live check rather than reverting them after.

### Decision: Skipped the Cross-Repo Observability Mirror

This entry documents cross-repo behavior (Synapse-L4 → Sentinel-L7 via the
`synapse:axioms` stream) but changes no integration-boundary code in either
repo, unlike the Sentinel-L7 adapter entry that earned `cross_ref:
observability` for actually widening a shared contract. Also found, while
checking, that `rhizome-observability`'s local copy of this skill
(`~/dev/rhizome-observability/skills/journal-anki.md`) has not been updated
to the per-file/`cross_ref_id` convention this repo uses — it still
describes the older single `docs/journal.md` + `cross-ref: observability`
(no id) format. Per the skill's own conflict rule the local copy wins, but
reconciling that drift is a separate task, not something to resolve as a
side effect of this entry. Flagged here rather than silently mirrored or
silently skipped.

### Decision: Also Verified Through the CLI, Not Just the Adapter Function Directly

The three cases above were run by calling `make_synapse_l4_system_under_test()`
directly from a script — proves the adapter, not necessarily the
`sentinel-eval` console script wrapping it. Re-ran the fast-path and
judge-rejection cases a second time through the actual
`uv run sentinel-eval --system synapse-l4 ...` CLI (one-off fixtures under
`/tmp`, matching the real `{source_id, payload}` envelope) to confirm the
same behavior at the surface users actually invoke, following the same
"claim what you actually confirmed" standard as the "Instrumented vs
confirmed flowing" pattern above. This surfaced a real gap the adapter-level
check couldn't have shown: `cli.py`'s `main()` catches
`httpx.ConnectError`/`TimeoutException` for a friendly one-line message, but
not `SynapseL4Error` — the judge-rejection case produced a raw Python
traceback and exit code `1` instead of the friendly `error: ...` message the
Sentinel-L7 path gives on a connection failure. Documented as a new Known
Issue in the README rather than fixed this session (verification-only, per
the top of this entry) — `run_eval()`/`cli.py` have no per-example error
handling at all today, a pre-existing limitation already flagged in the
original Synapse-L4 adapter entry's docstring discussion, now confirmed to
reach all the way to the CLI's exit behavior.

### Challenge: EventHorizon Consumer Noise Is Unrelated Background Failure

The local Synapse-L4 process logs repeated `[Errno 111] Connection refused,
reconnecting in Ns` from its EventHorizon WebSocket consumer task the whole
time it's up — expected, since no local EventHorizon process was running,
and unrelated to the `/ingest` path under test. Worth naming explicitly so
a future reader of the raw server log doesn't mistake it for a regression
in the pipeline being verified.
