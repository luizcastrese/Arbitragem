import io
import os
import zipfile

import fitz
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

from app.db.models import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402

CASE_CREDENTIALS = {}


@pytest.fixture()
def client():
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


def create_case(client):
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
    credentials = case.pop("access_credentials")
    assert "manager" not in credentials
    assert set(credentials) == {"claimant", "respondent"}
    CASE_CREDENTIALS[case["id"]] = credentials
    return case


def actor_headers(case_id, party):
    return {"X-Actor-Token": CASE_CREDENTIALS[case_id][party]}


def register_user(client, name, email):
    response = client.post(
        "/auth/register",
        json={
            "display_name": name,
            "email": email,
            "password": "senha-segura-123",
        },
    )
    assert response.status_code == 201
    result = response.json()
    result["session_token"] = response.cookies.get("valinor_session")
    return result


def add_contract(client, case_id):
    response = client.post(
        f"/cases/{case_id}/documents/text",
        json={
            "name": "contrato.txt",
            "content": (
                "A Fornecedora entregará o sistema até 30 de junho. "
                "O pagamento será feito após aceite. A parte requerente afirma "
                "que apenas metade das funcionalidades foi entregue."
            ),
            "submitted_by": "claimant",
            "material_type": "evidence",
            "purpose": "Comprovar prazo, aceite e alegação de entrega parcial.",
        },
        headers=actor_headers(case_id, "claimant"),
    )
    assert response.status_code == 201
    return response.json()


def accept_procedure(client, case_id):
    for party in ("claimant", "respondent"):
        response = client.post(
            f"/cases/{case_id}/consent",
            json={"party": party, "accepted": True},
            headers=actor_headers(case_id, party),
        )
        assert response.status_code == 200
    return client.get(f"/cases/{case_id}").json()["consent"]


def complete_contradictory(client, case_id, document_id):
    acknowledgement = client.post(
        f"/cases/{case_id}/documents/{document_id}/acknowledge",
        json={"party": "respondent"},
        headers=actor_headers(case_id, "respondent"),
    )
    assert acknowledgement.status_code == 200
    response = client.post(
        f"/cases/{case_id}/documents/{document_id}/respond",
        json={
            "party": "respondent",
            "response_status": "answered",
            "response_text": "A empresa contesta a extensão da entrega parcial.",
        },
        headers=actor_headers(case_id, "respondent"),
    )
    assert response.status_code == 200
    admission = client.post(
        f"/cases/{case_id}/documents/{document_id}/admit",
        headers=actor_headers(case_id, "claimant"),
    )
    assert admission.status_code == 200
    return admission.json()


def prepare_locked_case(client):
    case_id = create_case(client)["id"]
    accept_procedure(client, case_id)
    document = add_contract(client, case_id)["document"]
    complete_contradictory(client, case_id, document["id"])
    locked = client.post(
        f"/cases/{case_id}/lock",
        headers=actor_headers(case_id, "claimant"),
    )
    assert locked.status_code == 200
    return case_id, document, locked


