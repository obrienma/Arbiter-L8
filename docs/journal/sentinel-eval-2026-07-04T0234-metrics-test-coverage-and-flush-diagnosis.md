---
id: sentinel-eval-2026-07-04T0234-metrics-test-coverage-and-flush-diagnosis
repo: sentinel-eval
title: "Metrics/Env/Stub Test Coverage, Live Collector Verification, and a force_flush() Misdiagnosis"
date: 2026-07-04
phase: 2
tags: [additive-test-instrumentation, atexit, periodic-exporting-metric-reader, prometheus-scrape-interval]
files: [tests/test_metrics.py, tests/test_env.py, tests/test_online_stubs.py, src/sentinel_eval/observability/metrics.py]
---

### Pattern: Additive Test Instrumentation (extended to metrics)

The previous phase attached an `InMemorySpanExporter` to the shared global
`TracerProvider` via `add_span_processor` to assert on real trace output
without a Collector. Same approach extended to metrics:
`InMemoryMetricReader` attached to the global `MeterProvider` via
`add_metric_reader`, confirmed empirically to see only measurements
recorded *after* it was registered — so per-test isolation holds even
though every test shares one process-wide provider.

### Anti-Pattern Avoided: Diagnosing from Symptom Timing Alone

Initially concluded `run_eval()` needed an explicit `force_flush()` call
because a Prometheus query run seconds after a `pytest` invocation came
back empty, and a query run after a script that *did* call `force_flush()`
came back populated. That correlation was coincidental, not causal: the
real fix was reading `PeriodicExportingMetricReader`'s source directly
(`MeterProvider.__init__` registers `atexit.register(...)`; the reader's
`_ticker` thread performs one final `collect()` the moment `shutdown()`
fires) rather than inferring the mechanism from two data points that
happened to also differ in elapsed wall-clock time.

### Challenge: Two independent latencies produce an identical symptom

An empty metrics query right after a process exits can mean either (a) the
OTel SDK hasn't exported yet, or (b) the SDK exported fine but Prometheus's
own pull-based `scrape_interval` (15s in `rhizome-observability/prometheus.yml`)
hasn't run yet. Both produce the exact same observable symptom — nothing
in the query result — so the first hypothesis (missing flush) was wrong
but not unreasonable from the symptom alone. Resolved with a control
experiment: a script with *no* `force_flush()` call, exiting normally,
still landed in Prometheus 18 seconds later — isolating the delay to
Prometheus's scrape cycle, not the export path.

### Decision: Document the mechanism instead of adding force_flush()

No `force_flush()` call was added to `run_eval()`. The atexit-triggered
shutdown path already covers the realistic failure mode (a one-shot
process exiting normally); the only case it doesn't cover is a hard kill
(SIGKILL/OOM) that skips atexit entirely, which is a risk every
OTel-instrumented service in this suite already accepts and isn't specific
to sentinel-eval. Instead: a comment in `observability/metrics.py`
explaining the mechanism, plus a test
(`test_shutdown_flushes_pending_metrics_without_waiting_for_the_export_interval`)
that constructs an isolated `MeterProvider` with a 10-minute export
interval and a fake in-process exporter, proving `shutdown()` alone
delivers pending data — so a future OTel SDK version that changed this
contract would fail the test loudly instead of silently reintroducing the
misdiagnosed gap.
