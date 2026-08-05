# ADR 0003 — Narrative-Only Grounding Heuristic

**Status:** Accepted **Date:** 2026-08-04

---

## Context

Spike 0001 (`docs/spikes/0001-narrative-citation-format.md`) investigated
whether Sentinel-L7's `narrative` free text cites `policy_refs` in a
consistent, extractable format. It found the opposite, and worse: across
49 live `cache_miss` samples, 18 had non-empty `policy_refs`, and **zero**
of those had any `policy_refs` value appear verbatim in the narrative
text. It also surfaced a more consequential finding along the way — the
RAG retrieval log showed `chunk_count: 0` on every one of 57 retrieval
attempts in that session (the `policies` Upstash Vector namespace holds
only 4 chunks, none clearing the 0.70 similarity threshold), yet the model
still asserted a confident, non-empty `policy_refs` on 18 of those 49
calls, at an average stated confidence of 0.88. `policy_refs` was, in
that sample, routinely fabricated rather than retrieved.

Sentinel-L7 has since shipped **ADR-0034** ("Guard Against `policy_refs`
Fabrication on Empty Retrieval," commits `3570cf7` and `a1b660c`),
directly triggered by spike 0001's finding. `AbstractComplianceDriver`
now runs `guardPolicyRefsAgainstEmptyRetrieval()` after every parsed
response: if `chunk_count === 0` for the retrieval that produced it, the
driver forces `result['policy_refs'] = []` regardless of what the model
returned, and logs a `'{Driver}: policy_refs fabricated on empty
retrieval'` warning with the original asserted refs in context. This
closes the specific fabrication mode spike 0001 measured — `policy_refs`
is now a trustworthy field on the Sentinel-L7 side.

ADR-0034's own docblock records an explicit scope boundary
(`AbstractComplianceDriver.php:56-62`): the guard **only sanitizes the
structured `policy_refs` field. It does not touch `narrative`.** Free
text reaches `compliance_events.audit_narrative` and the cached
transaction analysis unmodified. A narrative can still assert "per
regulatory mandates... GDPR" or cite a specific section number in prose
even when nothing was retrieved — the exact pattern spike 0001's Sample B
showed (`"...requires screening against OFAC, EU, and UN sanctions lists
per regulatory mandates..."` against `policy_refs: ["BSA Requirements
(OFAC Screening)", "GDPR-001", "Sanctions Compliance Policy"]`, zero
verbatim overlap). ADR-0034 fixed the ground-truth field; it did not fix
the thing spike 0001 was originally scoped to check.

This ADR scopes what's still open: an arbiter-l8-side heuristic that
judges narrative text itself for ungrounded citation-shaped or
regulation-referencing claims, independent of `policy_refs`'s (now
upstream-guarded) cleanliness. Per this repo's own boundary
(`docs/adr/0001-standalone-module.md`), the design below treats
`narrative`/`policy_refs` as optional, opportunistic `raw_output` keys —
it must no-op cleanly for any system-under-test whose payload doesn't
carry them, exactly as `check_narrative_confidence_contradiction`
(`src/arbiter_l8/online/heuristics.py:78-95`) already does.

Two constraints from the existing codebase shape the design directly:

- The Sentinel-L7 MCP adapter's `raw_output` never exposes `chunk_count`
  (`src/arbiter_l8/adapters/sentinel_l7.py:120-126` — only `{source,
  is_threat, message, elapsed_ms, risk_level, narrative, confidence,
  policy_refs}`). Arbiter-L8 cannot read Sentinel-L7's own retrieval
  signal directly; any grounding check has to either infer from
  `policy_refs` or re-derive retrieval success independently.
- ADR-0002 already established a dependency-gated escalation pattern
  (flagged **and** dependency supplied → escalate, otherwise skip rather
  than error) and a reusable embedding/Upstash-Vector-query pipeline
  (`src/arbiter_l8/online/consistency.py`) that must reuse Sentinel-L7's
  exact embedding model/dimension rather than an independently chosen one.

---

## Decision

