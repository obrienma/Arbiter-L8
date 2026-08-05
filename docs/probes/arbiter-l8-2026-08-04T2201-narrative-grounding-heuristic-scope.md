---
type: cloze
deck: Rhizome::arbiter-l8
tags: [arbiter-l8, adr, rag-grounding, hallucination]
---
Sentinel-L7's ADR-0034 fixed `policy_refs` fabrication by forcing it to
`{{c1::[]}}` whenever `{{c2::chunk_count === 0}}` — but its own scope note
says the guard only sanitizes the structured `policy_refs` field, not the
free-text `narrative` field, leaving narrative-level fabrication as the
gap ADR-0003 scopes.

Extra: arbiter-l8 · Decision: Narrowed Scope to Narrative-Only, Not a Rebuild of the Original Check
See: docs/journal/arbiter-l8-2026-08-04T2201-narrative-grounding-heuristic-scope.md

---
type: cloze
deck: Rhizome::arbiter-l8
tags: [arbiter-l8, adr, adapter-contract]
---
The Sentinel-L7 MCP adapter's `raw_output` never exposes
{{c1::chunk_count}} — only `{source, is_threat, message, elapsed_ms,
risk_level, narrative, confidence, policy_refs}` — so ADR-0003's semantic
stage has to re-derive that signal independently by
{{c2::re-querying the same `policies` Upstash Vector namespace}} rather
than reading it directly.

Extra: arbiter-l8 · Challenge: The Adapter Doesn't Expose chunk_count At All
See: docs/journal/arbiter-l8-2026-08-04T2201-narrative-grounding-heuristic-scope.md

---
type: basic
deck: Rhizome::arbiter-l8
tags: [arbiter-l8, adr, rag-grounding]
---
Q: ADR-0003 considered comparing a narrative's embedding directly against
`policy_refs`' title strings instead of re-querying the `policies`
Upstash namespace. Why was that rejected?

A: Because it only tests whether the narrative sounds like the label
Sentinel-L7 already asserted — circular, since `policy_refs` can still
be wrong for reasons other than the all-zero-retrieval case ADR-0034
covers (e.g. correct chunk_count but the wrong chunk matched).
Re-querying the actual `policies` namespace via the existing
`query_upstash_vector()` checks the narrative against real corpus
content instead of trusting the driver's own claimed refs, and reuses
infrastructure that already exists rather than adding new code.

Extra: arbiter-l8 · Decision: Reuse consistency.py's Upstash Infra, Reject the Title-String Shortcut
See: docs/journal/arbiter-l8-2026-08-04T2201-narrative-grounding-heuristic-scope.md

---
type: cloze
deck: Rhizome::arbiter-l8
tags: [arbiter-l8, adr, dependency-gating]
---
ADR-0002's dependency-gated escalation (run a layer only when both
"flagged" and "dependency supplied" hold) is reused in ADR-0003 at a
finer grain: the new check's regex stage is unconditional, but its
semantic stage only escalates when an {{c1::embed_fn}} is supplied —
which is also why the check couldn't be added to `heuristics.py`'s
`DEFAULT_CHECKS`, since every function there is a
{{c2::pure, zero-dependency}} check by construction.

Extra: arbiter-l8 · Pattern: Dependency-Gated Escalation, Applied One Layer Earlier
See: docs/journal/arbiter-l8-2026-08-04T2201-narrative-grounding-heuristic-scope.md

---
type: cloze
deck: Rhizome::arbiter-l8
tags: [arbiter-l8, adr, spike-0001]
---
Of 49 real Sentinel-L7 samples with non-empty `policy_refs`, {{c1::0 of
18}} had a formal citation token in the narrative at all — the dominant
fabrication pattern is prose naming a regulation concept (e.g. "GDPR")
with no formal ID, which is why ADR-0003 left its regulatory-keyword
pre-filter list {{c2::unspecified, as a build-time decision}} rather than
pinning it from n=49 alone.

Extra: arbiter-l8 · Decision: Regulatory-Keyword List Left Unspecified in the ADR
See: docs/journal/arbiter-l8-2026-08-04T2201-narrative-grounding-heuristic-scope.md
