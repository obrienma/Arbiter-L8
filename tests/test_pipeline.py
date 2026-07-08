from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from arbiter_l8.models import EvalPrediction
from arbiter_l8.online import judge as judge_module
from arbiter_l8.online.judge import JudgeCircuitBreaker
from arbiter_l8.online.pipeline import evaluate_item


def _capture_spans():
    exporter = InMemorySpanExporter()
    trace.get_tracer_provider().add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


def test_evaluate_item_only_runs_heuristics_when_not_flagged():
    exporter = _capture_spans()

    prediction = EvalPrediction(
        id="txn-1",
        raw_output={"status": "nominal"},
        label="low",
        confidence=0.95,
    )

    result = evaluate_item(prediction)

    assert result.heuristic_result.flagged is False
    assert result.disagreement_result is None
    assert result.consistency_result is None
    assert result.judge_verdict is None

    span_names = {s.name for s in exporter.get_finished_spans()}
    assert span_names == {"heuristics_check", "evaluate_item"}


def test_evaluate_item_escalates_to_judge_when_flagged_and_judge_supplied(monkeypatch):
    exporter = _capture_spans()

    monkeypatch.setattr(judge_module, "_call_ollama", lambda p, c: "high")

    # Low confidence trips check_confidence_threshold -> flagged.
    prediction = EvalPrediction(
        id="txn-2",
        raw_output={"status": "degraded"},
        label="high",
        confidence=0.1,
    )

    result = evaluate_item(prediction, judge=JudgeCircuitBreaker())

    assert result.heuristic_result.flagged is True
    assert result.judge_verdict is not None
    assert result.judge_verdict.verdict_label == "high"
    # Neither dependency was supplied, so these layers are skipped entirely.
    assert result.disagreement_result is None
    assert result.consistency_result is None

    span_names = {s.name for s in exporter.get_finished_spans()}
    assert span_names == {"heuristics_check", "ollama_attempt", "judge_call", "evaluate_item"}
    assert "cross_provider_disagreement" not in span_names
    assert "embedding_consistency" not in span_names
