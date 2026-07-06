---
type: cloze
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, prompt-versioning]
---
`prompts/judge.txt` v2 fixes a prompt-following gap where `qwen3.5`
sometimes answered `"verdict"` as a {{c1::correctness judgment}}
(`"correct"`/`"reject"`) instead of {{c2::a label}} in the same taxonomy
as `{predicted_label}`.

Extra: sentinel-eval · Decision: Fix the Prompt, Not Just the Parser
See: docs/journal/sentinel-eval-2026-07-06T1819-judge-prompt-following-fix.md

---
type: cloze
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, domain-agnostic, circuit-breaker]
---
`_parse_verdict()` can't validate `verdict` against a real label taxonomy
because `EvalPrediction.label` is a plain {{c1::str}}, not a shared enum —
so instead it rejects a fixed denylist of tokens
(`{{c2::"correct"}}`/`{{c3::"reject"}}`/etc.) that are never valid in any
taxonomy this judge scores against, raising `ValueError` so the circuit
breaker falls through exactly like any other failure.

Extra: sentinel-eval · Pattern: A Rejected Verdict Is Just Another Circuit-Breaker Failure
See: docs/journal/sentinel-eval-2026-07-06T1819-judge-prompt-following-fix.md

---
type: basic
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, live-verification]
---
Q: Why didn't fixing the judge prompt-following gap include re-running the
full 25-item live validation sample from step 8?

A: A single live spot-check (`_call_ollama` called directly against the
real Ollama judge host, 13.9s, returned a clean `'high'` label) was enough
to confirm the v2 prompt renders correctly and the model still behaves
sensibly under it. A full before/after accuracy comparison against the
original 92%/80% numbers would require re-running the entire 25-item
sample, a larger undertaking scoped as its own future step rather than
folded into this fix.

Extra: sentinel-eval · Decision: Spot-Verified Live, Not a Full Re-Validation Run
See: docs/journal/sentinel-eval-2026-07-06T1819-judge-prompt-following-fix.md
