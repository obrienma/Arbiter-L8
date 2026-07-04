from sentinel_eval import config


def test_synapse_l4_base_url_default(monkeypatch):
    monkeypatch.delenv("SYNAPSE_L4_BASE_URL", raising=False)
    assert config.synapse_l4_base_url() == "http://localhost:8000"


def test_synapse_l4_base_url_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("SYNAPSE_L4_BASE_URL", "http://synapse.internal:8000/")
    assert config.synapse_l4_base_url() == "http://synapse.internal:8000"


def test_sentinel_l7_mcp_url_default(monkeypatch):
    monkeypatch.delenv("SENTINEL_L7_MCP_URL", raising=False)
    assert config.sentinel_l7_mcp_url() == "http://localhost:8080/mcp"


def test_ollama_judge_host_and_model_defaults(monkeypatch):
    monkeypatch.delenv("OLLAMA_JUDGE_HOST", raising=False)
    monkeypatch.delenv("OLLAMA_JUDGE_MODEL", raising=False)
    assert config.ollama_judge_host() == "http://100.82.223.70:11434"
    assert config.ollama_judge_model() == "qwen3.5:9b-q4_K_M"


def test_ollama_embedding_host_and_model_defaults_differ_from_judge(monkeypatch):
    monkeypatch.delenv("OLLAMA_EMBEDDING_HOST", raising=False)
    monkeypatch.delenv("OLLAMA_EMBEDDING_MODEL", raising=False)
    assert config.ollama_embedding_host() == "http://localhost:11434"
    assert config.ollama_embedding_model() == "nomic-embed-text:v1.5"
    # Judge and embedding hosts must never accidentally collapse to the same
    # value — they're different machines serving different purposes.
    assert config.ollama_embedding_host() != config.ollama_judge_host()


def test_gemini_api_key_reads_env(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert config.gemini_api_key() is None
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-123")
    assert config.gemini_api_key() == "test-key-123"


def test_gemini_flash_url_default_matches_sentinel_l7_convention(monkeypatch):
    monkeypatch.delenv("GEMINI_FLASH_URL", raising=False)
    assert config.gemini_flash_url() == (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-2.0-flash:generateContent"
    )
