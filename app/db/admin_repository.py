"""Consultas do painel de operação.

O painel existe para a operação ajudar pessoas e manter o serviço de pé, não
para ler os casos. Por isso tudo aqui devolve **metadados**: situação, papéis,
contagens, tipos de evento, falhas, modelos usados. Nunca o teor de peças,
documentos, propostas ou decisões. Cada leitura de um caso e cada intervenção
é gravada em `admin_actions` pelas rotas.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (
    AdminAction,
    AuditEvent,
    Case,
    CaseMember,
    Deadline,
    Document,
    EmailOutbox,
    Invitation,
    LLMExecution,
    PilotLead,
    User,
)
from app.domain.concurrency import PROCESSING_TTL, TERMINAL_STATUSES

NO_MERIT = ("inconclusive", "invalidated", "inadmissible", "system_failure")
STALLED_AFTER = timedelta(days=14)
INVITE_STALE_AFTER = timedelta(days=3)
LEAD_STATUSES = ("new", "contacted", "qualified", "discarded")
ACTIVE_EXCLUDED = set(TERMINAL_STATUSES) | {"agreement", "decided"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return _aware(value).isoformat()


def _load(raw: Optional[str], default=None):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Registro de ações
# ---------------------------------------------------------------------------


def log_action(
    db: Session,
    admin: User,
    action: str,
    *,
    target_type: str = "",
    target_id: Optional[str] = None,
    detail: str = "",
) -> AdminAction:
    record = AdminAction(
        id=str(uuid.uuid4()),
        admin_user_id=admin.id,
        admin_email=admin.email,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail[:1000],
    )
    db.add(record)
    db.commit()
    return record


def action_to_dict(item: AdminAction) -> Dict[str, Any]:
    return {
        "id": item.id,
        "admin_email": item.admin_email,
        "action": item.action,
        "target_type": item.target_type,
        "target_id": item.target_id,
        "detail": item.detail,
        "created_at": _iso(item.created_at),
    }


def list_actions(db: Session, *, target_id: Optional[str] = None, limit: int = 100) -> List[Dict]:
    query = db.query(AdminAction)
    if target_id:
        query = query.filter(AdminAction.target_id == target_id)
    rows = query.order_by(AdminAction.created_at.desc()).limit(limit).all()
    return [action_to_dict(item) for item in rows]


# ---------------------------------------------------------------------------
# Casos
# ---------------------------------------------------------------------------


def _is_stuck(case: Case, now: datetime) -> bool:
    started = _aware(case.processing_started_at)
    return bool(
        str(case.status or "").startswith("processing")
        and started is not None
        and now - started > PROCESSING_TTL
    )


def _is_terminal(case: Case) -> bool:
    return str(case.status or "") in ACTIVE_EXCLUDED


def _failed_stage_case_ids(db: Session, since: datetime, case_ids: Optional[List[str]] = None) -> set:
    query = db.query(AuditEvent.case_id).filter(
        AuditEvent.event_type.in_(("stage_failed", "contest_attempt_failed")),
        AuditEvent.timestamp_utc >= since.isoformat(),
    )
    if case_ids is not None:
        query = query.filter(AuditEvent.case_id.in_(case_ids))
    return {row[0] for row in query.distinct().all()}


def case_flags(case: Case, now: datetime, failed_ids: set) -> List[str]:
    flags: List[str] = []
    if _is_stuck(case, now):
        flags.append("stuck")
    if case.id in failed_ids and not _is_terminal(case):
        flags.append("stage_failed")
    conclusion = case.procedure_conclusion or ""
    if conclusion in NO_MERIT or case.status in NO_MERIT:
        flags.append("no_merit")
    updated = _aware(case.updated_at)
    if not _is_terminal(case) and updated is not None and now - updated > STALLED_AFTER:
        flags.append("stalled")
    if case.contested_at or case.status == "contested":
        flags.append("contested")
    if case.status == "withdrawn":
        flags.append("withdrawn")
    return flags


def case_row(case: Case, now: datetime, failed_ids: set) -> Dict[str, Any]:
    return {
        "id": case.id,
        "title": case.title,
        "claimant": case.claimant,
        "respondent": case.respondent,
        "status": case.status,
        "procedure_conclusion": case.procedure_conclusion,
        "manifest_locked": bool(case.manifest_locked),
        "created_at": _iso(case.created_at),
        "updated_at": _iso(case.updated_at),
        "flags": case_flags(case, now, failed_ids),
    }


def _attention_filter(query, attention: str, now: datetime, failed_ids_query):
    if attention == "stuck":
        return query.filter(
            Case.status.like("processing%"),
            Case.processing_started_at < now - PROCESSING_TTL,
        )
    if attention == "stage_failed":
        return query.filter(Case.id.in_(failed_ids_query), Case.status.notin_(list(ACTIVE_EXCLUDED)))
    if attention == "no_merit":
        return query.filter(
            or_(Case.procedure_conclusion.in_(NO_MERIT), Case.status.in_(NO_MERIT))
        )
    if attention == "stalled":
        return query.filter(
            Case.status.notin_(list(ACTIVE_EXCLUDED)),
            Case.updated_at < now - STALLED_AFTER,
        )
    if attention == "contested":
        return query.filter(or_(Case.contested_at.isnot(None), Case.status == "contested"))
    return query


def list_cases(
    db: Session,
    *,
    status: str = "",
    attention: str = "",
    q: str = "",
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    now = now_utc()
    query = db.query(Case)
    if status:
        query = query.filter(Case.status == status)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Case.id.like(like),
                Case.title.ilike(like),
                Case.claimant.ilike(like),
                Case.respondent.ilike(like),
            )
        )
    if attention:
        failed_subquery = db.query(AuditEvent.case_id).filter(
            AuditEvent.event_type.in_(("stage_failed", "contest_attempt_failed")),
            AuditEvent.timestamp_utc >= (now - timedelta(hours=24)).isoformat(),
        )
        query = _attention_filter(query, attention, now, failed_subquery)
    total = query.count()
    cases = (
        query.order_by(Case.updated_at.desc()).offset(offset).limit(limit).all()
    )
    failed_ids = _failed_stage_case_ids(
        db, now - timedelta(hours=24), [case.id for case in cases]
    )
    return {
        "total": total,
        "items": [case_row(case, now, failed_ids) for case in cases],
    }


def case_detail(db: Session, case: Case) -> Dict[str, Any]:
    """Metadados do caso. Sem peças, documentos, propostas ou decisões."""
    now = now_utc()
    failed_ids = _failed_stage_case_ids(db, now - timedelta(hours=24), [case.id])
    pathway = _load(case.pathway_json, {}) or {}
    steward = _load(case.steward_json, {}) or {}

    members = (
        db.query(CaseMember, User)
        .join(User, User.id == CaseMember.user_id)
        .filter(CaseMember.case_id == case.id)
        .all()
    )
    invitations = (
        db.query(Invitation).filter(Invitation.case_id == case.id).order_by(Invitation.created_at).all()
    )
    deadlines = db.query(Deadline).filter(Deadline.case_id == case.id).order_by(Deadline.due_at).all()
    documents = db.query(Document).filter(Document.case_id == case.id).all()
    events = (
        db.query(AuditEvent).filter(AuditEvent.case_id == case.id).order_by(AuditEvent.id).all()
    )
    executions = (
        db.query(LLMExecution)
        .filter(LLMExecution.case_id == case.id)
        .order_by(LLMExecution.created_at)
        .all()
    )
    emails = (
        db.query(EmailOutbox)
        .filter(EmailOutbox.case_id == case.id)
        .order_by(EmailOutbox.created_at.desc())
        .limit(50)
        .all()
    )

    timeline = []
    for event in events:
        entry: Dict[str, Any] = {
            "id": event.id,
            "event_type": event.event_type,
            "timestamp_utc": event.timestamp_utc,
        }
        if event.event_type in ("stage_failed", "contest_attempt_failed"):
            payload = _load(event.payload_json, {}) or {}
            entry["detail"] = " — ".join(
                str(item)
                for item in (payload.get("stage"), payload.get("error"))
                if item
            )[:300]
        timeline.append(entry)

    return {
        "case": {
            **case_row(case, now, failed_ids),
            "pathway": {
                "via": pathway.get("via") or pathway.get("pathway"),
                "matter": pathway.get("matter_framework_id") or pathway.get("matter"),
            },
            "consent": {
                "claimant": bool(case.claimant_consent),
                "respondent": bool(case.respondent_consent),
            },
            "submission_ready": {
                "claimant": bool(case.claimant_submission_ready),
                "respondent": bool(case.respondent_submission_ready),
            },
            "steward": {
                "action": steward.get("action"),
                "state": steward.get("state"),
                "reason": steward.get("reason"),
            },
            "processing_started_at": _iso(case.processing_started_at),
            "documents": {
                "total": len(documents),
                "admitted": sum(1 for item in documents if item.admitted),
                "pending_response": sum(
                    1 for item in documents if item.response_status == "pending"
                ),
            },
            "audit_events": len(events),
        },
        "members": [
            {
                "role": member.role,
                "user_id": user.id,
                "display_name": user.display_name,
                "email": user.email,
                "email_verified": user.email_verified_at is not None,
                "active": bool(user.active),
                "joined_at": _iso(member.joined_at),
            }
            for member, user in members
        ],
        "invitations": [
            {
                "id": item.id,
                "role": item.role,
                "status": item.status,
                "expires_at": _iso(item.expires_at),
                "created_at": _iso(item.created_at),
            }
            for item in invitations
        ],
        "deadlines": [
            {
                "id": item.id,
                "label": item.label,
                "assigned_to": item.assigned_to,
                "due_at": _iso(item.due_at),
                "completed_at": _iso(item.completed_at),
            }
            for item in deadlines
        ],
        "timeline": timeline,
        "llm_executions": [execution_to_dict(item) for item in executions],
        "emails": [email_to_dict(item) for item in emails],
    }


def execution_to_dict(item: LLMExecution) -> Dict[str, Any]:
    return {
        "agent": item.agent,
        "task": item.task,
        "provider": item.effective_provider or item.requested_provider,
        "model": item.effective_model or item.requested_model,
        "status": item.status,
        "attempts": item.attempts,
        "fallback_used": bool(item.fallback_used),
        "fallback_reason": item.fallback_reason,
        "prompt_tokens": item.prompt_tokens,
        "completion_tokens": item.completion_tokens,
        "latency_ms": round(item.latency_ms) if item.latency_ms is not None else None,
        "created_at": _iso(item.created_at),
    }


# ---------------------------------------------------------------------------
# E-mails
# ---------------------------------------------------------------------------


def email_to_dict(item: EmailOutbox) -> Dict[str, Any]:
    return {
        "id": item.id,
        "case_id": item.case_id,
        "to_email": item.to_email,
        "kind": item.kind,
        "audience": item.audience,
        "subject": item.subject,
        "status": item.status,
        "attempts": item.attempts,
        "last_error": item.last_error,
        "created_at": _iso(item.created_at),
        "sent_at": _iso(item.sent_at),
        "next_attempt_at": _iso(item.next_attempt_at),
    }


def list_emails(
    db: Session,
    *,
    status: str = "",
    audience: str = "",
    case_id: str = "",
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    query = db.query(EmailOutbox)
    if status:
        query = query.filter(EmailOutbox.status == status)
    if audience:
        query = query.filter(EmailOutbox.audience == audience)
    if case_id:
        query = query.filter(EmailOutbox.case_id == case_id)
    total = query.count()
    rows = query.order_by(EmailOutbox.created_at.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": [email_to_dict(item) for item in rows]}


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------


def lead_to_dict(item: PilotLead) -> Dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "company": item.company,
        "email": item.email,
        "monthly_volume": item.monthly_volume,
        "source": item.source,
        "status": item.status or "new",
        "notes": item.notes or "",
        "notification_status": item.notification_status,
        "created_at": _iso(item.created_at),
        "updated_at": _iso(item.updated_at),
    }


def list_leads(db: Session, *, status: str = "", limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    query = db.query(PilotLead)
    if status:
        query = query.filter(PilotLead.status == status)
    total = query.count()
    rows = query.order_by(PilotLead.created_at.desc()).offset(offset).limit(limit).all()
    counts = dict(
        db.query(PilotLead.status, func.count(PilotLead.id)).group_by(PilotLead.status).all()
    )
    return {
        "total": total,
        "counts": {name: int(counts.get(name, 0)) for name in LEAD_STATUSES},
        "items": [lead_to_dict(item) for item in rows],
    }


# ---------------------------------------------------------------------------
# Usuários
# ---------------------------------------------------------------------------


def user_row(item: User, cases: int) -> Dict[str, Any]:
    return {
        "id": item.id,
        "email": item.email,
        "display_name": item.display_name,
        "active": bool(item.active),
        "email_verified": item.email_verified_at is not None,
        "locked_until": _iso(item.locked_until),
        "failed_login_attempts": item.failed_login_attempts,
        "created_at": _iso(item.created_at),
        "cases": cases,
        "is_admin": get_settings().is_admin_email(item.email),
    }


def user_summary(db: Session, item: User) -> Dict[str, Any]:
    cases = db.query(CaseMember).filter(CaseMember.user_id == item.id).count()
    return user_row(item, cases)


def list_users(db: Session, *, q: str = "", limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    query = db.query(User)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(User.email.ilike(like), User.display_name.ilike(like)))
    total = query.count()
    users = query.order_by(User.created_at.desc()).offset(offset).limit(limit).all()
    counts = dict(
        db.query(CaseMember.user_id, func.count(CaseMember.id))
        .filter(CaseMember.user_id.in_([item.id for item in users] or [""]))
        .group_by(CaseMember.user_id)
        .all()
    )
    return {
        "total": total,
        "items": [user_row(item, int(counts.get(item.id, 0))) for item in users],
    }


# ---------------------------------------------------------------------------
# Visão geral
# ---------------------------------------------------------------------------


def _llm_summary(db: Session, since: datetime) -> Dict[str, Any]:
    rows = db.query(LLMExecution).filter(LLMExecution.created_at >= since).all()
    by_model: Dict[str, Dict[str, Any]] = {}
    failed = fallback = 0
    tokens = 0
    latencies: List[float] = []
    for item in rows:
        key = f"{item.effective_provider or item.requested_provider}/{item.effective_model or item.requested_model or '?'}"
        entry = by_model.setdefault(
            key, {"model": key, "calls": 0, "failed": 0, "tokens": 0, "latency_ms": []}
        )
        entry["calls"] += 1
        entry["tokens"] += int(item.total_tokens or 0)
        if item.status != "completed":
            entry["failed"] += 1
            failed += 1
        if item.fallback_used:
            fallback += 1
        tokens += int(item.total_tokens or 0)
        if item.latency_ms is not None:
            latencies.append(item.latency_ms)
            entry["latency_ms"].append(item.latency_ms)
    models = []
    for entry in by_model.values():
        values = entry.pop("latency_ms")
        entry["avg_latency_ms"] = round(sum(values) / len(values)) if values else None
        models.append(entry)
    models.sort(key=lambda item: -item["calls"])
    return {
        "calls": len(rows),
        "failed": failed,
        "fallback_used": fallback,
        "tokens": tokens,
        "avg_latency_ms": round(sum(latencies) / len(latencies)) if latencies else None,
        "models": models,
    }


def config_checks() -> List[Dict[str, Any]]:
    settings = get_settings()
    checks = [
        ("smtp", "E-mail transacional (SMTP)", settings.email_enabled,
         "Sem SMTP nenhum aviso sai: os e-mails ficam só no log."),
        ("llm", "Modelos de linguagem (OpenRouter)", settings.openrouter_enabled,
         "Sem a chave, toda decisão termina inconclusiva."),
        ("attestation", "Chave Ed25519 das attestations", settings.attestation_enabled,
         "Sem ela não há attestation nem prazo de recurso automático."),
        ("privacy", "Controlador dos dados (política de privacidade)", settings.privacy_contacts_declared,
         "A política de privacidade fica sem responsável."),
        ("notifications", "Avisos por e-mail ligados", settings.notifications_enabled,
         "As partes não são avisadas dos atos e prazos."),
        ("ops_alerts", "Destino dos alertas de operação", bool(settings.ops_recipients),
         "Falhas de etapa só aparecem aqui, sem alerta por e-mail."),
        ("independence", "Julgador e revisor de famílias distintas",
         settings.model_independence_satisfied,
         "A auditoria perde independência."),
        ("payments", "Pagamento da decisão (Stripe)", settings.payments_enabled,
         "Opcional: desligado, o recurso não aparece."),
    ]
    return [
        {"key": key, "label": label, "ok": bool(ok), "hint": hint}
        for key, label, ok, hint in checks
    ]


def overview(db: Session) -> Dict[str, Any]:
    now = now_utc()
    day = now - timedelta(hours=24)
    week = now - timedelta(days=7)

    by_status = dict(db.query(Case.status, func.count(Case.id)).group_by(Case.status).all())
    cases_total = sum(by_status.values())
    stuck = (
        db.query(Case)
        .filter(Case.status.like("processing%"), Case.processing_started_at < now - PROCESSING_TTL)
        .count()
    )
    failed_stage = (
        db.query(Case)
        .filter(
            Case.id.in_(
                db.query(AuditEvent.case_id).filter(
                    AuditEvent.event_type.in_(("stage_failed", "contest_attempt_failed")),
                    AuditEvent.timestamp_utc >= day.isoformat(),
                )
            ),
            Case.status.notin_(list(ACTIVE_EXCLUDED)),
        )
        .count()
    )
    no_merit = (
        db.query(Case)
        .filter(or_(Case.procedure_conclusion.in_(NO_MERIT), Case.status.in_(NO_MERIT)))
        .count()
    )
    stalled = (
        db.query(Case)
        .filter(Case.status.notin_(list(ACTIVE_EXCLUDED)), Case.updated_at < now - STALLED_AFTER)
        .count()
    )
    stale_invites = (
        db.query(Invitation)
        .filter(Invitation.status == "pending", Invitation.created_at < now - INVITE_STALE_AFTER)
        .count()
    )

    outbox_counts = dict(
        db.query(EmailOutbox.status, func.count(EmailOutbox.id)).group_by(EmailOutbox.status).all()
    )
    overdue_pending = (
        db.query(EmailOutbox)
        .filter(EmailOutbox.status == "pending", EmailOutbox.next_attempt_at < now - timedelta(minutes=10))
        .count()
    )
    lead_counts = dict(
        db.query(PilotLead.status, func.count(PilotLead.id)).group_by(PilotLead.status).all()
    )

    return {
        "generated_at": now.isoformat(),
        "users": {
            "total": db.query(User).count(),
            "verified": db.query(User).filter(User.email_verified_at.isnot(None)).count(),
            "new_7d": db.query(User).filter(User.created_at >= week).count(),
        },
        "cases": {
            "total": cases_total,
            "new_7d": db.query(Case).filter(Case.created_at >= week).count(),
            "by_status": {key: int(value) for key, value in sorted(by_status.items())},
        },
        "attention": {
            "stuck": stuck,
            "stage_failed": failed_stage,
            "no_merit": no_merit,
            "stalled": stalled,
            "stale_invitations": stale_invites,
            "emails_failed": int(outbox_counts.get("failed", 0)),
            "emails_overdue": overdue_pending,
            "leads_new": int(lead_counts.get("new", 0)),
        },
        "leads": {name: int(lead_counts.get(name, 0)) for name in LEAD_STATUSES},
        "emails": {
            name: int(outbox_counts.get(name, 0))
            for name in ("pending", "sending", "sent", "logged", "failed")
        },
        "llm": {"last_24h": _llm_summary(db, day), "last_7d": _llm_summary(db, week)},
        "config": config_checks(),
    }
