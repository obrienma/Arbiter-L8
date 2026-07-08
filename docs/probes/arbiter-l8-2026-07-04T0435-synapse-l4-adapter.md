---
type: cloze
deck: Rhizome::arbiter-l8
tags: [arbiter-l8, adapter-pattern]
---
`make_synapse_l4_system_under_test()` maps Synapse-L4's Axiom
`{{c1::status}}` field to `EvalPrediction.label` and `{{c2::anomaly_score}}`
to `confidence`, while the harness itself imports nothing from
`adapters/` — the dependency runs one direction only.

Extra: arbiter-l8 · Pattern: Adapter, reused and made concrete
See: docs/journal/arbiter-l8-2026-07-04T0435-synapse-l4-adapter.md

---
type: basic
deck: Rhizome::arbiter-l8
tags: [arbiter-l8, adapter-pattern]
---
Q: Why does the Synapse-L4 adapter call the service over HTTP instead of
importing its Python modules directly, given both are Python?

A: Four independent reasons converge: Synapse-L4's config.py instantiates
a pydantic-settings singleton at import time requiring a reachable Redis
URL; its dependency set (fastapi, instructor, openai, redis) is heavy and
service-specific; it runs on Python 3.14 against arbiter-l8's pinned
3.12; and depending on its internals at all would violate the
standalone-module ADR's no-service-specific-code mandate. HTTP sidesteps
all four at once.

Extra: arbiter-l8 · Decision: HTTP over direct import
See: docs/journal/arbiter-l8-2026-07-04T0435-synapse-l4-adapter.md

---
type: cloze
deck: Rhizome::arbiter-l8
tags: [arbiter-l8, additive-observability]
---
The Synapse-L4 adapter's tests are {{c1::mocked-only}} (via respx) because
the real service wasn't running locally when it was built — "tested
against a faithful mock" and "confirmed against the real running service"
are kept as two distinct claims, not conflated.

Extra: arbiter-l8 · Challenge: No live verification this step
See: docs/journal/arbiter-l8-2026-07-04T0435-synapse-l4-adapter.md
