"""Narrative-only grounding heuristic (docs/adr/0003-narrative-grounding-heuristic.md).

Sentinel-L7's ADR-0034 guards the structured `policy_refs` field against
fabrication on empty retrieval, but explicitly leaves free-text `narrative`
untouched. This module judges `narrative` itself for citation-shaped or
regulation-referencing claims that were never grounded, independent of
whatever `policy_refs` says.

Opportunistic, like heuristics.py's narrative checks: no-ops for any
system-under-test payload without a `narrative` key (docs/adr/0001-standalone
-module.md). Not part of heuristics.py's DEFAULT_CHECKS because, unlike
every check there, its Stage 3 genuinely needs an optional `embed_fn` — the
same dependency-gated-escalation shape docs/adr/0002-online-escalation-
pipeline.md uses for layers 2-4, applied one layer earlier since Stage 1/2
are free and run unconditionally.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from arbiter_l8 import config
from arbiter_l8.models import EvalPrediction
from arbiter_l8.observability import traced_layer
from arbiter_l8.online.consistency import EmbeddingFn, query_upstash_vector

# Policy-ID-shaped tokens (e.g. "AML-BSA-001", "GDPR-001"), with an optional
# trailing " Section N" captured as part of the same match so normalization
# can strip it before comparing against policy_refs (spike 0001 Sample A:
# narrative says "AML-BSA-001 Section 5", policy_refs says "AML-BSA-001").
_POLICY_ID_RE = re.compile(
    r"\b[A-Z]{2,}(?:-[A-Z0-9]+)+\b(?:\s+Section\s+\d+[A-Za-z0-9.()]*)?",
)
# Bare section/regulation references not attached to a policy-ID token
# (e.g. "§205.6(b)", "Section 5" on its own).
_SECTION_TOKEN_RE = re.compile(
    r"§\s?\d+(?:\.\d+)*(?:\([a-z0-9]+\))*|\bSection\s+\d+[A-Za-z0-9.()]*\b",
    re.IGNORECASE,
)
_SECTION_SUFFIX_RE = re.compile(r"\s+Section\s+\d+[A-Za-z0-9.()]*\s*$", re.IGNORECASE)

# Illustrative, not exhaustive (ADR-0003 Stage 2 step 5) — deliberately left
# untuned pending real false-positive/negative data (ADR-0003 Consequences,
# Follow-up). Dominant real case per spike 0001's n=49: narrative names a
# regulation in prose with no formal citation token at all.
DEFAULT_REGULATORY_KEYWORDS = frozenset(
    {"policy", "regulation", "pursuant", "mandate", "ofac", "sanctions", "aml", "gdpr", "sar", "ctr"}
)


def _keyword_pattern(keywords: frozenset[str]) -> re.Pattern[str]:
    return re.compile(r"\b(" + "|".join(re.escape(k) for k in keywords) + r")\b", re.IGNORECASE)


def _fold_hyphens(text: str) -> str:
    # U+2011 (non-breaking hyphen) to ASCII U+002D — spike 0001 observed
    # this exact inconsistency across policy_refs values (e.g.
    # "Anti-Money Laundering (AML) Policy" vs "Anti‑Money Laundering
    # Policy"). Applied before extraction too, not just before comparison —
    # otherwise a narrative token using U+2011 internally (e.g.
    # "AML‑BSA‑001") would never match _POLICY_ID_RE's ASCII "-"
    # in the first place.
    return text.replace("‑", "-")


def _extract_citation_tokens(narrative: str) -> list[str]:
    narrative = _fold_hyphens(narrative)
    tokens = [m.group(0) for m in _POLICY_ID_RE.finditer(narrative)]
    tokens.extend(m.group(0) for m in _SECTION_TOKEN_RE.finditer(narrative))
    return tokens


def _normalize(text: str) -> str:
    # Strips a trailing " Section N" suffix — the other concrete mismatch
    # spike 0001 documented (narrative: "AML-BSA-001 Section 5", policy_refs:
    # "AML-BSA-001"). Also re-folds hyphens so policy_refs values (which
    # never go through _extract_citation_tokens) get the same treatment.
    return _SECTION_SUFFIX_RE.sub("", _fold_hyphens(text)).strip()


@dataclass
class NarrativeGroundingFlag:
    reason: str
    severity: float  # 0.0-1.0, higher = more suspicious


@dataclass
class NarrativeGroundingResult:
    prediction_id: str
    flagged: bool
    flag: NarrativeGroundingFlag | None = None
    stage: str = "none"  # "skip" | "regex" | "keyword" | "semantic" | "none"


def _semantic_stage(
    prediction: EvalPrediction,
    narrative: str,
    embed_fn: EmbeddingFn | None,
    *,
    namespace: str | None,
    threshold: float | None,
    reason_prefix: str,
) -> NarrativeGroundingResult:
    if embed_fn is None:
        return NarrativeGroundingResult(prediction_id=prediction.id, flagged=False, stage="skip")

    vector = embed_fn(narrative)
    matches = query_upstash_vector(
        vector,
        namespace=namespace or config.upstash_vector_policies_namespace(),
        threshold=(
            threshold if threshold is not None else config.upstash_vector_policies_similarity_threshold()
        ),
    )
    if matches:
        return NarrativeGroundingResult(prediction_id=prediction.id, flagged=False, stage="semantic")

    return NarrativeGroundingResult(
        prediction_id=prediction.id,
        flagged=True,
        flag=NarrativeGroundingFlag(
            reason=f"{reason_prefix}; semantic re-query against the policies namespace found no match",
            severity=0.7,
        ),
        stage="semantic",
    )


@traced_layer("narrative_grounding_check")
def check_narrative_grounding(
    prediction: EvalPrediction,
    *,
    embed_fn: EmbeddingFn | None = None,
    namespace: str | None = None,
    threshold: float | None = None,
    regulatory_keywords: frozenset[str] = DEFAULT_REGULATORY_KEYWORDS,
) -> NarrativeGroundingResult:
    """Flag a narrative that asserts a citation-shaped or regulation-
    referencing claim with no grounding evidence for it.

    Decision tree (ADR-0003 Stage 2):
    1. No `narrative` key, or Tier-3 (`source: fallback`) -> no-op. Tier 3's
       narrative is always fixed-template string interpolation of already-
       structured fields, never a natural-language citation (spike 0001).
    2. A citation-shaped token is found and matches a `policy_refs` entry
       (after normalization) -> not flagged.
    3. A token is found, no match, `policy_refs` is empty -> flag directly,
       no embedding call. Post-ADR-0034 (Sentinel-L7), empty `policy_refs`
       is a reliable "definitely nothing retrieved" signal.
    4. A token is found, no match, `policy_refs` is non-empty -> escalate to
       Stage 3 rather than flag on the regex near-miss alone.
    5. No token, but the narrative trips `regulatory_keywords` -> escalate
       to Stage 3. This is the dominant real case per spike 0001's n=49.
    6. Neither -> no-op.

    Stage 3 (semantic re-query) only runs when `embed_fn` is supplied,
    mirroring the optional-dependency, no-op-if-absent contract
    docs/adr/0002-online-escalation-pipeline.md uses for layers 2-4.
    """
    if prediction.metadata.get("source") == "fallback":
        return NarrativeGroundingResult(prediction_id=prediction.id, flagged=False, stage="skip")

    narrative = prediction.raw_output.get("narrative")
    if not narrative:
        return NarrativeGroundingResult(prediction_id=prediction.id, flagged=False, stage="skip")

    policy_refs: list[str] = prediction.raw_output.get("policy_refs") or []
    normalized_refs = [_normalize(ref) for ref in policy_refs]

    tokens = _extract_citation_tokens(narrative)
    if tokens:
        if any(_normalize(token) in normalized_refs for token in tokens):
            return NarrativeGroundingResult(prediction_id=prediction.id, flagged=False, stage="regex")

        if not policy_refs:
            return NarrativeGroundingResult(
                prediction_id=prediction.id,
                flagged=True,
                flag=NarrativeGroundingFlag(
                    reason=f"narrative cites {tokens[0]!r} but policy_refs is empty",
                    severity=0.9,
                ),
                stage="regex",
            )

        return _semantic_stage(
            prediction,
            narrative,
            embed_fn,
            namespace=namespace,
            threshold=threshold,
            reason_prefix=f"narrative cites {tokens[0]!r}, not found in policy_refs {policy_refs!r}",
        )

    if _keyword_pattern(regulatory_keywords).search(narrative):
        return _semantic_stage(
            prediction,
            narrative,
            embed_fn,
            namespace=namespace,
            threshold=threshold,
            reason_prefix="narrative references a regulatory concept with no citation token",
        )

    return NarrativeGroundingResult(prediction_id=prediction.id, flagged=False, stage="none")
