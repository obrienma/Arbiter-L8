# sentinel-eval

A standalone AI evaluation framework for scoring the outputs of services in
the Rhizome-Praetor suite — currently **Sentinel-L7** (`ComplianceDriver`
compliance/AML verdicts) and **Synapse-L4** (`Axiom` telemetry validation).
It is not embedded in either service: the harness knows nothing about
Sentinel or Synapse specifically, only about the normalized prediction
contract described below. See
[`docs/adr/0001-standalone-module.md`](docs/adr/0001-standalone-module.md)
for the full design rationale.

## The prediction contract

Every system-under-test is a callable that takes a raw input dict and
returns an `EvalPrediction`:

```python
class EvalPrediction(BaseModel):
    id: str                        # source_id / correlation token
    raw_output: dict[str, Any]     # untouched domain payload, for debugging
    label: str                     # normalized outcome — e.g. Sentinel's
                                    # risk_level or Synapse's status
    confidence: float
    metadata: dict[str, Any] = {}
```

`label` is a plain `str`, not a shared enum. Sentinel's `risk_level`
(`low|medium|high|critical|unknown`) and Synapse's `status`
(`nominal|degraded|critical`) are different taxonomies — forcing them into
one enum would leak one service's vocabulary into the harness. Each
system-under-test wrapper maps its own domain output into `label`; the
harness only ever compares `label` against ground truth for whichever
system it's currently scoring.

## Offline vs. online evaluation

### Offline (ground truth) — `sentinel_eval.harness.run_eval`

Runs a labeled dataset through a system-under-test and scores its
predictions against known-correct labels: precision/recall/F1 per label,
plus overall accuracy. **No LLM dependency anywhere in this path** — it
works even if every external model/service is down.

```python
from sentinel_eval.harness import run_eval
from sentinel_eval.models import EvalDataset

dataset = EvalDataset.model_validate({
    "examples": [
        {"input": {...}, "expected_label": "high"},
        ...
    ]
})

report = run_eval(my_system_under_test, dataset)
print(report.accuracy, report.per_label)
```

Two fixtures ship under `tests/fixtures/`: `compliance_dataset.json`
(hand-written, 15 examples) and `sentinel_l7_ground_truth.json` (200
examples, generated from Sentinel-L7's real pre-AI simulation profiles via
`php artisan sentinel:export-ground-truth` — see that repo's
`app/Console/Commands/ExportGroundTruth.php`). The latter's `expected_label`
is only ever `'high'`/`'low'` — ground truth pre-AI only knows a binary
threat flag, not a graded `risk_level` — so scoring Sentinel-L7 predictions
against it should collapse `medium`/`critical` into `'high'` the same way
`TransactionProcessorService::gradeAiResult()` does internally
(`is_threat = risk_level != 'low'`), rather than penalizing a correctly-
caught threat just because it landed on a different severity than `'high'`.

### Online (unlabeled, realistic traffic) — `sentinel_eval.online.*`

Production/sampled traffic has no ground truth, so it's scored by a
layered, cost-ordered pipeline instead. Each layer is more expensive (and
more speculative) than the last, and later layers are only meant to run on
what earlier layers flag as ambiguous — not on every item.

1. **`online/heuristics.py`** — rule-based checks (confidence thresholds,
   field-contradiction checks). Free, deterministic, always available.
   **Implemented.**
