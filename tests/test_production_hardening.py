import dataclasses
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
    manager = client.post(
        "/auth/register",
        json={
            "display_name": "Gestora Ana",
            "email": "gestora@example.com",
            "password": "senha-segura-123",
        },
    ).json()
    created = client.post(
        "/cases",
        headers={"X-Session-Token": manager["session_token"]},
        json={
            "title": "Cobrança contestada",
            "claimant": "Cliente Carlos",
            "respondent": "Empresa Delta",
        },
    ).json()
    invite = client.post(
        f"/cases/{created['id']}/invitations",
        headers={"X-Actor-Token": manager["session_token"]},
        json={"email": "cliente@example.com", "role": "claimant"},
    )
    assert invite.status_code == 201
    body = invite.json()
    assert body["email_delivery"] == {"delivered": False, "transport": "log"}
    # No modo local o token continua disponível para o fluxo sem e-mail.
    assert body["acceptance_token"]


# --- Postura de produção ------------------------------------------------------


def test_production_forces_auth_and_disables_role_tokens(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PLATFORM_SIGNING_SECRET", "a-very-long-production-secret-value")
    config.get_settings.cache_clear()
    try:
        settings = config.get_settings()
        assert settings.is_production is True
        assert settings.auth_required is True
        assert settings.allow_role_tokens is False
        assert settings.rate_limit_enabled is True
    finally:
        config.get_settings.cache_clear()


# --- Entrega do convite -------------------------------------------------------


def _as_production(settings):
    """Settings é um dataclass congelado; a postura de produção vira uma cópia."""
    return dataclasses.replace(settings, app_env="production", auth_required=True)


def _manager_session(client):
    return client.post(
        "/auth/register",
        json={
            "display_name": "Gestora Ana",
            "email": "gestora-convites@example.com",
            "password": "senha-segura-123",
        },
    ).json()["session_token"]


def _case_for(client, session_token):
    return client.post(
        "/cases",
        headers={"X-Session-Token": session_token},
        json={
            "title": "Cobrança contestada",
            "claimant": "Cliente Carlos",
            "respondent": "Empresa Delta",
        },
    ).json()["id"]


def test_acceptance_link_is_returned_when_email_was_not_delivered():
    # Sem SMTP o convite não chega a ninguém; devolver o link é o que impede
    # que o caso trave sem nenhuma das partes conseguir entrar.
    fields = main._acceptance_fields("tok", {"delivered": False, "transport": "log"})
    assert fields["acceptance_token"] == "tok"
    assert fields["acceptance_path"] == "/ui/?invite=tok"


def test_acceptance_link_is_withheld_in_production_when_email_was_delivered(monkeypatch):
    monkeypatch.setattr(main, "settings", _as_production(main.settings))
    assert main._acceptance_fields("tok", {"delivered": True, "transport": "smtp"}) == {}


def test_resend_invitation_issues_a_new_usable_token(client):
    session = _manager_session(client)
    case_id = _case_for(client, session)
    created = client.post(
        f"/cases/{case_id}/invitations",
        headers={"X-Actor-Token": session},
        json={"email": "cliente@example.com", "role": "claimant"},
    ).json()

    resent = client.post(
        f"/cases/{case_id}/invitations/{created['id']}/resend",
        headers={"X-Actor-Token": session},
    )
    assert resent.status_code == 200
    body = resent.json()
    assert body["id"] == created["id"]
    assert body["status"] == "pending"
    assert body["acceptance_token"] != created["acceptance_token"]

    invitee = client.post(
        "/auth/register",
        json={
            "display_name": "Cliente Carlos",
            "email": "cliente@example.com",
            "password": "senha-segura-123",
        },
    ).json()["session_token"]

    # O token antigo morre com o reenvio; só o novo abre o caso.
    stale = client.post(
        "/invitations/accept",
        headers={"X-Session-Token": invitee},
        json={"token": created["acceptance_token"]},
    )
    assert stale.status_code == 409
    accepted = client.post(
        "/invitations/accept",
        headers={"X-Session-Token": invitee},
        json={"token": body["acceptance_token"]},
    )
    assert accepted.status_code == 200
    assert accepted.json()["role"] == "claimant"


def test_resend_rejects_an_already_accepted_invitation(client):
    session = _manager_session(client)
    case_id = _case_for(client, session)
    created = client.post(
        f"/cases/{case_id}/invitations",
        headers={"X-Actor-Token": session},
        json={"email": "cliente@example.com", "role": "claimant"},
    ).json()
    invitee = client.post(
        "/auth/register",
        json={
            "display_name": "Cliente Carlos",
            "email": "cliente@example.com",
            "password": "senha-segura-123",
        },
    ).json()["session_token"]
    client.post(
        "/invitations/accept",
        headers={"X-Session-Token": invitee},
        json={"token": created["acceptance_token"]},
    )

    blocked = client.post(
        f"/cases/{case_id}/invitations/{created['id']}/resend",
        headers={"X-Actor-Token": session},
    )
    assert blocked.status_code == 409


def test_resend_requires_the_manager_role(client):
    session = _manager_session(client)
    case_id = _case_for(client, session)
    created = client.post(
        f"/cases/{case_id}/invitations",
        headers={"X-Actor-Token": session},
        json={"email": "cliente@example.com", "role": "claimant"},
    ).json()
    outsider = client.post(
        "/auth/register",
        json={
            "display_name": "Terceiro",
            "email": "terceiro@example.com",
            "password": "senha-segura-123",
        },
    ).json()["session_token"]

    denied = client.post(
        f"/cases/{case_id}/invitations/{created['id']}/resend",
        headers={"X-Actor-Token": outsider},
    )
    assert denied.status_code == 403


# --- Criação de caso ----------------------------------------------------------


def test_case_creation_requires_a_session_when_auth_is_required(client, monkeypatch):
    # Um caso sem gestor vinculado nasceria órfão: em produção os tokens por
    # papel não valem e ninguém conseguiria voltar a ele.
    monkeypatch.setattr(main, "settings", _as_production(main.settings))
    anonymous = client.post(
        "/cases",
        json={
            "title": "Cobrança contestada",
            "claimant": "Cliente Carlos",
            "respondent": "Empresa Delta",
        },
    )
    assert anonymous.status_code == 401


def test_case_creation_binds_the_authenticated_manager(client):
    session = _manager_session(client)
    case_id = _case_for(client, session)
    listed = client.get("/cases", headers={"X-Session-Token": session}).json()
    assert case_id in [item["id"] for item in listed]
