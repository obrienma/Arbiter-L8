---
id: arbiter-l8-2026-07-04T1512-judge-layer
repo: arbiter-l8
title: "LLM-as-Judge (Layer 4): Real Calls, and a Validation Gate That Found a Fixture Bug"
date: 2026-07-04
phase: 3
tags: [circuit-breaker, prompts-convention, live-verification, fixture-defect]
files: [src/arbiter_l8/online/judge.py, prompts/judge.md, prompts/judge.txt, tests/test_judge.py, README.md]
---

### Pattern: Circuit Breaker with a Real Fallback Chain

`JudgeCircuitBreaker` (already scaffolded before this phase) tries the
remote Ollama judge first, falls through to Gemini Flash on any exception,
then to heuristics-only. This step implemented the two leaf calls
(`_call_ollama`, `_call_gemini_flash`) for real: both force strict-JSON
output at the API level (Ollama's `"format": "json"`, Gemini's
`generationConfig.responseMimeType: "application/json"`) rather than
trusting prompt instructions alone — same convention Sentinel-L7's
`OllamaDriver`/`GeminiDriver` already use, verified directly against those
files rather than assumed. Both leaves raise on any failure
(`httpx.HTTPStatusError`, malformed JSON, missing API key) rather than
swallowing — the breaker's `except Exception` catch is what turns a raised
exception into a fallback attempt, so the leaves themselves must never
return a sentinel value.

### Pattern: Prompts Convention Applied for the First Time in This Repo

`prompts/judge.md` + `prompts/judge.txt` is the first prompt template in
arbiter-l8, following the user's standing directive (mirrored from
Sentinel-L7's `prompts/*.md`+`*.txt` pairing) that LLM prompts live in a
versioned `prompts/` directory, never hardcoded inline. Loaded via
`Path.read_text()` + literal placeholder substitution (`str.replace`, not
`str.format()`) — the template's JSON response example contains literal
`{`/`}` that `str.format()` would misinterpret as interpolation targets,
the same reason Sentinel-L7's `AbstractComplianceDriver` uses `strtr()`
over PHP's `sprintf`-style formatting for its own prompt templates.

### Challenge: A 6.7% Accuracy Score That Wasn't the Judge's Fault

Ran the judge live against `tests/fixtures/compliance_dataset.json` via
`run_eval()`, per `docs/adr/0001-standalone-module.md`'s explicit
requirement to validate judge verdicts before trusting them online.
Accuracy came back at 6.7% — alarming on its face. Inspecting individual
predictions showed the judge reading `raw_output.status` (e.g.
`"nominal"`) and correctly restating it, while `expected_label` used
Sentinel's `risk_level` vocabulary (`"low"`) for the same example: right
answer, wrong taxonomy. The fixture's `raw_output` fields are
Synapse-L4-shaped (`status`, `anomaly_score`, `source_id`) but its
`expected_label` values are Sentinel-L7-shaped — a pre-existing mismatch
that `run_eval()` never surfaces on its own, since it only ever compares
`label` to `expected_label` and never inspects `raw_output` shape. It took
a component that actually reasons over `raw_output` content (the judge) to
expose it.

### Decision: Defer Full Judge Validation to Step 8

Presented the finding and three options (fix the prompt to enumerate the
target taxonomy now, build a small throwaway Sentinel-shaped fixture just
for judge validation, or defer to step 8's ground-truth export). User chose
deferral: step 8 already plans to export real Sentinel-shaped
`{transaction, is_threat}` pairs from `TransactionStreamService`, which
will be a taxonomy-consistent fixture the judge can be meaningfully scored
against. Marking step 5 done on implementation + a real single-example
live round-trip (sensible verdict from Ollama, correct raise-on-429 from
Gemini Flash) rather than on the fixture-accuracy number, which measures
the wrong thing here.

### Decision: Only `verdict` Is Consumed, Not `reasoning`

The prompt schema requires both `verdict` and `reasoning` fields (the
latter measurably improves small-model answer quality by forcing
justification), but `_call_ollama`/`_call_gemini_flash` return only the
verdict string, matching the pre-existing scaffold's `-> str` signature and
`JudgeVerdict.reasoning` only being populated by the heuristics-fallback
path today. Not widened in this step — surfacing judge reasoning through
`JudgeVerdict` for the Ollama/Flash sources is a separate, small follow-up
if it turns out to be needed for debugging judge quality later.
