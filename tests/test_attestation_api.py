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
os.environ["AUTH_REQUIRED"] = "false"

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
            "creator_role": "claimant",
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
    # Admissão, trava, composição, organização, decisão e auditoria são atos
    # do próprio rito: basta as duas partes encerrarem a produção de material.
    for party in ("claimant", "respondent"):
        assert (
            client.post(
                f"/cases/{case_id}/submission-complete",
                json={"closed": True},
                headers=_headers(case_id, party),
            ).status_code
            == 200
        )
    # Sem IA, o caso termina explicitamente sem decisão executável.
    assert client.get(f"/cases/{case_id}").json()["status"] == "unresolved"
    return case_id


def test_signing_key_is_published(client):
    response = client.get("/.well-known/valinor-signing-key")
    assert response.status_code == 200
    body = response.json()
    assert body["algorithm"] == "Ed25519"
    assert body["public_key_b64"]
    assert body["key_id"]


def test_safe_mode_case_never_yields_attestation(client):
    """O rito leva o caso até a auditoria sozinho, mas não emite attestation
    para uma decisão inconclusiva — nem quando é ele próprio quem conduz."""
    case_id = _reviewed_safe_case(client)
    assert (
        client.get(
            f"/cases/{case_id}/attestation",
            headers={"X-Session-Token": ""},
        ).status_code
        == 404
    )
    advanced = client.post(
        f"/cases/{case_id}/advance", headers=_headers(case_id, "claimant")
    )
    assert advanced.status_code == 200
    assert advanced.json()["attestation_issued"] is False