**Add a narrative-grounding check as a new module,
`src/arbiter_l8/online/narrative_grounding.py`**, run as a sub-step
immediately after `run_heuristics` in `pipeline.py`, rather than as an
additional function in `heuristics.py`'s `DEFAULT_CHECKS`.

**Why a new module, not a new `DEFAULT_CHECKS` entry:** every existing
check in `heuristics.py:37-95` is a pure, zero-dependency `EvalPrediction
-> HeuristicFlag | None`. This check needs an *optional*
`embed_fn: EmbeddingFn | None` for its semantic stage — the same
dependency-gating shape ADR-0002 established for layers 2–4
(`docs/adr/0002-online-escalation-pipeline.md`, "Decision," points 2–4),
just applied one layer earlier since its regex half is free and can run
unconditionally.

### Unconditional Tier-3 skip

No-op immediately when `prediction.metadata.get("source") == "fallback"`.
Confirmed by spike 0001 (`docs/spikes/0001...md:68-71`): Tier 3's
narrative is always fixed-template string interpolation of already-
structured fields — never natural-language citation, regardless of driver.

### Stage 1 — regex extraction (free, always runs)

Extract citation-shaped tokens from `narrative`: policy-ID patterns
(e.g. `AML-BSA-001`) and section-reference patterns (e.g. `§205.6(b)`,
`Section 5`). Bare dollar amounts and decimals are deliberately excluded
as tokens — spike 0001 flagged `$100` and `0.80` (a restated anomaly
score) as false-positive risk in exactly this shape
(`docs/spikes/0001...md:73`).

Before comparing an extracted token against `policy_refs`, normalize
both sides: fold Unicode hyphens (U+2011) to ASCII (U+002D), and strip a
trailing `" Section N"`-style suffix from the narrative token. These are
the two concrete failure modes spike 0001 documented — `AML-BSA-001
Section 5` in narrative vs. `AML-BSA-001` in `policy_refs`, and
`Anti-Money Laundering (AML) Policy` vs. `Anti‑Money Laundering Policy`
as two distinct strings for the same concept (`docs/spikes/0001...md:67`,
`:105`).

### Stage 2 — decision tree

1. No `narrative` key, or Tier-3 source → no-op.
2. Regex finds a token; normalized match found in `policy_refs` → not
   flagged.
3. Regex finds a token; no match; `policy_refs` is empty → **flag,
   high severity, no embedding call.** Post-ADR-0034, an empty
   `policy_refs` is a reliable "definitely nothing retrieved" signal —
   a citation-shaped token in narrative under that condition is strong,
   cheaply-detected fabrication evidence on its own.
4. Regex finds a token; no match; `policy_refs` is non-empty → escalate
   to Stage 3 before flagging (guards against a near-miss the
   normalization step didn't catch, rather than flagging on regex
   near-misses alone).
5. No regex token, but narrative trips a small fixed regulatory-keyword
   list (illustrative, not exhaustive: "policy", "regulation",
   "pursuant", "mandate", "OFAC", "sanctions", "AML", "GDPR", "SAR",
   "CTR") → escalate to Stage 3. This is the *dominant* real case per
   n=49: 0 of 18 real non-empty-`policy_refs` narratives had a citation
   token at all; Sample B named "OFAC"/"GDPR" in prose with no formal ID.
   Only reachable when `embed_fn` is supplied — otherwise no-op, per the
   dependency-gating convention.
6. Neither token nor keyword hit → no-op. Per the n=49 addendum's
   coverage-gap finding, most low-risk narratives simply describe the
   transaction with no citation intent at all; flagging those would be
   pure noise.

The exact keyword list is a build-time decision left to implementation,
not fixed by this ADR — it is expected to need tuning against real
false-positive/negative rates (see Consequences).

### Stage 3 — semantic re-query

Embed the narrative via the existing `EmbeddingFn` contract, then query
the same `policies` Upstash Vector namespace Sentinel-L7 itself uses,
reusing `query_upstash_vector()` exactly as-is
(`src/arbiter_l8/online/consistency.py:80-121`, which already accepts an
explicit `namespace` override). If no match clears threshold, flag —
this independently re-derives what Sentinel-L7's own `chunk_count` would
have said, compensating for the adapter not exposing that field
directly. If a match clears threshold, no flag: grounding is
independently confirmed against real corpus content, not merely against
`policy_refs`'s self-reported value.

