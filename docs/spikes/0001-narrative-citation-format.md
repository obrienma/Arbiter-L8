# Spike 0001: Narrative citation format in Sentinel-L7 output

|  |  |
| --- | --- |
| **Status** | Resolved |
| **Date** | 2026-08-01 |
| **Owner** | Amanda |
| **Related** | Proposed narrative-grounding heuristic for arbiter-l8 (attribution/specificity split, per the Emmimal/llm-eval-layer pattern) |

## Result

-   **Regex-only extraction against `policy_refs` will not work.** Across 49 live samples, 18 had a non-empty `policy_refs`, and none of those 18 had a single `policy_refs` value appear verbatim in its narrative.
-   **A hybrid approach is better supported:** regex where a recognizable citation token exists, semantic similarity between narrative sentences and `policy_refs` content for everything else. Tokens were rare. Of all 51 real narratives, only one (n=2 Sample A) contained one.
-   **Tier 3 (rule-based fallback) needs an unconditional skip.** Its narratives are fixed templates that cannot contain a citation.
-   **New blocker: `policy_refs` is not reliable ground truth.** RAG retrieved zero chunks on every call, yet the model still returned confident `policy_refs` values. A heuristic that checks narrative against `policy_refs` would be checking one unreliable field against another.

**Next:** before building the extractor, measure `policy_refs` fabrication rate against `chunk_count` from the RAG retrieval log, either as a follow-up spike or as the first step of the build.

## Question

Sentinel-L7's `raw_output` has a free-text `narrative` and `policy_refs`, the RAG-retrieved policy documents the narrative should be grounded in. The proposed arbiter-l8 heuristic flags "confident but ungrounded" narratives by extracting citation-like tokens (section numbers, dollar thresholds, policy IDs) from `narrative` and checking them against `policy_refs`.

That assumes citations appear in a consistent, extractable format, which had not been checked. If they don't, an extractor silently undercounts: it looks right on hand-picked examples and misses most real cases. This spike checks the assumption before any extraction logic is written.

**Check for each sample:**

1.  **Format consistency.** Do specific claims appear in a few recognizable patterns (e.g. `§205.6(b)`, `policy #1042`), or is phrasing too varied for a fixed regex set?
2.  **Tier 3 narrative.** Does the rule-based fallback populate `narrative` at all? This decides whether the heuristic needs a no-op guard.
3.  **Correspondence with `policy_refs`.** Do citations map 1:1 to `policy_refs` entries, or does the model reference policy content in prose with no extractable ID?
4.  **False positives.** Do non-citation numbers in narratives (amounts, timestamps, scores) risk being misread as policy references?

## Method

Two passes on 2026-08-01. The first was meant to be the whole spike but produced too few samples.

**Pass 1: stored data (n=2).** Real `narrative`/`policy_refs` pairs from two live Sentinel-L7 stores:

-   Upstash Vector `transactions` namespace (queried via the `/range` REST endpoint). This is the durable store for Tier 2 (`cache_miss`) results. Tier 1 (`cache_hit`) reuses the same `analysis.narrative` and `analysis.policy_refs` verbatim, so it is not a separate style to sample.
-   Postgres `compliance_events` (Neon), the Axiom/anomaly pipeline's persistence.

The deployment turned out to be a low-traffic dev/demo instance. The `transactions` namespace held 2 vectors. `compliance_events` had 5 rows with `driver_used = 'openrouter'`, all with `audit_narrative IS NULL`, which look like leftover seed data. That left 2 usable samples against a target of 30 to 50.

**Pass 2: live run (n=49).** To close the gap, `php artisan sentinel:stream --limit=50` was run against a live `sentinel:watch` consumer. A temporary `Log::info('ARBITER_SPIKE_SAMPLE', $result)` in `WatchTransactions::processMessage()` captured the full `narrative`, `policy_refs`, `risk_level` and `confidence` per transaction.

Getting a working AI driver took three attempts:

| Driver | Outcome |
| --- | --- |
| Ollama (`OLLAMA_URL`) | Private Tailscale IP, unreachable from the sandbox |
| `SENTINEL_AI_DRIVER=gemini` | Free-tier quota exhausted (`limit: 0`, not transient) |
| `meta-llama/llama-3.3-8b-instruct:free` on OpenRouter | No endpoints remain |
| **`openai/gpt-oss-20b:free` on OpenRouter** | **Worked; used for the batch** |

Of 51 transactions processed, 49 were `source: cache_miss` (real AI calls) with no duplicates or errors. The other 2 were Tier 3 fallback rows from before the driver fix and were excluded.

## Findings

### 1\. Format consistency: inconsistent

**Live batch (n=49).** No narrative contained a citation token: no `§`, no `Section N`, no formal ID. Narratives describe the situation, while `policy_refs` is a separately generated tag.

> narrative: "The transaction involves a remittance service named 'RapidRemit Structuring Node' with an amount below $10,000, raising moderate concerns about potential structuring activity." policy\_refs: `["Anti-Money Laundering (AML) Policy", "Structuring Policy"]`

> narrative: "This is a small retail purchase at a local farm market with no indicators of suspicious activity." policy\_refs: `["Retail Transaction Policy"]`

**Stored data (n=2).** The only narratives with citation-like tokens:

