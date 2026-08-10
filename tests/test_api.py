from datetime import timedelta
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


def create_case(client, creator_role="claimant"):
    response = client.post(
        "/cases",
        json={
            "title": "Entrega parcial de software",
            "claimant": "Empresa Alfa",
            "respondent": "Fornecedor Beta",
            "creator_role": creator_role,
        },
    )
    assert response.status_code == 201
    case = response.json()
    CASE_CREDENTIALS[case["id"]] = case.pop("access_credentials")
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
    return response.json()


def close_submissions(client, case_id, parties=("claimant", "respondent")):
    result = None
    for party in parties:
        response = client.post(
            f"/cases/{case_id}/submission-complete",
            json={"closed": True},
            headers=actor_headers(case_id, party),
        )
        assert response.status_code == 200
        result = response.json()
    return result


def prepare_locked_case(client):
    case_id = create_case(client)["id"]
    accept_procedure(client, case_id)
    document = add_contract(client, case_id)["document"]
    complete_contradictory(client, case_id, document["id"])
    final = close_submissions(client, case_id)
    assert final["manifest_locked"] is True
    return case_id, document, final


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

    # O material ainda não foi admitido: falta o contraditório.
    assert client.get(f"/cases/{case_id}").json()["documents"][0]["admitted"] is False

    complete_contradictory(client, case_id, document["id"])

    # Cumprido o contraditório, o próprio rito admitiu o material. Nenhum
    # terceiro humano interveio.
    admitted = client.get(f"/cases/{case_id}").json()["documents"][0]
    assert admitted["admitted"] is True
    assert admitted["contradictory_complete"] is True

    # Sem o encerramento das duas partes, o rito não trava nada.
    assert client.get(f"/cases/{case_id}").json()["manifest_locked"] is False

    final = close_submissions(client, case_id)
    assert final["manifest_locked"] is True
    assert final["locked_manifest"]["platform_signature"]

    verification = client.get(f"/cases/{case_id}/manifest/verify").json()
    assert verification == {
        "valid": True,
        "hash_valid": True,
        "signature_valid": True,
    }

    # Em modo seguro a triagem não recomenda novas rodadas, e o rito segue
    # sozinho até a auditoria.
    persisted = client.get(f"/cases/{case_id}").json()
    assert persisted["status"] == "reviewed"
    assert persisted["conciliation"]["convergence"] == "undetermined"
    assert persisted["conciliation"]["recommended_path"] == "human_screening"
    assert persisted["conciliation"]["continue_recommended"] is False
    assert persisted["organized"]["execution"]["mode"] == "safe_fallback"
    assert persisted["decision"]["outcome"] == "inconclusive"
    assert persisted["decision"]["requires_human_review"] is True
    assert persisted["review"]["approved"] is False
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
        "deadline_created",
        "notice_acknowledged",
        "response_submitted",
        "evidence_admitted",
        "deadline_completed",
        # Cumprido o contraditório, o rito abre o prazo de encerramento de
        # produção para cada parte — é o que torna a preclusão possível.
        "deadline_created",
        "deadline_created",
        "submission_closed",
        "deadline_completed",
        "submission_closed",
        "deadline_completed",
        "manifest_locked",
        "conciliation_screened",
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
    assert report["review"]["approved"] is False
    assert "decisão computacional" in report["disclaimer"]


def test_no_act_of_the_procedure_is_attributed_to_a_human_third_party(client):
    """Toda etapa conduzida pelo rito é registrada como `actor: procedure`, e
    toda etapa das partes é registrada com o papel da parte. Não existe um
    terceiro humano na cadeia de auditoria."""
    case_id, _, _ = prepare_locked_case(client)

    events = client.get(f"/cases/{case_id}/audit").json()["events"]
    actors_by_event = {
        event["event_type"]: event["payload"].get("actor") for event in events
    }

    assert actors_by_event["consent_accepted"] in {"claimant", "respondent"}
    assert actors_by_event["document_added"] == "claimant"
    assert actors_by_event["notice_acknowledged"] == "respondent"
    assert actors_by_event["response_submitted"] == "respondent"

    for event_type in (
        "evidence_disclosed",
        "evidence_admitted",
        "deadline_created",
        "manifest_locked",
        "conciliation_screened",
        "case_organized",
        "decision_generated",
        "review_generated",
    ):
        assert actors_by_event[event_type] == "procedure", event_type

    assert all(
        event["payload"].get("actor") in {"claimant", "respondent", "procedure"}
        for event in events
    )


