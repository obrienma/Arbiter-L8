import httpx
import pytest
import respx
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from arbiter_l8.models import EvalPrediction
from arbiter_l8.online import judge as judge_module
from arbiter_l8.online.judge import JudgeCircuitBreaker, JudgeSource, _call_gemini_flash, _call_ollama

OLLAMA_URL = "http://ollama-judge.test:11434"
GEMINI_URL = "https://gemini.test/v1beta/models/gemini-2.0-flash:generateContent"


@pytest.fixture(autouse=True)
def _judge_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_JUDGE_HOST", OLLAMA_URL)
    monkeypatch.setenv("GEMINI_FLASH_URL", GEMINI_URL)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")


def _capture_spans():
    exporter = InMemorySpanExporter()
    trace.get_tracer_provider().add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


def _prediction() -> EvalPrediction:
    return EvalPrediction(
        id="txn-9001",
        raw_output={"status": "degraded", "anomaly_score": 0.55},
        label="high",
        confidence=0.5,
    )


def test_ollama_timeout_then_flash_success_records_flash_source(monkeypatch):
    """The user's own example: Ollama times out, Flash succeeds. Both
    attempts should appear as nested spans, and the outcome is GEMINI_FLASH.
    """
    exporter = _capture_spans()

    def ollama_times_out(prediction, context):
        raise TimeoutError("ollama unreachable over tailscale")

    def flash_succeeds(prediction, context):
        return "high"

    monkeypatch.setattr(judge_module, "_call_ollama", ollama_times_out)
    monkeypatch.setattr(judge_module, "_call_gemini_flash", flash_succeeds)

    breaker = JudgeCircuitBreaker()
    verdict = breaker.judge(_prediction(), context="elevated label, low confidence")

    assert verdict.source is JudgeSource.GEMINI_FLASH
    assert verdict.verdict_label == "high"
    assert breaker.metrics.scored_by_gemini_flash == 1
    assert breaker.metrics.pct_scored_by_judge == 1.0

    span_names = [s.name for s in exporter.get_finished_spans()]
    assert span_names == ["ollama_attempt", "flash_attempt", "judge_call"]


def test_both_sources_unavailable_falls_back_to_heuristics(monkeypatch):
    exporter = _capture_spans()

    def ollama_fails(prediction, context):
        raise ConnectionError("ollama down")

    def flash_fails(prediction, context):
        raise ConnectionError("flash down")

    monkeypatch.setattr(judge_module, "_call_ollama", ollama_fails)
    monkeypatch.setattr(judge_module, "_call_gemini_flash", flash_fails)

    breaker = JudgeCircuitBreaker()
    verdict = breaker.judge(_prediction(), context="elevated label, low confidence")

    assert verdict.source is JudgeSource.HEURISTICS_FALLBACK
    assert verdict.verdict_label is None
    assert breaker.metrics.scored_by_heuristics_fallback == 1
    assert breaker.metrics.pct_scored_by_judge == 0.0

    span_names = [s.name for s in exporter.get_finished_spans()]
    assert span_names == ["ollama_attempt", "flash_attempt", "heuristics_fallback", "judge_call"]


@respx.mock
def test_call_ollama_sends_think_false_and_parses_verdict():
    route = respx.post(f"{OLLAMA_URL}/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={"message": {"content": '{"verdict": "high", "reasoning": "matches pattern"}'}},
        )
    )

    label = _call_ollama(_prediction(), context="elevated label, low confidence")

    assert label == "high"
    request_body = route.calls.last.request.content
    assert b'"think":false' in request_body
    assert b'"format":"json"' in request_body


@respx.mock
def test_call_ollama_raises_on_http_error():
    respx.post(f"{OLLAMA_URL}/api/chat").mock(return_value=httpx.Response(503))

    with pytest.raises(httpx.HTTPStatusError):
        _call_ollama(_prediction(), context="elevated label, low confidence")


@respx.mock
def test_call_ollama_raises_on_malformed_json_content():
    respx.post(f"{OLLAMA_URL}/api/chat").mock(
        return_value=httpx.Response(200, json={"message": {"content": "not json"}})
    )

    with pytest.raises(Exception):
        _call_ollama(_prediction(), context="elevated label, low confidence")


@pytest.mark.parametrize("bad_verdict", ["reject", "Correct", "YES", "no"])
@respx.mock
def test_call_ollama_raises_on_correctness_judgment_instead_of_label(bad_verdict):
    """Regression test for the step 8 live-validation finding: qwen3.5
    sometimes answers as if grading correctness instead of naming a label.
    """
    respx.post(f"{OLLAMA_URL}/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={"message": {"content": f'{{"verdict": "{bad_verdict}", "reasoning": "r"}}'}},
        )
    )

    with pytest.raises(ValueError, match="correctness judgment"):
        _call_ollama(_prediction(), context="elevated label, low confidence")


def test_non_label_verdict_falls_through_to_heuristics_like_any_other_failure(monkeypatch):
    """A rejected non-label verdict from Ollama should fall through the
    circuit breaker exactly like a timeout or connection error would —
    not a special case.
    """
    exporter = _capture_spans()

    def ollama_returns_correctness_judgment(prediction, context):
        raise ValueError("judge returned a correctness judgment ('reject'), not a label")

    def flash_fails(prediction, context):
        raise ConnectionError("flash down")

    monkeypatch.setattr(judge_module, "_call_ollama", ollama_returns_correctness_judgment)
    monkeypatch.setattr(judge_module, "_call_gemini_flash", flash_fails)

    breaker = JudgeCircuitBreaker()
    verdict = breaker.judge(_prediction(), context="elevated label, low confidence")

    assert verdict.source is JudgeSource.HEURISTICS_FALLBACK
    span_names = [s.name for s in exporter.get_finished_spans()]
    assert span_names == ["ollama_attempt", "flash_attempt", "heuristics_fallback", "judge_call"]


@respx.mock
def test_call_gemini_flash_sends_response_mime_type_and_parses_verdict():
    route = respx.post(GEMINI_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": '{"verdict": "low", "reasoning": "benign"}'}]}}
                ]
            },
        )
    )

    label = _call_gemini_flash(_prediction(), context="elevated label, low confidence")

    assert label == "low"
    request = route.calls.last.request
    assert str(request.url).startswith(GEMINI_URL)
    assert b"responseMimeType" in request.content


def test_call_gemini_flash_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(RuntimeError):
        _call_gemini_flash(_prediction(), context="elevated label, low confidence")
