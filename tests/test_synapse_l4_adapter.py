import httpx
import pytest
import respx

from arbiter_l8.adapters.synapse_l4 import SynapseL4Error, make_synapse_l4_system_under_test


@respx.mock
def test_successful_call_maps_axiom_into_eval_prediction():
    route = respx.post("http://synapse.test/ingest").mock(
        return_value=httpx.Response(
            200,
            json={
                "axiom": {
                    "status": "degraded",
                    "metric_value": 42.5,
                    "anomaly_score": 0.63,
                    "source_id": "txn-abc",
                    "domain": "aml",
                },
                "pipeline_ms": 87,
            },
        )
    )

    sut = make_synapse_l4_system_under_test(base_url="http://synapse.test")
    prediction = sut({"source_id": "txn-abc", "payload": {"raw": "telemetry"}})

    assert route.called
    request_body = route.calls.last.request.content
    assert b'"source_id":"txn-abc"' in request_body or b'"source_id": "txn-abc"' in request_body

    assert prediction.id == "txn-abc"
    assert prediction.label == "degraded"
    assert prediction.confidence == 0.63
    assert prediction.raw_output["domain"] == "aml"
    assert prediction.metadata["pipeline_ms"] == 87


@respx.mock
def test_extraction_failed_raises_synapse_l4_error():
    respx.post("http://synapse.test/ingest").mock(
        return_value=httpx.Response(
            422, json={"error": "extraction_failed", "detail": "malformed payload"}
        )
    )

    sut = make_synapse_l4_system_under_test(base_url="http://synapse.test")

    with pytest.raises(SynapseL4Error) as exc_info:
        sut({"source_id": "txn-bad", "payload": {}})

    assert exc_info.value.status_code == 422
    assert exc_info.value.body["error"] == "extraction_failed"


@respx.mock
def test_emit_failed_raises_synapse_l4_error():
    respx.post("http://synapse.test/ingest").mock(
        return_value=httpx.Response(
            502, json={"error": "emit_failed", "detail": "redis unreachable", "status_code": 502}
        )
    )

    sut = make_synapse_l4_system_under_test(base_url="http://synapse.test")

    with pytest.raises(SynapseL4Error) as exc_info:
        sut({"source_id": "txn-emit-fail", "payload": {}})

    assert exc_info.value.status_code == 502
    assert exc_info.value.body["error"] == "emit_failed"


@respx.mock
def test_default_base_url_matches_config():
    from arbiter_l8 import config

    route = respx.post(f"{config.synapse_l4_base_url()}/ingest").mock(
        return_value=httpx.Response(
            200,
            json={
                "axiom": {
                    "status": "nominal",
                    "metric_value": 1.0,
                    "anomaly_score": 0.02,
                    "source_id": "txn-default",
                    "domain": None,
                },
                "pipeline_ms": 5,
            },
        )
    )

    sut = make_synapse_l4_system_under_test()
    sut({"source_id": "txn-default", "payload": {}})

    assert route.called
