import json

import httpx
import pytest
import respx

from sentinel_eval.cli import main

SENTINEL_URL = "http://sentinel.test/mcp"
SYNAPSE_URL = "http://synapse.test"


def _mcp_result(summary: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"content": [{"type": "text", "text": json.dumps(summary)}], "isError": False},
    }


def _write_fixture(tmp_path, examples: list[dict]):
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps({"examples": examples}))
    return path


@respx.mock
def test_sentinel_l7_run_prints_text_report(tmp_path, capsys):
    respx.post(SENTINEL_URL).mock(
        return_value=httpx.Response(
            200,
            json=_mcp_result(
                {
                    "source": "cache_miss",
                    "is_threat": True,
                    "message": "m",
                    "elapsed_ms": 1.0,
                    "risk_level": "high",
                    "narrative": "n",
                    "confidence": 0.9,
                    "policy_refs": [],
                }
            ),
        )
    )
    fixture = _write_fixture(
        tmp_path,
        [{"input": {"amount": 10.0, "currency": "USD", "merchant": "Shop"}, "expected_label": "high"}],
    )

    exit_code = main(
        ["--system", "sentinel-l7", "--fixture", str(fixture), "--url", SENTINEL_URL]
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "accuracy: 1/1 (100.0%)" in out
    assert "high" in out


@respx.mock
def test_synapse_l4_run_prints_text_report(tmp_path, capsys):
    respx.post(f"{SYNAPSE_URL}/ingest").mock(
        return_value=httpx.Response(
            200,
            json={
                "axiom": {
                    "status": "nominal",
                    "metric_value": 1.0,
                    "anomaly_score": 0.1,
                    "source_id": "txn-1",
                    "domain": "aml",
                },
                "pipeline_ms": 10,
            },
        )
    )
    fixture = _write_fixture(
        tmp_path,
        [{"input": {"source_id": "txn-1", "payload": {}}, "expected_label": "nominal"}],
    )

    exit_code = main(
        ["--system", "synapse-l4", "--fixture", str(fixture), "--url", SYNAPSE_URL]
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "accuracy: 1/1 (100.0%)" in out


def test_driver_flag_rejected_for_synapse_l4(tmp_path):
    fixture = _write_fixture(tmp_path, [])

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--system",
                "synapse-l4",
                "--fixture",
                str(fixture),
                "--driver",
                "ollama",
            ]
        )

    assert exc_info.value.code == 2


def test_binary_flag_rejected_for_synapse_l4(tmp_path):
    fixture = _write_fixture(tmp_path, [])

    with pytest.raises(SystemExit) as exc_info:
        main(["--system", "synapse-l4", "--fixture", str(fixture), "--binary"])

    assert exc_info.value.code == 2


@respx.mock
def test_binary_flag_collapses_non_low_labels_before_scoring(tmp_path, capsys):
    respx.post(SENTINEL_URL).mock(
        return_value=httpx.Response(
            200,
            json=_mcp_result(
                {
                    "source": "cache_miss",
                    "is_threat": True,
                    "message": "m",
                    "elapsed_ms": 1.0,
                    "risk_level": "critical",
                    "narrative": "n",
                    "confidence": 0.9,
                    "policy_refs": [],
                }
            ),
        )
    )
    fixture = _write_fixture(
        tmp_path,
        [{"input": {"amount": 10.0, "currency": "USD", "merchant": "Shop"}, "expected_label": "high"}],
    )

    exit_code = main(
        [
            "--system",
            "sentinel-l7",
            "--fixture",
            str(fixture),
            "--url",
            SENTINEL_URL,
            "--binary",
        ]
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "accuracy: 1/1 (100.0%)" in out


@respx.mock
def test_limit_only_scores_first_n_examples(tmp_path, capsys):
    route = respx.post(SENTINEL_URL).mock(
        return_value=httpx.Response(
            200,
            json=_mcp_result(
                {
                    "source": "cache_miss",
                    "is_threat": False,
                    "message": "m",
                    "elapsed_ms": 1.0,
                    "risk_level": "low",
                    "narrative": "n",
                    "confidence": 0.5,
                    "policy_refs": [],
                }
            ),
        )
    )
    fixture = _write_fixture(
        tmp_path,
        [
            {"input": {"amount": 1.0, "currency": "USD", "merchant": "A"}, "expected_label": "low"},
            {"input": {"amount": 2.0, "currency": "USD", "merchant": "B"}, "expected_label": "low"},
            {"input": {"amount": 3.0, "currency": "USD", "merchant": "C"}, "expected_label": "low"},
        ],
    )

    exit_code = main(
        ["--system", "sentinel-l7", "--fixture", str(fixture), "--url", SENTINEL_URL, "--limit", "1"]
    )

    assert exit_code == 0
    assert route.call_count == 1


@respx.mock
def test_connection_error_returns_1_and_prints_to_stderr(tmp_path, capsys):
    respx.post(SENTINEL_URL).mock(side_effect=httpx.ConnectError("refused"))
    fixture = _write_fixture(
        tmp_path,
        [{"input": {"amount": 1.0, "currency": "USD", "merchant": "A"}, "expected_label": "low"}],
    )

    exit_code = main(
        ["--system", "sentinel-l7", "--fixture", str(fixture), "--url", SENTINEL_URL]
    )

    assert exit_code == 1
    assert "could not reach sentinel-l7" in capsys.readouterr().err


@respx.mock
def test_sentinel_l7_error_returns_1_and_prints_to_stderr_not_a_traceback(tmp_path, capsys):
    respx.post(SENTINEL_URL).mock(return_value=httpx.Response(422, text="bad request"))
    fixture = _write_fixture(
        tmp_path,
        [{"input": {"amount": 1.0, "currency": "USD", "merchant": "A"}, "expected_label": "low"}],
    )

    exit_code = main(
        ["--system", "sentinel-l7", "--fixture", str(fixture), "--url", SENTINEL_URL]
    )

    assert exit_code == 1
    assert "Sentinel-L7 /mcp call failed (422)" in capsys.readouterr().err


@respx.mock
def test_synapse_l4_error_returns_1_and_prints_to_stderr_not_a_traceback(tmp_path, capsys):
    respx.post(f"{SYNAPSE_URL}/ingest").mock(
        return_value=httpx.Response(
            422, json={"error": "judge_rejected", "rule": "anomaly_score_status_consistency"}
        )
    )
    fixture = _write_fixture(
        tmp_path,
        [{"input": {"source_id": "txn-1", "payload": {}}, "expected_label": "nominal"}],
    )

    exit_code = main(
        ["--system", "synapse-l4", "--fixture", str(fixture), "--url", SYNAPSE_URL]
    )

    assert exit_code == 1
    assert "Synapse-L4 /ingest failed (422)" in capsys.readouterr().err


@respx.mock
def test_json_output_is_valid_json(tmp_path, capsys):
    respx.post(SENTINEL_URL).mock(
        return_value=httpx.Response(
            200,
            json=_mcp_result(
                {
                    "source": "cache_miss",
                    "is_threat": True,
                    "message": "m",
                    "elapsed_ms": 1.0,
                    "risk_level": "high",
                    "narrative": "n",
                    "confidence": 0.9,
                    "policy_refs": [],
                }
            ),
        )
    )
    fixture = _write_fixture(
        tmp_path,
        [{"input": {"amount": 10.0, "currency": "USD", "merchant": "Shop"}, "expected_label": "high"}],
    )

    exit_code = main(
        ["--system", "sentinel-l7", "--fixture", str(fixture), "--url", SENTINEL_URL, "--json"]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["accuracy"] == 1.0
