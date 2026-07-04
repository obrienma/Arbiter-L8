---
type: cloze
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, atexit]
---
`MeterProvider` registers an {{c1::atexit}} hook on construction, and
`PeriodicExportingMetricReader`'s background thread performs one final
{{c2::collect()}} the moment `shutdown()` fires — so a one-shot script
never needs an explicit `force_flush()` call to deliver its metrics.

Extra: sentinel-eval · Decision: Document the mechanism instead of adding force_flush()
See: docs/journal/sentinel-eval-2026-07-04T0234-metrics-test-coverage-and-flush-diagnosis.md

---
type: basic
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, prometheus-scrape-interval]
---
Q: A Prometheus query run right after a process exits comes back empty.
What are the two independent explanations, and how do you tell them apart?

A: (1) The OTel SDK hasn't exported the metric yet, or (2) it exported
fine, but Prometheus's own pull-based scrape_interval hasn't run yet — both
produce an identical empty result. Tell them apart with a control
experiment: remove any explicit flush call and wait longer than the scrape
interval; if the data still appears, the export path was never the
bottleneck.

Extra: sentinel-eval · Anti-Pattern Avoided: Diagnosing from Symptom Timing Alone
See: docs/journal/sentinel-eval-2026-07-04T0234-metrics-test-coverage-and-flush-diagnosis.md

---
type: cloze
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, additive-test-instrumentation]
---
An `InMemoryMetricReader` attached mid-process via
`{{c1::add_metric_reader}}` only sees measurements recorded *after* its own
registration — confirmed empirically — which is what makes per-test metric
isolation safe even though every test in the suite shares one
process-wide `MeterProvider`.

Extra: sentinel-eval · Pattern: Additive Test Instrumentation
See: docs/journal/sentinel-eval-2026-07-04T0234-metrics-test-coverage-and-flush-diagnosis.md
