---
id: arbiter-l8-2026-07-03T1916-otel-instrumentation
repo: arbiter-l8
title: "OpenTelemetry Instrumentation: Traces, Metrics, evaluate_item Pipeline"
date: 2026-07-03
phase: 2
tags: [circuit-breaker, context-decorator, otlp, root-span-fragmentation, additive-observability, prometheus, tempo]
files: [pyproject.toml, src/arbiter_l8/observability/_env.py, src/arbiter_l8/observability/tracing.py, src/arbiter_l8/observability/metrics.py, src/arbiter_l8/observability/decorators.py, src/arbiter_l8/observability/__init__.py, src/arbiter_l8/online/heuristics.py, src/arbiter_l8/online/disagreement.py, src/arbiter_l8/online/consistency.py, src/arbiter_l8/online/judge.py, src/arbiter_l8/online/pipeline.py, src/arbiter_l8/harness.py, tests/test_observability.py, tests/test_judge.py, tests/test_pipeline.py, README.md]
cross_ref: observability
cross_ref_id: arbiter-l8-2026-07-03T1916-otel-instrumentation
---

### Pattern: Context Manager as Decorator (`contextlib.ContextDecorator`)

`traced_layer(name)` is a single `@contextmanager`-decorated generator, used
both as `@traced_layer("heuristics_check")` around a whole layer function and
as `with traced_layer("ollama_attempt"):` around an inline block inside
`JudgeCircuitBreaker.judge()`. This works because a generator wrapped by
`contextlib.contextmanager` returns a `_GeneratorContextManager`, which
subclasses `ContextDecorator` — so the same object is usable both ways
without a separate decorator implementation to keep in sync as more layers
get built.

### Pattern: Circuit Breaker (traced)

Extends the existing `JudgeCircuitBreaker` (Ollama → Gemini Flash →
heuristics-only) with a nested span per attempt
(`ollama_attempt`/`flash_attempt`/`heuristics_fallback`), all children of one
`judge_call` span. A trace now shows the *path* through the breaker, not
just the terminal outcome — e.g. an Ollama timeout followed by a Flash
success renders as two sibling spans under one parent, which is what makes
"why did this one item get scored by Flash instead of Ollama" answerable
from a trace instead of only from logs.

### Anti-Pattern Avoided: Deferred SDK Initialization (Root-Span Fragmentation)

Investigated Synapse-L4's suspected "three traces instead of one" bug before
wiring arbiter-l8's tracer the same way. Root cause: Synapse-L4's
`main.py` constructs the `FastAPI` app and registers routes at import time,
but defers `configure_logfire()` / `instrument_fastapi(app)` into the
`lifespan()` handler, which only runs once Uvicorn starts serving. Starlette
lazily builds and caches its ASGI middleware stack on the first ASGI event
it receives — which includes the lifespan-startup event itself, flowing
through the same top-level `app.__call__` *before* `instrument_fastapi(app)`
has run. The OTel/Logfire ASGI middleware ends up attached after other
middleware ordering has already latched in, producing inconsistent
root-span parenting. This generalizes beyond FastAPI: it's the same
init-order discipline already called out for EventHorizon's Node SDK
("must come before any instrumented module is imported"). arbiter-l8's
`observability/tracing.py` and `metrics.py` set up their providers as a
plain import-time module-level side effect instead — no lifecycle hook to
get the ordering wrong behind.

### Challenge: OTLP retry backoff adds ~7s to every test run without a local Collector

Once metrics/trace export was wired into `harness.py` and the online layers,
`uv run pytest` started printing "connection refused" warnings and taking
several extra seconds to exit — the OTLP exporters retry with exponential
backoff before giving up when `localhost:4318` isn't listening. Checked
whether EventHorizon or Synapse-L4 configure an explicit shorter timeout to
avoid this: neither does. Left the SDK defaults in place rather than
diverging from the established convention on my own judgment — noted as a
known, harmless cost of "additive observability" in the README instead of
silently tuning it.

### Decision: `evaluate_item` added as a new `online/pipeline.py`, since none existed

The requested span hierarchy needed a parent (`evaluate_item`) that calls
the online layers — no orchestrator existed yet (the README previously said
so explicitly). Built the minimum needed: heuristics always runs; layers
2-4 run only if heuristics flagged the item *and* the caller supplied that
layer's dependency (`providers`, `embed_fn`, `judge`) — a layer without its
dependency is skipped, not an error. This keeps `disagreement.py` /
`consistency.py` free to stay `NotImplementedError` stubs without blocking
`evaluate_item` from being exercised end-to-end today via the judge layer
alone.

### Decision: `judge_outcome_counter.add()` lives inside `JudgeMetrics.record()`, not at each call site

`JudgeCircuitBreaker.judge()` already called `self.metrics.record(source)`
at three call sites (Ollama success, Flash success, fallback). Rather than
adding a second `judge_outcome_counter.add(1, ...)` call alongside each one,
folded the OTel counter emission into `JudgeMetrics.record()` itself — one
place tracks both the in-process `pct_scored_by_judge` property and the
Prometheus-bound counter, so they can't drift out of sync.
