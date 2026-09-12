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
    monkeypatch.setenv("DATA_CONTROLLER_NAME", "Valinor Testes Ltda")
    monkeypatch.setenv("PRIVACY_CONTACT_EMAIL", "privacidade@example.com")
    get_settings.cache_clear()
    try:
        assert get_settings().auth_required is True
    finally:
        get_settings.cache_clear()


def test_production_exige_controlador_e_canal_de_privacidade(monkeypatch):
    """Publicar sem dizer quem é o controlador e como o titular fala com ele
    deixa a política de privacidade sem endereço. O boot recusa."""
    import pytest

    from app.core.encryption import generate_key

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PLATFORM_SIGNING_SECRET", "test-signing-secret")
    monkeypatch.setenv("DOCUMENT_ENCRYPTION_KEY", generate_key())
    monkeypatch.delenv("DATA_CONTROLLER_NAME", raising=False)
    monkeypatch.delenv("PRIVACY_CONTACT_EMAIL", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="DATA_CONTROLLER_NAME"):
            get_settings()
    finally:
        get_settings.cache_clear()
