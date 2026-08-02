# Spike 0001 — Narrative Citation Format in Sentinel-L7 Output

**Status:** Resolved **Date:** 2026-08-01 **Owner:** coder **Related:** proposed narrative-grounding heuristic for arbiter-l8 (attribution/specificity split, per Emmimal/llm-eval-layer pattern)

---

## Question

Sentinel-L7's `raw_output` includes a `narrative` field (free text) alongside `policy_refs` (the RAG-retrieved policy documents it should be grounded in). A proposed arbiter-l8 heuristic would flag "confident but ungrounded" narratives by regex-extracting citation-like tokens (section numbers, dollar thresholds, policy IDs) from `narrative` and checking whether they appear in `policy_refs`.

This assumes citations show up in a consistent, extractable format. That assumption hasn't been checked against real output. This spike exists to check it before any extraction logic gets written.

## Why this matters

If the format is inconsistent, or citations are frequently expressed as prose rather than structured tokens, a regex-based extractor will silently undercount — producing a heuristic that looks like it works on hand-picked examples but misses most real cases. Better to find that out now than after the scorer ships.

## What to pull

-   30–50 real `narrative` + `policy_refs` pairs from Sentinel-L7, spanning all three cascade tiers (semantic cache hit, Ollama + RAG, rule-based fallback). Check the response's driver/source field to confirm which tier produced each sample — narrative style may differ by tier.
-   Prefer live/recent production or staging logs over synthetic test fixtures — hand-written test narratives won't reflect real model phrasing quirks.
-   Include a mix of `risk_level` values, not just `critical`/`high` — low-risk narratives may not cite anything, which matters for the "missing citation" edge case.

## What to check for each sample

1.  **Citation format consistency** — do specific claims (dollar thresholds, regulation/section numbers, policy IDs) appear in a small number of recognizable patterns (e.g. `§205.6(b)`, `Reg-E 205.6`, `policy #1042`), or is phrasing inconsistent enough that a fixed regex set will miss most of them?
2.  **Does the rule-based fallback tier populate `narrative` at all?** — confirm whether Tier 3 (no AI model involved) leaves narrative empty/null or generates templated text. Determines whether the new heuristic needs a no-op guard for that path.
3.  **Do citations correspond 1:1 with `policy_refs` entries**, or does the model sometimes reference policy content in prose without a formal-looking citation token at all (e.g. "per standard merchant category guidelines" with no extractable ID)? If prose-only references are common, note it — pure regex extraction will undercount, and the design may need a fallback to semantic-only attribution for those cases.
4.  **False-positive risk** — are there numbers in narrative that aren't citations at all (transaction amounts, timestamps) that a naive regex could misclassify as policy references?

## Deliverable

A short written summary appended to this file (not code) covering:

-   The actual citation format(s) observed, with a few representative examples.
-   Whether the format is consistent enough for regex extraction, or needs a different approach (e.g. semantic-only attribution, or a hybrid).
-   Confirmation of what the rule-based fallback tier produces for `narrative`.

This determines whether the narrative-grounding heuristic proceeds as originally scoped or needs a redesigned extraction approach.

---

## Findings

**Date conducted:** 2026-08-01

### Data pulled

Real stored `narrative`/`policy_refs` pairs, not synthetic fixtures, from two live Sentinel-L7 stores:

-   Upstash Vector `transactions` namespace (`VectorCacheService`, queried via the `/range` REST endpoint) — this is the durable store for the Tier 2 (`cache_miss`) AI result; Tier 1 (`cache_hit`) reuses this exact same `analysis.narrative`/`analysis.policy_refs` verbatim, so it is not a separate style to sample.
-   Postgres `compliance_events` table (Neon, queried via `run_sql`) — the Axiom/anomaly pipeline's persistence, via `driver_used`/`routed_to_ai`/`audit_narrative`.

