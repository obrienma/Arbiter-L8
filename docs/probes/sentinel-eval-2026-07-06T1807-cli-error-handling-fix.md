---
type: cloze
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, error-handling]
---
`cli.py`'s `main()` catches {{c1::SentinelL7Error}} and
{{c2::SynapseL4Error}} alongside `httpx.ConnectError`/`TimeoutException` —
both already carry a fully-formed message, so the CLI just prints
`error: {exc}` and exits `1` instead of letting the exception propagate as
a raw traceback.

Extra: sentinel-eval · Pattern: Fail Loud at the Boundary, Not Silent Inside It
See: docs/journal/sentinel-eval-2026-07-06T1807-cli-error-handling-fix.md

---
type: basic
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, error-handling]
---
Q: The prior journal entry claimed the uncaught-adapter-error CLI gap was
Synapse-L4-specific, since "Sentinel-L7's adapter has no equivalent error
type." Why was that wrong, and how was it caught?

A: `adapters/sentinel_l7.py` already defines `SentinelL7Error`, raised on a
non-2xx MCP response, a JSON-RPC `error` envelope, or `isError` — `cli.py`
never caught either adapter's error type, not just Synapse-L4's. Caught by
re-reading the sibling adapter's source directly before writing the fix,
rather than trusting the previous session's own README note as already
correct.

Extra: sentinel-eval · Decision: The Gap Was Both Adapters, Not Just Synapse-L4
See: docs/journal/sentinel-eval-2026-07-06T1807-cli-error-handling-fix.md
