import httpx
import pytest
import respx

from arbiter_l8.models import EvalPrediction
from arbiter_l8.online.narrative_grounding import check_narrative_grounding

UPSTASH_URL = "https://upstash-narrative.test"


@pytest.fixture(autouse=True)
def _upstash_env(monkeypatch):
    monkeypatch.setenv("UPSTASH_VECTOR_REST_URL", UPSTASH_URL)
    monkeypatch.setenv("UPSTASH_VECTOR_REST_TOKEN", "test-token")


def _prediction(*, narrative=None, policy_refs=None, source="cache_miss", raw_output=None):
    payload = dict(raw_output or {})
    if narrative is not None:
        payload["narrative"] = narrative
    if policy_refs is not None:
        payload["policy_refs"] = policy_refs
    return EvalPrediction(
        id="txn-1",
        raw_output=payload,
        label="low",
        confidence=0.8,
        metadata={"source": source},
    )


def test_no_narrative_key_is_a_noop():
    result = check_narrative_grounding(_prediction(raw_output={"status": "nominal"}))

    assert result.flagged is False
    assert result.stage == "skip"


def test_empty_narrative_is_a_noop():
    result = check_narrative_grounding(_prediction(narrative="", policy_refs=[]))

    assert result.flagged is False
    assert result.stage == "skip"


def test_tier3_fallback_source_is_a_noop_even_with_citation_shaped_narrative():
    result = check_narrative_grounding(
        _prediction(
            narrative="High value transaction at Acme Corp ($5000) AML-BSA-001 Section 5",
            policy_refs=[],
            source="fallback",
        )
    )

    assert result.flagged is False
    assert result.stage == "skip"


def test_no_token_and_no_keyword_is_a_noop():
    # Spike 0001 n=49: most low-risk narratives simply describe the
    # transaction with no citation or regulatory intent at all.
    result = check_narrative_grounding(
        _prediction(
            narrative="This is a small retail purchase at a local farm market with no indicators of suspicious activity.",
            policy_refs=["Retail Transaction Policy"],
        )
    )

    assert result.flagged is False
    assert result.stage == "none"


def test_regex_token_matches_policy_refs_after_section_suffix_normalization():
    # Spike 0001 Sample A: narrative says "AML-BSA-001 Section 5",
    # policy_refs says "AML-BSA-001" — matches only after stripping the
    # " Section N" suffix.
    result = check_narrative_grounding(
        _prediction(
            narrative=(
                "automated anomaly scoring above 0.80 would mandate a human review under "
                "AML-BSA-001 Section 5 and GDPR-001 Section 4."
            ),
            policy_refs=["AML-BSA-001", "GDPR-001"],
        )
    )

    assert result.flagged is False
    assert result.stage == "regex"


def test_regex_token_matches_policy_refs_after_unicode_hyphen_fold():
    result = check_narrative_grounding(
        _prediction(
            narrative="Reviewed under AML‑BSA‑001 guidance.",
            policy_refs=["AML-BSA-001"],
        )
    )

    assert result.flagged is False
    assert result.stage == "regex"


def test_regex_token_with_empty_policy_refs_flags_directly_no_embed_call():
    calls = []

    def embed_fn(text):
        calls.append(text)
        return [0.1, 0.2]

    result = check_narrative_grounding(
        _prediction(
            narrative="High value transaction at Acme Corp per policy AML-BSA-001 Section 5.",
            policy_refs=[],
        ),
        embed_fn=embed_fn,
    )

    assert result.flagged is True
    assert result.stage == "regex"
    assert "AML-BSA-001" in result.flag.reason
    assert calls == []  # empty policy_refs is decisive; Stage 3 never runs.


def test_regex_token_no_match_nonempty_policy_refs_escalates_to_semantic_stage_no_embed_fn():
    # Spike 0001 Sample B, roughly: a token that doesn't verbatim-match any
    # policy_refs entry, but policy_refs is non-empty -> Stage 3, and no
    # embed_fn supplied means Stage 3 no-ops rather than errors.
    result = check_narrative_grounding(
        _prediction(
            narrative="Flagged per Section 9 for manual review.",
            policy_refs=["Sanctions Compliance Policy"],
        )
    )

    assert result.flagged is False
    assert result.stage == "skip"


@respx.mock
def test_keyword_only_narrative_escalates_and_flags_when_no_semantic_match():
    # Spike 0001 Sample B pattern: no formal citation token, but the
    # narrative names regulatory concepts in prose.
    respx.post(f"{UPSTASH_URL}/query/policies").mock(
        return_value=httpx.Response(200, json={"result": []})
    )

    result = check_narrative_grounding(
        _prediction(
            narrative=(
                "The transaction involving Pacific Forex Exchange requires screening against "
                "OFAC, EU, and UN sanctions lists per regulatory mandates, with automated "
                "decision-making logic fully documented to ensure data subject rights under "
                "GDPR are respected if flagged for investigation."
            ),
            policy_refs=[
                "BSA Requirements (OFAC Screening)",
                "GDPR-001",
                "Sanctions Compliance Policy",
            ],
        ),
        embed_fn=lambda text: [0.1, 0.2],
    )

    assert result.flagged is True
    assert result.stage == "semantic"
    assert "regulatory concept" in result.flag.reason

    route = respx.routes[0]
    assert route.calls.last.request.url.path.endswith("/query/policies")


@respx.mock
def test_keyword_only_narrative_not_flagged_when_semantic_match_clears_threshold():
    respx.post(f"{UPSTASH_URL}/query/policies").mock(
        return_value=httpx.Response(
            200,
            json={"result": [{"id": "chunk-1", "score": 0.95, "metadata": {}}]},
        )
    )

    result = check_narrative_grounding(
        _prediction(
            narrative="Screened per sanctions and OFAC mandate requirements.",
            policy_refs=["Sanctions Compliance Policy"],
        ),
        embed_fn=lambda text: [0.1, 0.2],
    )

    assert result.flagged is False
    assert result.stage == "semantic"


@respx.mock
def test_uses_policies_namespace_and_default_threshold_not_transactions_defaults():
    route = respx.post(f"{UPSTASH_URL}/query/policies").mock(
        return_value=httpx.Response(
            200,
            json={"result": [{"id": "chunk-1", "score": 0.75, "metadata": {}}]},
        )
    )

    # 0.75 clears the policies-namespace default (0.70) but would be
    # dropped against the transactions-namespace default (0.90) —
    # confirms the policies-specific threshold, not the shared one, is used.
    result = check_narrative_grounding(
        _prediction(
            narrative="Reviewed per applicable regulation.",
            policy_refs=["Some Policy"],
        ),
        embed_fn=lambda text: [0.1, 0.2],
    )

    assert result.flagged is False
    assert route.called