def test_contest_requires_attestation_and_party_credential(client):
    case_id = _reviewed_safe_case(client)
    # Sem attestation emitida, contestar é 409
    response = client.post(
        f"/cases/{case_id}/contest",
        json={"reason": "Discordo do resultado apresentado."},
        headers=_headers(case_id, "claimant"),
    )
    assert response.status_code == 409

    # Sem credencial de parte, contestar é 403. Não há terceiro no caso que
    # pudesse contestar em nome de alguém.
    response = client.post(
        f"/cases/{case_id}/contest",
        json={"reason": "Tentativa indevida de contestação."},
        headers={"X-Actor-Token": "credencial-que-nao-pertence-ao-caso"},
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


def _reserved_decision_case(client, monkeypatch, *, outcome="partial"):
    """Caso com decisão executável mas ressalvada pela auditoria: a execução
    automática está bloqueada e só a ratificação das partes a destrava."""
    from app.core import procedure

    monkeypatch.setattr(
        procedure,
        "assess_conciliation",
        lambda context, round_number: {
            "round_number": round_number,
            "convergence": "not_detected",
            "recommended_path": "adjudication",
            "neutral_summary": "Sem convergência.",
            "common_interests": [],
            "negotiable_issues": [],
            "non_negotiable_issues": [],
            "possible_terms": [],
            "reasoning": [],
            "confidence": 0.6,
            "continue_recommended": False,
            "recommended_additional_rounds": 0,
            "next_round_focus": "",
            "stop_reason": "Posições esgotadas.",
            "requires_party_consent": True,
            "execution": {"mode": "openai", "model": "fake", "reason": None},
        },
    )
    monkeypatch.setattr(
        procedure,
        "organizer_organize_case",
        lambda documents, chunks: {
            "factual_overview": "Entrega parcial.",
            "execution": {"mode": "openai", "model": "fake", "reason": None},
        },
    )
    monkeypatch.setattr(
        procedure,
        "judge_decide_case",
        lambda context: {
            "outcome": outcome,
            "partial_claimant_bps": 6000,
            "decision": "Divisão proporcional à entrega comprovada.",
            "confidence": 0.55,
            "requires_human_review": True,
            "execution": {"mode": "openai", "model": "fake", "reason": None},
        },
    )
    monkeypatch.setattr(
        procedure,
        "review_decision",
        lambda payload: {
            "approved": False,
            "requires_human_review": True,
            "risks": ["Confiança baixa na proporção adotada."],
            "execution": {"mode": "openai", "model": "fake", "reason": None},
        },
    )
    return _reviewed_case_id(client)


def _reviewed_case_id(client):
    response = client.post(
        "/cases",
        json={
            "title": "Entrega parcial de software",
            "claimant": "Empresa Alfa",
            "respondent": "Fornecedor Beta",
            "creator_role": "claimant",
        },
    )
    case = response.json()
    case_id = case["id"]
    CASE_CREDENTIALS[case_id] = case["access_credentials"]
    for party in ("claimant", "respondent"):
        client.post(
            f"/cases/{case_id}/consent",
            json={"party": party, "accepted": True},
            headers=_headers(case_id, party),
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
    client.post(
        f"/cases/{case_id}/documents/{document['id']}/acknowledge",
        json={"party": "respondent"},
        headers=_headers(case_id, "respondent"),
    )
    client.post(
        f"/cases/{case_id}/documents/{document['id']}/respond",
        json={
            "party": "respondent",
            "response_status": "answered",
            "response_text": "A empresa contesta a extensão da entrega parcial.",
        },
        headers=_headers(case_id, "respondent"),
    )
    for party in ("claimant", "respondent"):
        client.post(
            f"/cases/{case_id}/submission-complete",
            json={"closed": True},
            headers=_headers(case_id, party),
        )
    return case_id


def test_party_ratification_unlocks_execution_and_is_recorded_in_the_artifact(
    client, monkeypatch
):
    """A ratificação das duas partes supera a ressalva da auditoria — e a
    attestation diz, de forma assinada, que a execução se apoia nela."""
    case_id = _reserved_decision_case(client, monkeypatch)
    assert client.get(f"/cases/{case_id}").json()["status"] == "ratification"

    for party in ("claimant", "respondent"):
        assert (
            client.post(
                f"/cases/{case_id}/ratification",
                json={"accepted": True},
                headers=_headers(case_id, party),
            ).status_code
            == 200
        )

    attestation = client.get(f"/cases/{case_id}/attestation").json()
    assert attestation["basis"] == "party_ratification"
    assert attestation["ratification"]["ratified"] is True
    assert attestation["ratification"]["claimant_at"]
    assert attestation["ratification"]["respondent_at"]
    assert attestation["decision"]["split"] == {
        "claimant_bps": 6000,
        "respondent_bps": 4000,
    }
    # A ressalva continua visível no artefato: a ratificação não a apaga.
    assert attestation["review"]["approved"] is False

    verified = client.post(
        "/attestations/verify", json={"attestation": attestation}
    ).json()
    assert verified["valid"] is True


def test_a_party_that_ratified_cannot_then_contest(client, monkeypatch):
    case_id = _reserved_decision_case(client, monkeypatch)
    for party in ("claimant", "respondent"):
        client.post(
            f"/cases/{case_id}/ratification",
            json={"accepted": True},
            headers=_headers(case_id, party),
        )
    assert client.get(f"/cases/{case_id}/attestation").status_code == 200

    contested = client.post(
        f"/cases/{case_id}/contest",
        json={"reason": "Mudei de ideia sobre a proporção adotada."},
        headers=_headers(case_id, "claimant"),
    )
    assert contested.status_code == 409
    assert "ratificou" in contested.json()["detail"]


def test_ratification_never_makes_an_inconclusive_decision_executable(
    client, monkeypatch
):
    """A ratificação supera ressalvas de mérito, nunca a ausência de
    resultado: decisão inconclusiva não tem split a executar."""
    case_id = _reserved_decision_case(client, monkeypatch, outcome="inconclusive")

    case = client.get(f"/cases/{case_id}").json()
    assert case["status"] == "unresolved"
    assert case["ratification"]["open"] is False
    assert client.get(f"/cases/{case_id}/attestation").status_code == 404
