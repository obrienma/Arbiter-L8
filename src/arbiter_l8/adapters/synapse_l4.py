"""System-under-test adapter for Synapse-L4's Axiom pipeline.

Calls the real service over HTTP (POST /ingest) rather than importing
Synapse-L4's Python modules directly. Direct import was considered and
rejected: synapse-l4's config.py instantiates a pydantic-settings
singleton at import time requiring a reachable Redis URL, its dependency
set (fastapi, instructor, openai, redis) is heavy and service-specific,
it runs on Python 3.14 against arbiter-l8's pinned 3.12, and depending
on its internals at all would violate the standalone-module mandate in
docs/adr/0001-standalone-module.md. HTTP is a clean boundary that avoids
all four problems at once.
"""

from __future__ import annotations

from typing import Any

import httpx

from arbiter_l8 import config
from arbiter_l8.harness import SystemUnderTest
from arbiter_l8.models import EvalPrediction


class SynapseL4Error(RuntimeError):
    """Raised when Synapse-L4's /ingest call fails or returns an error body.

    Synapse-L4's own error responses are structured (422 for
    extraction_failed/judge_rejected, 502 for emit_failed) — this wraps
    them rather than raising a bare HTTPStatusError, so callers can see
    which pipeline stage failed and why.
    """

    def __init__(self, status_code: int, body: dict[str, Any]):
        self.status_code = status_code
        self.body = body
        super().__init__(f"Synapse-L4 /ingest failed ({status_code}): {body}")


def make_synapse_l4_system_under_test(
    *,
    base_url: str | None = None,
    client: httpx.Client | None = None,
    timeout: float = 10.0,
) -> SystemUnderTest:
    """Build a system_under_test callable that scores input through Synapse-L4.

    Each `input` dict passed to the returned callable (e.g. via an
    EvalDataset example) must be shaped like Synapse-L4's RawTelemetry
    request body: `{"source_id": str, "payload": dict}`.

    Maps the response Axiom into EvalPrediction: `status` -> `label`,
    `anomaly_score` -> `confidence`, the full axiom -> `raw_output`.

    Raises `SynapseL4Error` on a non-2xx response — one failing example
    aborts the whole run_eval() call today, since run_eval() has no
    per-example error handling; making a single bad example degrade
    gracefully instead of aborting a batch run is a harness-level concern,
    not something this adapter papers over on its own.
    """
    http_client = client or httpx.Client(
        base_url=base_url or config.synapse_l4_base_url(), timeout=timeout
    )

    def system_under_test(input_data: dict) -> EvalPrediction:
        response = http_client.post(
            "/ingest",
            json={"source_id": input_data["source_id"], "payload": input_data["payload"]},
        )
        if response.status_code >= 400:
            raise SynapseL4Error(response.status_code, response.json())

        body = response.json()
        axiom = body["axiom"]
        return EvalPrediction(
            id=axiom["source_id"],
            raw_output=axiom,
            label=axiom["status"],
            confidence=axiom["anomaly_score"],
            metadata={"pipeline_ms": body.get("pipeline_ms")},
        )

    return system_under_test
