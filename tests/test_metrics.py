from opentelemetry import metrics as metrics_api
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    InMemoryMetricReader,
    MetricExporter,
    MetricExportResult,
    PeriodicExportingMetricReader,
)

from sentinel_eval.models import EvalDataset, EvalPrediction
from sentinel_eval.harness import run_eval
from sentinel_eval.online import judge as judge_module
from sentinel_eval.online.judge import JudgeCircuitBreaker
from sentinel_eval.observability.metrics import (
    harness_metric_gauge,
    judge_outcome_counter,
    layer_latency_histogram,
    record_harness_metrics,
)


def _capture_metrics() -> InMemoryMetricReader:
    """Attach an in-memory reader to the already-configured global
    MeterProvider (additive, like the InMemorySpanExporter pattern used for
    traces) so metric values can be asserted without a real Collector.
    """
    reader = InMemoryMetricReader()
    metrics_api.get_meter_provider().add_metric_reader(reader)
    return reader


def _data_points(reader: InMemoryMetricReader, metric_name: str):
    data = reader.get_metrics_data()
    points = []
    if data is None:
        return points
    for resource_metrics in data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                if metric.name == metric_name:
                    points.extend(metric.data.data_points)
    return points


def _prediction() -> EvalPrediction:
    return EvalPrediction(
        id="txn-metrics-1",
        raw_output={"status": "degraded"},
        label="high",
        confidence=0.1,
    )


def test_judge_outcome_counter_labeled_by_source():
    reader = _capture_metrics()

    def ollama_fails(prediction, context):
        raise ConnectionError("down")

    def flash_succeeds(prediction, context):
        return "high"

    import unittest.mock as mock

    with mock.patch.object(judge_module, "_call_ollama", ollama_fails), mock.patch.object(
        judge_module, "_call_gemini_flash", flash_succeeds
    ):
        JudgeCircuitBreaker().judge(_prediction(), context="test")

    points = _data_points(reader, "sentinel_eval.judge.outcome")
    by_source = {dp.attributes["source"]: dp.value for dp in points}
    assert by_source.get("gemini_flash") == 1
    assert by_source.get("ollama") is None  # ollama never resolved anything


def test_judge_outcome_counter_accumulates_across_calls():
    reader = _capture_metrics()

    import unittest.mock as mock

    with mock.patch.object(judge_module, "_call_ollama", lambda p, c: "high"):
        breaker = JudgeCircuitBreaker()
        breaker.judge(_prediction(), context="a")
        breaker.judge(_prediction(), context="b")

    points = _data_points(reader, "sentinel_eval.judge.outcome")
    by_source = {dp.attributes["source"]: dp.value for dp in points}
    assert by_source["ollama"] == 2


def test_layer_latency_histogram_only_tracks_the_four_layers():
    reader = _capture_metrics()

    from sentinel_eval.online.heuristics import run_heuristics

    run_heuristics(_prediction())

    import unittest.mock as mock

    with mock.patch.object(judge_module, "_call_ollama", lambda p, c: "high"):
        JudgeCircuitBreaker().judge(_prediction(), context="test")

    points = _data_points(reader, "sentinel_eval.layer.latency")
    layers = {dp.attributes["layer"] for dp in points}
    # heuristics_check and judge_call are tracked layers; ollama_attempt is a
    # nested attempt span within judge_call and must not show up here.
    assert layers == {"heuristics_check", "judge_call"}
    assert all(dp.count >= 1 for dp in points)


