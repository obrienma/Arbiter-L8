# Prompt: Eval-Quality Judge

**Used by:** `sentinel_eval.online.judge` (`_call_ollama`, `_call_gemini_flash`, via `JudgeCircuitBreaker.judge()`)
**Model:** `qwen3.5:9b-q4_K_M` (Ollama, primary — same model/host convention as Sentinel-L7's `OllamaDriver`), `gemini-2.0-flash` (Gemini Flash, fallback)
**Version:** 1
**Template file:** `prompts/judge.txt`

### Changelog
- **v1** (2026-07-04): Initial version, introduced for Phase 3 step 5 (layer 4 — LLM-as-judge for the online/unlabeled path).

---

## Purpose

Given a prediction that layers 1-3 (heuristics, cross-provider disagreement,
embedding consistency) have already flagged as ambiguous, produce a second
opinion: a corrected label plus one-sentence reasoning. Distinct from
Sentinel-L7's `prompts/synapse-l4-judge.md`, which scores `anomaly_score` for
production routing of Axioms — different purpose, different consumer, see
`docs/adr/0001-standalone-module.md`.

---

## Template

See [`judge.txt`](judge.txt) — the live template loaded by both
`_call_ollama` and `_call_gemini_flash` at runtime (loaded via file read +
literal placeholder substitution, mirroring Sentinel-L7's
`AbstractComplianceDriver`'s `strtr()`/`file_get_contents()` convention rather
than `str.format()`, since the JSON example in the template body contains
literal `{`/`}` that `str.format()` would otherwise try to interpolate).

---

## Variables

| Variable | Source |
|---|---|
| `{prediction_id}` | `EvalPrediction.id` |
| `{predicted_label}` | `EvalPrediction.label` |
| `{confidence}` | `EvalPrediction.confidence` |
| `{raw_output}` | `EvalPrediction.raw_output`, JSON-serialized |
| `{context}` | Caller-supplied evidence for why layers 1-3 flagged this prediction |

## Notes

- Both callers force strict-JSON output at the API level (Ollama's
  `"format": "json"`, Gemini's `generationConfig.responseMimeType:
  "application/json"`) rather than relying on prompt instructions alone to
  produce parseable output — same convention as Sentinel-L7's
  `OllamaDriver`/`GeminiDriver`.
- Ollama call sends `"think": false` — `qwen3.5` is a hybrid reasoning model
  that otherwise emits a verbose `message.thinking` trace before answering
  (~20x slower for no gain here), the same gotcha already documented in
  Sentinel-L7's `OllamaDriver`.
- Only the `verdict` field is consumed by `JudgeCircuitBreaker` today
  (`_call_ollama`/`_call_gemini_flash` return `str`, matching the
  pre-existing scaffold's type signature) — `reasoning` is required in the
  schema (so the model has to justify its answer, which measurably improves
  small-model verdict quality) but not yet surfaced through `JudgeVerdict`.
