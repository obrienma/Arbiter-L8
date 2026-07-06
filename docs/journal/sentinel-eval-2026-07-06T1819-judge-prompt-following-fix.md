---
id: sentinel-eval-2026-07-06T1819-judge-prompt-following-fix
repo: sentinel-eval
title: "Judge Prompt-Following Fix: Reject Correctness Judgments, Not Just Malformed JSON"
date: 2026-07-06
phase: 3
tags: [prompt-versioning, circuit-breaker, fail-fast, domain-agnostic]
files: [prompts/judge.txt, prompts/judge.md, src/sentinel_eval/online/judge.py, tests/test_judge.py]
---

Second item off the punch list left by the Synapse-L4 live-verification
entry. Closes the gap first flagged in the step 8 ground-truth-validation
entry: 2/25 live judge verdicts were `"reject"`/`"correct"` instead of an
actual label — the model answering as if grading correctness rather than
naming a label.

### Decision: Fix the Prompt, Not Just the Parser

The root cause is genuinely a prompt clarity problem — the old template's
`"<the label you believe is correct>"` placeholder reads ambiguously enough
that a small model can interpret "verdict" as "was this correct?" rather
than "what label is correct?". `prompts/judge.txt` v2 adds an explicit
instruction: `verdict` must be a label in the same taxonomy as
`{predicted_label}`, and explicitly forbids `"correct"`/`"reject"`/yes-no
answers. This is the actual fix; the parser guard below is a backstop, not
a substitute for it.

### Decision: Can't Validate Against an Enum, Because There Isn't One

The obvious hardening — validate `verdict` against the real label taxonomy
— isn't available here by design: `EvalPrediction.label` is a plain `str`,
not a shared enum, specifically so this same judge (and this same prompt)
can score both Sentinel-L7's `low|medium|high|critical|unknown` and
Synapse-L4's `nominal|degraded|critical` without leaking one system's
vocabulary into the harness (see the README's Prediction Contract section).
Instead, `_parse_verdict()` rejects a small, fixed denylist of tokens that
are never a valid label in *any* taxonomy this judge has been asked to
score against (`"correct"`, `"reject"`, `"yes"`, `"no"`, etc.) — narrower
than a full enum check, but doesn't require threading a taxonomy parameter
through `judge()`/`evaluate_item()`/every caller for a fix this contained.

### Pattern: A Rejected Verdict Is Just Another Circuit-Breaker Failure

`_parse_verdict()` raises `ValueError` on a denylisted token, exactly like
`json.JSONDecodeError`/`KeyError` on malformed output — no special-casing
in `JudgeCircuitBreaker.judge()` at all. A verdict-rejection at the Ollama
stage falls through to Gemini Flash exactly the same way a timeout would;
if both stages fail, it falls to `heuristics_fallback`. Verified with a
dedicated test (`test_non_label_verdict_falls_through_to_heuristics_like_
any_other_failure`) asserting the exact same span sequence
(`ollama_attempt`, `flash_attempt`, `heuristics_fallback`, `judge_call`)
that the pre-existing "both sources unavailable" test already asserts.

### Decision: Spot-Verified Live, Not a Full Re-Validation Run

Called the real Ollama judge host (`_call_ollama` directly, same
`OLLAMA_JUDGE_HOST`/`OLLAMA_JUDGE_MODEL` as the step 5/8 live
verifications) once with a representative ambiguous prediction under the
new prompt: `13.9s`, returned a clean `'high'` label, no guard
false-positive. This confirms the v2 template renders correctly and the
real model still responds sensibly — it does **not** re-run the full
25-item live sample from step 8, which would be needed for a real
before/after accuracy comparison against the old 92%/80% numbers. Flagged
as a new Roadmap item rather than assumed to be covered by this session's
narrower check.

### Challenge: None on Implementation — Confirming the Taxonomy-Leak Constraint Took the Longest

The actual code change was small. Most of the time went into confirming,
by re-reading `online/pipeline.py` and the README's Prediction Contract
section, that no `valid_labels`-style parameter already existed anywhere
in the call chain from `evaluate_item()` down to `judge()` — needed to be
sure the "no enum available" framing above was actually true of the
current code, not an assumption carried over from the original step 5/8
entries.
