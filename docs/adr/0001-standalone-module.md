# ADR 0001 — Build arbiter-l8 as a Standalone Module, Not Embedded in Sentinel-L7

**Status:** Accepted
**Date:** 2026-07-03

---

## Context

Sentinel-L7's `TransactionProcessorService` and Synapse-L4's
`AxiomProcessorService` both produce AI-justified outputs (semantic-cache
verdicts, Gemini Flash + RAG extractions), but neither system has a way to
systematically measure whether those outputs are *correct* — only whether
they're *structurally valid* (Axiom contract enforcement via
Pydantic/Instructor is validation, not quality scoring).

Two systems now produce this class of output. That's the concrete
downstream trigger — per this suite's "wait until it hurts" ADR
philosophy — for treating evaluation as its own layer rather than
deferring the abstraction further.

Two paths were considered:

1. Embed eval logic inside `sentinel-l7`, calling `ComplianceDriver`
   directly.
2. Build `arbiter-l8` as a separate module/repo with a
   system-under-test interface, scoring Sentinel-L7 and Synapse-L4 (and
   future services) without being deployed alongside either.

---

## Decision

Build `arbiter-l8` as a standalone module with a defined interface:

```python
def run_eval(system_under_test: Callable, dataset: EvalDataset) -> EvalReport:
    ...
```

`system_under_test` wraps whatever service is being scored (initially
Sentinel-L7's `ComplianceDriver`, later Synapse-L4's Axiom pipeline) behind
a common call signature, so the harness itself has no Sentinel-specific or
Synapse-specific code in it.

### Prediction contract

`ComplianceDriver::analyze()` and Synapse-L4's `Axiom`/`AxiomDraft` return
different domain shapes (compliance verdict vs. telemetry extraction), so
the callable can't return an unconstrained structure — the harness needs a
normalized prediction envelope, not raw domain output, to score
generically:

```python
class EvalPrediction(BaseModel):
    id: str                        # source_id / correlation token
    raw_output: dict[str, Any]     # untouched domain payload, for debugging
    label: str                     # normalized outcome, e.g. Sentinel's
                                    # risk_level (low|medium|high|critical|
                                    # unknown) or Synapse's status
                                    # (nominal|degraded|critical)
    confidence: float
    metadata: dict[str, Any] = {}  # latency, provider used, token usage
```

`label` is intentionally a plain string, not a shared Literal enum —
Sentinel's `risk_level` and Synapse's `status` are different taxonomies
with different values, and forcing them into one enum would leak one
service's domain vocabulary into the harness. Each system-under-test
wrapper is responsible for mapping its own domain output into `label`; the
harness only ever compares `label` against ground truth for whichever
system it's currently scoring.

### Offline / online split

Reframes the existing Option A vs. B ground-truth decision as the split
itself, rather than a single flag serving two purposes:

- **Offline (Option A — ground truth):** `TransactionSeeder`-generated
  labeled corpus. Run through the system-under-test, score against
  `is_threat` directly. Precision/recall/F1 over time as prompts/models
  change. No judge model required — this path is unaffected by LLM
  availability entirely.
- **Online (Option B — realistic, unlabeled):** sampled production
  traffic, no ground truth available. Scored via a layered, cost-ordered
  escalation pipeline (heuristics → cross-provider disagreement →
  embedding consistency → LLM-as-judge), gated so each layer beyond
  heuristics only runs when the item was flagged and the caller supplied
  that layer's dependency. Full design, judge-availability handling, and
  rejected alternatives for this pipeline are in
  `docs/adr/0002-online-escalation-pipeline.md`.

  Note: the eval judge in that pipeline is distinct from the stubbed
  `synapse-l4-judge.md` prompt already in Sentinel-L7's `prompts/`
  directory, which scores `anomaly_score` for routing Axioms to AI audit
  in production — different purpose, different consumer, not yet
  implemented. Worth keeping these two "judge" concepts named distinctly
  in docs so they don't get conflated.

---

## Alternatives Considered

**Embed in Sentinel-L7.** Rejected. Would couple eval-run failures to
Sentinel's deploy/dependency surface, and would hard-code the eval
interface to `ComplianceDriver` specifically — precluding Synapse-L4 (or
any future service) from being scored without duplicating the harness.
Also weaker as a standalone portfolio artifact: an interviewer evaluating
"did you build an eval framework" shouldn't have to read a compliance
engine to find it.

Rejected alternatives for the online escalation pipeline specifically
(judge-as-default, judge-without-validation, escalation without dependency
gating) are covered in `docs/adr/0002-online-escalation-pipeline.md`,
along with the 2026-07-04 judge validation result.

---

## Consequences

**Positive:**
- `arbiter-l8` becomes a citable, standalone artifact independent of
  Sentinel-L7's repo.
- Offline eval runs are fully decoupled from LLM availability — the
  harness's core signal (precision/recall on labeled data) works even if
  both Ollama and Flash are down.
- Online eval quality degrades gracefully rather than failing outright
  when the judge is unavailable, at the cost of coarser signal on the
  ambiguous tail during outages.

**Negative / Trade-offs:**
- Adds a new repo/module to maintain and version against Sentinel-L7 and
  Synapse-L4's evolving interfaces — acceptable given both already expose
  stable-enough contracts (`ComplianceDriver`, Axiom schema).
- Defers (not solves) the harder question of *what ground truth looks
  like for Synapse-L4's Axiom extraction* specifically, since
  `TransactionSeeder` currently only labels Sentinel-side threat
  detection. Flagged as follow-up scope, not blocking this ADR.