"""Painel de operação: acesso restrito, metadados sem teor e ações com registro."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.api import context
from app.api.routes import admin as admin_routes
from app.db.models import AdminAction, AuditEvent, Case, EmailOutbox, Invitation, PilotLead, User
from app.db.session import get_db
from app.main import app
from tests.test_api import client, register_user  # noqa: F401
from tests.test_user_flow_publication import open_case_between

ADMIN_EMAIL = "ops@valinor.test"
SECRET = "Cláusula confidencial: o desconto foi de R$ 7.321,55."


def session():
    return next(app.dependency_overrides[get_db]())


def hdr(user):
    return {"X-Session-Token": user["session_token"]}


@pytest.fixture()
def ops(client):
    return register_user(client, "Operação Valinor", ADMIN_EMAIL)


@pytest.fixture()
def world(client, ops):
    """Dois participantes num caso com um material sigiloso."""
    claimant = register_user(client, "Cliente Carlos", "cliente@example.com")
    case_id, invitation = open_case_between(client, claimant, "empresa@example.com")
    respondent = register_user(client, "Empresa Delta", "empresa@example.com")
    client.post(
        "/invitations/accept",
        headers=hdr(respondent),
        json={"token": invitation["acceptance_token"]},
    )
    client.post(
        f"/cases/{case_id}/consent",
        headers={"X-Actor-Token": claimant["session_token"]},
        json={"party": "claimant", "accepted": True},
    )
    client.post(
        f"/cases/{case_id}/documents/text",
        headers={"X-Actor-Token": claimant["session_token"]},
        json={
            "name": "contrato.txt",
            "content": SECRET,
            "submitted_by": "claimant",
            "material_type": "evidence",
            "purpose": "Provar o desconto.",
        },
    )
    return {"client": client, "case_id": case_id, "claimant": claimant, "respondent": respondent}


def test_panel_requires_a_session_and_an_admin_account(client, ops):
    client.cookies.clear()  # o cliente de teste guarda o cookie do último cadastro
    assert client.get("/admin/overview").status_code == 401
    ordinary = register_user(client, "Cliente Carlos", "cliente@example.com")
    assert client.get("/admin/overview", headers=hdr(ordinary)).status_code == 403
    for path in ("/admin/cases", "/admin/leads", "/admin/emails", "/admin/users", "/admin/actions"):
        assert client.get(path, headers=hdr(ordinary)).status_code == 403, path
    assert client.get("/admin/overview", headers=hdr(ops)).status_code == 200


def test_role_tokens_never_open_the_panel(client, ops):
    client.cookies.clear()
    response = client.get("/admin/overview", headers={"X-Actor-Token": "qualquer"})
    assert response.status_code == 401


def test_admin_with_unverified_email_is_refused_when_verification_is_required(client, ops, monkeypatch):
    monkeypatch.setattr(
        context, "settings", replace(context.settings, email_verification_required=True)
    )
    response = client.get("/admin/overview", headers=hdr(ops))
    assert response.status_code == 403
    assert "Confirme o e-mail" in response.json()["detail"]


def test_account_payload_flags_admins_only(client, ops):
    ordinary = register_user(client, "Cliente Carlos", "cliente@example.com")
    assert client.get("/auth/me", headers=hdr(ops)).json()["is_admin"] is True
    assert client.get("/auth/me", headers=hdr(ordinary)).json()["is_admin"] is False


def test_overview_counts_the_platform(world, ops):
    client = world["client"]
    data = client.get("/admin/overview", headers=hdr(ops)).json()
    assert data["users"]["total"] == 3
    assert data["cases"]["total"] == 1
    assert data["cases"]["by_status"]
    assert set(data["attention"]) >= {
        "stuck", "stage_failed", "no_merit", "stalled",
        "stale_invitations", "emails_failed", "emails_overdue", "leads_new",
    }
    assert data["emails"]["pending"] >= 1  # avisos do convite aceito, consentimento e material
    assert {item["key"] for item in data["config"]} >= {"smtp", "llm", "attestation"}
    assert data["llm"]["last_24h"]["calls"] == 0


def test_case_detail_is_metadata_only_and_logged(world, ops):
    client = world["client"]
    response = client.get(f"/admin/cases/{world['case_id']}", headers=hdr(ops))
    assert response.status_code == 200
    body = response.json()
    # Nenhum teor do caso sai pelo painel.
    raw = response.text
    assert SECRET not in raw
    assert "Provar o desconto" not in raw
    assert "7.321" not in raw
    assert body["case"]["documents"]["total"] == 1
    assert {m["role"] for m in body["members"]} == {"claimant", "respondent"}
    assert any(event["event_type"] == "document_added" for event in body["timeline"])
    assert any(item["kind"] == "evidence_disclosed" for item in body["emails"])

    log = client.get("/admin/actions", headers=hdr(ops)).json()["items"]
    assert [item["action"] for item in log if item["target_id"] == world["case_id"]] == ["case_viewed"]
    assert log[0]["admin_email"] == ADMIN_EMAIL


def test_case_list_filters_by_status_text_and_attention(world, ops):
    client = world["client"]
    case_id = world["case_id"]
    listing = client.get("/admin/cases", headers=hdr(ops)).json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == case_id
    assert client.get("/admin/cases?q=Delta", headers=hdr(ops)).json()["total"] == 1
    assert client.get("/admin/cases?q=inexistente", headers=hdr(ops)).json()["total"] == 0
    assert client.get("/admin/cases?status=locked", headers=hdr(ops)).json()["total"] == 0
    assert client.get("/admin/cases?attention=bogus", headers=hdr(ops)).status_code == 422

    db = session()
    try:
        case = db.get(Case, case_id)
        case.status = "processing_decision"
        case.processing_started_at = datetime.now(timezone.utc) - timedelta(minutes=30)
        db.commit()
    finally:
        db.close()
    stuck = client.get("/admin/cases?attention=stuck", headers=hdr(ops)).json()
    assert stuck["total"] == 1 and "stuck" in stuck["items"][0]["flags"]
    assert client.get("/admin/overview", headers=hdr(ops)).json()["attention"]["stuck"] == 1


def test_failed_stage_is_flagged(world, ops):
    from app.db.repository import append_audit, get_case

    db = session()
    try:
        case = get_case(db, world["case_id"])
        append_audit(db, case, "stage_failed", {"stage": "decide", "error": "timeout do provedor", "restored_status": "organized"})
        db.commit()
    finally:
        db.close()
    client = world["client"]
    flagged = client.get("/admin/cases?attention=stage_failed", headers=hdr(ops)).json()
    assert flagged["total"] == 1 and "stage_failed" in flagged["items"][0]["flags"]
    detail = client.get(f"/admin/cases/{world['case_id']}", headers=hdr(ops)).json()
    failure = [e for e in detail["timeline"] if e["event_type"] == "stage_failed"][0]
    assert "decide" in failure["detail"] and "timeout" in failure["detail"]


def test_unstick_releases_only_stale_processing_and_records_it_in_the_case(world, ops):
    client = world["client"]
    case_id = world["case_id"]
    body = {"reason": "Provedor caiu durante a decisão"}

    not_stuck = client.post(f"/admin/cases/{case_id}/unstick", headers=hdr(ops), json=body)
    assert not_stuck.status_code == 409

    db = session()
    try:
        case = db.get(Case, case_id)
        case.status = "processing_decision"
        case.processing_started_at = datetime.now(timezone.utc) - timedelta(minutes=2)
        db.commit()
    finally:
        db.close()
    recent = client.post(f"/admin/cases/{case_id}/unstick", headers=hdr(ops), json=body)
    assert recent.status_code == 409  # dentro do TTL pode estar rodando em outra réplica

    db = session()
    try:
        case = db.get(Case, case_id)
        case.processing_started_at = datetime.now(timezone.utc) - timedelta(minutes=30)
        db.commit()
    finally:
        db.close()
    assert client.post(
        f"/admin/cases/{case_id}/unstick", headers=hdr(ops), json={"reason": "x"}
    ).status_code == 422  # motivo obrigatório
    done = client.post(f"/admin/cases/{case_id}/unstick", headers=hdr(ops), json=body)
    assert done.status_code == 200 and done.json()["status"] == "organized"

    db = session()
    try:
        event = db.query(AuditEvent).filter(AuditEvent.event_type == "operations_released_stage").one()
        action = db.query(AdminAction).filter(AdminAction.action == "case_unstuck").one()
    finally:
        db.close()
    assert "Provedor caiu" in event.payload_json
    assert action.target_id == case_id


def test_resume_asks_the_steward_and_is_refused_for_closed_cases(world, ops, monkeypatch):
    calls = []
    monkeypatch.setattr(
        admin_routes, "_conduct_steward", lambda db, case, **kw: calls.append((case.id, kw))
    )
    client = world["client"]
    case_id = world["case_id"]
    body = {"reason": "Retomar depois do reinício"}
    assert client.post(f"/admin/cases/{case_id}/resume", headers=hdr(ops), json=body).status_code == 200
    assert calls and calls[0][0] == case_id and calls[0][1]["run_model_stages"] is True

    db = session()
    try:
        db.get(Case, case_id).status = "attested"
        db.commit()
    finally:
        db.close()
    assert client.post(f"/admin/cases/{case_id}/resume", headers=hdr(ops), json=body).status_code == 409


def test_leads_are_listed_and_worked(client, ops):
    created = client.post(
        "/leads",
        json={"name": "Ana Souza", "company": "Banco Delta", "email": "ana@bancodelta.test", "monthly_volume": 800},
    )
    assert created.status_code == 201
    listing = client.get("/admin/leads", headers=hdr(ops)).json()
    assert listing["counts"]["new"] == 1
    lead = listing["items"][0]
    assert lead["company"] == "Banco Delta" and lead["status"] == "new"

    updated = client.patch(
        f"/admin/leads/{lead['id']}",
        headers=hdr(ops),
        json={"status": "contacted", "notes": "Ligar quinta; quer piloto com 50 casos."},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "contacted"
    assert "50 casos" in updated.json()["notes"]
    assert client.get("/admin/leads?status=new", headers=hdr(ops)).json()["total"] == 0
    assert client.get("/admin/leads?status=contacted", headers=hdr(ops)).json()["total"] == 1
    assert client.patch(
        f"/admin/leads/{lead['id']}", headers=hdr(ops), json={"status": "inventado"}
    ).status_code == 422
    assert client.patch(
        "/admin/leads/nao-existe", headers=hdr(ops), json={"status": "new"}
    ).status_code == 404

    db = session()
    try:
        stored = db.get(PilotLead, lead["id"])
        assert stored.handled_by_user_id is not None and stored.updated_at is not None
    finally:
        db.close()


def test_failed_emails_can_be_requeued_and_dispatched(world, ops):
    client = world["client"]
    db = session()
    try:
        row = db.query(EmailOutbox).first()
        row.status, row.attempts, row.last_error = "failed", 5, "SMTPAuthenticationError"
        row_id = row.id
        db.commit()
    finally:
        db.close()
    failed = client.get("/admin/emails?status=failed", headers=hdr(ops)).json()
    assert failed["total"] == 1 and failed["items"][0]["last_error"] == "SMTPAuthenticationError"
    assert client.get("/admin/overview", headers=hdr(ops)).json()["attention"]["emails_failed"] == 1

    retried = client.post(f"/admin/emails/{row_id}/retry", headers=hdr(ops))
    assert retried.status_code == 200 and retried.json()["status"] == "pending"
    sent = client.post(f"/admin/emails/{row_id}/retry", headers=hdr(ops))
    assert sent.status_code == 200  # pendente também pode ser reenfileirado
    assert client.post("/admin/emails/nao-existe/retry", headers=hdr(ops)).status_code == 404

    counts = client.post("/admin/emails/dispatch", headers=hdr(ops)).json()
    assert counts["logged"] >= 1  # sem SMTP no teste, a fila vira registro em log
    assert client.get("/admin/emails?audience=party", headers=hdr(ops)).json()["total"] >= 1


def test_user_support_actions(client, ops):
    victim = register_user(client, "Empresa Delta", "empresa@example.com")
    listing = client.get("/admin/users?q=delta", headers=hdr(ops)).json()
    assert listing["total"] == 1
    user_id = listing["items"][0]["id"]
    assert listing["items"][0]["is_admin"] is False

    resent = client.post(f"/admin/users/{user_id}/resend-verification", headers=hdr(ops))
    assert resent.status_code == 200
    assert "token" not in resent.text  # o link vai só para a caixa de entrada

    db = session()
    try:
        user = db.get(User, user_id)
        user.failed_login_attempts = 5
        user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=10)
        db.commit()
    finally:
        db.close()
    unlocked = client.post(f"/admin/users/{user_id}/unlock", headers=hdr(ops)).json()
    assert unlocked["locked_until"] is None and unlocked["failed_login_attempts"] == 0

    suspended = client.post(
        f"/admin/users/{user_id}/active", headers=hdr(ops),
        json={"active": False, "reason": "Conta usada para abuso"},
    )
    assert suspended.status_code == 200 and suspended.json()["active"] is False
    assert client.get("/auth/me", headers=hdr(victim)).status_code == 401  # sessão revogada
    me = next(u for u in client.get("/admin/users", headers=hdr(ops)).json()["items"] if u["is_admin"])
    own = client.post(
        f"/admin/users/{me['id']}/active", headers=hdr(ops),
        json={"active": False, "reason": "teste do próprio acesso"},
    )
    assert own.status_code == 409

    actions = [item["action"] for item in client.get("/admin/actions", headers=hdr(ops)).json()["items"]]
    assert {"verification_resent", "user_unlocked", "user_suspended"} <= set(actions)


def test_verified_account_cannot_be_asked_to_verify_again(client, ops):
    db = session()
    try:
        user = db.query(User).filter(User.email == ADMIN_EMAIL).one()
        user.email_verified_at = datetime.now(timezone.utc)
        db.commit()
        user_id = user.id
    finally:
        db.close()
    assert client.post(f"/admin/users/{user_id}/resend-verification", headers=hdr(ops)).status_code == 409
