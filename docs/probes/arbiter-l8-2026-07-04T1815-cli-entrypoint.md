---
type: basic
deck: Rhizome::arbiter-l8
tags: [arbiter-l8, cli, scope]
---
Q: Why does `arbiter-l8`'s CLI only wrap the offline harness
(`run_eval`) and have no subcommand for the online layers
(`online.pipeline.evaluate_item`)?

A: The offline path has a context-free shape — a fixture and an adapter go
in, a report comes out — but the online path's meaningful inputs
(which providers to compare, an `embed_fn`, a judge circuit breaker) are a
per-deployment decision owned by whatever caller runs the sampling loop.
There's no sensible default the CLI could supply on its own, so a one-shot
command for it would either be a thin, useless wrapper or would have to
bake in assumptions that belong to the caller instead.

Extra: arbiter-l8 · Pattern: The CLI Wraps the Offline Harness Only, Not the Online Layers
See: docs/journal/arbiter-l8-2026-07-04T1815-cli-entrypoint.md

---
type: cloze
deck: Rhizome::arbiter-l8
tags: [arbiter-l8, cli, taxonomy]
---
`--binary` is implemented as `_collapse_binary()`, a
`SystemUnderTest -> SystemUnderTest` {{c1::wrapper}} applied before
`run_eval()` sees the callable — not a flag threaded through
`harness.run_eval()` itself — so the harness core stays taxonomy-agnostic
across every system it scores.

Extra: arbiter-l8 · Pattern: A Post-Hoc Wrapper for --binary, Not a Harness-Level Flag
See: docs/journal/arbiter-l8-2026-07-04T1815-cli-entrypoint.md

---
type: basic
deck: Rhizome::arbiter-l8
tags: [arbiter-l8, live-verification, timeout]
---
Q: A live `--limit 5` CLI run against a real local Sentinel-L7 server
(`--driver ollama`) hit a genuine `httpx.TimeoutException` on one item,
while a `--limit 1` run succeeded. Why was this treated as a successful
verification rather than a bug to fix?

A: A raw timing check showed individual Ollama driver-override calls
taking 8–9s against the real model, close to the adapter's default 10s
per-request timeout — occasionally crossing it is expected model-latency
variance, not a defect. The CLI's `try/except
(httpx.ConnectError, httpx.TimeoutException)` handler caught it exactly as
designed, printing a friendly one-line error and exiting `1` instead of a
raw traceback — exercising that error-handling path against a genuine
timeout is a stronger verification than an all-success run would have
been.

Extra: arbiter-l8 · Challenge: Live Ollama Driver-Override Latency Is Close to the Adapter's Default Timeout
See: docs/journal/arbiter-l8-2026-07-04T1815-cli-entrypoint.md

---
type: basic
deck: Rhizome::arbiter-l8
tags: [arbiter-l8, cli, fixture-defect]
---
Q: Why does `--fixture` have no per-`--system` default path (e.g.
defaulting `synapse-l4` to `compliance_dataset.json`)?

A: `compliance_dataset.json`'s `input` shape doesn't actually match either
adapter's real request contract — it's the same fixture already flagged as
a false alarm in the judge-validation benchmark (Synapse-shaped fields
flattened, missing the `source_id`/`payload` envelope `synapse_l4.py`
expects). Defaulting to a fixture that silently doesn't fit the chosen
adapter would reproduce that exact mismatch one layer up; requiring
`--fixture` explicitly turns a shape mismatch into a normal runtime error
against real data instead of a baked-in default foot-gun.

Extra: arbiter-l8 · Decision: Require --fixture Explicitly, No Per-System Default Path
See: docs/journal/arbiter-l8-2026-07-04T1815-cli-entrypoint.md