def test_complete_safe_flow_is_persistent_and_auditable(client):
    assert client.get("/health").json()["status"] == "ok"
    case = create_case(client)
    case_id = case["id"]
    consent = accept_procedure(client, case_id)
    assert consent["complete"] is True
    document = add_contract(client, case_id)["document"]
    assert document["chunks_count"] >= 1
    assert document["submitted_by"] == "claimant"
    assert document["disclosed_at"]
    complete_contradictory(client, case_id, document["id"])

    locked = client.post(
        f"/cases/{case_id}/lock",
        headers=actor_headers(case_id, "claimant"),
    )
    assert locked.status_code == 200
    assert locked.json()["manifest"]["platform_signature"]

    verification = client.get(f"/cases/{case_id}/manifest/verify").json()
    assert verification == {
        "valid": True,
        "hash_valid": True,
        "signature_valid": True,
    }

    conciliation = client.post(
        f"/cases/{case_id}/conciliation",
        headers=actor_headers(case_id, "claimant"),
    )
    assert conciliation.status_code == 200
    assert conciliation.json()["convergence"] == "undetermined"
    assert conciliation.json()["recommended_path"] == "adjudication"
    assert conciliation.json()["requires_party_consent"] is True
    assert conciliation.json()["round_number"] == 1
    assert conciliation.json()["continue_recommended"] is False

    second_round = client.post(
        f"/cases/{case_id}/conciliation",
        headers=actor_headers(case_id, "claimant"),
        json={
            "advance": True,
            "claimant_response": "Aceita discutir novo prazo.",
            "respondent_response": "Aceita avaliar entrega complementar.",
            "new_information": "As partes mantêm a relação comercial.",
        },
    )
    assert second_round.status_code == 200
    assert second_round.json()["round_number"] == 2

    organized = client.post(
        f"/cases/{case_id}/organize",
        headers=actor_headers(case_id, "claimant"),
    )
    assert organized.status_code == 200
    assert organized.json()["execution"]["mode"] == "safe_fallback"

    decision = client.post(
        f"/cases/{case_id}/decide",
        headers=actor_headers(case_id, "claimant"),
    )
    assert decision.status_code == 200
    assert decision.json()["outcome"] == "inconclusive"
    assert decision.json().get("requires_human_review") is None
    assert "provider_unavailable" in decision.json().get("abstention_reasons", [])
    assert decision.json()["confidence"] == 0.0
    assert "decisão de mérito" in decision.json()["decision"]

    review = client.post(
        f"/cases/{case_id}/review",
        headers=actor_headers(case_id, "claimant"),
    )
    assert review.status_code == 200
    assert review.json()["approved"] is False
    assert review.json().get("requires_human_review") is None
    assert review.json().get("outcome") in {"inconclusive", "rejected"}

    persisted = client.get(f"/cases/{case_id}").json()
    assert persisted["status"] == "reviewed"
    assert persisted["decision"]["outcome"] == "inconclusive"
    assert persisted["documents"][0]["sha256"] == document["sha256"]

    audit = client.get(f"/cases/{case_id}/audit").json()
    assert audit["valid"] is True
    assert audit["errors"] == []
    assert [event["event_type"] for event in audit["events"]] == [
        "case_created",
        "consent_accepted",
        "consent_accepted",
        "document_added",
        "evidence_disclosed",
        "notice_acknowledged",
        "response_submitted",
        "evidence_admitted",
        "manifest_locked",
        "conciliation_screened",
        "conciliation_round_generated",
        "case_organized",
        "decision_generated",
        "review_generated",
    ]

    report = client.get(f"/cases/{case_id}/report").json()
    assert report["status"] == "reviewed"
    assert report["manifest"]["manifest_hash"]
    assert report["consent"]["complete"] is True
    assert report["contradictory"]["complete"] is True
    assert report["documents"][0]["admitted"] is True
    assert report["conciliation"]["requires_party_consent"] is True
    assert len(report["conciliation_rounds"]) == 2
    assert report["review"]["approved"] is False
    assert "decisão computacional" in report["disclaimer"]


