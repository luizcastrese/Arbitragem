"""Seletor de modelos: ranking de benchmark, agente e trava no manifesto."""

from __future__ import annotations

from app.core.config import get_settings
from app.llm.catalog import snapshot_catalog
from app.llm.models import families_are_independent, model_vendor
from app.llm.selection import pick_from_rank, select_stage_models, validate_selection
from app.llm.stage_requirements import STAGE_REQUIREMENTS


def test_snapshot_ranking_assigns_distinct_families_to_decision_stages():
    catalog = snapshot_catalog()
    result = pick_from_rank(catalog, pins={})
    judge = result.assignments["judge"].model
    reviewer = result.assignments["reviewer"].model
    appeal = result.assignments["appeal"].model
    assert families_are_independent(judge, reviewer)
    assert families_are_independent(judge, appeal)
    assert families_are_independent(reviewer, appeal)
    assert result.assignments["embedding"].model.startswith("openai/text-embedding")
    assert model_vendor(result.assignments["conciliator"].model)
    for agent in STAGE_REQUIREMENTS:
        assert agent in result.shortlists
        assert result.shortlists[agent]


def test_operator_pin_is_preserved(monkeypatch):
    monkeypatch.setenv("JUDGE_MODEL", "openai/gpt-4.1")
    catalog = snapshot_catalog()
    result = pick_from_rank(catalog)
    assert result.assignments["judge"].model == "openai/gpt-4.1"
    assert result.assignments["judge"].pinned is True
    assert result.assignments["judge"].source == "operator_pin"
    assert families_are_independent(
        result.assignments["judge"].model,
        result.assignments["reviewer"].model,
    )


def test_selector_choice_outside_shortlist_is_ignored():
    catalog = snapshot_catalog()
    ranked = pick_from_rank(catalog, pins={})
    repaired = validate_selection(
        {"judge": "invented/not-a-model", "reviewer": ranked.assignments["reviewer"].model},
        catalog,
        ranked.shortlists,
        pins={},
    )
    assert repaired.assignments["judge"].model == ranked.assignments["judge"].model


def test_selector_same_family_is_repaired():
    catalog = snapshot_catalog()
    ranked = pick_from_rank(catalog, pins={})
    openai_judge = next(
        item.model.id
        for item in ranked.shortlists["judge"]
        if model_vendor(item.model.id) == "openai"
    )
    openai_reviewer = next(
        item.model.id
        for item in ranked.shortlists["reviewer"]
        if model_vendor(item.model.id) == "openai"
    )
    repaired = validate_selection(
        {"judge": openai_judge, "reviewer": openai_reviewer},
        catalog,
        ranked.shortlists,
        pins={},
    )
    assert families_are_independent(
        repaired.assignments["judge"].model,
        repaired.assignments["reviewer"].model,
    )


def test_select_stage_models_uses_ranker_without_llm_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("JUDGE_MODEL", raising=False)
    get_settings.cache_clear()
    try:
        result = select_stage_models(catalog=snapshot_catalog())
        assert result.method == "catalog_rank"
        assert result.assignments["judge"].model
        assert families_are_independent(
            result.assignments["judge"].model,
            result.assignments["reviewer"].model,
        )
    finally:
        get_settings.cache_clear()


def test_execution_policy_honors_locked_manifest():
    from app.llm.registry import execution_policy_for

    policy = execution_policy_for(
        "judge",
        model_policy={
            "judge": {"provider": "openrouter", "model": "deepseek/deepseek-chat-v3.1"},
        },
    )
    assert policy.model == "deepseek/deepseek-chat-v3.1"
    assert policy.provider == "openrouter"


def test_selector_agent_records_execution_when_llm_is_scripted(monkeypatch):
    from app.llm.fake_provider import FakeProvider
    from app.llm.registry import set_provider_override

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    get_settings.cache_clear()
    catalog = snapshot_catalog()
    ranked = pick_from_rank(catalog, pins={})
    judge = ranked.shortlists["judge"][0].model.id
    reviewer = next(
        item.model.id
        for item in ranked.shortlists["reviewer"]
        if model_vendor(item.model.id) != model_vendor(judge)
    )
    set_provider_override(
        FakeProvider(
            {
                "selector": {
                    "choices": [
                        {
                            "agent": "judge",
                            "model": judge,
                            "reason": "maior intelligence da shortlist",
                        },
                        {
                            "agent": "reviewer",
                            "model": reviewer,
                            "reason": "família distinta da do julgador",
                        },
                    ],
                    "notes": "alocação justificada",
                }
            }
        )
    )
    try:
        result = select_stage_models(catalog=catalog)
        assert result.method == "selector_agent"
        assert result.assignments["judge"].model == judge
        assert result.assignments["judge"].source == "selector_agent"
        assert result.selector_execution["provider"] == "fake"
        assert families_are_independent(
            result.assignments["judge"].model,
            result.assignments["reviewer"].model,
        )
    finally:
        set_provider_override(None)
        get_settings.cache_clear()


