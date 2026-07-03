"""Shared OTel environment configuration.

Mirrors EventHorizon's src/observation/tracing.ts: OTEL_EXPORTER_OTLP_ENDPOINT
defaults to http://localhost:4318 (the same local Collector every service
in the suite exports to); OTEL_SERVICE_NAME defaults per-service so traces
are attributable in Grafana/Tempo.
"""

from __future__ import annotations

import os

_DEFAULT_ENDPOINT = "http://localhost:4318"
_DEFAULT_SERVICE_NAME = "sentinel-eval"


def otlp_endpoint() -> str:
    return os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", _DEFAULT_ENDPOINT).rstrip("/")


def service_name() -> str:
    return os.environ.get("OTEL_SERVICE_NAME", _DEFAULT_SERVICE_NAME)
