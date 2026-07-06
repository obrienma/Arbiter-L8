---
type: cloze
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, live-verification]
---
A test passing against a mocked HTTP contract proves an adapter speaks the
{{c1::documented}} contract; only a real round trip against a running
instance proves it speaks the {{c2::real service's}} contract — "instrumented"
and "confirmed flowing" are separate claims.

Extra: sentinel-eval · Pattern: "Instrumented" and "Confirmed Flowing" Are Still Separate Claims
See: docs/journal/sentinel-eval-2026-07-06T0245-synapse-l4-live-verification.md

---
type: cloze
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, validator-as-judge, silent-contradiction]
---
Synapse-L4's Judge stage rejects an `AxiomDraft` whose `anomaly_score` is
`>= {{c1::0.8}}` unless `status` is `{{c2::"critical"}}` — this is the
rule-based check for the anti-pattern the codebase calls
{{c3::Silent Contradiction}}.

Extra: sentinel-eval · Pattern: Validator-as-Judge Catching a Genuine Silent Contradiction
See: docs/journal/sentinel-eval-2026-07-06T0245-synapse-l4-live-verification.md

---
type: cloze
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, redis-streams]
---
Synapse-L4 delivers Axioms to Sentinel-L7 by `XADD`-ing to the Redis stream
key {{c1::synapse:axioms}}, which Sentinel-L7 consumes via its
{{c2::sentinel:watch-axioms}} artisan command.

Extra: sentinel-eval · Decision: Left the Real Redis Write in Place
See: docs/journal/sentinel-eval-2026-07-06T0245-synapse-l4-live-verification.md

---
type: basic
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, live-verification]
---
Q: Why was the Synapse-L4 adapter's HTTP timeout bumped to 60s for only one
of the three live-verification cases, instead of raising the adapter's
default globally?

A: Only the LLM-path case (unstructured payload, forcing a real Ollama
structured-generation call over Tailscale) needed more time — it timed out
at the default 10s and completed in 13.9s once retried at 60s, matching
latency already seen against this same host in the CLI entrypoint step. The
fast-path and judge-rejection cases both used Synapse-L4's deterministic
extraction shortcut, completed well under 10s, and needed no change — so the
timeout was raised per-call for the one case that actually required it
rather than loosened globally for cases that didn't.

Extra: sentinel-eval · Decision: Bumped the Adapter's Timeout Only for the LLM-Path Case
See: docs/journal/sentinel-eval-2026-07-06T0245-synapse-l4-live-verification.md

---
type: cloze
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, error-handling]
---
`cli.py`'s `main()` catches {{c1::httpx.ConnectError}} and
{{c2::httpx.TimeoutException}} for a friendly one-line error, but a
Synapse-L4 `422`/`502` response raises {{c3::SynapseL4Error}}, which is
uncaught — it surfaces as a raw traceback and exit code 1 instead.

Extra: sentinel-eval · Decision: Also Verified Through the CLI, Not Just the Adapter Function Directly
See: docs/journal/sentinel-eval-2026-07-06T0245-synapse-l4-live-verification.md
