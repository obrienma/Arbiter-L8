# ADR 0002 — Cost-Ordered, Escalation-Gated Online Scoring Pipeline

**Status:** Accepted
**Date:** 2026-07-04 (extracted from ADR 0001; original decision undated split, see below)

---

## Context

ADR 0001 established the offline/online split for `arbiter-l8`: offline
scoring runs against `TransactionSeeder`'s labeled corpus (precision/recall/
F1, no LLM required), while online scoring covers sampled production
traffic with no ground truth available. That ADR's "Offline / online split"
section originally carried the full design for the online path's four-layer
pipeline. This ADR extracts that content into its own document — one
decision per ADR — so the escalation logic is discoverable on its own
terms rather than nested inside a document titled around the
standalone-module decision. No design content is changed from ADR 0001;
one implementation detail (dependency gating, below) is added because it
exists in `pipeline.py` but was never written down.

Two systems (Sentinel-L7, Synapse-L4) produce AI-justified output with no
ground truth available at inference time. Scoring every item against an
LLM judge is the most accurate option per-item, but neither available judge
source (partner's remote Ollama, Gemini Flash free tier) carries an uptime
guarantee, and running a judge call on every item defeats the point of a
cost-ordered pipeline.

---

## Decision

`evaluate_item()` runs online-eval layers in cost-ascending order, escalating
only the ambiguous tail:

1. **Rule-based heuristics** (confidence thresholds, field-contradiction
   checks) — free, deterministic, always runs, on every item.
2. **Cross-provider disagreement** (Gemini vs. OpenRouter via the existing
   dual-provider `ComplianceDriver`, or same-provider temperature
   variance) — reuses infrastructure already built, no new cost.
3. **Embedding-based consistency** (Upstash Vector) — flags verdicts that
   diverge from near-identical historical embeddings.
4. **LLM-as-judge** (remote Ollama over Tailscale, falling back to Gemini
   Flash) — reserved for the ambiguous tail flagged by layers 1–3, not run
   on every item.

Layers 2–4 only execute when **both** conditions hold: the item was
flagged by an earlier layer, **and** the caller supplied that layer's
dependency (a provider map, an embedding function, a judge circuit
breaker). A layer whose dependency wasn't supplied is skipped, not treated
as an error — the pipeline degrades to whatever subset of layers the
caller has wired up rather than failing closed. This means only the
layers actually invoked get a child span under `evaluate_item`'s trace,
which keeps online-eval telemetry honest about what was actually checked
versus what was configured but unavailable.

### Judge availability as a first-class failure mode

The remote Ollama judge sits behind a circuit breaker with the same shape
as Sentinel's existing external-provider handling:

- Try Ollama (free, but uptime not guaranteed — partner-owned remote host).
- On failure/timeout, fall back to Gemini Flash free tier.
- On failure/timeout there too, fall back to heuristics-only scoring for
  that item.
- Judge availability is logged as its own metric (`% ambiguous items
  scored by judge vs. fallback`), not hidden inside the eval output — this
  is itself a useful signal about real operating conditions, not a gap to
  paper over.

No paid LLM tier is assumed anywhere in this design.

### Embedding dimension consistency

Layer 3 must call through the same embedding path Sentinel-L7 uses, not
maintain its own. Sentinel-L7 is mid-migration from Gemini embeddings to
`nomic-embed-text:v1.5` (768-dim, per Sentinel-L7's
`docs/adr/0025-ollama-local-embedding-provider.md`). If `arbiter-l8`
embeds independently against a different model or dimension, Upstash
Vector will reject writes/queries on dimension mismatch the moment the two
diverge. `arbiter-l8` should call Sentinel-L7's embedding driver (or read
its config) rather than hardcoding a model name.

---

## Alternatives Considered

**LLM-as-judge as the default/required layer.** Rejected. Both available
LLM sources (partner's remote Ollama, Flash free-tier credits) are
unreliable by construction — neither is a service with an uptime
guarantee. Making the judge required would make the entire online-eval
path fail closed whenever either dependency is down. Deterministic and
infrastructure-reuse layers (heuristics, cross-provider disagreement,
embedding consistency) are ordered first specifically because they have no
external dependency at all.

**Judge model trusted without validation.** Rejected implicitly by design
— before the Ollama judge is used to score unlabeled traffic, its verdicts
should be validated against the labeled `TransactionSeeder` set first
(same harness, offline path, per ADR 0001). A judge that hasn't been
evaluated against ground truth isn't yet trustworthy to evaluate anything
else.

> **Validated 2026-07-04** (Phase 3 step 8): live 25-example sample against
> the real Ollama judge and a real Sentinel-L7 server, scored against the
> `sentinel:export-ground-truth` fixture — 92% binary agreement (threat vs.
> not), matching Sentinel-L7's own accuracy on the same sample. Full
> results and methodology in
> `docs/journal/arbiter-l8-2026-07-04T1720-ground-truth-export-and-judge-validation.md`.
> A prompt-following gap was found (occasional non-taxonomy verdict tokens)
> and is tracked there as a follow-up, not a blocker to this gate.

**Escalate on flag alone, without dependency gating.** Rejected implicitly
by the implementation — a strict "flagged → always run layers 2–4" design
would raise a runtime error any time a caller invoked the harness without,
say, a configured judge. Gating on both flag and supplied dependency lets
partial configurations (e.g. offline test runs with no judge circuit
breaker wired up) exercise the pipeline without special-casing that
absence at every call site.

---

## Consequences

**Positive:**
- Online eval quality degrades gracefully rather than failing outright
  when a layer's dependency is unavailable, at the cost of coarser signal
  on the ambiguous tail.
- Cost stays bounded: expensive layers only run on the subset of traffic
  that cheaper layers couldn't resolve.
- Escalation logic is now independently citable and discoverable, separate
  from the standalone-module packaging decision in ADR 0001.

**Negative / Trade-offs:**
- A misconfigured caller (missing dependency) degrades silently to a
  weaker check rather than erroring — correct for the intended graceful-
  degradation behavior, but means a caller who *meant* to wire up all four
  layers and forgot one gets no explicit signal beyond the trace showing
  fewer child spans than expected.
- Defers the same open question ADR 0001 flags: ground truth for
  Synapse-L4's Axiom extraction specifically is not yet defined, so this
  pipeline's validation to date (92% agreement) covers Sentinel-L7's
  threat detection only.

---

## Relation to ADR 0001

ADR 0001 retains the standalone-module decision, the `EvalPrediction`
contract, and the offline/online split at a high level. This ADR is the
detailed record for the online path specifically. ADR 0001's "Offline /
online split" section should be trimmed to a short summary pointing here,
rather than carrying both copies of this content.