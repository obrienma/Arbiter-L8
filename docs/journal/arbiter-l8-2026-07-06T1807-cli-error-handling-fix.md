---
id: arbiter-l8-2026-07-06T1807-cli-error-handling-fix
repo: arbiter-l8
title: "CLI Error Handling: Catch Adapter Errors, Not Just Connection Failures"
date: 2026-07-06
phase: 3
tags: [error-handling, fail-fast, live-verification]
files: [src/arbiter_l8/cli.py, tests/test_cli.py, README.md, docs/DEV_GETTING_STARTED.md]
---

First item off the punch list left by the Synapse-L4 live-verification
entry (`arbiter-l8-2026-07-06T0245-synapse-l4-live-verification.md`).
That entry's "Known Issues" note turned out to be mis-scoped on first
write — worth recording precisely because it was corrected before landing
anywhere permanent, not after.

### Decision: The Gap Was Both Adapters, Not Just Synapse-L4

The original note claimed "Sentinel-L7's adapter has no equivalent error
type today, so this gap is Synapse-L4-specific." Re-reading
`adapters/sentinel_l7.py` before touching `cli.py` showed that claim was
wrong: `SentinelL7Error` already exists there (raised on a non-2xx
response, a JSON-RPC `error` envelope, or `isError`) — `cli.py`'s
`except (httpx.ConnectError, httpx.TimeoutException)` clause never caught
either adapter's own error type, not just Synapse-L4's. Caught by reading
the sibling adapter's source directly instead of trusting the prior
session's own README note — the same "verify against the file, not the
prior claim" standard applied throughout this plan (e.g. the MCP tool-name
casing check in the Sentinel-L7 adapter entry).

### Pattern: Fail Loud at the Boundary, Not Silent Inside It

`cli.py`'s `main()` now catches `(SentinelL7Error, SynapseL4Error)`
alongside the existing `(httpx.ConnectError, httpx.TimeoutException)`
clause and prints `error: {exc}` to stderr with exit code `1` — both
exception types already carry a fully-formed message (status code +
response body), so the CLI doesn't need to reconstruct or re-summarize
anything, just stop the traceback from leaking to the user. `run_eval()`
itself still has no per-example error handling (one bad example aborts a
whole batch) — that limitation is unchanged and was never in scope here;
this fix is only about *how* the abort surfaces at the CLI boundary.

### Decision: Live-Verified the Fix, Not Just Unit-Tested It

Added `respx`-mocked tests for both error types (`test_sentinel_l7_error_
returns_1_and_prints_to_stderr_not_a_traceback`, `test_synapse_l4_error_
returns_1_and_prints_to_stderr_not_a_traceback`) — but also re-started the
same local Synapse-L4 instance from the previous entry and re-ran the
exact judge-rejection case through the real CLI before updating any docs.
Confirmed real output: `error: Synapse-L4 /ingest failed (422): {'error':
'judge_rejected', ...}` and exit code `1`, no traceback. Docs
(`README.md`'s Known Issues bullet, `DEV_GETTING_STARTED.md` section 3)
were written to describe this confirmed behavior, not the code as read.

### Challenge: The Bug Existing Docs Described Had Already Shipped

`DEV_GETTING_STARTED.md` told a reader to *expect* a raw traceback as the
correct, current behavior. Fixing `cli.py` without also rewriting that
paragraph would have left a getting-started guide actively lying about
what happens. Removed the stale "expect a traceback" framing and replaced
it with the real fixed-behavior transcript rather than leaving both
versions side by side or marking the old one merely "outdated."