> **Sample A** (`risk_level: low`, `policy_refs: ["AML-BSA-001", "GDPR-001"]`): "The transaction of $100 CAD to Test Co presents low compliance risk as it falls well below the CTR threshold and does not trigger SAR filing requirements based on current policy criteria; however, automated anomaly scoring above 0.80 would mandate a human review under **AML-BSA-001 Section 5** and **GDPR-001 Section 4**."

Sample A's tokens carry a `" Section N"` suffix that is not in the `policy_refs` strings, so an exact-match regex misses both.

> **Sample B** (`risk_level: medium`, `policy_refs: ["BSA Requirements (OFAC Screening)", "GDPR-001", "Sanctions Compliance Policy"]`): "The transaction involving Pacific Forex Exchange requires screening against OFAC, EU, and UN sanctions lists per regulatory mandates, with automated decision-making logic fully documented to ensure data subject rights under GDPR are respected if flagged for investigation."

Sample B matches none of its `policy_refs` verbatim. It says "GDPR", not `GDPR-001`.

**The ground-truth side has no stable grammar either.**

-   `policy_refs` mixes short codes (`AML-BSA-001`) with full prose titles (`Sanctions Compliance Policy`).
-   The live batch produced 10 distinct strings for a handful of underlying concepts.
-   Some are character-level near-duplicates: `Anti-Money Laundering (AML) Policy` vs `Anti‑Money Laundering Policy`, the second using a non-breaking hyphen (U+2011) instead of U+002D. A regex tuned to one phrasing misses the other.

### 2\. Tier 3 narrative: fixed templates, confirmed from code

No real Tier 3 narratives exist to sample because the path is deterministic. Code review shows:

-   **Transaction path** (`ThreatAnalysisService.php:11-18,36`, via `TransactionProcessorService.php:171`): one of two templates, `"High value transaction at {merchant} (${amount})"` or `"Layer 7 Clear: {merchant} - OK"`. `policy_refs` is hardcoded to `[]` (`TransactionProcessorService.php:173`).
-   **Axiom/anomaly path** (`AxiomThreatAnalysisService.php:23`): `"Rule-based fallback: anomaly score {score} exceeds audit threshold {threshold} for domain {domain} — AI analysis unavailable."`

Both are string interpolation of structured fields, never natural-language citations. The heuristic should skip Tier 3 unconditionally instead of running a regex over text that cannot contain a citation.

**`source: fallback` covers two different cases.** The code analysis above describes the first. The live run surfaced the second:

1.  The AI driver is never reached (embedding or cache failure), so RAG is skipped.
2.  RAG is consulted (empty), and the chat-model call then fails. Both excluded fallback rows were this case, most likely an OpenRouter free-tier rate limit near the end of a roughly 50-request burst.

Both are labeled identically in `source`, so anything that branches on that field should account for it.

### 3\. Correspondence with `policy_refs`: none

-   **Live batch:** 0 of 18 non-empty `policy_refs` had any value verbatim in the narrative.
-   **Stored data:** Sample A matched partially (suffixed), Sample B not at all.

Prose-only and paraphrased references are the norm, not an edge case.

### 4\. False-positive risk: present

Sample A contains `$100` and `0.80` (the anomaly-score threshold restated in prose). Neither is a citation, and a bare decimal like `0.80` could trip a loosely written numeric regex. No section-number-shaped false positives were observed, but the prompt schema places no constraints on how numbers appear in prose.

### 5\. New: `policy_refs` is fabricated, not retrieved

This was not one of the original four questions.

-   The RAG retrieval log (`AbstractComplianceDriver::fetchPolicyContext`) has 57 `policy RAG retrieval` lines, and **`chunk_count: 0` in every one**.
-   Processing is single-threaded and sequential, so each RAG line sits immediately before its own result line. Pairing them chronologically accounts for all 57: 6 are manual `tinker` calls made while debugging drivers, and the other 51 map 1:1 to the watcher-processed transactions, including both fallback rows.
-   The `policies` Upstash Vector namespace holds only 4 chunks, and none cleared the 0.70 similarity threshold for any of these queries. The prompt sent to the model said `"No specific policy context retrieved."` on every call, across every driver tried (Ollama, Gemini, OpenRouter).
-   The model still produced a plausible `policy_refs` title on 18 of 49 successful calls, at an **average stated confidence of 0.88** (range 0.6 to 0.95).

## Limits of this evidence

-   **Risk-level skew.** The live batch was 44 low, 5 medium, 0 high, 0 critical, because the synthetic stream is mostly small routine purchases. The earlier pull added one medium. No critical sample exists in either dataset, so citation behavior where narratives may be denser with regulatory language is unverified.
-   **Single model.** The live batch used one free-tier model (`openai/gpt-oss-20b:free`). Other drivers may phrase narratives differently.
-   **Empty retrieval.** Because RAG returned nothing, this run cannot say how narratives cite policy when retrieval works. The 0% match rate may partly reflect that.

## Cleanup

All temporary changes were reverted immediately after data capture. Sentinel-L7's live driver configuration is unchanged.

-   `sentinel-l7/.env`: `SENTINEL_EMBEDDING_DRIVER`, `SENTINEL_AI_DRIVER` and `OPENROUTER_MODEL` restored to `ollama`, `ollama` and `meta-llama/llama-3.3-8b-instruct:free`.
-   `WatchTransactions.php`: temporary `Log::info` line removed.
-   Nothing committed to the Sentinel-L7 repo; `.env` was never tracked.