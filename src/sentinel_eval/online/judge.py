"""Layer 4: LLM-as-judge — best-effort, behind a circuit breaker.

Distinct from Sentinel-L7's existing `prompts/synapse-l4-judge.md`, which
scores `anomaly_score` for production routing of Axioms to AI audit. This
judge scores *eval quality* of a prediction that layers 1-3 have already
flagged as ambiguous — different purpose, different consumer. Do not
conflate the two.

Not required for the online path to function: on failure/timeout the chain
falls back Ollama -> Gemini Flash free tier -> heuristics-only, and judge
availability itself is tracked as a metric rather than hidden. Before this
judge is trusted to score unlabeled traffic, its verdicts should first be
validated against the labeled fixture dataset via the offline harness
(run_eval) — see docs/adr/0001-standalone-module.md.

This layer is reserved for the ambiguous tail flagged by layers 1-3; it is
not intended to run on every prediction.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import httpx

from opentelemetry import trace

from sentinel_eval import config
from sentinel_eval.models import EvalPrediction
from sentinel_eval.observability import judge_outcome_counter, traced_layer

logger = logging.getLogger(__name__)

# repo_root/prompts/judge.txt — see prompts/judge.md for the versioned
# convention this mirrors (Sentinel-L7's prompts/*.md + *.txt pairing).
_PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "judge.txt"


def _render_prompt(prediction: EvalPrediction, context: str) -> str:
    """Literal placeholder substitution, not str.format() — the template's
    JSON response example contains literal `{`/`}` that str.format() would
    otherwise try to interpolate. Mirrors Sentinel-L7's
    AbstractComplianceDriver strtr()/file_get_contents() convention.
    """
    template = _PROMPT_PATH.read_text()
    replacements = {
        "{prediction_id}": prediction.id,
        "{predicted_label}": prediction.label,
        "{confidence}": str(prediction.confidence),
        "{raw_output}": json.dumps(prediction.raw_output),
        "{context}": context,
    }
    for placeholder, value in replacements.items():
        template = template.replace(placeholder, value)
    return template


def _parse_verdict(content: str) -> str:
    return json.loads(content)["verdict"]


class JudgeSource(str, Enum):
    OLLAMA = "ollama"
    GEMINI_FLASH = "gemini_flash"
    HEURISTICS_FALLBACK = "heuristics_fallback"


@dataclass
class JudgeVerdict:
    prediction_id: str
    source: JudgeSource
    # None when the chain fell all the way back to heuristics-only and no
    # judge model produced an opinion.
    verdict_label: str | None = None
    reasoning: str | None = None


@dataclass
class JudgeMetrics:
    """Availability tracking — logged as a first-class metric, not hidden.

    `% ambiguous transactions scored by judge vs fallback` per the ADR.
    """

    total_judged: int = 0
    scored_by_ollama: int = 0
    scored_by_gemini_flash: int = 0
    scored_by_heuristics_fallback: int = 0

    def record(self, source: JudgeSource) -> None:
        self.total_judged += 1
        if source is JudgeSource.OLLAMA:
            self.scored_by_ollama += 1
        elif source is JudgeSource.GEMINI_FLASH:
            self.scored_by_gemini_flash += 1
        else:
            self.scored_by_heuristics_fallback += 1
        judge_outcome_counter.add(1, {"source": source.value})

    @property
    def pct_scored_by_judge(self) -> float:
        if self.total_judged == 0:
            return 0.0
        judged = self.scored_by_ollama + self.scored_by_gemini_flash
        return judged / self.total_judged


def _call_ollama(prediction: EvalPrediction, context: str) -> str:
    """Call the remote Ollama judge over Tailscale (partner-owned host).

    Raises (httpx.HTTPStatusError, httpx.TimeoutException,
    httpx.ConnectError, json.JSONDecodeError, KeyError) on any failure so
    the circuit breaker falls through to the next source — never returns a
    sentinel value.
    """
    prompt = _render_prompt(prediction, context)
    response = httpx.post(
        f"{config.ollama_judge_host()}/api/chat",
        json={
            "model": config.ollama_judge_model(),
            "messages": [{"role": "user", "content": prompt}],
            "format": "json",
            "stream": False,
            # qwen3.5 is a hybrid reasoning model; without this it emits a
            # verbose message.thinking trace before answering, ~20x slower
            # for no gain here — same gotcha as Sentinel-L7's OllamaDriver.
            "think": False,
        },
        timeout=30.0,
    )
    response.raise_for_status()
    return _parse_verdict(response.json()["message"]["content"])


def _call_gemini_flash(prediction: EvalPrediction, context: str) -> str:
    """Call Gemini Flash free tier as the secondary fallback.

    Same contract as _call_ollama: raise on failure/timeout, don't swallow.
    """
    api_key = config.gemini_api_key()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    prompt = _render_prompt(prediction, context)
    response = httpx.post(
        f"{config.gemini_flash_url()}?key={api_key}",
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        },
        timeout=15.0,
    )
    response.raise_for_status()
    content = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    return _parse_verdict(content)


@dataclass
class JudgeCircuitBreaker:
    """Ollama -> Gemini Flash -> heuristics-only, with availability tracked."""

    metrics: JudgeMetrics = field(default_factory=JudgeMetrics)

    @traced_layer("judge_call")
    def judge(self, prediction: EvalPrediction, context: str) -> JudgeVerdict:
        """Attempt to get a judge verdict for an ambiguous prediction.

        `context` is caller-supplied evidence for why this prediction was
        flagged (e.g. the heuristic flags / disagreement / consistency
        results from layers 1-3) — TODO: define once those layers exist.

        Each attempt in the fallback chain gets its own nested span
        (ollama_attempt / flash_attempt / heuristics_fallback) so a trace
        shows the full circuit-breaker path — e.g. an Ollama timeout
        followed by a Gemini Flash success — not just the final outcome.
        """
        trace.get_current_span().set_attribute("prediction_id", prediction.id)

        # NotImplementedError is re-raised rather than treated as a
        # fallback trigger: until _call_ollama/_call_gemini_flash are wired
        # up, calling judge() should fail loudly, not silently report every
        # verdict as heuristics_fallback.
        try:
            with traced_layer("ollama_attempt"):
                label = _call_ollama(prediction, context)
            self.metrics.record(JudgeSource.OLLAMA)
            return JudgeVerdict(
                prediction_id=prediction.id,
                source=JudgeSource.OLLAMA,
                verdict_label=label,
            )
        except NotImplementedError:
            raise
        except Exception:
            logger.warning(
                "ollama judge unavailable for prediction %s, falling back to gemini flash",
                prediction.id,
            )

        try:
            with traced_layer("flash_attempt"):
                label = _call_gemini_flash(prediction, context)
            self.metrics.record(JudgeSource.GEMINI_FLASH)
            return JudgeVerdict(
                prediction_id=prediction.id,
                source=JudgeSource.GEMINI_FLASH,
                verdict_label=label,
            )
        except NotImplementedError:
            raise
        except Exception:
            logger.warning(
                "gemini flash judge unavailable for prediction %s, falling back to heuristics-only",
                prediction.id,
            )

        with traced_layer("heuristics_fallback"):
            self.metrics.record(JudgeSource.HEURISTICS_FALLBACK)

        return JudgeVerdict(
            prediction_id=prediction.id,
            source=JudgeSource.HEURISTICS_FALLBACK,
            verdict_label=None,
            reasoning="judge chain exhausted; no LLM opinion available",
        )