2. **`online/disagreement.py`** — cross-provider/cross-run disagreement
   (e.g. Sentinel-L7's dual Gemini/OpenRouter `ComplianceDriver`). Reuses
   infrastructure the system-under-test already has. **Implemented and
   live-verified.** `score_disagreement()` calls each named provider with
   the same input and compares labels; a provider call that raises is
   captured in `errors_by_provider` rather than dropped, and `agreed` is
   only `True` when every provider answered with the exact same label —
   an error makes agreement unknowable, not automatically true. Uses
   Sentinel-L7's per-request driver override (Phase 3 step 6):
   `adapters.sentinel_l7.make_sentinel_l7_system_under_test(driver=...)`
   builds one callable per provider, each bypassing the semantic cache so
   the comparison is never contaminated by a different provider's cached
   verdict. Live-verified against a real local Sentinel-L7 server: Ollama
   returned a real verdict; OpenRouter and Gemini both genuinely failed
   (OpenRouter's configured free model was retired upstream — a 404 "No
   endpoints found"; Gemini hit the same free-tier quota exhaustion seen
   validating the judge layer) and both were correctly surfaced in
   `errors_by_provider` rather than silently swallowed or crashing the
   comparison — exercising the error path against real external failures,
   not just mocks.
3. **`online/consistency.py`** — embedding-based consistency against
   Upstash Vector's `transactions` namespace. `make_ollama_embed_fn()`
   calls Sentinel-L7's own local Ollama host/model/task-prefix convention
   exactly (verified against `OllamaEmbeddingDriver::embed()` directly),
   never a hardcoded model — Sentinel-L7's live config has
   `SENTINEL_EMBEDDING_DRIVER=ollama`, 768-dim `nomic-embed-text:v1.5`, and
   embedding independently here would cause Upstash dimension-mismatch
   errors the moment the two diverge. `query_upstash_vector()` mirrors
   `VectorCacheService::searchNamespace()`'s exact request shape.
   **Implemented and live-verified**: a real embed call against the actual
   Ollama host returned a 768-dim vector, and a real Upstash Vector query
   against the live index succeeded (0 matches, confirmed correct via the
   index's own `/info` endpoint — the `transactions` namespace has no
   vectors yet in this dev environment, so an empty result is the right
   answer, not a bug).
4. **`online/judge.py`** — LLM-as-judge, reserved for the ambiguous tail
   flagged by layers 1–3. Best-effort only, behind a circuit breaker: try
   remote Ollama (over Tailscale) → on failure/timeout fall back to Gemini
   Flash free tier → on failure fall back to heuristics-only. Judge
   availability is tracked as its own metric
   (`JudgeMetrics.pct_scored_by_judge`) rather than hidden — a judge that
   silently falls back on every call is itself a signal worth seeing.
   **Implemented and live-verified.** Both calls force strict-JSON output
   at the API level (Ollama's `"format": "json"`, Gemini's
   `generationConfig.responseMimeType`) and load their shared prompt from
   `prompts/judge.txt` (versioned in `prompts/judge.md`, mirroring
   Sentinel-L7's `prompts/*.md`+`*.txt` convention) rather than hardcoding
   the prompt text inline. A real call against the Tailscale Ollama host
   (`qwen3.5:9b-q4_K_M`) returned a genuine verdict in ~12s; a real call to
   Gemini Flash correctly raised `httpx.HTTPStatusError` on a live 429
   (free-tier quota exhausted), confirming the fail-through contract holds
   against a real failure, not just a mocked one.

   This eval judge is distinct from Sentinel-L7's `prompts/synapse-l4-judge.md`,
   which scores `anomaly_score` for production routing — different purpose,
   different consumer. Before this judge is used to score unlabeled
   traffic, its verdicts should be validated against a labeled dataset via
   the offline `run_eval` path first. An early attempt against
   `tests/fixtures/compliance_dataset.json` scored only 6.7% accuracy, but
   inspection showed the judge reasoning correctly and just answering in
   the *wrong taxonomy* — that fixture's `raw_output` is Synapse-shaped
   (`status`/`anomaly_score`) while its `expected_label` is Sentinel's
   `risk_level` vocabulary, a mismatch invisible to `run_eval()` (which
   never inspects `raw_output`, only compares `label`) until something
   reasoned over the raw fields directly. **Validated** as of Step 8 against
   the taxonomy-consistent `sentinel_l7_ground_truth.json` fixture instead
   — see [Benchmark results](#benchmark-results) below.

## Benchmark results

Live-verification runs against real services, not mocks. The Journal column
links to the entry with full methodology (sample composition, seed, raw
per-item output).

| Date | Fixture | System | Sample | Strict accuracy | Binary accuracy | Notes | Journal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-07-04 | `sentinel_l7_ground_truth.json` | Sentinel-L7 (`driver=ollama`, cache bypassed) | 25 live / 200 (all 10 `high` + 15 random `low`, seed 42) | 84% | **92%** | First attempt (no driver override) scored 52% — a real semantic-cache amplification bug, not a model failure; tracked as a Known Issue in sentinel-l7's own README. | [step 8](docs/journal/sentinel-eval-2026-07-04T1720-ground-truth-export-and-judge-validation.md) |
| 2026-07-04 | `sentinel_l7_ground_truth.json` | Judge (`qwen3.5:9b-q4_K_M` via Ollama) | Same 25, called unconditionally (bypassing the heuristic gate) | 80% | **92%** | 2/25 verdicts were non-taxonomy tokens (`"reject"`, `"correct"`) instead of a label — a prompt-following gap, not yet fixed. | [step 8](docs/journal/sentinel-eval-2026-07-04T1720-ground-truth-export-and-judge-validation.md) |
| 2026-07-04 | `compliance_dataset.json` | Judge (`qwen3.5:9b-q4_K_M` via Ollama) | All 15 | 6.7% | — | Fixture defect, not a judge failure: `raw_output` is Synapse-shaped, `expected_label` is Sentinel-shaped — the judge answered correctly in the wrong taxonomy. Superseded by the row above; kept here as a documented false alarm. | [step 5](docs/journal/sentinel-eval-2026-07-04T1512-judge-layer.md) |

**Strict vs. binary**: `sentinel_l7_ground_truth.json`'s `expected_label` is
only ever `'high'`/`'low'` (ground truth pre-AI knows only a boolean threat
flag — see "Offline (ground truth)" above). *Strict* compares the predicted
label string exactly; *binary* collapses `medium`/`high`/`critical` to
`'high'` first (`is_threat = risk_level != 'low'`, matching
`TransactionProcessorService::gradeAiResult()`). Binary is the number that
reflects what this ground truth can actually justify claiming — a
`critical` verdict on a real threat is a correct catch, not a miss, and
strict accuracy alone would misrepresent that as a failure.

## Plugging in a new system-under-test

Two real adapters exist under `src/sentinel_eval/adapters/`:

- **`synapse_l4.py`**: `make_synapse_l4_system_under_test()` POSTs to
  Synapse-L4's `/ingest` and maps its Axiom response into `EvalPrediction`
  (`status` → `label`, `anomaly_score` → `confidence`). Calls the real
  service over HTTP rather than importing its Python modules directly —
  see the module docstring for why (heavy service-specific dependencies,
  a Python-version mismatch, and an import-time config requirement that
  would all violate the standalone-module mandate).
- **`sentinel_l7.py`**: `make_sentinel_l7_system_under_test()` speaks
  MCP-over-HTTP directly to Sentinel-L7's `/mcp` endpoint (`analyze-transaction`
  tool) — a hand-rolled minimal JSON-RPC client for this one tool call,
  not the full `mcp` SDK. `risk_level` → `label`, `confidence` → `confidence`
  (`0.0` when Sentinel-L7's rule-based fallback path ran with no AI model
  involved, since `EvalPrediction.confidence` is non-optional). Required a
  small additive change to Sentinel-L7 itself
  (`TransactionProcessorService::process()` previously collapsed its full
  compliance grading down to a boolean `is_threat` before this tool could
  see it — `risk_level`/`narrative`/`confidence`/`policy_refs` are now
  surfaced too, verified backward-compatible against that repo's full test
  suite). Also takes an optional `driver` parameter (`'gemini'`/`'openrouter'`/
  `'ollama'`) that forces Sentinel-L7's per-request `ComplianceManager`
  override instead of its app-wide default — building one instance per
  provider is how `online.disagreement.score_disagreement` gets independent,
  cache-bypassing verdicts for the same transaction.

To wire up a new one:

1. Write a callable `(input: dict) -> EvalPrediction` that calls the target
   service and maps its domain output into the prediction contract above.
   Put the untouched domain payload in `raw_output` and a normalized
   outcome string in `label`.
2. For offline scoring: build an `EvalDataset` (see
   `tests/fixtures/compliance_dataset.json` for the shape) and call
   `run_eval(your_callable, dataset)`.
3. For online scoring: call `online.pipeline.evaluate_item(prediction, ...)`.
   It always runs heuristics first, then only escalates to
   disagreement/consistency/judge for predictions heuristics flags — and
   only for the layers whose dependency (`providers`, `embed_fn`, `judge`)
   you actually pass in. A layer you don't wire up is skipped, not an
   error.

## Observability

Every layer function and `evaluate_item` are wrapped in `@traced_layer(...)`
(`sentinel_eval.observability.decorators`), which is both a decorator and a
context manager — the same helper wraps `run_heuristics` as a whole
function and wraps individual attempts inside `JudgeCircuitBreaker.judge()`
as inline blocks (`ollama_attempt`, `flash_attempt`, `heuristics_fallback`),
so a Tempo trace for one scored item shows the full circuit-breaker path —
e.g. an Ollama timeout followed by a Gemini Flash success — not just the
final outcome.

Traces and metrics both export via OTLP/HTTP to
`${OTEL_EXPORTER_OTLP_ENDPOINT}/v1/traces` and `/v1/metrics`
(`OTEL_EXPORTER_OTLP_ENDPOINT` defaults to `http://localhost:4318`,
`OTEL_SERVICE_NAME` defaults to `sentinel-eval`) — the same Collector
endpoint EventHorizon and Synapse-L4 export to, so all three show up
distinctly in Grafana/Tempo. Metrics:

- `sentinel_eval.judge.outcome` (counter, labeled `source=ollama|flash|
  fallback`) — the "% scored by judge vs fallback" signal from
  `docs/adr/0001-standalone-module.md`.
- `sentinel_eval.layer.latency` (histogram, labeled `layer=...`) — per-layer
  latency for the four online layers.
- `sentinel_eval.harness.metric` (gauge, labeled `metric=precision|recall|
  f1|accuracy`, `label=<label>|overall`) — emitted once per `run_eval()`
  call, so a prompt/model change shows up as a step change in Grafana.

The SDK is initialized as an import-time side effect
(`sentinel_eval/observability/tracing.py`, `metrics.py`) rather than behind
a lazily-invoked init function — see that module's docstring for why:
Synapse-L4's current pattern (configuring OTel inside a FastAPI `lifespan`
handler, after the app and its routes are already constructed) is the
suspected cause of its trace-fragmentation bug, and this repo deliberately
avoids reproducing that ordering.

## Configuration

`src/sentinel_eval/config.py` holds env-var-with-default settings for
calling real systems-under-test (same style as `observability/_env.py`):
`SYNAPSE_L4_BASE_URL`, `SENTINEL_L7_MCP_URL`, `OLLAMA_JUDGE_HOST`/
`OLLAMA_JUDGE_MODEL` (remote, over Tailscale — LLM-as-judge only),
`OLLAMA_URL`/`OLLAMA_EMBEDDING_MODEL` (same env var names as Sentinel-L7's
own embedding config — in this environment both `OLLAMA_JUDGE_HOST` and
`OLLAMA_URL` happen to point at the same Tailscale host, since one Ollama
instance serves both the judge and embedding models here, but they're
independent settings), `GEMINI_API_KEY`/`GEMINI_FLASH_URL` (same env var
names Sentinel-L7 uses, so one value covers both services), and
`UPSTASH_VECTOR_REST_URL`/`UPSTASH_VECTOR_REST_TOKEN`/
`UPSTASH_VECTOR_THRESHOLD` (same env var names and default threshold as
Sentinel-L7's `config/services.php` — no default URL/token, since those
are account-specific secrets).

## CLI

`sentinel-eval` (a `[project.scripts]` entry point, `sentinel_eval.cli:main`)
runs the offline harness from the shell against a real adapter — no code
required for a one-off scoring run:

```bash
uv run sentinel-eval \
  --system sentinel-l7 \
  --fixture tests/fixtures/sentinel_l7_ground_truth.json \
  --driver ollama --binary --limit 25
```

`--system` selects `sentinel-l7` or `synapse-l4`; `--fixture` must be an
`EvalDataset` JSON whose `input` shape matches that system's adapter
contract (`sentinel_l7_ground_truth.json` for Sentinel-L7 —
`compliance_dataset.json` is *not* adapter-compatible, see its note under
"Benchmark results" above). `--url` overrides the configured base/MCP URL;
`--driver` (Sentinel-L7 only) forces the per-request `ComplianceManager`
override; `--binary` (Sentinel-L7 only) collapses a predicted label to
`'high'` unless it's exactly `'low'`, matching
`TransactionProcessorService::gradeAiResult()`; `--limit` scores only the
first N examples; `--json` prints the `EvalReport` as JSON instead of a
text table. A connection failure prints a one-line error to stderr and
exits `1` rather than a raw traceback.

There is deliberately no CLI surface for the online path
(`online.pipeline.evaluate_item`) — it's meant to be wired into a caller's
own sampling/production loop (which providers/embed_fn/judge to pass in is
a per-deployment decision), not run as a one-shot command the way a
labeled-fixture score is.

**Live-verified**: run against a temporarily-started local Sentinel-L7
server with `--driver ollama` (bypassing the semantic cache) — a single
live item scored correctly (`accuracy: 1/1 (100.0%)`). A `--limit 5` batch
surfaced a real timeout on a slower Ollama response (a single
driver-override call has been observed to take 8–9s against the real
model, close to the adapter's default 10s per-request timeout) — the CLI's
`httpx.ConnectError`/`TimeoutException` handling caught it and exited `1`
with a friendly message rather than crashing, exercising that path against
a genuine failure, not a mock.

## Development

```bash
uv sync                 # install dependencies
uv run pytest           # run the test suite
```

Running the test suite without a local OTel Collector at
`localhost:4318` is expected to print harmless "connection refused" retry
warnings on process exit — the same "additive observability" posture
Synapse-L4 already uses (instrumentation degrades gracefully; it never
affects correctness). No timeout override is configured, matching
EventHorizon's and Synapse-L4's exporters, both of which also rely on SDK
defaults.

## Manual verification (live services)

Everything below was actually run against real services to confirm it
works, not just asserted — every command here was re-run while writing
this section. Use it as the exhaustive step-by-step checklist for
confirming a fresh checkout actually works end to end, not just that
`pytest` is green.

### 0. Setup

```bash
uv sync
```

Env vars used below (all have dev-environment defaults in
`src/sentinel_eval/config.py` — see [Configuration](#configuration)):
`SENTINEL_L7_MCP_URL`, `SYNAPSE_L4_BASE_URL`, `OLLAMA_URL`,
`OLLAMA_EMBEDDING_MODEL`, `OLLAMA_JUDGE_HOST`, `OLLAMA_JUDGE_MODEL`,
`GEMINI_API_KEY`, `UPSTASH_VECTOR_REST_URL`, `UPSTASH_VECTOR_REST_TOKEN`.
None are required just to run the automated test suite (step 1) — they
only matter for the live steps below.

### 1. Automated suite

```bash
uv run pytest -v
```

Expect all tests passing (70 as of the CLI step). The "connection refused"
OTel warnings on exit are expected without a local Collector at
`:4318` — see the note above.

### 2. CLI against a real Sentinel-L7 server

Requires a checked-out, configured Sentinel-L7 (`~/dev/sentinel-l7` in this
environment — see that repo's own README/CLAUDE.md for its env setup:
`GEMINI_API_KEY`, `OLLAMA_URL`, DB migrations, etc.).

```bash
# terminal 1 — from the sentinel-l7 checkout
cd ~/dev/sentinel-l7
php artisan serve --port=8080
```

```bash
# terminal 2 — health check before trusting anything the CLI reports
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/mcp \
  -X POST -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"analyze-transaction","arguments":{"amount":10,"currency":"USD","merchant":"Test"}}}'
# expect: 200
```

```bash
# terminal 2 — from this repo, scoring one real example with the
# driver override (bypasses the semantic cache so it's a fresh verdict)
cd ~/dev/sentinel-eval
SENTINEL_L7_MCP_URL=http://127.0.0.1:8080/mcp uv run sentinel-eval \
  --system sentinel-l7 \
  --fixture tests/fixtures/sentinel_l7_ground_truth.json \
  --driver ollama --binary --limit 1 --json
```

Expect a JSON `EvalReport` with `"accuracy": 1.0` and one prediction whose
`raw_output.source` is `"driver_override"`. **Observed real latency: a
single driver-override call has taken anywhere from ~4.7s to timing out
past the adapter's default 10s** — if you see
`error: could not reach sentinel-l7 — timed out`, that's real Ollama
latency variance, not a CLI bug; just re-run.

Confirm the plain-text report path too, and try a larger sample:

```bash
uv run sentinel-eval --system sentinel-l7 \
  --fixture tests/fixtures/sentinel_l7_ground_truth.json \
  --driver ollama --limit 5
```

Note: omitting `--driver` lets Sentinel-L7 use its app-wide default and its
semantic cache — repeated runs against a narrow-profile merchant can then
return `cache_hit` for every item (a real amplification effect documented
in [Benchmark results](#benchmark-results), not a CLI bug). Use `--driver`
whenever you want a guaranteed fresh, cache-bypassing verdict.

Confirm the error path by stopping the server (`Ctrl+C` in terminal 1)
and re-running the same command:

```bash
uv run sentinel-eval --system sentinel-l7 \
  --fixture tests/fixtures/sentinel_l7_ground_truth.json --limit 1
echo "exit code: $?"
```

Expect stdout empty, stderr
`error: could not reach sentinel-l7 — [Errno 111] Connection refused`,
and exit code `1`.

Stop the server for good afterward (`Ctrl+C`, or
`pkill -f "php artisan serve --port=8080"`) — it's a temporary process for
this verification only, not a persistent service.

### 3. CLI against a real Synapse-L4 server

Synapse-L4 needs a reachable Redis (`SENTINEL_REDIS_URL`) and an LLM key
(`OPENAI_API_KEY` or `ANTHROPIC_API_KEY`) before it will even boot — see
`~/dev/synapse-l4/.env.example`.

```bash
# terminal 1 — from the synapse-l4 checkout
cd ~/dev/synapse-l4
uv run fastapi dev main.py   # serves on :8000
```

```bash
# terminal 2 — health check
curl -s -X POST http://127.0.0.1:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"source_id": "manual-check-1", "payload": {"metric": "test"}}'
```

No fixture shaped for Synapse-L4's real `{source_id, payload}` contract
ships in `tests/fixtures/` yet (`compliance_dataset.json`'s `input` is
flattened, not that envelope) — write a one-off fixture to exercise this
path:

```bash
cat > /tmp/synapse_smoke.json <<'EOF'
{"examples": [{"input": {"source_id": "manual-1", "payload": {"metric": "test"}}, "expected_label": "nominal"}]}
EOF

# terminal 2 — from this repo
cd ~/dev/sentinel-eval
uv run sentinel-eval --system synapse-l4 \
  --fixture /tmp/synapse_smoke.json --limit 1 --json
```

**Not yet live-verified in this environment** — Synapse-L4 wasn't running
locally when its adapter (step 2 of the plan) was originally built or when
this section was written; only the respx-mocked test suite has exercised
this path so far. Treat this subsection as the script to run the first
time a live Synapse-L4 instance is available, not a result already
confirmed the way step 2 is.

### 4. Online layers (no CLI surface — by design, see [CLI](#cli))

These have no one-shot command; wiring them is a per-deployment decision.
Run each snippet with `uv run python -c "..."` from this repo so the venv
resolves correctly.

**Embedding consistency** — needs `OLLAMA_URL` pointed at a host that
actually has the embedding model pulled. In this dev environment the
*default* `OLLAMA_URL` (`localhost:11434`) has no models pulled at all, and
even the Tailscale host's model is tagged `nomic-embed-text:v1.5`, not the
untagged `nomic-embed-text` `OLLAMA_EMBEDDING_MODEL` defaults to (a
documented drift — see the plan's "Corrections discovered mid-plan"
notes) — both must be overridden together or you'll hit a real `404 model
not found`:

```bash
OLLAMA_URL=http://100.82.223.70:11434 \
OLLAMA_EMBEDDING_MODEL=nomic-embed-text:v1.5 \
uv run python -c "
from sentinel_eval.online.consistency import make_ollama_embed_fn, query_upstash_vector
embed = make_ollama_embed_fn()
vector = embed('a \$500 purchase at a grocery store')
print('embedding dim:', len(vector))            # expect 768
print(query_upstash_vector(vector))              # UpstashVectorError if creds unset — expected
"
```

**Disagreement** — needs a running local Sentinel-L7 (step 2 above):

```bash
uv run python -c "
from sentinel_eval.adapters.sentinel_l7 import make_sentinel_l7_system_under_test
from sentinel_eval.online.disagreement import score_disagreement
providers = {
    d: make_sentinel_l7_system_under_test(mcp_url='http://127.0.0.1:8080/mcp', driver=d)
    for d in ('ollama',)   # add 'gemini'/'openrouter' if those keys/quota are live
}
result = score_disagreement({'amount': 500, 'currency': 'USD', 'merchant': 'Test'}, providers)
print(result.agreed, result.labels_by_provider, result.errors_by_provider)
"
```

Expect `True {'ollama': 'low'} {}` for a low-risk merchant. Adding
`'gemini'`/`'openrouter'` to `providers` is expected to genuinely fail in
this dev environment (retired free model / exhausted free-tier quota — see
[Benchmark results](#benchmark-results)); a populated `errors_by_provider`
for those keys is the correct, verified outcome, not a bug.

**Judge** — needs `OLLAMA_JUDGE_HOST` reachable (defaults to the Tailscale
host already used above):

```bash
uv run python -c "
from sentinel_eval.models import EvalPrediction
from sentinel_eval.online.judge import JudgeCircuitBreaker
prediction = EvalPrediction(id='t1', raw_output={'risk_level': 'high'}, label='high', confidence=0.4)
verdict = JudgeCircuitBreaker().judge(prediction, context='low confidence on a high verdict')
print(verdict.source, verdict.verdict_label)
"
```

Expect `JudgeSource.OLLAMA high` (or a similar taxonomy-consistent label)
on success; a slow/unreachable Ollama should fall through to Gemini Flash
and then heuristics-only per the circuit-breaker contract described above.
