---
id: sentinel-eval-2026-07-04T1815-cli-entrypoint
repo: sentinel-eval
title: "CLI Entrypoint (Step 9): The Offline Harness, Reachable Without Writing Code"
date: 2026-07-04
phase: 3
tags: [cli, argparse, console-scripts, offline-harness]
files: [src/sentinel_eval/cli.py, pyproject.toml, tests/test_cli.py, README.md]
---

### Pattern: The CLI Wraps the Offline Harness Only, Not the Online Layers

`sentinel-eval` (`[project.scripts]` -> `sentinel_eval.cli:main`) wires a
labeled fixture and an adapter (`sentinel-l7` / `synapse-l4`) into
`run_eval()` and prints the resulting `EvalReport`. It deliberately has no
subcommand for `online.pipeline.evaluate_item` — which
providers/`embed_fn`/judge to wire up is a per-deployment decision made by
whatever caller owns the sampling loop, not something a one-shot CLI
invocation can meaningfully default. A CLI surface only exists where there
is a genuinely context-free "run this against that" shape: fixture in,
report out.

### Pattern: A Post-Hoc Wrapper for `--binary`, Not a Harness-Level Flag

`--binary` (Sentinel-L7 only) collapses a predicted label to `'high'`
unless it's exactly `'low'`, matching
`TransactionProcessorService::gradeAiResult()`. Implemented as
`_collapse_binary()`, a `SystemUnderTest -> SystemUnderTest` wrapper applied
*before* `run_eval()` ever sees the callable, rather than as a flag threaded
through `harness.run_eval()` itself. `run_eval()` stays a pure label
comparison with no knowledge of any single system's taxonomy-collapsing
rules — keeping that domain-specific rule in the CLI layer (where the
`--system sentinel-l7` context already lives) instead of leaking it into
the harness core, which serves both systems and must stay taxonomy-agnostic
per `docs/adr/0001-standalone-module.md`.

### Challenge: Live Ollama Driver-Override Latency Is Close to the Adapter's Default Timeout

Live-verifying the CLI against a temporarily-started local Sentinel-L7
server (`--driver ollama`, bypassing the semantic cache per step 6/7's
established pattern) showed a single item scoring correctly in ~9.4s — but
a `--limit 5` batch hit a real `httpx.TimeoutException` on a slower
response, since `make_sentinel_l7_system_under_test()`'s default per-request
timeout is 10.0s and a raw `curl` timing check showed individual
driver-override calls taking 8–9s against the real model. Not a CLI bug —
the CLI's `try/except (httpx.ConnectError, httpx.TimeoutException)` handler
caught it exactly as designed and exited `1` with a friendly message
instead of a raw traceback, which is itself the more informative live
verification: it exercised the error path against a genuine timeout, not a
mock. No CLI-level `--timeout` flag was added to work around this — out of
scope for what this step asked for, and the adapter's own `timeout=`
constructor parameter is the correct place to change it if a real
deployment needs more headroom.

### Decision: Require `--fixture` Explicitly, No Per-System Default Path

Considered defaulting `--fixture` based on `--system` (e.g. `synapse-l4` ->
`compliance_dataset.json`), but `compliance_dataset.json`'s `input` shape
doesn't actually match either adapter's real request contract (its
Synapse-shaped fields are flattened, missing the `source_id`/`payload`
envelope `synapse_l4.py` expects) — the exact fixture/taxonomy mismatch
already documented as a "false alarm" in the judge-validation benchmark
row. Defaulting to a fixture that silently doesn't fit the chosen adapter's
input contract would reproduce that same failure mode one layer up.
Requiring `--fixture` explicitly keeps the shape mismatch a normal runtime
KeyError against real data rather than a foot-gun baked into the CLI's
defaults.
