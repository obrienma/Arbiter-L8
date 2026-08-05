---
id: arbiter-l8-2026-08-04T2201-narrative-grounding-heuristic-scope
repo: arbiter-l8
title: "ADR-0003: Scoping the Narrative-Only Grounding Heuristic After Sentinel-L7's ADR-0034"
date: 2026-08-04
phase: scoping
tags: [adr, scoping, rag-grounding, hallucination, dependency-gating, cross-repo]
files: [docs/adr/0003-narrative-grounding-heuristic.md]
---

Wrote `docs/adr/0003-narrative-grounding-heuristic.md`, the follow-on to
spike 0001 (`docs/spikes/0001-narrative-citation-format.md`), now that
Sentinel-L7 has shipped its own ADR-0034 in response to that spike's
findings. Design/scoping only — no code in this phase, matching this
repo's spike → ADR → build sequence.

### Decision: Narrowed Scope to Narrative-Only, Not a Rebuild of the Original Check

Spike 0001 originally flagged two problems: narrative citations don't
verbatim-match `policy_refs`, and `policy_refs` itself is sometimes
fabricated relative to what was actually retrieved. Sentinel-L7's
ADR-0034 fixed the second problem at the source —
`AbstractComplianceDriver` now forces `policy_refs = []` whenever
`chunk_count === 0`, closing the fabrication mode the spike measured (18
of 49 real calls, avg. confidence 0.88). The obvious-looking option was
to just re-scope the heuristic as "verify the ADR-0034 guard actually
fires" — but that guard is upstream, already covered by Sentinel-L7's own
logging (`policy_refs fabricated on empty retrieval` warning), and
re-checking it from arbiter-l8 would just be redundant monitoring of a
problem that's already fixed and observable at its source. ADR-0034's
own scope note is explicit that it only sanitizes the structured field,
not `narrative` — so the real remaining gap, and the one ADR-0003 scopes,
is narrative prose making a citation-shaped or regulation-referencing
claim that was never grounded, independent of whether `policy_refs` now
looks clean.

### Challenge: The Adapter Doesn't Expose `chunk_count` At All

Confirming what data arbiter-l8 actually has to work with meant rereading
`adapters/sentinel_l7.py:120-126` directly rather than assuming symmetry
with what Sentinel-L7 logs internally. Sentinel-L7's own `chunk_count`
signal — the thing ADR-0034's guard keys off of — never crosses the MCP
boundary; the adapter's `raw_output` is only `{source, is_threat,
message, elapsed_ms, risk_level, narrative, confidence, policy_refs}`.
That ruled out the simplest design ("just read chunk_count and gate on
it") and forced the semantic stage to re-derive an equivalent signal
independently, by re-querying the same `policies` Upstash Vector
namespace Sentinel-L7 itself queries and checking whether anything
clears threshold — the same information, recomputed from arbiter-l8's
side rather than trusted secondhand.

### Decision: Reuse `consistency.py`'s Upstash Infra, Reject the Title-String Shortcut

Considered comparing a narrative's embedding directly against
`policy_refs`' title strings (e.g. "GDPR-001") as a cheaper alternative
to a full namespace re-query — no new namespace-query code, just an
embed-and-cosine-compare between two short strings. Rejected it: that
comparison only tests whether the narrative *sounds like* the label
Sentinel-L7 already asserted, which is circular if `policy_refs` is
wrong for a reason other than the all-zero-retrieval case ADR-0034
covers (right `chunk_count`, wrong chunk matched, for instance).
Re-querying the real `policies` namespace via the existing
`query_upstash_vector()` (`online/consistency.py:80-121`, already
supports an explicit `namespace` override) checks narrative against
actual corpus content instead of against the driver's own claim, and
costs nothing new to build — it's the same function Layer 3 already
uses, called with a different namespace and a different threshold
(0.70, matching Sentinel-L7's own policy-retrieval threshold, vs. the
transactions-namespace default of 0.90 already in `config.py`).

### Pattern: Dependency-Gated Escalation, Applied One Layer Earlier

ADR-0002 established that Layers 2–4 only run when both "flagged by an
earlier layer" and "caller supplied the dependency" hold, degrading
gracefully rather than erroring when a dependency (embedding function,
judge circuit breaker) isn't wired up. ADR-0003 applies the identical
gating shape to a single new check rather than a whole layer: its regex
stage is unconditional (free, no dependency), but its semantic stage
only escalates when an `embed_fn` is supplied — same "optional
dependency, no-op if absent" contract, just scoped to one module instead
of the whole online pipeline. This is also why the check couldn't just
be dropped into `heuristics.py`'s existing `DEFAULT_CHECKS` tuple: every
function there is a pure, zero-dependency check by construction, and
this one genuinely isn't.

### Decision: Regulatory-Keyword List Left Unspecified in the ADR

The dominant real fabrication pattern per spike 0001's n=49 (0 of 18
non-empty-`policy_refs` narratives had a formal citation token at all —
just prose like "per regulatory mandates... GDPR") means a keyword
pre-filter is doing most of the real work of deciding when to escalate
to the semantic stage. Deliberately left the exact keyword list as a
build-time decision rather than pinning it in the ADR — n=49 is enough
to know prose-only citation is the dominant case, not enough to tune a
specific word list against real precision/recall, and no `high`/
`critical` risk_level sample exists yet in either spike pull to check
whether the list holds at the end of the risk spectrum where it likely
matters most. Recorded as a named follow-up rather than guessed at now.
