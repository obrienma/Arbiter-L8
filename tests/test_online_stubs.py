import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from sentinel_eval.models import EvalPrediction
from sentinel_eval.online.consistency import score_consistency
from sentinel_eval.online.disagreement import score_disagreement


def _capture_spans():
    exporter = InMemorySpanExporter()
    trace.get_tracer_provider().add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


def test_score_disagreement_raises_not_implemented_and_records_error_span():
    exporter = _capture_spans()

    with pytest.raises(NotImplementedError):
        score_disagreement({"status": "degraded"}, providers={"gemini": lambda d: None})

    spans = exporter.get_finished_spans()
    assert [s.name for s in spans] == ["cross_provider_disagreement"]
    assert spans[0].status.status_code.name == "ERROR"


def test_score_consistency_raises_not_implemented_and_records_error_span():
    exporter = _capture_spans()

    prediction = EvalPrediction(
        id="txn-1", raw_output={"status": "nominal"}, label="low", confidence=0.9
    )

    with pytest.raises(NotImplementedError):
        score_consistency(prediction, "some narrative text", embed_fn=lambda text: [0.0])

    spans = exporter.get_finished_spans()
    assert [s.name for s in spans] == ["embedding_consistency"]
    assert spans[0].status.status_code.name == "ERROR"