def test_accounts_invitations_deadlines_and_word_report(client):
    claimant = register_user(client, "Cliente Ana", "ana@example.com")
    claimant_session = claimant["session_token"]
    session_headers = {"X-Session-Token": claimant_session}

    created = client.post(
        "/cases",
        headers=session_headers,
        json={
            "title": "Cobrança contestada",
            "claimant": "Cliente Ana",
            "respondent": "Empresa Delta",
        },
    )
    assert created.status_code == 201
    case = created.json()
    case_id = case["id"]
    CASE_CREDENTIALS[case_id] = case["access_credentials"]
    assert case["participants"][0]["role"] == "claimant"
    assert case["participants"][0]["party"] == "claimant"
    assert "manager" not in (case.get("access_credentials") or CASE_CREDENTIALS[case_id])

    invite = client.post(
        f"/cases/{case_id}/invitations",
        headers={"X-Actor-Token": claimant_session},
        json={"email": "empresa@example.com", "role": "respondent"},
    )
    assert invite.status_code == 201
    invitation_token = invite.json()["acceptance_token"]
    assert invite.json()["status"] == "pending"
    assert invite.json()["party"] == "respondent"

    company = register_user(client, "Empresa Delta", "empresa@example.com")
    accepted = client.post(
        "/invitations/accept",
        headers={"X-Session-Token": company["session_token"]},
        json={"token": invitation_token},
    )
    assert accepted.status_code == 200
    assert accepted.json()["role"] == "respondent"

    company_case_list = client.get(
        "/cases",
        headers={"X-Session-Token": company["session_token"]},
    ).json()
    assert [item["id"] for item in company_case_list] == [case_id]

    document = client.post(
        f"/cases/{case_id}/documents/text",
        headers={"X-Actor-Token": claimant_session},
        json={
            "name": "relato.txt",
            "content": "O cliente contesta a cobrança porque o serviço foi cancelado.",
            "submitted_by": "claimant",
            "material_type": "argument",
            "purpose": "Explicar a contestação da cobrança.",
        },
    )
    assert document.status_code == 201

    deadline = client.post(
        f"/cases/{case_id}/deadlines",
        headers={"X-Actor-Token": claimant_session},
        json={
            "label": "Resposta da empresa",
            "kind": "response",
            "assigned_to": "respondent",
            "due_at": "2030-01-15T18:00:00Z",
        },
    )
    assert deadline.status_code == 201
    assert deadline.json()["status"] == "open"

    report = client.get(f"/cases/{case_id}/report.docx")
    assert report.status_code == 200
    assert report.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument"
    )
    with zipfile.ZipFile(io.BytesIO(report.content)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
    assert "Cobrança contestada" in document_xml
    assert "Resposta da empresa" in document_xml

    audit_types = [
        event["event_type"]
        for event in client.get(f"/cases/{case_id}/audit").json()["events"]
    ]
    assert "participant_invited" in audit_types
    assert "invitation_accepted" in audit_types
    assert "deadline_created" in audit_types


def test_documents_are_immutable_after_manifest_lock(client):
    case_id, document, _ = prepare_locked_case(client)

    response = client.post(
        f"/cases/{case_id}/documents/text",
        json={
            "name": "novo.txt",
            "content": "Tentativa de alteração.",
            "submitted_by": "respondent",
            "material_type": "argument",
            "purpose": "Nova alegação.",
        },
        headers=actor_headers(case_id, "respondent"),
    )
    assert response.status_code == 409

    acknowledgement = client.post(
        f"/cases/{case_id}/documents/{document['id']}/acknowledge",
        json={"party": "respondent"},
        headers=actor_headers(case_id, "respondent"),
    )
    replacement_response = client.post(
        f"/cases/{case_id}/documents/{document['id']}/respond",
        json={
            "party": "respondent",
            "response_status": "answered",
            "response_text": "Tentativa de substituir a resposta fixada.",
        },
        headers=actor_headers(case_id, "respondent"),
    )
    admission = client.post(
        f"/cases/{case_id}/documents/{document['id']}/admit",
        headers=actor_headers(case_id, "claimant"),
    )
    assert acknowledgement.status_code == 409
    assert replacement_response.status_code == 409
    assert admission.status_code == 409


def test_stages_are_idempotent(client):
    case_id = create_case(client)["id"]
    accept_procedure(client, case_id)
    document = add_contract(client, case_id)["document"]
    complete_contradictory(client, case_id, document["id"])

    first_lock = client.post(
        f"/cases/{case_id}/lock",
        headers=actor_headers(case_id, "claimant"),
    )
    second_lock = client.post(
        f"/cases/{case_id}/lock",
        headers=actor_headers(case_id, "claimant"),
    )
    assert first_lock.json()["manifest"] == second_lock.json()["manifest"]

    first_conciliation = client.post(
        f"/cases/{case_id}/conciliation",
        headers=actor_headers(case_id, "claimant"),
    ).json()
    second_conciliation = client.post(
        f"/cases/{case_id}/conciliation",
        headers=actor_headers(case_id, "claimant"),
    ).json()
    assert first_conciliation == second_conciliation

    first_organization = client.post(
        f"/cases/{case_id}/organize",
        headers=actor_headers(case_id, "claimant"),
    ).json()
    second_organization = client.post(
        f"/cases/{case_id}/organize",
        headers=actor_headers(case_id, "claimant"),
    ).json()
    assert first_organization == second_organization

    audit = client.get(f"/cases/{case_id}/audit").json()["events"]
    assert [event["event_type"] for event in audit].count("manifest_locked") == 1
    assert [event["event_type"] for event in audit].count("conciliation_screened") == 1
    assert [event["event_type"] for event in audit].count("case_organized") == 1


def test_pdf_upload_extracts_text(client):
    case_id = create_case(client)["id"]
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Contrato de prestação de serviços")
    content = pdf.tobytes()
    pdf.close()

    response = client.post(
        f"/cases/{case_id}/documents/pdf",
        data={
            "submitted_by": "respondent",
            "material_type": "evidence",
            "purpose": "Contrato apresentado pela empresa.",
        },
        files={"file": ("contrato.pdf", io.BytesIO(content), "application/pdf")},
        headers=actor_headers(case_id, "respondent"),
    )
    assert response.status_code == 201
    assert "Contrato de prestação" in response.json()["text_preview"]


def test_invalid_transition_and_payload_are_rejected(client):
    case_id = create_case(client)["id"]
    assert client.post(
        f"/cases/{case_id}/decide",
        headers=actor_headers(case_id, "claimant"),
    ).status_code == 409
    assert client.post(
        f"/cases/{case_id}/conciliation",
        headers=actor_headers(case_id, "claimant"),
    ).status_code == 409

    add_contract(client, case_id)
    assert client.post(
        f"/cases/{case_id}/lock",
        headers=actor_headers(case_id, "claimant"),
    ).status_code == 409
    accept_procedure(client, case_id)
    assert client.post(
        f"/cases/{case_id}/lock",
        headers=actor_headers(case_id, "claimant"),
    ).status_code == 409
    document_id = client.get(f"/cases/{case_id}").json()["documents"][0]["id"]
    complete_contradictory(client, case_id, document_id)
    assert client.post(
        f"/cases/{case_id}/lock",
        headers=actor_headers(case_id, "claimant"),
    ).status_code == 200
    assert client.post(
        f"/cases/{case_id}/organize",
        headers=actor_headers(case_id, "claimant"),
    ).status_code == 409

    invalid = client.post(
        "/cases",
        json={"title": "x", "claimant": "", "respondent": "B"},
    )
    assert invalid.status_code == 422


def test_counterparty_controls_acknowledgement_and_response(client):
    case_id = create_case(client)["id"]
    document = add_contract(client, case_id)["document"]

    wrong_party = client.post(
        f"/cases/{case_id}/documents/{document['id']}/acknowledge",
        json={"party": "claimant"},
        headers=actor_headers(case_id, "claimant"),
    )
    assert wrong_party.status_code == 403

    before_ack = client.post(
        f"/cases/{case_id}/documents/{document['id']}/respond",
        json={
            "party": "respondent",
            "response_status": "answered",
            "response_text": "Resposta antecipada.",
        },
        headers=actor_headers(case_id, "respondent"),
    )
    assert before_ack.status_code == 409


def test_decision_cannot_start_with_pending_contradictory(client):
    case_id = create_case(client)["id"]
    accept_procedure(client, case_id)
    add_contract(client, case_id)

    case = client.get(f"/cases/{case_id}").json()
    assert case["contradictory"]["complete"] is False
    assert case["contradictory"]["pending_document_ids"]
    assert client.post(
        f"/cases/{case_id}/lock",
        headers=actor_headers(case_id, "claimant"),
    ).status_code == 409