def test_harness_metric_gauge_records_precision_recall_f1_per_label():
    reader = _capture_metrics()

    dataset = EvalDataset.model_validate(
        {
            "examples": [
                {"input": {"anomaly_score": 0.01}, "expected_label": "low"},
                {"input": {"anomaly_score": 0.9}, "expected_label": "critical"},
            ]
        }
    )

    def perfect_sut(input_data: dict) -> EvalPrediction:
        label = "low" if input_data["anomaly_score"] < 0.5 else "critical"
        return EvalPrediction(id="x", raw_output=input_data, label=label, confidence=0.9)

    report = run_eval(perfect_sut, dataset)

    points = _data_points(reader, "sentinel_eval.harness.metric")
    readings = {(dp.attributes["metric"], dp.attributes["label"]): dp.value for dp in points}

    assert readings[("accuracy", "overall")] == 1.0
    assert readings[("precision", "low")] == 1.0
    assert readings[("recall", "low")] == 1.0
    assert readings[("f1", "low")] == 1.0
    assert readings[("precision", "critical")] == 1.0
    assert readings[("recall", "critical")] == 1.0
    assert readings[("f1", "critical")] == 1.0


def test_record_harness_metrics_direct_call_matches_report_values():
    reader = _capture_metrics()

    dataset = EvalDataset.model_validate(
        {
            "examples": [
                {"input": {}, "expected_label": "low"},
                {"input": {}, "expected_label": "low"},
                {"input": {}, "expected_label": "high"},
            ]
        }
    )

    def half_wrong_sut(input_data: dict) -> EvalPrediction:
        return EvalPrediction(id="x", raw_output=input_data, label="low", confidence=0.5)

    report = run_eval(half_wrong_sut, dataset)
    # run_eval already calls record_harness_metrics once; call again directly
    # to confirm the function itself (not just its use inside run_eval)
    # produces the expected readings.
    record_harness_metrics(report)

    points = _data_points(reader, "sentinel_eval.harness.metric")
    readings = {(dp.attributes["metric"], dp.attributes["label"]): dp.value for dp in points}

    high_metrics = next(m for m in report.per_label if m.label == "high")
    low_metrics = next(m for m in report.per_label if m.label == "low")

    assert readings[("accuracy", "overall")] == report.accuracy
    assert readings[("precision", "high")] == high_metrics.precision
    assert readings[("recall", "high")] == high_metrics.recall
    assert readings[("f1", "high")] == high_metrics.f1
    assert readings[("precision", "low")] == low_metrics.precision
    assert readings[("recall", "low")] == low_metrics.recall
    assert readings[("f1", "low")] == low_metrics.f1


class _RecordingExporter(MetricExporter):
    """Minimal MetricExporter that just remembers what it was handed.

    Stands in for OTLPMetricExporter so this test can prove
    PeriodicExportingMetricReader's shutdown-triggers-one-final-export
    behavior without touching the network or the shared global provider.
    """

    def __init__(self):
        super().__init__()
        self.exported_batches = []

    def export(self, metrics_data, timeout_millis=10_000, **kwargs):
        self.exported_batches.append(metrics_data)
        return MetricExportResult.SUCCESS

    def force_flush(self, timeout_millis=10_000):
        return True

    def shutdown(self, timeout_millis=30_000, **kwargs):
        pass


def test_shutdown_flushes_pending_metrics_without_waiting_for_the_export_interval():
    """Confirms the mechanism the "no force_flush needed" comment in
    observability/metrics.py relies on: PeriodicExportingMetricReader's
    background thread performs one final collect()+export the moment
    shutdown() fires, rather than only on its periodic timer. Uses a
    deliberately long export_interval_millis so the periodic timer cannot
    be the thing that delivers the data — only the shutdown path can.
    """
    exporter = _RecordingExporter()
    reader = PeriodicExportingMetricReader(
        exporter,
        export_interval_millis=600_000,  # 10 minutes — must not fire during this test
    )
    provider = MeterProvider(metric_readers=[reader])
    meter = provider.get_meter("test")
    counter = meter.create_counter("test.counter")

    counter.add(1, {"probe": "shutdown-flush"})
    assert exporter.exported_batches == []  # nothing exported yet, timer hasn't fired

    provider.shutdown()

    assert len(exporter.exported_batches) == 1
    points = [
        dp
        for rm in exporter.exported_batches[0].resource_metrics
        for sm in rm.scope_metrics
        for m in sm.metrics
        for dp in m.data.data_points
    ]
    assert any(dp.attributes.get("probe") == "shutdown-flush" for dp in points)