def test_creator_joins_as_a_party_and_can_only_invite_the_counterparty(client):
    claimant = register_user(client, "Cliente Carlos", "cliente@example.com")
    session_headers = {"X-Session-Token": claimant["session_token"]}

    created = client.post(
        "/cases",
        headers=session_headers,
        json={
            "title": "Cobrança contestada",
            "claimant": "Cliente Carlos",
            "respondent": "Empresa Delta",
            "creator_role": "claimant",
        },
    )
    assert created.status_code == 201
    case = created.json()
    case_id = case["id"]
    CASE_CREDENTIALS[case_id] = case["access_credentials"]

    # Quem abre o caso entra como parte, nunca como administrador dele.
    assert [item["role"] for item in case["participants"]] == ["claimant"]

    # Convidar para o próprio papel, ou para um terceiro, é recusado.
    same_role = client.post(
        f"/cases/{case_id}/invitations",
        headers={"X-Actor-Token": claimant["session_token"]},
        json={"email": "outro@example.com", "role": "claimant"},
    )
    assert same_role.status_code == 403

    third_party = client.post(
        f"/cases/{case_id}/invitations",
        headers={"X-Actor-Token": claimant["session_token"]},
        json={"email": "gestor@example.com", "role": "manager"},
    )
    assert third_party.status_code == 422

    invite = client.post(
        f"/cases/{case_id}/invitations",
        headers={"X-Actor-Token": claimant["session_token"]},
        json={"email": "empresa@example.com", "role": "respondent"},
    )
    assert invite.status_code == 201
    invitation_token = invite.json()["acceptance_token"]

    # Um segundo convite para o mesmo papel é barrado enquanto o primeiro
    # estiver pendente.
    duplicate = client.post(
        f"/cases/{case_id}/invitations",
        headers={"X-Actor-Token": claimant["session_token"]},
        json={"email": "empresa2@example.com", "role": "respondent"},
    )
    assert duplicate.status_code == 409

    company = register_user(client, "Empresa Delta", "empresa@example.com")
    accepted = client.post(
        "/invitations/accept",
        headers={"X-Session-Token": company["session_token"]},
        json={"token": invitation_token},
    )
    assert accepted.status_code == 200
    assert accepted.json()["role"] == "respondent"

    company_cases = client.get(
        "/cases",
        headers={"X-Session-Token": company["session_token"]},
    ).json()
    assert [item["id"] for item in company_cases] == [case_id]


def test_one_person_cannot_hold_both_sides_of_a_case(client):
    """A invariante mais frágil sem terceiro humano: sem ninguém observando,
    é o código que precisa impedir alguém de litigar consigo mesmo e colher
    uma decisão assinada de uma disputa que nunca existiu."""
    person = register_user(client, "Fulano", "fulano@example.com")
    headers = {"X-Session-Token": person["session_token"]}

    case = client.post(
        "/cases",
        headers=headers,
        json={
            "title": "Caso simulado",
            "claimant": "Fulano",
            "respondent": "Fulano de novo",
            "creator_role": "claimant",
        },
    ).json()
    case_id = case["id"]
    CASE_CREDENTIALS[case_id] = case["access_credentials"]

    # Convidar o próprio e-mail é recusado na origem.
    self_invite = client.post(
        f"/cases/{case_id}/invitations",
        headers={"X-Actor-Token": person["session_token"]},
        json={"email": "fulano@example.com", "role": "respondent"},
    )
    assert self_invite.status_code == 403

    # E se o convite chegar por outro caminho, aceitá-lo com uma conta que já
    # é parte também é recusado.
    other = register_user(client, "Sicrano", "sicrano@example.com")
    invite = client.post(
        f"/cases/{case_id}/invitations",
        headers={"X-Actor-Token": person["session_token"]},
        json={"email": "sicrano@example.com", "role": "respondent"},
    )
    assert invite.status_code == 201
    token = invite.json()["acceptance_token"]

    reused_by_first_party = client.post(
        "/invitations/accept",
        headers={"X-Session-Token": person["session_token"]},
        json={"token": token},
    )
    # O convite pertence a outro e-mail; e mesmo que pertencesse, a conta já
    # é parte no caso.
    assert reused_by_first_party.status_code == 409

    accepted = client.post(
        "/invitations/accept",
        headers={"X-Session-Token": other["session_token"]},
        json={"token": token},
    )
    assert accepted.status_code == 200

    roles = [
        item["role"]
        for item in client.get(f"/cases/{case_id}", headers=headers).json()["participants"]
    ]
    assert sorted(roles) == ["claimant", "respondent"]
    assert len(set(roles)) == 2


