---
id: sentinel-eval-2026-07-04T0328-config-module-foundation
repo: sentinel-eval
title: "Config Module Foundation for Real System-Under-Test Integrations"
date: 2026-07-04
phase: 3
tags: [additive-observability, config-convention-reuse]
files: [pyproject.toml, src/sentinel_eval/config.py, tests/test_config.py]
---

First step of wiring sentinel-eval up to real services (Synapse-L4,
Sentinel-L7, a remote judge) instead of only fixture data. Added `httpx`
and `respx` (dev), and `src/sentinel_eval/config.py` — env-var-with-default
settings matching `observability/_env.py`'s existing style rather than
introducing pydantic-settings as a second config convention.

### Decision: Two separate Ollama hosts, not one

`OLLAMA_JUDGE_HOST` (remote, over Tailscale, `qwen3.5:9b-q4_K_M`) and
`OLLAMA_EMBEDDING_HOST` (local, mirrors Sentinel-L7's `nomic-embed-text:v1.5`
host) are deliberately distinct settings with different defaults, per
docs/adr/0001-standalone-module.md's explicit note that these are separate
machines serving separate purposes. Collapsing them into one "OLLAMA_HOST"
setting would point the embedding call at a host that was never migrated
to serve embeddings, or point the judge call at a host with no LLM-judge
capability. Test asserts the two defaults are never equal, specifically to
catch a future accidental collapse.

### Decision: Reuse Sentinel-L7's GEMINI_API_KEY/GEMINI_FLASH_URL names verbatim

Rather than inventing sentinel-eval-specific env var names for Gemini
Flash, reused Sentinel-L7's exact names and default URL
(`config/services.php`: `GEMINI_API_KEY`, `GEMINI_FLASH_URL` defaulting to
`gemini-2.0-flash:generateContent`) — verified against the actual file
rather than guessed (an earlier draft of this default pointed at a
plausible-looking but wrong `gemini-flash-latest` model id; caught by
reading the real config before committing to it). One shared env var value
now covers both services in a local dev environment.

### Challenge: Guessed a plausible default before verifying it

Wrote `gemini_flash_url()`'s default as `gemini-flash-latest` from
familiarity with Gemini's model-naming conventions in general, without
first checking Sentinel-L7's actual `config/services.php`. Caught it
before committing by deliberately re-reading the source file to confirm
the "mirrors sentinel-l7's convention" claim in the docstring was actually
true. The lesson isn't "don't write a default from memory" — it's that a
comment claiming to *mirror* another repo's value is itself a testable
claim and should be checked against that repo, not just written confidently.
