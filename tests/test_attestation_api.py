"""Testes de API do enforcement: em modo seguro (sem OpenAI) a decisão é
inconclusiva e a auditoria reprova — nenhuma attestation pode ser emitida."""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["OPENAI_API_KEY"] = ""
os.environ["PLATFORM_SIGNING_SECRET"] = "test-signing-secret"

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.core.attestation import generate_private_key_b64  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402

CASE_CREDENTIALS = {}
TEST_KEY_B64 = generate_private_key_b64()


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("PLATFORM_ED25519_PRIVATE_KEY", TEST_KEY_B64)
    get_settings.cache_clear()
    CASE_CREDENTIALS.clear()
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

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    get_settings.cache_clear()


def _headers(case_id, party):
    return {"X-Actor-Token": CASE_CREDENTIALS[case_id][party]}


def _reviewed_safe_case(client):
    response = client.post(
        "/cases",
        json={
            "title": "Entrega parcial de software",
            "claimant": "Empresa Alfa",
            "respondent": "Fornecedor Beta",
        },
    )
    assert response.status_code == 201
    case = response.json()
    case_id = case["id"]
    CASE_CREDENTIALS[case_id] = case["access_credentials"]

    for party in ("claimant", "respondent"):
        assert (
            client.post(
                f"/cases/{case_id}/consent",
                json={"party": party, "accepted": True},
                headers=_headers(case_id, party),
            ).status_code
            == 200
        )

    document = client.post(
        f"/cases/{case_id}/documents/text",
        json={
            "name": "contrato.txt",
            "content": "Entrega até 30 de junho. Alegação de entrega parcial.",
            "submitted_by": "claimant",
            "material_type": "evidence",
            "purpose": "Comprovar prazo e alegação.",
        },
        headers=_headers(case_id, "claimant"),
    ).json()["document"]

    assert (
        client.post(
            f"/cases/{case_id}/documents/{document['id']}/acknowledge",
            json={"party": "respondent"},
            headers=_headers(case_id, "respondent"),
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/cases/{case_id}/documents/{document['id']}/respond",
            json={
                "party": "respondent",
                "response_status": "answered",
                "response_text": "A empresa contesta a extensão da entrega parcial.",
            },
            headers=_headers(case_id, "respondent"),
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/cases/{case_id}/documents/{document['id']}/admit",
            headers=_headers(case_id, "manager"),
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/cases/{case_id}/lock", headers=_headers(case_id, "manager")
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/cases/{case_id}/conciliation", headers=_headers(case_id, "manager")
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/cases/{case_id}/organize", headers=_headers(case_id, "manager")
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/cases/{case_id}/decide", headers=_headers(case_id, "manager")
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/cases/{case_id}/review", headers=_headers(case_id, "manager")
        ).status_code
        == 200
    )
    return case_id


def test_signing_key_is_published(client):
    response = client.get("/.well-known/valinor-signing-key")
    assert response.status_code == 200
    body = response.json()
    assert body["algorithm"] == "Ed25519"
    assert body["public_key_b64"]
    assert body["key_id"]


def test_safe_mode_case_never_yields_attestation(client):
    case_id = _reviewed_safe_case(client)
    response = client.post(
        f"/cases/{case_id}/attestation", headers=_headers(case_id, "manager")
    )
    assert response.status_code == 409
    assert (
        client.get(
            f"/cases/{case_id}/attestation",
            headers={"X-Session-Token": ""},
        ).status_code
        == 404
    )


def test_contest_requires_attestation_and_party_credential(client):
    case_id = _reviewed_safe_case(client)
    # Sem attestation emitida, contestar é 409
    response = client.post(
        f"/cases/{case_id}/contest",
        json={"reason": "Discordo do resultado apresentado."},
        headers=_headers(case_id, "claimant"),
    )
    assert response.status_code == 409

    # Gestor não pode contestar
    response = client.post(
        f"/cases/{case_id}/contest",
        json={"reason": "Tentativa indevida de contestação."},
        headers=_headers(case_id, "manager"),
    )
    assert response.status_code == 403


def test_stateless_verify_rejects_garbage(client):
    response = client.post(
        "/attestations/verify",
        json={"attestation": {"attestation_hash": "00", "signature": "AA=="}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
