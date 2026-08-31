"""Camada LLM: FakeProvider, allowlist, retry, timeout e logs sem segredo."""

from __future__ import annotations

import logging

import pytest
from pydantic import BaseModel

from app.core.config import get_settings
from app.llm.errors import (
    LLMCallError,
    LLMPolicyError,
    LLMTimeout,
    LLMTransientError,
    LLMUnavailable,
)
from app.llm.fake_provider import FakeProvider
from app.llm.openai_provider import OpenAIProvider
from app.llm.openrouter_provider import OpenRouterProvider
from app.llm.registry import generate_structured, set_provider_override
from app.llm.schemas import ExecutionPolicy


class TinyOut(BaseModel):
    ok: bool
    text: str


@pytest.fixture(autouse=True)
def _clear_override():
    set_provider_override(None)
    yield
    set_provider_override(None)
    get_settings.cache_clear()


def _policy(**overrides) -> ExecutionPolicy:
    base = ExecutionPolicy(
        provider="fake",
        model="fake-model",
        timeout_seconds=1,
        max_retries=2,
        agent="judge",
    )
    return ExecutionPolicy(**{**base.__dict__, **overrides})


def test_fake_provider_returns_structured_output_without_network():
    provider = FakeProvider({"judge": {"ok": True, "text": "ok"}})
    set_provider_override(provider)
    result = generate_structured(
        "judge",
        "sys",
        {"hello": "world"},
        TinyOut,
        _policy(),
    )
    assert result.parsed_output.ok is True
    assert result.effective_provider == "fake"
    assert result.effective_model == "fake-model"
    assert result.fallback_used is False


def test_distinct_providers_are_recorded():
    provider = FakeProvider({"judge": TinyOut(ok=True, text="a")})
    set_provider_override(provider)
    first = generate_structured("judge", "s", {}, TinyOut, _policy(provider="openai", model="gpt-a"))
    second = generate_structured(
        "judge", "s", {}, TinyOut, _policy(provider="openrouter", model="or-b")
    )
    assert first.requested_provider != second.requested_provider
    assert first.requested_model != second.requested_model


def test_disallowed_provider_is_rejected(monkeypatch):
    monkeypatch.setenv("LLM_ALLOWED_PROVIDERS", "openai")
    get_settings.cache_clear()
    with pytest.raises(LLMPolicyError):
        generate_structured("judge", "s", {}, TinyOut, _policy(provider="openrouter"))
    get_settings.cache_clear()


def test_disallowed_model_is_rejected(monkeypatch):
    monkeypatch.setenv("LLM_ALLOWED_MODELS", "gpt-5-mini")
    get_settings.cache_clear()
    with pytest.raises(LLMPolicyError):
        generate_structured("judge", "s", {}, TinyOut, _policy(model="secret-model"))
    get_settings.cache_clear()


def test_explicit_fallback_is_recorded():
    from app.llm.schemas import FallbackPolicy

    class Switching(FakeProvider):
        def generate_structured(self, task, system_prompt, user_payload, response_model, execution_policy):
            if execution_policy.provider == "openai":
                raise LLMCallError("primary down")
            return super().generate_structured(
                task, system_prompt, user_payload, response_model, execution_policy
            )

    provider = Switching({"judge": {"ok": True, "text": "fb"}})
    set_provider_override(provider)
    result = generate_structured(
        "judge",
        "s",
        {},
        TinyOut,
        ExecutionPolicy(
            provider="openai",
            model="gpt-a",
            fallback=FallbackPolicy(
                provider="openrouter", model="or-b", reason="primary_unavailable"
            ),
        ),
    )
    assert result.fallback_used is True
    assert result.fallback_reason == "primary_unavailable"
    assert result.requested_provider == "openai"
    assert result.effective_model == "or-b"


def test_missing_key_does_not_call_network():
    with pytest.raises(LLMUnavailable):
        OpenAIProvider(api_key="")
    with pytest.raises(LLMUnavailable):
        OpenRouterProvider(api_key="")


def test_permanent_error_does_not_retry_forever():
    calls = {"n": 0}

    class Once(FakeProvider):
        def generate_structured(self, task, system_prompt, user_payload, response_model, execution_policy):
            calls["n"] += 1
            raise LLMCallError("schema boom")

    set_provider_override(Once())
    with pytest.raises(LLMCallError):
        generate_structured("judge", "s", {}, TinyOut, _policy(max_retries=8))
    assert calls["n"] == 1


def test_transient_retry_is_bounded(monkeypatch):
    from app.llm import openai_provider as mod

    class Boom(Exception):
        status_code = 429

    class Dummy:
        def __init__(self, *args, **kwargs):
            pass

        def responses(self):
            return self

        def parse(self, **kwargs):
            raise Boom("rate")

    class Client:
        def __init__(self, *args, **kwargs):
            self.responses = type("R", (), {"parse": lambda *a, **k: (_ for _ in ()).throw(Boom("rate"))})()

    monkeypatch.setattr(mod, "OpenAI", lambda *a, **k: Client())
    provider = object.__new__(OpenAIProvider)
    provider._api_key = "sk-test"
    provider._timeout = 1
    sleeps = []
    monkeypatch.setattr(mod.time, "sleep", lambda s: sleeps.append(s))
    with pytest.raises((LLMCallError, LLMTransientError, Boom)):
        provider.generate_structured(
            "judge",
            "s",
            {},
            TinyOut,
            ExecutionPolicy(provider="openai", model="m", max_retries=2, timeout_seconds=1),
        )
    assert len(sleeps) <= 2


def test_timeout_is_classified_without_network(monkeypatch):
    from app.llm import openai_provider as mod

    class Client:
        def __init__(self, *args, **kwargs):
            self.responses = type(
                "R",
                (),
                {"parse": lambda *a, **k: (_ for _ in ()).throw(TimeoutError("timed out"))},
            )()

    monkeypatch.setattr(mod, "OpenAI", lambda *a, **k: Client())
    provider = object.__new__(OpenAIProvider)
    provider._api_key = "sk-test"
    provider._timeout = 1
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    with pytest.raises(LLMTimeout):
        provider.generate_structured(
            "judge",
            "s",
            {},
            TinyOut,
            ExecutionPolicy(provider="openai", model="m", max_retries=0, timeout_seconds=1),
        )


def test_logs_do_not_contain_secrets(caplog):
    provider = FakeProvider({"judge": {"ok": True, "text": "ok"}})
    set_provider_override(provider)
    with caplog.at_level(logging.INFO, logger="valinor.llm"):
        generate_structured(
            "judge",
            "sys",
            {"secret": "sk-live-abc", "document": "conteudo confidencial"},
            TinyOut,
            _policy(),
        )
    joined = " ".join(record.getMessage() for record in caplog.records)
    assert "sk-live-abc" not in joined
    assert "conteudo confidencial" not in joined
