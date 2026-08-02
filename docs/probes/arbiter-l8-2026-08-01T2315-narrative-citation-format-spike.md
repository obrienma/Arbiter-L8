---
type: cloze
deck: Rhizome::arbiter-l8
tags: [arbiter-l8, spike, hybrid-extraction]
---
At n=49 real Sentinel-L7 samples with non-empty `policy_refs`, the rate of
a `policy_refs` value appearing verbatim in its own `narrative` text was
{{c1::0%}} — confirming the narrative-grounding heuristic needs
{{c2::hybrid regex + semantic-similarity}} extraction, not pure regex.

Extra: arbiter-l8 · Pattern: The n=2 Finding Held at n=49 — More Starkly
See: docs/journal/arbiter-l8-2026-08-01T2315-narrative-citation-format-spike.md

---
type: cloze
deck: Rhizome::arbiter-l8
tags: [arbiter-l8, spike, rag-grounding, hallucination]
---
Across the whole live-run session, {{c1::57}} total policy-RAG retrievals
were logged, chunk_count=0 in every one — 6 from manual diagnostics, 51
mapping 1:1 onto all 51 watcher-processed transactions. The model still
fabricated a plausible `policy_refs` value on 18/49 `cache_miss` calls at
an average stated confidence of {{c2::0.88}} — meaning `policy_refs`
can't be trusted as ground truth for a narrative-grounding heuristic
without first checking it against the retrieval log.

Extra: arbiter-l8 · Decision: Checked What the RAG Retrieval Log Actually Said, and Found a Bigger Problem
See: docs/journal/arbiter-l8-2026-08-01T2315-narrative-citation-format-spike.md

---
type: basic
deck: Rhizome::arbiter-l8
tags: [arbiter-l8, spike, verification]
---
Q: Sentinel-L7's ADR-0034 flagged that this spike's addendum said
chunk_count=0 held "for all 51 requests in the run," while also saying
Tier 3 fallback never calls fetchPolicyContext — an apparent contradiction
for the 2 fallback rows. How was this actually resolved?

A: Paired every `policy RAG retrieval` log line with its adjacent
`ARBITER_SPIKE_SAMPLE` line in strict chronological order (processing is
single-threaded, so each transaction's RAG line is immediately followed by
its own result line) instead of trusting a raw `grep | tail -51` count.
Found: 6 of the 57 total RAG lines were manual diagnostic calls unrelated
to the batch; the remaining 51 mapped 1:1 onto all 51 watcher-processed
transactions — including both fallback rows, which really did reach
`fetchPolicyContext` (chunk_count=0) before failing later at the
chat-model call itself (likely an OpenRouter free-tier rate-limit hiccup),
not at the embedding/vector-search stage that would skip RAG entirely. The
"51" was correct, but the original reasoning for it wasn't verified — an
unverified correct number is still a defect worth fixing.

Extra: arbiter-l8 · Challenge: A Downstream Reviewer Caught an Inconsistency I'd Have Shipped
See: docs/journal/arbiter-l8-2026-08-01T2315-narrative-citation-format-spike.md

---
type: cloze
deck: Rhizome::arbiter-l8
tags: [arbiter-l8, spike, silent-failure]
---
Every transaction in the first live-run attempt silently fell to Tier 3
fallback after ~33s with no logged exception, because
`TransactionProcessorService::process()`'s outer try/catch swallows the
error by design (so Tier 3 can take over cleanly) — the real cause
({{c1::OLLAMA_URL pointing at an unreachable private Tailscale IP}}) was
only found by calling the embedding/compliance services directly in
{{c2::artisan tinker}}, bypassing the catch entirely.

Extra: arbiter-l8 · Pattern: Silent Catch Blocks Hide the Real Failure
See: docs/journal/arbiter-l8-2026-08-01T2315-narrative-citation-format-spike.md

---
type: basic
deck: Rhizome::arbiter-l8
tags: [arbiter-l8, spike]
---
Q: Getting a working AI driver for the n=49 live run took three attempts.
What were the three dead ends, in order, and why did each fail?

A: (1) Ollama — the configured driver's embedding/chat calls go to
`OLLAMA_URL`, a Tailscale/CGNAT private IP unreachable from a sandboxed
shell, so every call silently timed out into Tier 3 fallback. (2) Gemini —
after switching both the embedding driver and the AI driver (they're
separate `Manager` classes, `EmbeddingManager` vs `ComplianceManager`,
easy to fix only one), Gemini's free tier returned `RESOURCE_EXHAUSTED`
with `limit: 0` — a dead quota, not a transient rate limit. (3) OpenRouter
— the configured free model `meta-llama/llama-3.3-8b-instruct:free` no
longer had any endpoints (404), since deprecated/removed from OpenRouter's
catalog. Fetching OpenRouter's public `/models` list and picking a
currently-available free model (`openai/gpt-oss-20b:free`) finally worked.

Extra: arbiter-l8 · Challenge: Three Dead AI Drivers Before Finding One That Worked
See: docs/journal/arbiter-l8-2026-08-01T2315-narrative-citation-format-spike.md
