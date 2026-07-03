"""traced_layer — one dual-purpose decorator/context manager for every span.

A plain `@contextmanager`-decorated generator returns a
`_GeneratorContextManager`, which subclasses `contextlib.ContextDecorator` —
so the same `traced_layer(name)` object works both as
`@traced_layer("heuristics_check")` around a layer function and as
`with traced_layer("ollama_attempt"):` around an inline block inside
judge_call. One implementation, no separate decorator/context-manager
class pair to keep in sync as more layers get built.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry.trace import Span

from sentinel_eval.observability.metrics import layer_latency_histogram
from sentinel_eval.observability.tracing import tracer

# Only the four cost-ordered online layers are Prometheus-visible latency
# signals. The evaluate_item parent span and the judge_call fallback-chain
# attempt spans (ollama_attempt/flash_attempt/heuristics_fallback) are
# trace-only — they'd double-count or dilute the per-layer histogram.
_LATENCY_TRACKED_LAYERS = frozenset(
    {"heuristics_check", "cross_provider_disagreement", "embedding_consistency", "judge_call"}
)


@contextmanager
def traced_layer(name: str, **attributes: object) -> Iterator[Span]:
    start = time.monotonic()
    with tracer.start_as_current_span(name) as span:
        for key, value in attributes.items():
            span.set_attribute(key, value)
        try:
            yield span
        finally:
            if name in _LATENCY_TRACKED_LAYERS:
                elapsed_ms = (time.monotonic() - start) * 1000
                layer_latency_histogram.record(elapsed_ms, {"layer": name})
