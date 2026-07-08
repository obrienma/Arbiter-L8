"""TracerProvider setup — configured as an import-time side effect, eagerly.

This mirrors EventHorizon's src/observation/tracing.ts, which calls
`sdk.start()` unconditionally at module scope rather than deferring it into
a lifecycle hook. It deliberately does NOT mirror Synapse-L4's current
pattern: Synapse-L4's `configure_logfire()` / `instrument_fastapi(app)` run
inside its FastAPI `lifespan()` handler, which only executes once Uvicorn
starts serving — by which point the `FastAPI(...)` app object and its
routes were already constructed at import time. Starlette lazily builds and
caches its ASGI middleware stack on the first ASGI event it receives, and
the lifespan-startup event flows through that same top-level `app.__call__`
before `instrument_fastapi(app)` has run — so the OTel/Logfire ASGI
middleware ends up attached after other middleware ordering has already
latched in. That produces inconsistent root-span parenting: the suspected
cause of Synapse-L4's "three traces instead of one" bug. This is a general
Python-SDK-init-order problem, not a FastAPI-only quirk (the same
instruction already exists for EventHorizon's Node SDK: instrumentation
must be wired before any instrumented object is constructed, not deferred
behind a hook that fires after the fact).

arbiter-l8 has no framework app to instrument, so the specific
middleware-ordering failure mode doesn't apply here — but the general rule
does: this module sets up the TracerProvider as a plain import-time side
effect, so anything that imports `arbiter_l8.observability` (directly or
transitively) gets a real provider before it can create its first span.
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from arbiter_l8.observability._env import otlp_endpoint, service_name

_provider = TracerProvider(resource=Resource.create({"service.name": service_name()}))
_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{otlp_endpoint()}/v1/traces"))
)
trace.set_tracer_provider(_provider)

tracer = trace.get_tracer("arbiter_l8")
