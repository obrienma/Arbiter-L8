---
type: basic
deck: Rhizome::arbiter-l8
tags: [arbiter-l8, semantic-cache, live-verification]
---
Q: A live validation run against 25 real transactions returned
`risk_level: 'low'` for every single one, including ones ground-truth-
labeled `high` — 52% accuracy. Why wasn't this a judge or model failure?

A: Sentinel-L7's semantic vector cache matches on embedding similarity
(threshold 0.95), not transaction identity. The suspicious merchant
profile's transactions are narrow enough in amount/wording that they embed
near-identically to each other, so the *first* one analyzed got cached as
`low` and every subsequent similar transaction inherited that one stale,
individually-wrong cached verdict — a real cache-amplification effect.
Forcing the per-request driver override (`driver='ollama'`) bypassed the
cache entirely and got a fresh, uncached answer per transaction.

Extra: arbiter-l8 · Pattern: Force the Driver Override to Get an Independent Answer, Not a Stale Cache Hit
See: docs/journal/arbiter-l8-2026-07-04T1720-ground-truth-export-and-judge-validation.md

---
type: basic
deck: Rhizome::arbiter-l8
tags: [arbiter-l8, taxonomy, scoring]
---
Q: Why does scoring Sentinel-L7 predictions against the new ground-truth
fixture report both a "strict" and a "binary" accuracy number, and which
one should actually be trusted?

A: The fixture's `expected_label` is only ever `'high'`/`'low'` because
ground truth pre-AI only knows a binary threat flag — but Sentinel-L7
predicts a graded `risk_level` (`low`/`medium`/`high`/`critical`). Strict
string equality would count a `critical` verdict on a real threat as
wrong, even though it correctly caught the threat. The binary collapse
(`medium`/`high`/`critical` → `'high'`, matching
`is_threat = risk_level != 'low'`) is the number that reflects what the
ground truth can actually justify claiming — 92% in the live sample,
versus 84% strict — and is the one to trust for this fixture.

Extra: arbiter-l8 · Decision: Binary-Collapse the Scoring, Not Just the Export
See: docs/journal/arbiter-l8-2026-07-04T1720-ground-truth-export-and-judge-validation.md

---
type: basic
deck: Rhizome::arbiter-l8
tags: [arbiter-l8, judge, prompt-engineering]
---
Q: In the live judge-validation sample, 2 of 25 verdicts were the literal
strings `"reject"` and `"correct"` instead of a real `risk_level` value.
What does this reveal, and was it fixed in this step?

A: It's a prompt-following gap — the judge prompt asks for "the label you
believe is correct," but the model sometimes echoes an evaluative word
instead of restating an actual taxonomy value. Both were correctly scored
as wrong under strict comparison. This wasn't fixed here — the 25-example
run was scoped as a validation pass, not a prompt-iteration pass — but it's
flagged as a concrete `prompts/judge.txt` improvement (e.g. constraining
`verdict` to an explicit enum) for a future step.

Extra: arbiter-l8 · Challenge: The Judge Sometimes Returns a Non-Taxonomy Token Instead of a Label
See: docs/journal/arbiter-l8-2026-07-04T1720-ground-truth-export-and-judge-validation.md

---
type: cloze
deck: Rhizome::arbiter-l8
tags: [arbiter-l8, evaluate_item, judge]
---
`evaluate_item()`'s judge escalation only fires when {{c1::run_heuristics()}}
flags a prediction — since Sentinel-L7's live confidence stayed uniformly
high (0.85-0.98) across the validation sample, the heuristic gate never
fired, so the validation script called `JudgeCircuitBreaker.judge()`
directly to get a judge-only agreement number instead of going through the
normal gated path.

Extra: arbiter-l8 · Decision: Call the Judge Unconditionally for This Validation, Bypassing the Heuristic Gate
See: docs/journal/arbiter-l8-2026-07-04T1720-ground-truth-export-and-judge-validation.md