def test_changing_judge_to_reviewer_family_reassigns_the_others():
    catalog = snapshot_catalog()
    ranked = pick_from_rank(catalog, pins={})
    reviewer_model = ranked.assignments["reviewer"].model
    repaired = validate_selection(
        {"judge": reviewer_model},
        catalog,
        ranked.shortlists,
        pins={},
    )
    assert repaired.assignments["judge"].model == reviewer_model
    assert families_are_independent(
        repaired.assignments["judge"].model,
        repaired.assignments["reviewer"].model,
    )
    assert families_are_independent(
        repaired.assignments["judge"].model,
        repaired.assignments["appeal"].model,
    )
    assert families_are_independent(
        repaired.assignments["reviewer"].model,
        repaired.assignments["appeal"].model,
    )


def test_selector_reason_is_kept_when_the_choice_is_valid():
    catalog = snapshot_catalog()
    ranked = pick_from_rank(catalog, pins={})
    judge = ranked.assignments["judge"].model
    repaired = validate_selection(
        {"judge": {"model": judge, "reason": "maior índice de inteligência da shortlist"}},
        catalog,
        ranked.shortlists,
        pins={},
    )
    assert repaired.assignments["judge"].source == "selector_agent"
    assert repaired.assignments["judge"].reason == "maior índice de inteligência da shortlist"


def test_live_catalog_keeps_snapshot_score_when_api_omits_it(monkeypatch):
    from app.llm.catalog import fetch_live_catalog

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    get_settings.cache_clear()

    def fake_get(url, api_key, timeout):
        if "/models" in url:
            return {
                "data": [
                    {
                        "id": "anthropic/claude-sonnet-4",
                        "context_length": 200000,
                        "pricing": {"prompt": "0.000003"},
                        "architecture": {"output_modalities": ["text"]},
                        "supported_parameters": ["response_format"],
                    }
                ]
            }
        return {"data": []}

    monkeypatch.setattr("app.llm.catalog._http_get_json", fake_get)
    try:
        catalog = fetch_live_catalog()
    finally:
        get_settings.cache_clear()
    model = catalog.by_id("anthropic/claude-sonnet-4")
    assert model is not None
    assert model.intelligence == 72.0
    assert model.prompt_price == 3.0
    assert catalog.by_id("openai/text-embedding-3-small") is not None


def test_locked_manifest_records_selector_assignment():
    from app.core.manifest import lock_case_manifest
    from app.core.terms import current_terms

    terms = current_terms()
    manifest = lock_case_manifest(
        {
            "id": "case-selector-1",
            "title": "Disputa",
            "claimant": "A",
            "respondent": "B",
            "documents": [
                {
                    "id": "doc-1",
                    "name": "contrato.txt",
                    "sha256": "a" * 64,
                    "submitted_by": "claimant",
                    "admitted": True,
                    "chunks_count": 0,
                }
            ],
            "chunks": [],
            "consent": {
                "complete": True,
                "claimant": {
                    "accepted": True,
                    "terms_version": terms.version,
                    "terms_sha256": terms.sha256,
                },
                "respondent": {
                    "accepted": True,
                    "terms_version": terms.version,
                    "terms_sha256": terms.sha256,
                },
            },
            "contradictory": {"complete": True, "pending_document_ids": []},
        }
    )
    policy = manifest["model_policy"]
    assert "selection" in policy
    assert policy["selection"]["method"] in {"catalog_rank", "selector_agent", "disabled"}
    assert policy["judge"]["model"]
    assert policy["reviewer"]["model"]
    assert families_are_independent(policy["judge"]["model"], policy["reviewer"]["model"])
    assert policy["prompts"]["selector"]["sha256"]
