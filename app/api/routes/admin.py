"""Painel de operação: o que o time precisa para ajudar pessoas e manter o
serviço de pé.

Acesso restrito às contas de `ADMIN_EMAILS`. A operação enxerga metadados
(situação, papéis, falhas, e-mails, modelos), nunca o teor das peças,
documentos, propostas ou decisões: o caso é confidencial entre as partes. Cada
consulta a um caso e cada intervenção é gravada em `admin_actions`, e uma
intervenção que muda o andamento entra também na trilha de auditoria do caso,
visível às partes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.common import _case_or_404, _require_admin
from app.api.routes.auth import _send_verification
from app.api.steward import _RESTORE_FROM_PROCESSING, _conduct_steward
from app.db import admin_repository as repo
from app.db.access_repository import clear_failed_logins, revoke_user_sessions
from app.db.models import EmailOutbox, PilotLead, User
from app.db.repository import append_audit, get_case
from app.db.session import get_db
from app.domain.concurrency import PROCESSING_TTL, TERMINAL_STATUSES, release_processing
from app.notifications.outbox import dispatch_pending, requeue
from app.schemas import AdminLeadUpdate, AdminReasonRequest, AdminUserActiveRequest

logger = logging.getLogger("valinor.admin")

router = APIRouter(prefix="/admin")


@router.get("/overview")
def admin_overview(
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    _require_admin(db, x_session_token)
    return repo.overview(db)


# --- casos ------------------------------------------------------------------


@router.get("/cases")
def admin_cases(
    status: str = "",
    attention: str = Query(default="", pattern="^(|stuck|stage_failed|no_merit|stalled|contested)$"),
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    _require_admin(db, x_session_token)
    return repo.list_cases(
        db, status=status, attention=attention, q=q, limit=limit, offset=offset
    )


@router.get("/cases/{case_id}")
def admin_case_detail(
    case_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    admin = _require_admin(db, x_session_token)
    case = _case_or_404(db, case_id)
    repo.log_action(db, admin, "case_viewed", target_type="case", target_id=case.id)
    detail = repo.case_detail(db, case)
    detail["actions"] = repo.list_actions(db, target_id=case.id, limit=50)
    return detail


@router.post("/cases/{case_id}/unstick")
def admin_unstick_case(
    case_id: str,
    payload: AdminReasonRequest,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """Devolve ao status anterior um caso preso em `processing_*` depois do TTL.

    É o que a varredura de recuperação faria sozinha; aqui a operação o faz sob
    demanda e deixa o motivo na trilha do caso."""
    admin = _require_admin(db, x_session_token)
    case = _case_or_404(db, case_id)
    status = str(case.status or "")
    restored = _RESTORE_FROM_PROCESSING.get(status)
    if restored is None:
        raise HTTPException(status_code=409, detail="O caso não está preso em uma etapa de modelo")
    started = case.processing_started_at
    if started is not None and started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if started is not None and datetime.now(timezone.utc) - started <= PROCESSING_TTL:
        # Dentro do TTL a etapa pode estar rodando em outra réplica.
        raise HTTPException(
            status_code=409,
            detail="A etapa ainda está dentro do prazo de execução de 10 minutos; aguarde",
        )
    release_processing(db, case, restored)
    append_audit(
        db,
        case,
        "operations_released_stage",
        {
            "actor": "operations",
            "abandoned_status": status,
            "restored_status": restored,
            "reason": payload.reason,
        },
    )
    db.commit()
    repo.log_action(
        db, admin, "case_unstuck", target_type="case", target_id=case.id,
        detail=f"{status} -> {restored}: {payload.reason}",
    )
    return {"case_id": case.id, "status": restored}


@router.post("/cases/{case_id}/resume")
def admin_resume_case(
    case_id: str,
    payload: AdminReasonRequest,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """Pede ao gestor que conduza o caso de novo a partir do que está gravado."""
    admin = _require_admin(db, x_session_token)
    case = _case_or_404(db, case_id)
    if case.status in TERMINAL_STATUSES or str(case.status).startswith("processing"):
        raise HTTPException(
            status_code=409,
            detail="O caso está encerrado ou em processamento; não há o que retomar",
        )
    append_audit(
        db,
        case,
        "operations_resumed_steward",
        {"actor": "operations", "status": case.status, "reason": payload.reason},
    )
    db.commit()
    repo.log_action(
        db, admin, "case_resumed", target_type="case", target_id=case.id,
        detail=payload.reason,
    )
    try:
        _conduct_steward(db, get_case(db, case.id), wait=0, run_model_stages=True)
    except HTTPException as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    db.expire_all()
    return {"case_id": case.id, "status": get_case(db, case.id).status}


# --- e-mails ----------------------------------------------------------------


@router.get("/emails")
def admin_emails(
    status: str = "",
    audience: str = "",
    case_id: str = "",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    _require_admin(db, x_session_token)
    return repo.list_emails(
        db, status=status, audience=audience, case_id=case_id, limit=limit, offset=offset
    )


@router.post("/emails/dispatch")
def admin_dispatch_emails(
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """Envia agora a fila vencida, sem esperar o próximo ciclo do despachante."""
    admin = _require_admin(db, x_session_token)
    counts = dispatch_pending(db)
    repo.log_action(db, admin, "emails_dispatched", target_type="email", detail=str(counts))
    return counts


@router.post("/emails/{email_id}/retry")
def admin_retry_email(
    email_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    admin = _require_admin(db, x_session_token)
    row = db.get(EmailOutbox, email_id)
    if row is None:
        raise HTTPException(status_code=404, detail="E-mail não encontrado")
    if row.status not in ("failed", "logged", "pending"):
        raise HTTPException(status_code=409, detail="Só se reenvia e-mail falho, registrado em log ou pendente")
    requeue(db, row)
    repo.log_action(
        db, admin, "email_requeued", target_type="email", target_id=row.id, detail=row.kind
    )
    return repo.email_to_dict(row)


# --- leads ------------------------------------------------------------------


@router.get("/leads")
def admin_leads(
    status: str = "",
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    _require_admin(db, x_session_token)
    return repo.list_leads(db, status=status, limit=limit, offset=offset)


@router.patch("/leads/{lead_id}")
def admin_update_lead(
    lead_id: str,
    payload: AdminLeadUpdate,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    admin = _require_admin(db, x_session_token)
    lead = db.get(PilotLead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead não encontrado")
    changes = []
    if payload.status is not None and payload.status != (lead.status or "new"):
        changes.append(f"status {lead.status or 'new'} -> {payload.status}")
        lead.status = payload.status
    if payload.notes is not None and payload.notes != (lead.notes or ""):
        changes.append("anotações")
        lead.notes = payload.notes
    if changes:
        lead.handled_by_user_id = admin.id
        lead.updated_at = datetime.now(timezone.utc)
        db.commit()
        repo.log_action(
            db, admin, "lead_updated", target_type="lead", target_id=lead.id,
            detail=", ".join(changes),
        )
    return repo.lead_to_dict(lead)


# --- usuários ---------------------------------------------------------------


@router.get("/users")
def admin_users(
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    _require_admin(db, x_session_token)
    return repo.list_users(db, q=q, limit=limit, offset=offset)


def _user_or_404(db: Session, user_id: str) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    return user


@router.post("/users/{user_id}/resend-verification")
def admin_resend_verification(
    user_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    admin = _require_admin(db, x_session_token)
    user = _user_or_404(db, user_id)
    if user.email_verified_at is not None:
        raise HTTPException(status_code=409, detail="O e-mail já foi confirmado")
    result = _send_verification(db, user)
    repo.log_action(
        db, admin, "verification_resent", target_type="user", target_id=user.id,
        detail=str(result["delivery"].get("transport")),
    )
    # O token nunca volta ao painel: quem confirma é o dono da caixa de entrada.
    return {"delivery": result["delivery"], "expires_at": result["expires_at"]}


@router.post("/users/{user_id}/unlock")
def admin_unlock_user(
    user_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    admin = _require_admin(db, x_session_token)
    user = _user_or_404(db, user_id)
    clear_failed_logins(db, user)
    repo.log_action(db, admin, "user_unlocked", target_type="user", target_id=user.id)
    return repo.user_summary(db, user)


@router.post("/users/{user_id}/active")
def admin_set_user_active(
    user_id: str,
    payload: AdminUserActiveRequest,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    admin = _require_admin(db, x_session_token)
    user = _user_or_404(db, user_id)
    if user.id == admin.id:
        raise HTTPException(status_code=409, detail="Não é possível suspender a própria conta")
    user.active = payload.active
    db.commit()
    if not payload.active:
        revoke_user_sessions(db, user)
    repo.log_action(
        db, admin, "user_reactivated" if payload.active else "user_suspended",
        target_type="user", target_id=user.id, detail=payload.reason,
    )
    return repo.user_summary(db, user)


# --- registro ---------------------------------------------------------------


@router.get("/actions")
def admin_actions(
    limit: int = Query(default=100, ge=1, le=500),
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    _require_admin(db, x_session_token)
    return {"items": repo.list_actions(db, limit=limit)}
