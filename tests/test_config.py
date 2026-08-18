from app.core.config import get_settings


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
    from app.core.encryption import generate_key

    monkeypatch.setenv("AUTH_REQUIRED", "false")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PLATFORM_SIGNING_SECRET", "test-signing-secret")
    monkeypatch.setenv("DOCUMENT_ENCRYPTION_KEY", generate_key())
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://valinor.exemplo.com")
    get_settings.cache_clear()
    try:
        assert get_settings().auth_required is True
    finally:
        get_settings.cache_clear()


def test_production_rejects_a_local_public_base_url(monkeypatch):
    """O link de aceite é o único caminho de entrada da contraparte.

    Apontando para localhost ele nasce inutilizável, e o caso fica parado
    esperando alguém que nunca conseguirá entrar.
    """
    import pytest

    from app.core.encryption import generate_key

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PLATFORM_SIGNING_SECRET", "test-signing-secret")
    monkeypatch.setenv("DOCUMENT_ENCRYPTION_KEY", generate_key())
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://localhost:8000")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="PUBLIC_BASE_URL"):
            get_settings()

        monkeypatch.setenv("PUBLIC_BASE_URL", "https://valinor.exemplo.com/")
        get_settings.cache_clear()
        assert get_settings().public_base_url == "https://valinor.exemplo.com"
    finally:
        get_settings.cache_clear()
