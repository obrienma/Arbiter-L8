from arbiter_l8.observability._env import otlp_endpoint, service_name


def test_otlp_endpoint_default(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert otlp_endpoint() == "http://localhost:4318"


def test_otlp_endpoint_reads_env_override(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector.internal:4318")
    assert otlp_endpoint() == "http://collector.internal:4318"


def test_otlp_endpoint_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector.internal:4318/")
    assert otlp_endpoint() == "http://collector.internal:4318"


def test_service_name_default(monkeypatch):
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    assert service_name() == "arbiter-l8"


def test_service_name_reads_env_override(monkeypatch):
    monkeypatch.setenv("OTEL_SERVICE_NAME", "arbiter-l8-canary")
    assert service_name() == "arbiter-l8-canary"
