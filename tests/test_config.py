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
    get_settings.cache_clear()
    try:
        assert get_settings().auth_required is True
    finally:
        get_settings.cache_clear()