def test_silence_precludes_instead_of_vetoing_the_procedure(client, monkeypatch):
    """Vencido o prazo, o silêncio da contraparte encerra a oportunidade em vez
    de travar o caso para sempre. Sem terceiro humano, esta é a única saída
    para uma parte que simplesmente não age."""
    from app.db import access_repository

    case_id = create_case(client)["id"]
    accept_procedure(client, case_id)
    add_contract(client, case_id)

    # Enquanto o prazo está aberto, o rito espera: não precluí nada.
    advanced = client.post(
        f"/cases/{case_id}/advance", headers=actor_headers(case_id, "claimant")
    )
    assert advanced.json()["performed"] == []
    assert advanced.json()["waiting_on"] == ["respondent"]

    pending = advanced.json()["pending"][0]
    assert pending["action"] == "acknowledge"
    assert pending["due_at"]

    # O tempo passa e a contraparte não se manifesta. Adiantar o relógio que o
    # rito usa para aferir vencimento é o bastante: os prazos já gravados
    # passam a estar vencidos.
    real_now = access_repository.utc_now
    monkeypatch.setattr(
        access_repository, "utc_now", lambda: real_now() + timedelta(days=30)
    )

    advanced = client.post(
        f"/cases/{case_id}/advance", headers=actor_headers(case_id, "claimant")
    )
    assert advanced.status_code == 200
    steps = [item["step"] for item in advanced.json()["performed"]]
    assert "responses_precluded" in steps

    case = client.get(f"/cases/{case_id}").json()
    precluded = case["documents"][0]
    assert precluded["response_status"] == "precluded"
    assert precluded["acknowledged_by"] == "preclusion"
    # A preclusão encerra a oportunidade, e o material segue para admissão.
    assert precluded["admitted"] is True
    assert case["contradictory"]["complete"] is True

    # O mesmo vale para o encerramento da produção: uma parte inerte não
    # impede a trava.
    assert "submission_closures_precluded" in steps
    assert case["manifest_locked"] is True
    assert case["submission"]["respondent"]["closed"] is True

    events = {
        event["event_type"]: event["payload"]
        for event in client.get(f"/cases/{case_id}/audit").json()["events"]
    }
    assert events["response_precluded"]["actor"] == "procedure"
    assert events["response_precluded"]["party"] == "respondent"
    assert events["response_precluded"]["due_at"]
    assert events["submission_closed_by_preclusion"]["actor"] == "procedure"


def test_consent_is_never_precluded(client, monkeypatch):
    """A adesão é voluntária: nenhum prazo transforma silêncio em aceite. Sem
    o consentimento das duas partes o procedimento simplesmente não existe."""
    from app.db import access_repository

    case_id = create_case(client)["id"]
    add_contract(client, case_id)

    real_now = access_repository.utc_now
    monkeypatch.setattr(
        access_repository, "utc_now", lambda: real_now() + timedelta(days=365)
    )

    advanced = client.post(
        f"/cases/{case_id}/advance", headers=actor_headers(case_id, "claimant")
    )
    assert advanced.status_code == 200

    case = client.get(f"/cases/{case_id}").json()
    assert case["consent"]["complete"] is False
    assert case["manifest_locked"] is False
    assert {item["action"] for item in advanced.json()["pending"]} >= {"consent"}


