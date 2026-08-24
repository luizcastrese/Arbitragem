"""Ciclo de vida da conta: verificação de e-mail, redefinição de senha e
bloqueio por tentativas. É a camada que sustenta a afirmação de que cada ato do
procedimento pertence a uma pessoa identificada."""

import dataclasses
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("PLATFORM_SIGNING_SECRET", "test-signing-secret")

from app.core import config  # noqa: E402

config.get_settings.cache_clear()

from app.db.models import Base, User  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app import main  # noqa: E402


PASSWORD = "senha-bem-comprida-1"


def override_settings(monkeypatch, **changes):
    """`Settings` é congelado de propósito: para variar uma opção no teste,
    troca-se a instância inteira nos pontos que a leem."""
    from app.db import access_repository

    replaced = dataclasses.replace(main.settings, **changes)
    monkeypatch.setattr(main, "settings", replaced)
    monkeypatch.setattr(config, "get_settings", lambda: replaced)
    monkeypatch.setattr(access_repository, "get_settings", lambda: replaced)
    return replaced


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(bind=engine)
    yield factory
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(session_factory):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[get_db] = override_get_db
    with TestClient(main.app) as test_client:
        yield test_client
    main.app.dependency_overrides.clear()


def register(client, email="parte@example.com", password=PASSWORD):
    response = client.post(
        "/auth/register",
        json={"display_name": "Parte Teste", "email": email, "password": password},
    )
    assert response.status_code == 201, response.text
    return response.json()


# --- verificação de e-mail --------------------------------------------------


def test_new_account_starts_unverified_and_receives_a_token(client):
    body = register(client)
    assert body["user"]["email_verified"] is False
    # Modo local: sem SMTP configurado o token volta na resposta.
    assert body["email_verification"]["verification_token"]
    assert body["email_verification"]["delivery"]["transport"] == "log"


def test_verification_token_is_single_use(client):
    token = register(client)["email_verification"]["verification_token"]

    first = client.post("/auth/verify-email", json={"token": token})
    assert first.status_code == 200
    assert first.json()["user"]["email_verified"] is True

    second = client.post("/auth/verify-email", json={"token": token})
    assert second.status_code == 409


def test_resend_invalidates_the_previous_verification_link(client):
    first_token = register(client)["email_verification"]["verification_token"]

    resent = client.post("/auth/verify-email/resend")
    assert resent.status_code == 200
    second_token = resent.json()["email_verification"]["verification_token"]
    assert second_token != first_token

    assert client.post("/auth/verify-email", json={"token": first_token}).status_code == 409
    assert client.post("/auth/verify-email", json={"token": second_token}).status_code == 200


def test_unknown_verification_token_is_rejected(client):
    response = client.post("/auth/verify-email", json={"token": "x" * 40})
    assert response.status_code == 409


def test_case_actions_require_a_verified_email_when_enforced(client, monkeypatch):
    register(client)
    override_settings(monkeypatch, email_verification_required=True)

    blocked = client.post(
        "/cases",
        json={"title": "Caso bloqueado", "claimant": "Cliente", "respondent": "Empresa"},
    )
    assert blocked.status_code == 403
    assert "Confirme seu e-mail" in blocked.json()["detail"]


def test_case_actions_are_released_after_verification(client, monkeypatch):
    token = register(client)["email_verification"]["verification_token"]
    client.post("/auth/verify-email", json={"token": token})
    override_settings(monkeypatch, email_verification_required=True)

    allowed = client.post(
        "/cases",
        json={"title": "Caso liberado", "claimant": "Cliente", "respondent": "Empresa"},
    )
    assert allowed.status_code == 201


# --- redefinição de senha ---------------------------------------------------


def test_password_reset_response_never_reveals_whether_the_account_exists(client):
    register(client, email="existe@example.com")

    known = client.post("/auth/password-reset", json={"email": "existe@example.com"})
    unknown = client.post("/auth/password-reset", json={"email": "ninguem@example.com"})

    assert known.status_code == unknown.status_code == 202
    assert known.json()["message"] == unknown.json()["message"]
    assert "reset_token" in known.json()
    assert "reset_token" not in unknown.json()


