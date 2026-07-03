"""MeterProvider setup — same eager-at-import pattern as tracing.py.

Same OTLP HTTP Collector endpoint as traces, exporting to /v1/metrics
instead of /v1/traces (Collector -> Prometheus, per the suite's
observability stack).
"""

from __future__ import annotations

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

from sentinel_eval.models import EvalReport
from sentinel_eval.observability._env import otlp_endpoint, service_name

_reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(endpoint=f"{otlp_endpoint()}/v1/metrics")
)
_provider = MeterProvider(
    resource=Resource.create({"service.name": service_name()}),
    metric_readers=[_reader],
)
metrics.set_meter_provider(_provider)

meter = metrics.get_meter("sentinel_eval")

judge_outcome_counter = meter.create_counter(
    "sentinel_eval.judge.outcome",
    unit="1",
    description=(
        "Judge-layer resolutions by source (ollama/flash/fallback) — "
        "the '% scored by judge vs fallback' signal from docs/adr/0001"
    ),
)

layer_latency_histogram = meter.create_histogram(
    "sentinel_eval.layer.latency",
    unit="ms",
    description="Per-layer latency for online scoring layers",
)

harness_metric_gauge = meter.create_gauge(
    "sentinel_eval.harness.metric",
    unit="1",
    description=(
        "Precision/recall/F1/accuracy from an offline run_eval() run, "
        "recorded once per run so Grafana can plot it as a time series"
    ),
)


def record_harness_metrics(report: EvalReport) -> None:
    """Emit one gauge reading per label per metric, plus an overall accuracy row.

    Called once at the end of run_eval() — not per example — so each
    harness run shows up as one set of points, letting a prompt/model
    change show up as a step change in Grafana.
    """
    harness_metric_gauge.set(report.accuracy, {"metric": "accuracy", "label": "overall"})
    for label_metrics in report.per_label:
        harness_metric_gauge.set(
            label_metrics.precision, {"metric": "precision", "label": label_metrics.label}
        )
        harness_metric_gauge.set(
            label_metrics.recall, {"metric": "recall", "label": label_metrics.label}
        )
        harness_metric_gauge.set(
            label_metrics.f1, {"metric": "f1", "label": label_metrics.label}
        )