**Sample size caveat, discovered mid-spike:** this deployment does not have the traffic volume the spike assumed. The `transactions` vector namespace holds **2** vectors total (`vectorCount: 2` from `/info`). `compliance_events` has 5 rows with `driver_used = 'openrouter'`, but all 5 have `audit_narrative IS NULL` — meaning zero usable real narrative samples exist for the Axiom pipeline's AI path; those rows look like leftover synthetic/seed test data rather than real narrative-producing traffic. Total usable real AI-narrative samples: **2**, not the 30–50 targeted. This is a low-traffic dev/demo instance, not a system with meaningful production history. Noted as a finding in its own right — see Recommendation below.

### The 2 real samples

**Sample A** (`risk_level: low`, `policy_refs: ["AML-BSA-001", "GDPR-001"]`):

> "The transaction of $100 CAD to Test Co presents low compliance risk as it falls well below the CTR threshold and does not trigger SAR filing requirements based on current policy criteria; however, automated anomaly scoring above 0.80 would mandate a human review under **AML-BSA-001 Section 5** and **GDPR-001 Section 4**."

**Sample B** (`risk_level: medium`, `policy_refs: ["BSA Requirements (OFAC Screening)", "GDPR-001", "Sanctions Compliance Policy"]`):

> "The transaction involving Pacific Forex Exchange requires screening against OFAC, EU, and UN sanctions lists per regulatory mandates, with automated decision-making logic fully documented to ensure data subject rights under GDPR are respected if flagged for investigation."

### Answers to the four check questions

