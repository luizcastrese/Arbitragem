"""Avisos por e-mail dos atos e prazos do procedimento.

Uma parte que não abre o painel perde o contraditório, o prazo de recurso e a
janela de acatamento. Estes testes fixam quem é avisado de quê, que o aviso
nasce junto do ato, que não vaza o teor do caso e que a fila repete o que falhou.
"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import AuditEvent, Case, Deadline, Document, EmailOutbox
from app.db.session import get_db
from app.main import app
from app.notifications import outbox, reminders, rules
from tests.test_api import client, register_user  # noqa: F401
from tests.test_user_flow_publication import open_case_between


def session():
    return next(app.dependency_overrides[get_db]())


def outbox_rows(**filters):
    db = session()
    try:
        query = db.query(EmailOutbox)
        for field, value in filters.items():
            query = query.filter(getattr(EmailOutbox, field) == value)
        return query.order_by(EmailOutbox.created_at, EmailOutbox.id).all()
    finally:
        db.close()


def headers(user):
    return {"X-Actor-Token": user["session_token"]}


@pytest.fixture()
def duo(client):
    """Reclamante e reclamada com conta, no mesmo caso, convite aceito."""
    claimant = register_user(client, "Cliente Carlos", "cliente@example.com")
    case_id, invitation = open_case_between(client, claimant, "empresa@example.com")
    respondent = register_user(client, "Empresa Delta", "empresa@example.com")
    accepted = client.post(
        "/invitations/accept",
        headers={"X-Session-Token": respondent["session_token"]},
        json={"token": invitation["acceptance_token"]},
    )
    assert accepted.status_code == 200
    return {"client": client, "case_id": case_id, "claimant": claimant, "respondent": respondent}


def consent(duo, user, party):
    response = duo["client"].post(
        f"/cases/{duo['case_id']}/consent",
        headers=headers(user),
        json={"party": party, "accepted": True},
    )
    assert response.status_code == 200, response.text


def add_material(duo, user, party, content="Segredo industrial: a fatura de R$ 9.999,00."):
    response = duo["client"].post(
        f"/cases/{duo['case_id']}/documents/text",
        headers=headers(user),
        json={
            "name": "fatura-secreta.txt",
            "content": content,
            "submitted_by": party,
            "material_type": "evidence",
            "purpose": "Comprovar a cobrança.",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["document"]


def test_invitation_acceptance_warns_the_creator_only(duo):
    rows = outbox_rows(kind="invitation_accepted")
    assert [row.to_email for row in rows] == ["cliente@example.com"]
    assert "entrou" in rows[0].subject or "entrou" in rows[0].body or "convite" in rows[0].body


def test_consent_warns_the_other_party_then_both_when_the_procedure_forms(duo):
    consent(duo, duo["claimant"], "claimant")
    first = outbox_rows(kind="consent_accepted")
    assert [row.to_email for row in first] == ["empresa@example.com"]

    consent(duo, duo["respondent"], "respondent")
    formed = [row for row in outbox_rows(kind="consent_accepted") if "formado" in row.subject]
    assert sorted(row.to_email for row in formed) == [
        "cliente@example.com",
        "empresa@example.com",
    ]


def test_disclosed_material_warns_the_counterparty_without_leaking_content(duo):
    consent(duo, duo["claimant"], "claimant")
    add_material(duo, duo["claimant"], "claimant")

    rows = outbox_rows(kind="evidence_disclosed")
    assert [row.to_email for row in rows] == ["empresa@example.com"]
    body = rows[0].body
    assert f"/ui/?case={duo['case_id']}" in body
    assert "Empresa Delta" in body  # saudação
    # O e-mail nunca leva o teor nem o nome do material.
    assert "fatura-secreta" not in body
    assert "9.999" not in body
    assert "Segredo industrial" not in body
    assert "Comprovar a cobrança" not in body


def test_the_same_fact_never_produces_two_notices(duo):
    db = session()
    try:
        event = db.query(AuditEvent).filter(AuditEvent.event_type == "invitation_accepted").one()
        case = db.get(Case, duo["case_id"])
        notice = rules.Notice(roles=["claimant"], subject="x", headline="y")
        # O aviso do próprio ato já foi enfileirado junto com ele.
        replay = rules.deliver_notice(db, case, notice, kind="invitation_accepted", key=f"evt:{event.id}:0")
        fresh = rules.deliver_notice(db, case, notice, kind="t", key="outro-fato")
        db.commit()
        again = rules.deliver_notice(db, case, notice, kind="t", key="outro-fato")
        db.commit()
    finally:
        db.close()
    assert (replay, fresh, again) == (0, 1, 0)


def test_unverified_accounts_do_not_receive_case_notices(duo, monkeypatch):
    settings = rules.get_settings()
    monkeypatch.setattr(
        rules, "get_settings", lambda: replace(settings, email_verification_required=True)
    )
    db = session()
    try:
        recipients = rules._recipients(db, duo["case_id"], ["claimant", "respondent"])
    finally:
        db.close()
    assert recipients == []  # contas de teste não confirmaram o e-mail


def test_anonymized_accounts_never_receive_notices(duo):
    db = session()
    try:
        from app.db.models import User

        user = db.query(User).filter(User.email == "empresa@example.com").one()
        user.email = "abc@anonimizado.invalid"
        db.commit()
        recipients = rules._recipients(db, duo["case_id"], ["respondent"])
    finally:
        db.close()
    assert recipients == []


def test_ops_alert_goes_to_operations_not_to_the_parties(duo, monkeypatch):
    settings = rules.get_settings()
    monkeypatch.setattr(
        rules, "get_settings", lambda: replace(settings, ops_alert_email="ops@valinor.test")
    )
    db = session()
    try:
        from app.db.repository import append_audit, get_case

        case = get_case(db, duo["case_id"])
        append_audit(db, case, "stage_failed", {"stage": "decide", "error": "timeout", "restored_status": "organized"})
        db.commit()
    finally:
        db.close()
    rows = outbox_rows(kind="ops_stage_failed")
    assert [row.to_email for row in rows] == ["ops@valinor.test"]
    assert rows[0].audience == "ops"
    assert "decide" in rows[0].body and "timeout" in rows[0].body
    assert "/ui/admin?case=" in rows[0].body


def test_notification_failure_never_breaks_the_act(duo, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("regra quebrada")

    monkeypatch.setitem(rules.RULES, "consent_accepted", boom)
    consent(duo, duo["claimant"], "claimant")  # não pode levantar
    assert outbox_rows(kind="consent_accepted") == []


def test_notifications_can_be_switched_off(duo, monkeypatch):
    settings = rules.get_settings()
    monkeypatch.setattr(
        rules, "get_settings", lambda: replace(settings, notifications_enabled=False)
    )
    consent(duo, duo["claimant"], "claimant")
    assert outbox_rows(kind="consent_accepted") == []


# --- fila -----------------------------------------------------------------


def smtp_on(monkeypatch):
    settings = outbox.get_settings()
    monkeypatch.setattr(
        outbox,
        "get_settings",
        lambda: replace(settings, smtp_host="smtp.test", smtp_from="no-reply@valinor.test"),
    )


def test_dispatch_marks_logged_without_smtp(duo):
    consent(duo, duo["claimant"], "claimant")
    db = session()
    try:
        counts = outbox.dispatch_pending(db)
    finally:
        db.close()
    assert counts["logged"] >= 1
    assert all(row.status == "logged" for row in outbox_rows())


def test_dispatch_sends_and_records_delivery(duo, monkeypatch):
    smtp_on(monkeypatch)
    consent(duo, duo["claimant"], "claimant")
    sent = []

    def fake_deliver(message, *, kind, to_email):
        sent.append((message["To"], message["Subject"], message["From"], message["X-Valinor-Case"]))
        return {"delivered": True, "transport": "smtp"}

    db = session()
    try:
        counts = outbox.dispatch_pending(db, deliver=fake_deliver)
    finally:
        db.close()
    assert counts["sent"] >= 1
    assert ("empresa@example.com", "A outra parte aceitou os termos", "no-reply@valinor.test", duo["case_id"]) in sent
    row = [r for r in outbox_rows() if r.kind == "consent_accepted"][0]
    assert row.status == "sent" and row.sent_at is not None and row.attempts == 1


def test_failed_delivery_is_retried_with_backoff_then_marked_failed(duo, monkeypatch):
    smtp_on(monkeypatch)
    consent(duo, duo["claimant"], "claimant")
    now = datetime.now(timezone.utc)

    def failing(message, *, kind, to_email):
        return {"delivered": False, "error": "SMTPServerDisconnected"}

    for attempt in range(1, outbox.MAX_ATTEMPTS + 1):
        db = session()
        try:
            counts = outbox.dispatch_pending(db, now=now, deliver=failing)
        finally:
            db.close()
        row = outbox_rows(kind="consent_accepted")[0]
        assert row.attempts == attempt
        if attempt < outbox.MAX_ATTEMPTS:
            assert row.status == "pending"
            assert counts["retry"] >= 1
            # Antes do vencimento da espera não tenta de novo.
            db = session()
            try:
                assert outbox.dispatch_pending(db, now=now, deliver=failing)["retry"] == 0
            finally:
                db.close()
            now = now + timedelta(hours=1)
        else:
            assert row.status == "failed"
            assert row.last_error == "SMTPServerDisconnected"


def test_requeue_gives_a_failed_notice_a_new_round(duo, monkeypatch):
    smtp_on(monkeypatch)
    consent(duo, duo["claimant"], "claimant")
    db = session()
    try:
        row = db.query(EmailOutbox).filter(EmailOutbox.kind == "consent_accepted").one()
        row.status, row.attempts, row.last_error = "failed", 5, "x"
        db.commit()
        outbox.requeue(db, row)
        counts = outbox.dispatch_pending(
            db, deliver=lambda m, *, kind, to_email: {"delivered": True}
        )
    finally:
        db.close()
    assert counts["sent"] >= 1
    assert outbox_rows(kind="consent_accepted")[0].status == "sent"


def test_stale_claims_return_to_the_queue(duo, monkeypatch):
    smtp_on(monkeypatch)
    consent(duo, duo["claimant"], "claimant")
    db = session()
    try:
        row = db.query(EmailOutbox).filter(EmailOutbox.kind == "consent_accepted").one()
        row.status = "sending"
        row.claimed_at = datetime.now(timezone.utc) - timedelta(minutes=30)
        db.commit()
        counts = outbox.dispatch_pending(
            db, deliver=lambda m, *, kind, to_email: {"delivered": True}
        )
    finally:
        db.close()
    assert counts["sent"] >= 1


def test_purge_removes_only_old_delivered_notices(duo):
    consent(duo, duo["claimant"], "claimant")
    db = session()
    try:
        old = datetime.now(timezone.utc) - timedelta(days=200)
        rows = db.query(EmailOutbox).all()
        rows[0].status, rows[0].created_at = "sent", old
        rows[1].status, rows[1].created_at = "failed", old
        db.commit()
        removed = outbox.purge_delivered(db, 90)
        left = {row.status for row in db.query(EmailOutbox).all()}
    finally:
        db.close()
    assert removed == 1
    assert "failed" in left and "sent" not in left


def test_erasure_scrubs_the_notices_of_the_account(duo):
    consent(duo, duo["claimant"], "claimant")
    db = session()
    try:
        from app.db.models import User

        user = db.query(User).filter(User.email == "empresa@example.com").one()
        outbox.erase_for_user(db, user.id)
        db.commit()
        mine = db.query(EmailOutbox).filter(EmailOutbox.user_id == user.id).all()
    finally:
        db.close()
    assert mine
    assert all(row.body == "" and "anonimizado" in row.to_email for row in mine)


# --- lembretes --------------------------------------------------------------


def test_contest_window_reminders_are_sent_once(duo):
    now = datetime.now(timezone.utc)
    db = session()
    try:
        case = db.get(Case, duo["case_id"])
        case.status = "attested"
        case.attestation_json = (
            '{"attestation_hash": "abc123", '
            f'"issued_at_utc": "{(now - timedelta(days=5)).isoformat()}", '
            f'"contest_window_ends_utc": "{(now + timedelta(hours=20)).isoformat()}"}}'
        )
        db.commit()
        first = reminders.scan_reminders(db, now)
        second = reminders.scan_reminders(db, now)
    finally:
        db.close()
    assert first["attestations"] == 4  # 2 lembretes x 2 partes
    assert second["attestations"] == 0
    kinds = {row.kind for row in outbox_rows()}
    assert {"reminder_contest_closing", "reminder_reflection_over"} <= kinds
    closing = outbox_rows(kind="reminder_contest_closing")[0]
    assert "recurso" in closing.subject.lower() and "Prazo:" in closing.body


def test_no_contest_reminder_after_the_window_or_after_contest(duo):
    now = datetime.now(timezone.utc)
    db = session()
    try:
        case = db.get(Case, duo["case_id"])
        case.status = "attested"
        case.attestation_json = (
            '{"attestation_hash": "old", '
            f'"issued_at_utc": "{(now - timedelta(days=9)).isoformat()}", '
            f'"contest_window_ends_utc": "{(now - timedelta(days=2)).isoformat()}"}}'
        )
        db.commit()
        assert reminders.scan_reminders(db, now)["attestations"] == 0
    finally:
        db.close()


def test_stalled_material_reminds_only_the_party_that_owes_a_response(duo):
    consent(duo, duo["claimant"], "claimant")
    document = add_material(duo, duo["claimant"], "claimant")
    now = datetime.now(timezone.utc)
    db = session()
    try:
        assert reminders.scan_reminders(db, now)["stalled_material"] == 0  # recente
        doc = db.get(Document, document["id"])
        doc.disclosed_at = (now - timedelta(days=4)).isoformat()
        db.commit()
        assert reminders.scan_reminders(db, now)["stalled_material"] == 1
        assert reminders.scan_reminders(db, now)["stalled_material"] == 0
    finally:
        db.close()
    rows = outbox_rows(kind="reminder_stalled_material")
    assert [row.to_email for row in rows] == ["empresa@example.com"]


def test_deadline_reminders_due_soon_and_overdue(duo):
    now = datetime.now(timezone.utc)
    db = session()
    try:
        soon = Deadline(
            id="dl-soon", case_id=duo["case_id"], label="Juntar procuração",
            kind="submission", assigned_to="respondent", due_at=now + timedelta(hours=6),
        )
        late = Deadline(
            id="dl-late", case_id=duo["case_id"], label="Resposta ao material",
            kind="response", assigned_to="claimant", due_at=now - timedelta(days=1),
        )
        done = Deadline(
            id="dl-done", case_id=duo["case_id"], label="Já cumprido",
            kind="response", assigned_to="claimant", due_at=now + timedelta(hours=2),
            completed_at=now,
        )
        db.add_all([soon, late, done])
        db.commit()
        assert reminders.scan_reminders(db, now)["deadlines"] == 2
        assert reminders.scan_reminders(db, now)["deadlines"] == 0
    finally:
        db.close()
    assert [r.to_email for r in outbox_rows(kind="reminder_deadline_due")] == ["empresa@example.com"]
    assert [r.to_email for r in outbox_rows(kind="reminder_deadline_overdue")] == ["cliente@example.com"]


def test_expiring_invitation_reminds_the_inviter(client):
    claimant = register_user(client, "Cliente Carlos", "cliente@example.com")
    case_id, _invitation = open_case_between(client, claimant, "empresa@example.com")
    now = datetime.now(timezone.utc)
    db = session()
    try:
        from app.db.models import Invitation

        invitation = db.query(Invitation).one()
        invitation.expires_at = now + timedelta(hours=10)
        db.commit()
        assert reminders.scan_reminders(db, now)["invitations"] == 1
        assert reminders.scan_reminders(db, now)["invitations"] == 0
    finally:
        db.close()
    rows = outbox_rows(kind="reminder_invitation_expiring")
    assert [row.to_email for row in rows] == ["cliente@example.com"]


def test_a_failing_scan_does_not_stop_the_others(duo, monkeypatch):
    def boom(db, now):
        raise RuntimeError("falha")

    monkeypatch.setattr(reminders, "_scan_deadlines", boom)
    db = session()
    try:
        result = reminders.scan_reminders(db, datetime.now(timezone.utc))
    finally:
        db.close()
    assert result["deadlines"] == 0
    assert "attestations" in result and "invitations" in result


# --- matriz de regras --------------------------------------------------------

FUTURE = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

RULE_MATRIX = [
    # evento, payload, destinatários esperados (e-mails), trecho do assunto
    ("manifest_locked", {}, {"cliente@example.com", "empresa@example.com"}, "conciliação"),
    ("conciliation_screened", {"round_number": 1}, {"cliente@example.com", "empresa@example.com"}, "rodada"),
    ("conciliation_round_generated", {"round_number": 2}, {"cliente@example.com", "empresa@example.com"}, "rodada 2"),
    ("conciliation_position_recorded", {"party": "claimant"}, {"empresa@example.com"}, "posição"),
    ("conciliation_agreement_response", {"party": "respondent"}, {"cliente@example.com"}, "proposta"),
    ("conciliation_agreement_completed", {}, {"cliente@example.com", "empresa@example.com"}, "Acordo"),
    ("submission_ready", {"party": "respondent", "ready": True}, {"cliente@example.com"}, "encerrou"),
    ("submission_ready", {"party": "respondent", "ready": False}, set(), None),
    ("response_submitted", {"party": "respondent"}, {"cliente@example.com"}, "respondeu"),
    ("attestation_issued", {"contest_window_ends_utc": FUTURE}, {"cliente@example.com", "empresa@example.com"}, "recurso"),
    ("decision_record_issued", {"outcome_kind": "agreement"}, {"cliente@example.com", "empresa@example.com"}, "acordo"),
    ("decision_record_issued", {"outcome_kind": "no_merit_decision"}, {"cliente@example.com", "empresa@example.com"}, "sem decisão"),
    ("decision_record_issued", {"outcome_kind": "decision"}, set(), None),  # o aviso é o da attestation
    ("contest_registered", {"contested_by": "claimant"}, {"empresa@example.com"}, "Recurso"),
    ("appeal_completed", {}, {"cliente@example.com", "empresa@example.com"}, "Recurso concluído"),
    ("decision_accepted", {"party": "claimant"}, {"empresa@example.com"}, "acatou"),
    ("arbitrator_accepted", {}, {"cliente@example.com", "empresa@example.com"}, "árbitro"),
    ("arbitrator_confirmed", {"party": "claimant"}, {"empresa@example.com"}, "confirmou"),
    ("arbitral_award_signed", {}, {"cliente@example.com", "empresa@example.com"}, "Sentença"),
    ("arbitral_award_declined", {}, {"cliente@example.com", "empresa@example.com"}, "recusou"),
    ("withdrawn_to_court", {"party": "respondent"}, {"cliente@example.com"}, "via judicial"),
    ("consent_withdrawn", {"party": "claimant"}, {"empresa@example.com"}, "retirou"),
    ("deadline_created", {"assigned_to": "all", "due_at": FUTURE}, {"cliente@example.com", "empresa@example.com"}, "prazo"),
    ("deadline_created", {"assigned_to": "respondent", "due_at": FUTURE}, {"empresa@example.com"}, "prazo"),
    # eventos internos nunca viram aviso às partes
    ("document_added", {"document_id": "d1"}, set(), None),
    ("case_organized", {}, set(), None),
    ("steward_conducted", {"action": "lock"}, set(), None),
    ("notice_acknowledged", {"party": "respondent"}, set(), None),
]


@pytest.mark.parametrize("event,payload,expected,subject", RULE_MATRIX)
def test_rule_matrix(duo, event, payload, expected, subject):
    from app.db.repository import append_audit, get_case

    before = {row.id for row in outbox_rows()}
    db = session()
    try:
        case = get_case(db, duo["case_id"])
        append_audit(db, case, event, payload)
        db.commit()
    finally:
        db.close()
    fresh = [row for row in outbox_rows() if row.id not in before and row.kind == event]
    assert {row.to_email for row in fresh} == expected
    for row in fresh:
        assert subject.lower() in row.subject.lower()
        assert row.audience == "party"
        assert f"/ui/?case={duo['case_id']}" in row.body
        assert "Cobrança contestada" in row.body  # título do caso, nunca o teor


def test_paid_settlement_warns_only_the_payee(duo):
    from app.db.models import SettlementPayment
    from app.db.repository import append_audit, get_case

    db = session()
    try:
        db.add(
            SettlementPayment(
                id="pay-1", case_id=duo["case_id"], attestation_hash="h",
                payer_role="respondent", payee_role="claimant",
                amount_minor_units=1000, fee_minor_units=100, currency="BRL", status="paid",
            )
        )
        db.commit()
        append_audit(db, get_case(db, duo["case_id"]), "settlement_payment_paid", {"payment_id": "pay-1"})
        db.commit()
    finally:
        db.close()
    rows = outbox_rows(kind="settlement_payment_paid")
    assert [row.to_email for row in rows] == ["cliente@example.com"]
    assert "1000" not in rows[0].body and "10,00" not in rows[0].body  # sem valores no e-mail
