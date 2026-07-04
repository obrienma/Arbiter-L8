---
type: cloze
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, config-convention-reuse]
---
sentinel-eval's judge calls a {{c1::remote}} Ollama host over Tailscale
(`qwen3.5:9b-q4_K_M`), while the embedding-consistency layer calls a
{{c2::local}} Ollama host mirroring Sentinel-L7's own
`nomic-embed-text:v1.5` — two separate config settings, never collapsed
into one.

Extra: sentinel-eval · Decision: Two separate Ollama hosts, not one
See: docs/journal/sentinel-eval-2026-07-04T0328-config-module-foundation.md

---
type: basic
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, config-convention-reuse]
---
Q: Why did a code comment claiming "matches sentinel-l7's convention" turn
out to be wrong initially, and what's the actual lesson?

A: The `gemini_flash_url()` default was first written as
`gemini-flash-latest` from general familiarity with Gemini's naming, not
from checking Sentinel-L7's actual `config/services.php` — which really
defaults to `gemini-2.0-flash:generateContent`. The lesson: a comment that
claims to mirror another repo's value is a testable claim, not a
plausible-sounding guess — it should be checked against that repo's
source before being written with confidence, not after.

Extra: sentinel-eval · Challenge: Guessed a plausible default before verifying it
See: docs/journal/sentinel-eval-2026-07-04T0328-config-module-foundation.md