1.  **Citation format consistency — inconsistent, and not just at the margins.** Sample A's narrative cites `AML-BSA-001 Section 5` / `GDPR-001 Section 4` — recognizable tokens, but with a `" Section N"` suffix appended that isn't part of the `policy_refs` string itself, so an exact-match regex against `policy_refs` values would still miss both. Sample B's narrative names "OFAC", "EU", "UN sanctions lists", and "GDPR" in prose but **matches none of its own `policy_refs` entries verbatim** — not `BSA Requirements (OFAC Screening)`, not `GDPR-001` (narrative only says "GDPR"), not `Sanctions Compliance Policy`. `policy_refs` itself isn't a consistent format either — it mixes short codes (`AML-BSA-001`) with full prose titles (`Sanctions Compliance Policy`), so there's no single citation grammar to target even on the ground-truth side.
2.  **Rule-based fallback (Tier 3) narrative population — confirmed via code, not sampled (no real Tier 3 AI-adjacent narrative exists to sample since it's deterministic):**
    -   Transaction path (`ThreatAnalysisService.php:11-18,36` via `TransactionProcessorService.php:171`): narrative is always one of two fixed templates — `"High value transaction at {merchant} (${amount})"` or `"Layer 7 Clear: {merchant} - OK"` — and `policy_refs` is hardcoded to `[]` (`TransactionProcessorService.php:173`). No policy context is even fetched on this path.
    -   Axiom/anomaly path (`AxiomThreatAnalysisService.php:23`): fixed template `"Rule-based fallback: anomaly score {score} exceeds audit threshold {threshold} for domain {domain} — AI analysis unavailable."`
    -   Both are pure string interpolation of already-structured fields (merchant, amount, score, threshold, domain) — never natural-language citations. **The heuristic needs an unconditional no-op guard for Tier 3**: skip extraction entirely rather than running the regex against a narrative that mathematically cannot contain a citation.
3.  **1:1 correspondence between citations and `policy_refs` — no, confirmed by both real samples.** Sample A: partial/suffixed match. Sample B: zero verbatim matches despite 3 `policy_refs` entries and multiple related terms in prose. This directly confirms the spike's concern in the "why this matters" section — prose-only/paraphrased references are not an edge case here, they're what both available real samples do.
4.  **False-positive risk from non-citation numbers — present.** Sample A contains `$100`, `0.80` (the anomaly-score threshold restated in prose) — neither is a policy citation, but `0.80` in particular is a bare decimal that a loosely-written numeric regex could misfire on. No section-number-shaped false positives observed in n=2, but the risk is real given the prompt schema places no constraints on how numbers appear in prose.

### Conclusion

**Regex-only extraction, as originally scoped, will undercount** — both real samples confirm the spike's hypothesis rather than ruling it out: exact or prefix-token matching against `policy_refs` fails on Sample B entirely and only partially succeeds on Sample A. Prose-only/paraphrased references (policy named but not ID-matched, e.g. "GDPR" vs. `GDPR-001`) are common enough in n=2 that they can't be treated as a rare edge case. A hybrid approach — regex for the subset of narratives that do contain a recognizable token, falling back to semantic similarity between narrative sentences and the actual `policy_refs` content/titles for the rest — is better supported by the evidence than a pure regex extractor. Tier 3 needs an unconditional skip (no narrative-grounding check is meaningful there), which is a cheap, unambiguous guard to add regardless of which extraction approach is chosen.

**Confidence caveat (superseded below):** the above rests on n=2 real samples plus full code-level certainty on Tier 3. Directionally strong but not statistically robust on its own — resolved by generating fresh live traffic, see next section.

---

## Live run addendum (n=49)

**Date:** 2026-08-01, same day, follow-up to close the n=2 confidence gap.

Generated 49 fresh real Tier 2 samples by running `php artisan sentinel:stream --limit=50` against a live `sentinel:watch` consumer, with a temporary `Log::info('ARBITER_SPIKE_SAMPLE', $result)` added to `WatchTransactions::processMessage()` to capture full `narrative`/`policy_refs`/`risk_level`/`confidence` per transaction (reverted after data collection — see below). Getting a working AI driver took three attempts: `OLLAMA_URL` (private Tailscale IP) is unreachable from a sandboxed environment; `SENTINEL_AI_DRIVER=gemini` is quota-exhausted on the free tier (`limit: 0`, not transient); `OPENROUTER_MODEL=meta-llama/llama-3.3-8b-instruct:free` no longer has any endpoints on OpenRouter. Settled on `SENTINEL_AI_DRIVER=openrouter` with `OPENROUTER_MODEL=openai/gpt-oss-20b:free`, confirmed working, then ran the batch. All temporary `.env`/code changes reverted immediately after data capture (see "Cleanup" below) — this addendum does not change Sentinel-L7's live driver configuration.

### Result: 49/49 usable, 0 duplicates or errors

`source: cache_miss` (real AI call, not cache or fallback) for 49 of the 51 total processed; 2 were leftover Tier 3 fallback rows from before the driver fix and excluded from analysis.

### The zero-verbatim-match finding from n=2 holds at n=49 — even more starkly

Of the 49 real samples, **18 had a non-empty `policy_refs`; 0 of those 18 had any `policy_refs` value appear verbatim anywhere in the narrative text.** Not "mostly missed" — zero matches, full stop. Representative pairs:

> narrative: "The transaction involves a remittance service named 'RapidRemit Structuring Node' with an amount below $10,000, raising moderate concerns about potential structuring activity."
> policy_refs: `["Anti-Money Laundering (AML) Policy", "Structuring Policy"]`

> narrative: "This is a small retail purchase at a local farm market with no indicators of suspicious activity."
> policy_refs: `["Retail Transaction Policy"]`

The narrative never names the policy by its `policy_refs` title — it describes the *situation* (structuring concern, no red flags) while `policy_refs` is a separately-generated categorical tag. There is no citation token anywhere in this batch — no `§`, no `Section N`, no formal ID like `AML-BSA-001` (those did appear in the earlier n=2 pull, see below for why). This confirms question 1 and question 3 from the original spike checklist definitively: **regex extraction against `policy_refs` values has a 0% hit rate on this batch.**

`policy_refs` itself is also not a stable vocabulary across calls — 10 distinct strings for what is clearly a handful of underlying concepts, including a straight Unicode inconsistency (`Anti-Money Laundering (AML) Policy` vs `Anti‑Money Laundering Policy`, the second using U+2011 non-breaking hyphen instead of U+002D). A regex set tuned to one phrasing will miss its own near-duplicates.

### New, more consequential finding: `policy_refs` is fabricated, not retrieved, in this batch

Checked the RAG retrieval log line (`AbstractComplianceDriver::fetchPolicyContext`) across the session: **57 total `policy RAG retrieval` log lines, `chunk_count: 0` in every single one, no exceptions.** Verified precisely by pairing each RAG-retrieval line with its adjacent `ARBITER_SPIKE_SAMPLE` line in strict chronological order (processing is single-threaded and sequential, so each transaction's RAG line is immediately followed by its own result line): 6 of the 57 are manual `tinker` diagnostic calls made while debugging which AI driver would actually work (not part of the batch); the remaining **51 correspond 1:1 to all 51 watcher-processed transactions — including both of the 2 rows that ultimately fell back to Tier 3.**

That second point matters and corrects an earlier imprecise claim in this addendum's first draft: both fallback rows *did* reach `fetchPolicyContext` (and logged `chunk_count: 0`) before failing later, at the chat-model call itself — almost certainly an OpenRouter free-tier rate-limit hiccup near the end of a ~50-request burst, not an embedding/vector-search-level failure. So `source: fallback` in this codebase isn't monolithic: it covers both "never reached the AI driver at all" (embedding/cache failure, skips RAG entirely — the general case this spike's Tier 3 code analysis describes) *and* "reached RAG and the model call, but the model call itself failed" (RAG was consulted, still empty, then Tier 3 substituted anyway). Both are labeled identically in the `source` field, which is worth knowing before building anything that branches on it.

The `policies` Upstash Vector namespace only holds 4 chunks total (see original n=2 findings' `/info` call) and apparently none cleared the 0.70 similarity threshold for any of these transaction queries — the prompt sent to the model literally said `"No specific policy context retrieved."` in every case, across every driver tried (Ollama, Gemini, OpenRouter). The model fabricated a plausible-sounding `policy_refs` title anyway on 18/49 successful calls, at an average stated confidence of **0.88** (range 0.6–0.95) — high confidence on a citation that cites nothing real.

This is a bigger problem for the proposed heuristic than citation formatting: **`policy_refs` cannot be trusted as ground truth to check the narrative against, because `policy_refs` itself isn't reliably grounded in retrieved policy content.** A narrative-grounding heuristic built purely on "does narrative cite policy_refs" inherits this — it would be checking one hallucination-prone field against another. This wasn't in the original spike's four check questions and is flagged here as a new open question for whoever scopes the heuristic build, not resolved by this spike.

### Coverage gap acknowledged

This batch skews low-risk: 44 `low` / 5 `medium` / 0 `high` / 0 `critical`, because the synthetic stream's transaction mix is mostly small routine purchases. The original spike explicitly asked for risk_level diversity including high/critical. The earlier n=2 pull (Upstash Vector `transactions` namespace) did include one `medium`-with-sanctions-language sample; still, no `critical` example exists in either dataset. Citation behavior at the high/critical end (where narratives may be denser with regulatory language) remains unverified.

### Cleanup performed after data capture

- `sentinel-l7/.env`: `SENTINEL_EMBEDDING_DRIVER`, `SENTINEL_AI_DRIVER`, `OPENROUTER_MODEL` reverted to their original values (`ollama`, `ollama`, `meta-llama/llama-3.3-8b-instruct:free`).
- `sentinel-l7/app/Console/Commands/WatchTransactions.php`: temporary `Log::info('ARBITER_SPIKE_SAMPLE', ...)` line removed.
- No changes committed to Sentinel-L7's repo; `.env` was never tracked by git.

### Revised conclusion

Hybrid regex + semantic-similarity extraction (from the n=2 conclusion) still stands, now backed by n=49 showing a 0% verbatim-match rate rather than n=2's partial evidence. Additionally: **before building the extractor, confirm whether `policy_refs` should be treated as ground truth at all** — this run showed the model asserts confident `policy_refs` values even with zero retrieved policy context, which undermines using `policy_refs` as the target the narrative-grounding heuristic checks against. Recommend a follow-up spike (or fold into the same build) checking `policy_refs` fabrication rate against `chunk_count` from the RAG retrieval log before finalizing the heuristic's design.