def test_password_reset_changes_the_password_and_drops_open_sessions(client, session_factory):
    register(client, email="reset@example.com")
    token = client.post(
        "/auth/password-reset", json={"email": "reset@example.com"}
    ).json()["reset_token"]

    # A sessão criada no cadastro ainda vale antes da redefinição.
    assert client.get("/auth/me").status_code == 200

    confirmed = client.post(
        "/auth/password-reset/confirm",
        json={"token": token, "password": "outra-senha-longa-9"},
    )
    assert confirmed.status_code == 200
    # Concluir a redefinição prova o controle do e-mail.
    assert confirmed.json()["user"]["email_verified"] is True

    client.cookies.clear()
    assert client.get("/auth/me").status_code == 401
    assert client.post(
        "/auth/login", json={"email": "reset@example.com", "password": PASSWORD}
    ).status_code == 401
    assert client.post(
        "/auth/login",
        json={"email": "reset@example.com", "password": "outra-senha-longa-9"},
    ).status_code == 200


def test_reset_token_cannot_be_reused(client):
    register(client, email="reuso@example.com")
    token = client.post(
        "/auth/password-reset", json={"email": "reuso@example.com"}
    ).json()["reset_token"]

    payload = {"token": token, "password": "senha-nova-suficiente"}
    assert client.post("/auth/password-reset/confirm", json=payload).status_code == 200
    assert client.post("/auth/password-reset/confirm", json=payload).status_code == 409


def test_verification_token_is_not_accepted_as_a_reset_token(client):
    verification = register(client, email="cruzado@example.com")
    token = verification["email_verification"]["verification_token"]
    response = client.post(
        "/auth/password-reset/confirm",
        json={"token": token, "password": "senha-nova-suficiente"},
    )
    assert response.status_code == 409


# --- bloqueio por tentativas ------------------------------------------------


def test_repeated_wrong_passwords_lock_the_account(client, session_factory, monkeypatch):
    register(client, email="forca@example.com")
    override_settings(monkeypatch, login_max_attempts=3, login_lockout_seconds=900)

    wrong = {"email": "forca@example.com", "password": "senha-errada-longa"}
    assert client.post("/auth/login", json=wrong).status_code == 401
    assert client.post("/auth/login", json=wrong).status_code == 401

    locked = client.post("/auth/login", json=wrong)
    assert locked.status_code == 429
    assert locked.headers["Retry-After"]

    # Enquanto durar o bloqueio, nem a senha correta entra.
    still_locked = client.post(
        "/auth/login", json={"email": "forca@example.com", "password": PASSWORD}
    )
    assert still_locked.status_code == 429

    with session_factory() as db:
        user = db.query(User).filter(User.email == "forca@example.com").one()
        assert user.locked_until is not None


def test_successful_login_clears_the_attempt_counter(client, session_factory, monkeypatch):
    register(client, email="limpa@example.com")
    override_settings(monkeypatch, login_max_attempts=3)

    client.post(
        "/auth/login",
        json={"email": "limpa@example.com", "password": "senha-errada-longa"},
    )
    assert client.post(
        "/auth/login", json={"email": "limpa@example.com", "password": PASSWORD}
    ).status_code == 200

    with session_factory() as db:
        user = db.query(User).filter(User.email == "limpa@example.com").one()
        assert user.failed_login_attempts == 0
        assert user.locked_until is None


def test_auth_routes_have_their_own_narrow_rate_limit(client, monkeypatch):
    monkeypatch.setattr(main.auth_rate_limiter, "max_requests", 3, raising=False)
    main.auth_rate_limiter.reset()

    payload = {"email": "quem@example.com", "password": "qualquer-senha-longa"}
    for _ in range(3):
        client.post("/auth/login", json=payload)

    blocked = client.post("/auth/login", json=payload)
    assert blocked.status_code == 429
    assert "Muitas tentativas" in blocked.json()["detail"]
    # O limite é das rotas de credencial: as demais seguem atendendo.
    assert client.get("/health").status_code == 200
