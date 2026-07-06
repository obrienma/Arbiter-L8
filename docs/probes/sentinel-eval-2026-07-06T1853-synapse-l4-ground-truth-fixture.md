---
type: cloze
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, ground-truth]
---
`synapse_l4_ground_truth.json`'s `expected_label` values are computed by
hand from `_try_direct_extraction`'s deterministic mapping table, not
guessed — this is legitimate ground truth only because that fast path
runs with {{c1::no LLM involved}}, unlike genuine Axiom extraction, which
{{c2::ADR-0001}} still flags as unsolved.

Extra: sentinel-eval · Decision: Ground Truth for the Deterministic Fast Path, Not the LLM Path
See: docs/journal/sentinel-eval-2026-07-06T1853-synapse-l4-ground-truth-fixture.md

---
type: cloze
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, validator-as-judge, silent-contradiction]
---
In Synapse-L4's fast path, `status: "passed"` paired with
`classification: "critical"` deterministically produces
`status: {{c1::"nominal"}}` + `anomaly_score: {{c2::0.9}}` — because
`status` prioritizes `raw.payload.status` while `anomaly_score` is driven
by `classification` independently, reproducing the Judge's "Silent
Contradiction" case with {{c3::no LLM}} involved at all.

Extra: sentinel-eval · Pattern: Discovered a Real Contradiction Trap, Deterministically
See: docs/journal/sentinel-eval-2026-07-06T1853-synapse-l4-ground-truth-fixture.md

---
type: basic
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, ground-truth]
---
Q: Why wasn't the discovered fast-path contradiction trap (status "passed"
+ classification "critical" → a self-contradictory Axiom) just fixed in
Synapse-L4 while it was found?

A: It's Synapse-L4's own extraction code, not sentinel-eval's — fixing
another repo's logic is out of scope for "add a ground-truth fixture" and
wasn't requested. It was documented as a new README Known Issue instead,
the same treatment given to other out-of-repo issues like Sentinel-L7's
semantic-cache amplification: describe it precisely enough to reproduce
on demand, without patching code outside this repo's own boundary.

Extra: sentinel-eval · Decision: Documented, Not Fixed
See: docs/journal/sentinel-eval-2026-07-06T1853-synapse-l4-ground-truth-fixture.md
