from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from sentinel_eval.observability import traced_layer


def _capture_spans():
    """Attach an in-memory exporter to the already-configured global
    TracerProvider (additive, like Synapse-L4's dual Logfire+OTLP export)
    so spans can be asserted on without a real Collector.
    """
    exporter = InMemorySpanExporter()
    trace.get_tracer_provider().add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


def test_traced_layer_as_decorator_names_the_span():
    exporter = _capture_spans()

    @traced_layer("heuristics_check")
    def do_work():
        return "result"

    assert do_work() == "result"
    spans = exporter.get_finished_spans()
    assert [s.name for s in spans] == ["heuristics_check"]


def test_traced_layer_as_context_manager_names_the_span():
    exporter = _capture_spans()

    with traced_layer("ollama_attempt"):
        pass

    spans = exporter.get_finished_spans()
    assert [s.name for s in spans] == ["ollama_attempt"]


def test_traced_layer_nests_under_the_active_span():
    exporter = _capture_spans()

    with traced_layer("judge_call"):
        with traced_layer("ollama_attempt"):
            pass

    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert spans["ollama_attempt"].parent.span_id == spans["judge_call"].context.span_id


def test_traced_layer_records_exception_on_span():
    exporter = _capture_spans()

    @traced_layer("cross_provider_disagreement")
    def failing():
        raise ValueError("boom")

    try:
        failing()
    except ValueError:
        pass

    span = exporter.get_finished_spans()[-1]
    assert span.status.status_code.name == "ERROR"