def test_procedure_opens_and_closes_its_own_deadlines(client):
    case_id = create_case(client)["id"]
    accept_procedure(client, case_id)
    document = add_contract(client, case_id)["document"]

    deadlines = client.get(f"/cases/{case_id}/deadlines").json()
    assert len(deadlines) == 1
    assert deadlines[0]["assigned_to"] == "respondent"
    assert deadlines[0]["reference_id"] == document["id"]
    assert deadlines[0]["status"] == "open"

    complete_contradictory(client, case_id, document["id"])

    deadlines = client.get(f"/cases/{case_id}/deadlines").json()
    by_reference = {item["reference_id"]: item for item in deadlines}
    assert by_reference[document["id"]]["status"] == "completed"
    # E abre o prazo de encerramento de produção para cada parte.
    assert by_reference["claimant"]["status"] == "open"
    assert by_reference["respondent"]["status"] == "open"

    report = client.get(f"/cases/{case_id}/report.docx")
    assert report.status_code == 200
    with zipfile.ZipFile(io.BytesIO(report.content)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
    assert "Ciência e resposta" in document_xml


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
    assert acknowledgement.status_code == 409
    assert replacement_response.status_code == 409


def test_advance_is_idempotent(client):
    case_id, _, _ = prepare_locked_case(client)

    first = client.post(
        f"/cases/{case_id}/advance", headers=actor_headers(case_id, "claimant")
    )
    second = client.post(
        f"/cases/{case_id}/advance", headers=actor_headers(case_id, "respondent")
    )
    assert first.status_code == 200
    assert second.status_code == 200
    # O caso já chegou ao fim do que o rito podia fazer sozinho.
    assert first.json()["performed"] == []
    assert second.json()["performed"] == []

    event_types = [
        event["event_type"]
        for event in client.get(f"/cases/{case_id}/audit").json()["events"]
    ]
    assert event_types.count("manifest_locked") == 1
    assert event_types.count("conciliation_screened") == 1
    assert event_types.count("case_organized") == 1
    assert event_types.count("decision_generated") == 1
    assert event_types.count("review_generated") == 1


def test_procedure_state_reports_what_is_pending_and_from_whom(client):
    case_id = create_case(client)["id"]

    state = client.get(f"/cases/{case_id}/procedure").json()
    assert state["stage"] == "draft"
    assert state["manifest_locked"] is False
    assert {item["action"] for item in state["pending"]} == {"consent", "add_document"}

    accept_procedure(client, case_id)
    document = add_contract(client, case_id)["document"]

    state = client.get(f"/cases/{case_id}/procedure").json()
    pending = {(item["party"], item["action"]) for item in state["pending"]}
    assert ("respondent", "acknowledge") in pending
    assert state["waiting_on"] == ["respondent"]

    client.post(
        f"/cases/{case_id}/documents/{document['id']}/acknowledge",
        json={"party": "respondent"},
        headers=actor_headers(case_id, "respondent"),
    )
    state = client.get(f"/cases/{case_id}/procedure").json()
    pending = {(item["party"], item["action"]) for item in state["pending"]}
    assert ("respondent", "respond") in pending

    complete_contradictory(client, case_id, document["id"])
    state = client.get(f"/cases/{case_id}/procedure").json()
    assert {item["action"] for item in state["pending"]} == {"close_submission"}
    assert state["waiting_on"] == ["claimant", "respondent"]

    close_submissions(client, case_id, parties=("claimant",))
    state = client.get(f"/cases/{case_id}/procedure").json()
    assert state["waiting_on"] == ["respondent"]

    close_submissions(client, case_id, parties=("respondent",))
    state = client.get(f"/cases/{case_id}/procedure").json()
    assert state["manifest_locked"] is True
    assert state["pending"] == []


def test_composition_waits_for_both_parties_and_either_can_end_it(client, monkeypatch):
    """Com a IA disponível, o rito espera a posição das duas partes antes de
    abrir a rodada seguinte — e qualquer uma das partes pode encerrar a
    composição sozinha, porque ela é voluntária."""
    from app.core import procedure

    def fake_conciliation(context, round_number):
        return {
            "round_number": round_number,
            "convergence": "undetermined",
            "recommended_path": "conciliation",
            "neutral_summary": f"Rodada {round_number}",
            "common_interests": [],
            "negotiable_issues": [],
            "non_negotiable_issues": [],
            "possible_terms": [],
            "reasoning": [],
            "confidence": 0.5,
            "continue_recommended": True,
            "recommended_additional_rounds": 1,
            "next_round_focus": "prazo",
            "stop_reason": None,
            "requires_party_consent": True,
            "execution": {"mode": "openai", "model": "fake", "reason": None},
            "party_positions": context["current_party_responses"],
        }

    monkeypatch.setattr(procedure, "assess_conciliation", fake_conciliation)

    case_id, _, locked = prepare_locked_case(client)
    assert locked["status"] == "conciliation"
    assert len(locked["conciliation_rounds"]) == 1

    # A rodada seguinte não sai com apenas uma parte manifestada.
    client.post(
        f"/cases/{case_id}/composition/position",
        json={"position": "Aceito discutir novo prazo."},
        headers=actor_headers(case_id, "claimant"),
    )
    case = client.get(f"/cases/{case_id}").json()
    assert len(case["conciliation_rounds"]) == 1
    assert case["composition"]["claimant"]["submitted"] is True
    assert case["composition"]["respondent"]["submitted"] is False

    second = client.post(
        f"/cases/{case_id}/composition/position",
        json={"position": "Aceito avaliar entrega complementar."},
        headers=actor_headers(case_id, "respondent"),
    )
    assert second.status_code == 200
    rounds = second.json()["conciliation_rounds"]
    assert len(rounds) == 2
    # Cada posição entrou na rodada atribuída à parte que a escreveu.
    assert rounds[1]["party_positions"]["claimant"] == "Aceito discutir novo prazo."
    assert (
        rounds[1]["party_positions"]["respondent"]
        == "Aceito avaliar entrega complementar."
    )
    # As posições foram consumidas: a rodada seguinte começa do zero.
    assert second.json()["composition"]["complete"] is False

    # Uma única parte encerra a composição e o rito segue para o julgamento.
    closed = client.post(
        f"/cases/{case_id}/composition/close",
        headers=actor_headers(case_id, "respondent"),
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "reviewed"
    assert closed.json()["composition"]["closed_by"] == ["respondent"]


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


def test_lock_waits_for_every_precondition(client):
    case_id = create_case(client)["id"]

    # Sem material nenhum não há o que encerrar.
    premature = client.post(
        f"/cases/{case_id}/submission-complete",
        json={"closed": True},
        headers=actor_headers(case_id, "claimant"),
    )
    assert premature.status_code == 409

    document = add_contract(client, case_id)["document"]

    # Sem aceite bilateral, encerrar a produção não trava nada.
    close_submissions(client, case_id)
    assert client.get(f"/cases/{case_id}").json()["manifest_locked"] is False

    accept_procedure(client, case_id)
    case = client.get(f"/cases/{case_id}").json()
    assert case["manifest_locked"] is False
    assert case["contradictory"]["complete"] is False
    assert case["contradictory"]["pending_document_ids"] == [document["id"]]

    complete_contradictory(client, case_id, document["id"])
    assert client.get(f"/cases/{case_id}").json()["manifest_locked"] is True


def test_closed_submission_blocks_new_material_until_reopened(client):
    case_id = create_case(client)["id"]
    add_contract(client, case_id)
    close_submissions(client, case_id, parties=("claimant",))

    blocked = client.post(
        f"/cases/{case_id}/documents/text",
        json={
            "name": "extra.txt",
            "content": "Material apresentado depois do encerramento.",
            "submitted_by": "claimant",
            "material_type": "argument",
            "purpose": "Tentativa de reabrir a produção sem declarar.",
        },
        headers=actor_headers(case_id, "claimant"),
    )
    assert blocked.status_code == 409

    reopened = client.post(
        f"/cases/{case_id}/submission-complete",
        json={"closed": False},
        headers=actor_headers(case_id, "claimant"),
    )
    assert reopened.status_code == 200
    assert reopened.json()["submission"]["claimant"]["closed"] is False

    allowed = client.post(
        f"/cases/{case_id}/documents/text",
        json={
            "name": "extra.txt",
            "content": "Material apresentado depois de reabrir a produção.",
            "submitted_by": "claimant",
            "material_type": "argument",
            "purpose": "Complementar a alegação inicial.",
        },
        headers=actor_headers(case_id, "claimant"),
    )
    assert allowed.status_code == 201


def test_invalid_payloads_are_rejected(client):
    invalid = client.post(
        "/cases",
        json={
            "title": "x",
            "claimant": "",
            "respondent": "B",
            "creator_role": "claimant",
        },
    )
    assert invalid.status_code == 422

    without_side = client.post(
        "/cases",
        json={
            "title": "Caso sem lado declarado",
            "claimant": "A",
            "respondent": "B",
        },
    )
    assert without_side.status_code == 422

    third_party_side = client.post(
        "/cases",
        json={
            "title": "Caso com terceiro",
            "claimant": "A",
            "respondent": "B",
            "creator_role": "manager",
        },
    )
    assert third_party_side.status_code == 422


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
    close_submissions(client, case_id)

    case = client.get(f"/cases/{case_id}").json()
    assert case["contradictory"]["complete"] is False
    assert case["contradictory"]["pending_document_ids"]
    assert case["manifest_locked"] is False
    assert case["decision"] is None

    forced = client.post(
        f"/cases/{case_id}/advance", headers=actor_headers(case_id, "claimant")
    )
    assert forced.status_code == 200
    assert forced.json()["performed"] == []
    assert client.get(f"/cases/{case_id}").json()["manifest_locked"] is False
