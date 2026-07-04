"""Config for calling out to real system-under-test services.

Same env-var-with-default pattern as observability/_env.py — deliberately
not pydantic-settings, to keep one config style across the codebase rather
than introducing a second one for this narrower need.

OLLAMA_JUDGE_* and OLLAMA_EMBEDDING_* are separate hosts on purpose: the
judge calls a remote Ollama over Tailscale (partner-owned host, LLM-as-judge
duty), while the embedding call goes to the local Ollama Sentinel-L7 itself
uses for nomic-embed-text (see docs/adr/0001-standalone-module.md,
"Embedding dimension consistency"). Conflating the two would point the
embedding call at a host that was never migrated to nomic-embed-text and
was never meant to serve embeddings at all.
"""

from __future__ import annotations

import os


def synapse_l4_base_url() -> str:
    return os.environ.get("SYNAPSE_L4_BASE_URL", "http://localhost:8000").rstrip("/")


def sentinel_l7_mcp_url() -> str:
    return os.environ.get("SENTINEL_L7_MCP_URL", "http://localhost:8080/mcp")


def ollama_judge_host() -> str:
    return os.environ.get("OLLAMA_JUDGE_HOST", "http://100.82.223.70:11434").rstrip("/")


def ollama_judge_model() -> str:
    return os.environ.get("OLLAMA_JUDGE_MODEL", "qwen3.5:9b-q4_K_M")


def ollama_embedding_host() -> str:
    return os.environ.get("OLLAMA_EMBEDDING_HOST", "http://localhost:11434").rstrip("/")


def ollama_embedding_model() -> str:
    return os.environ.get("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text:v1.5")


def gemini_api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY")


def gemini_flash_url() -> str:
    # Default matches sentinel-l7's config/services.php 'flash_url' exactly —
    # same env var name too, so a shared GEMINI_FLASH_URL override applies
    # to both services without needing to be set twice.
    return os.environ.get(
        "GEMINI_FLASH_URL",
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
    )
