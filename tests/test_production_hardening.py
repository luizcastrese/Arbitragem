import importlib
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("PLATFORM_SIGNING_SECRET", "test-signing-secret")

from app.core import config  # noqa: E402
from app.core.email import (  # noqa: E402
    build_accept_url,
    build_invitation_message,
    deliver_invitation_email,
)
from app.core.ratelimit import SlidingWindowRateLimiter  # noqa: E402

config.get_settings.cache_clear()

from app.db.models import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app import main  # noqa: E402


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[get_db] = override_get_db
    with TestClient(main.app) as test_client:
        yield test_client
    main.app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


# --- Rate limiter (lógica pura) ---------------------------------------------


def test_sliding_window_blocks_after_capacity():
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60)
    assert limiter.allow("ip", now=0.0)[0] is True
    assert limiter.allow("ip", now=1.0)[0] is True
    allowed, retry_after = limiter.allow("ip", now=2.0)
    assert allowed is False
    assert retry_after > 0


def test_sliding_window_recovers_after_window():
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=10)
    assert limiter.allow("ip", now=0.0)[0] is True
    assert limiter.allow("ip", now=5.0)[0] is False
    # Passada a janela, a primeira marca expira e a chamada volta a ser aceita.
    assert limiter.allow("ip", now=11.0)[0] is True


def test_sliding_window_isolates_keys():
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
    assert limiter.allow("a", now=0.0)[0] is True
    assert limiter.allow("b", now=0.0)[0] is True
    assert limiter.allow("a", now=0.0)[0] is False


# --- Middleware ---------------------------------------------------------------


def test_request_id_header_is_present(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID")


def test_rate_limit_middleware_returns_429(client):
    limiter = main.rate_limiter
    original_enabled = limiter.enabled
    original_max = limiter.max_requests
    limiter.reset()
    limiter.enabled = True
    limiter.max_requests = 2
    try:
        assert client.get("/health").status_code == 200
        assert client.get("/health").status_code == 200
        blocked = client.get("/health")
        assert blocked.status_code == 429
        assert blocked.headers.get("Retry-After")
        assert blocked.headers.get("X-Request-ID")
    finally:
        limiter.enabled = original_enabled
        limiter.max_requests = original_max
        limiter.reset()


# --- E-mail de convite --------------------------------------------------------


def test_build_accept_url():
    assert (
        build_accept_url("http://localhost:8000", "abc")
        == "http://localhost:8000/ui/?invite=abc"
    )


def test_invitation_message_contents():
    message = build_invitation_message(
        to_email="cliente@example.com",
        role="claimant",
        case_title="Cobrança contestada",
        accept_url="http://localhost:8000/ui/?invite=tok",
        sender="no-reply@valinor.example",
    )
    assert message["To"] == "cliente@example.com"
    assert "Cobrança contestada" in message["Subject"]
    body = message.get_content()
    assert "parte reclamante" in body
    assert "http://localhost:8000/ui/?invite=tok" in body


def test_deliver_invitation_falls_back_to_log_when_unconfigured():
    config.get_settings.cache_clear()
    result = deliver_invitation_email(
        to_email="cliente@example.com",
        role="claimant",
        case_title="Caso X",
        token="tok",
    )
    assert result == {"delivered": False, "transport": "log"}


def test_invitation_endpoint_reports_email_delivery(client):
    registration = client.post(
        "/auth/register",
        json={
            "display_name": "Gestora Ana",
            "email": "gestora@example.com",
            "password": "senha-segura-123",
        },
    )
    manager_token = registration.cookies.get("valinor_session")
    created = client.post(
        "/cases",
        headers={"X-Session-Token": manager_token},
        json={
            "title": "Cobrança contestada",
            "claimant": "Cliente Carlos",
            "respondent": "Empresa Delta",
        },
    ).json()
    invite = client.post(
        f"/cases/{created['id']}/invitations",
        headers={"X-Actor-Token": manager_token},
        json={"email": "cliente@example.com", "role": "claimant"},
    )
    assert invite.status_code == 201
    body = invite.json()
    assert body["email_delivery"] == {"delivered": False, "transport": "log"}
    # No modo local o token continua disponível para o fluxo sem e-mail.
    assert body["acceptance_token"]


# --- Postura de produção ------------------------------------------------------


def test_production_forces_auth_and_disables_role_tokens(monkeypatch):
    from app.core.encryption import generate_key

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PLATFORM_SIGNING_SECRET", "a-very-long-production-secret-value")
    monkeypatch.setenv("DOCUMENT_ENCRYPTION_KEY", generate_key())
    config.get_settings.cache_clear()
    try:
        settings = config.get_settings()
        assert settings.is_production is True
        assert settings.auth_required is True
        assert settings.allow_role_tokens is False
        assert settings.rate_limit_enabled is True
    finally:
        config.get_settings.cache_clear()


def test_production_requires_document_encryption_key(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PLATFORM_SIGNING_SECRET", "a-very-long-production-secret-value")
    monkeypatch.delenv("DOCUMENT_ENCRYPTION_KEY", raising=False)
    config.get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="DOCUMENT_ENCRYPTION_KEY"):
            config.get_settings()
    finally:
        config.get_settings.cache_clear()