This requires one new config accessor,
`config.upstash_vector_policies_namespace()` → `"policies"`, mirroring
`upstash_vector_transactions_namespace()` (`config.py:98-102`), plus a
distinct default similarity threshold (0.70, matching Sentinel-L7's own
policy-retrieval threshold — not the transactions-namespace default of
0.90 already in `config.py:94-95`).

---

## Alternatives considered

**Regex-only extraction, no semantic stage.** Rejected: n=49 showed the
dominant fabrication pattern (prose naming a regulation with no formal
token) has zero citation tokens to extract in the first place. A
regex-only design would silently miss the case that matters most.

**Treat ADR-0034 as sufficient; build nothing new in arbiter-l8.**
Rejected: ADR-0034's guard explicitly excludes `narrative`
(`AbstractComplianceDriver.php:56-62`). Spike 0001's core finding — prose
citing a policy concept with no verbatim, matchable token — is about
narrative specifically and remains unaddressed by the upstream fix.

**Compare narrative embedding directly against `policy_refs` title
strings, without re-querying Upstash Vector.** Considered, rejected:
this only checks whether the narrative *sounds like* the label
Sentinel-L7 already asserted — circular, since `policy_refs` could still
be wrong for a reason other than the `chunk_count=0` case ADR-0034 fixed
(e.g. correct `chunk_count` but the wrong chunk matched). Re-querying the
actual `policies` namespace judges the narrative against real corpus
content instead of trusting the driver's own claimed refs, and costs
nothing extra to build since `query_upstash_vector()` already supports
an arbitrary namespace.

---

## Consequences

**Positive**

- Closes the one gap ADR-0034's own scope note left open — narrative
  text is now covered, not just the structured `policy_refs` field.
- Reuses existing embedding/Upstash-Vector infrastructure
  (`consistency.py`) entirely; only one new config accessor is needed.
- Free in the common case: no token and no keyword hit is a pure no-op,
  consistent with ADR-0002's cost-ordering philosophy — the expensive
  embedding/query path only runs on narratives that already look
  citation-adjacent.

**Negative / Trade-offs**

- The regulatory-keyword list (Stage 2, step 5) is an arbitrary,
  hand-maintained list. It will need tuning against real
  false-positive/negative rates once this runs against live traffic —
  not something this ADR can pin down from n=49 alone.
- Neither spike 0001 pull (n=2, n=49) contained a `high`/`critical`
  `risk_level` sample. Severities and thresholds recorded here are
  therefore provisional against low/medium-risk narrative style only,
  not validated at the end of the risk spectrum where citation accuracy
  arguably matters most.
- Requires live credentials to Sentinel-L7's `policies` Upstash
  namespace for Stage 3, even in arbiter-l8's own dev/test use — the
  same dependency shape Layer 3 (`consistency.py`) already carries, not
  a new category of exposure.

---

## Follow-up (outstanding)

- Validate Stage 2's keyword list and Stage 3's flag rate against a
  `high`/`critical` sample once one becomes available in either
  Sentinel-L7 store.
- If Stage 3's independent re-query keeps finding the same near-zero
  retrieval-hit-rate ADR-0034's own follow-up flagged (4-chunk corpus,
  possibly miscalibrated 0.70 threshold), that is further evidence for a
  Sentinel-L7 corpus-growth or threshold-retune decision — out of scope
  for arbiter-l8 to fix directly, per `docs/adr/0001-standalone-module.md`.
- No dedicated test file for `online/` checks exists yet
  (`heuristics.py` itself has no `test_heuristics.py`; its only coverage
  is indirect, via `test_metrics.py` and `test_pipeline.py`). Building
  this module should add `tests/test_narrative_grounding.py`, following
  `test_consistency.py`'s `respx`-mocked-Upstash style for Stage 3 and
  using spike 0001's real samples (Sample A, Sample B, and
  representative n=49 pairs) as fixture data — not written as part of
  this ADR, since this is a scoping decision, not an implementation.
