from app.core.config import get_settings


def _complete_production_environment(monkeypatch):
    """Preenche a infraestrutura mínima; cada teste remove o item sob teste."""
    from app.core.encryption import generate_key

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PLATFORM_SIGNING_SECRET", "a-very-long-production-secret-value")
    monkeypatch.setenv("DOCUMENT_ENCRYPTION_KEY", generate_key())
    monkeypatch.setenv("DATA_CONTROLLER_NAME", "Valinor Testes Ltda")
    monkeypatch.setenv("PRIVACY_CONTACT_EMAIL", "privacidade@example.com")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_FROM", "nao-responda@example.com")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://valinor.example.com")
    monkeypatch.setenv("CORS_ORIGINS", "https://valinor.example.com")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://valinor:strong-secret@db/valinor",
    )


def test_authentication_is_required_by_default(monkeypatch):
    monkeypatch.delenv("AUTH_REQUIRED", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("PLATFORM_SIGNING_SECRET", "test-signing-secret")
    get_settings.cache_clear()
    try:
        assert get_settings().auth_required is True
    finally:
        get_settings.cache_clear()


def test_production_forces_authentication(monkeypatch):
    _complete_production_environment(monkeypatch)
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    get_settings.cache_clear()
    try:
        assert get_settings().auth_required is True
    finally:
        get_settings.cache_clear()


def test_production_exige_controlador_e_canal_de_privacidade(monkeypatch):
    """Publicar sem dizer quem é o controlador e como o titular fala com ele
    deixa a política de privacidade sem endereço. O boot recusa."""
    import pytest

    _complete_production_environment(monkeypatch)
    monkeypatch.delenv("DATA_CONTROLLER_NAME", raising=False)
    monkeypatch.delenv("PRIVACY_CONTACT_EMAIL", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="DATA_CONTROLLER_NAME"):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_production_requires_transactional_email(monkeypatch):
    import pytest

    _complete_production_environment(monkeypatch)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="SMTP_HOST"):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_production_requires_public_https_url(monkeypatch):
    import pytest

    _complete_production_environment(monkeypatch)
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://localhost:8000")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="PUBLIC_BASE_URL"):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_production_rejects_wildcard_cors(monkeypatch):
    import pytest

    _complete_production_environment(monkeypatch)
    monkeypatch.setenv("CORS_ORIGINS", "*")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_production_rejects_sqlite(monkeypatch):
    import pytest

    _complete_production_environment(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./data/arbitragem.db")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="PostgreSQL"):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_production_rejects_default_database_password(monkeypatch):
    import pytest

    _complete_production_environment(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://valinor:change-this-password@db/valinor",
    )
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="senha padrão"):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_api_docs_default_to_disabled_in_production(monkeypatch):
    _complete_production_environment(monkeypatch)
    monkeypatch.delenv("EXPOSE_API_DOCS", raising=False)
    get_settings.cache_clear()
    try:
        assert get_settings().expose_api_docs is False
    finally:
        get_settings.cache_clear()


def test_production_rejects_development_signing_secret(monkeypatch):
    import pytest

    _complete_production_environment(monkeypatch)
    monkeypatch.setenv("PLATFORM_SIGNING_SECRET", "development-only-secret-change-me")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="PLATFORM_SIGNING_SECRET"):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_production_rejects_short_signing_secret(monkeypatch):
    import pytest

    _complete_production_environment(monkeypatch)
    monkeypatch.setenv("PLATFORM_SIGNING_SECRET", "curto-demais")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="32 caracteres"):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_production_rejects_same_judge_and_reviewer_when_llm_enabled(monkeypatch):
    import pytest

    _complete_production_environment(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.setenv("JUDGE_MODEL", "gpt-5-mini")
    monkeypatch.setenv("REVIEWER_MODEL", "gpt-5-mini")
    monkeypatch.setenv("JUDGE_PROVIDER", "openai")
    monkeypatch.setenv("REVIEWER_PROVIDER", "openai")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="julgador e o revisor"):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_defaults_use_openrouter_with_distinct_model_families(monkeypatch):
    from app.llm.models import families_are_independent, model_vendor

    monkeypatch.delenv("LLM_DEFAULT_PROVIDER", raising=False)
    monkeypatch.delenv("JUDGE_PROVIDER", raising=False)
    monkeypatch.delenv("REVIEWER_PROVIDER", raising=False)
    monkeypatch.delenv("JUDGE_MODEL", raising=False)
    monkeypatch.delenv("REVIEWER_MODEL", raising=False)
    monkeypatch.delenv("APPEAL_MODEL", raising=False)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.llm_default_provider == "openrouter"
        assert settings.judge_provider == "openrouter"
        assert settings.reviewer_provider == "openrouter"
        assert settings.appeal_provider == "openrouter"
        assert settings.embedding_provider == "openrouter"
        assert "/" in settings.judge_model
        assert families_are_independent(settings.judge_model, settings.reviewer_model)
        assert families_are_independent(settings.judge_model, settings.appeal_model)
        assert model_vendor(settings.embedding_model) == "openai"
        assert settings.model_independence_satisfied is True
    finally:
        get_settings.cache_clear()


def test_production_rejects_same_openrouter_family_when_llm_enabled(monkeypatch):
    import pytest

    _complete_production_environment(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-not-a-real-key")
    monkeypatch.setenv("JUDGE_PROVIDER", "openrouter")
    monkeypatch.setenv("REVIEWER_PROVIDER", "openrouter")
    monkeypatch.setenv("JUDGE_MODEL", "anthropic/claude-sonnet-4")
    monkeypatch.setenv("REVIEWER_MODEL", "anthropic/claude-3.7-sonnet")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="famílias distintas"):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_production_accepts_openrouter_defaults_when_key_is_set(monkeypatch):
    _complete_production_environment(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-not-a-real-key")
    monkeypatch.delenv("JUDGE_MODEL", raising=False)
    monkeypatch.delenv("REVIEWER_MODEL", raising=False)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.llm_enabled is True
        assert settings.openrouter_enabled is True
        assert settings.model_independence_satisfied is True
    finally:
        get_settings.cache_clear()


def test_bare_openai_model_ids_are_prefixed_for_openrouter(monkeypatch):
    monkeypatch.setenv("LLM_DEFAULT_PROVIDER", "openrouter")
    monkeypatch.setenv("JUDGE_PROVIDER", "openrouter")
    monkeypatch.setenv("JUDGE_MODEL", "gpt-4.1-mini")
    get_settings.cache_clear()
    try:
        assert get_settings().judge_model == "openai/gpt-4.1-mini"
    finally:
        get_settings.cache_clear()
