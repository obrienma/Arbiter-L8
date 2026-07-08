"""evaluate_item — orchestrates the online layers for a single prediction.

Layer 1 (heuristics) always runs. Layers 2-4 only run when the item was
flagged by an earlier layer AND the caller supplied the dependency that
layer needs (a provider map, an embedding function, a judge circuit
breaker) — a layer whose dependency wasn't supplied is skipped, not an
error, matching the cost-ordered, escalate-only-the-ambiguous-tail design
in docs/adr/0001-standalone-module.md. This also means only the layers
actually invoked get a child span under evaluate_item.
"""

from __future__ import annotations

from dataclasses import dataclass

from opentelemetry import trace

from arbiter_l8.models import EvalPrediction
from arbiter_l8.observability import traced_layer
from arbiter_l8.online.consistency import ConsistencyResult, EmbeddingFn, score_consistency
from arbiter_l8.online.disagreement import DisagreementResult, ProviderCall, score_disagreement
from arbiter_l8.online.heuristics import HeuristicResult, run_heuristics
from arbiter_l8.online.judge import JudgeCircuitBreaker, JudgeVerdict


@dataclass
class OnlineScoringResult:
    prediction_id: str
    heuristic_result: HeuristicResult
    disagreement_result: DisagreementResult | None = None
    consistency_result: ConsistencyResult | None = None
    judge_verdict: JudgeVerdict | None = None


@traced_layer("evaluate_item")
def evaluate_item(
    prediction: EvalPrediction,
    *,
    providers: dict[str, ProviderCall] | None = None,
    embed_fn: EmbeddingFn | None = None,
    consistency_text: str | None = None,
    judge: JudgeCircuitBreaker | None = None,
) -> OnlineScoringResult:
    trace.get_current_span().set_attribute("prediction_id", prediction.id)

    heuristic_result = run_heuristics(prediction)

    disagreement_result: DisagreementResult | None = None
    consistency_result: ConsistencyResult | None = None
    judge_verdict: JudgeVerdict | None = None

    if heuristic_result.flagged:
        if providers:
            disagreement_result = score_disagreement(prediction.raw_output, providers)
        if embed_fn is not None and consistency_text is not None:
            consistency_result = score_consistency(prediction, consistency_text, embed_fn)
        if judge is not None:
            context = "; ".join(flag.reason for flag in heuristic_result.flags)
            judge_verdict = judge.judge(prediction, context)

    return OnlineScoringResult(
        prediction_id=prediction.id,
        heuristic_result=heuristic_result,
        disagreement_result=disagreement_result,
        consistency_result=consistency_result,
        judge_verdict=judge_verdict,
    )
