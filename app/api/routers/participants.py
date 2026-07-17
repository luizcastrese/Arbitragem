"""Rotas de participantes do caso: convites, prazos e consentimento."""

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import (
    _case_or_404,
    _require_actor,
    _require_case_view,
    _session_user_or_401,
    get_db,
)
from app.db.access_repository import (
    accept_invitation,
    create_deadline,
    create_invitation,
    create_notification,
    deadline_to_dict,
    invitation_to_dict,
)
from app.db.models import Deadline
from app.db.repository import append_audit, case_to_dict, record_consent
from app.schemas import (
    AcceptInvitationRequest,
    ConsentRequest,
    DeadlineRequest,
    InvitationRequest,
)

router = APIRouter(tags=["participantes"])


@router.get("/cases/{case_id}/invitations")
def get_invitations(
    case_id: str,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_actor(db, case, x_actor_token, "manager")
    return [invitation_to_dict(item) for item in case.invitations]


@router.post("/cases/{case_id}/invitations", status_code=201)
def invite_participant(
    case_id: str,
    payload: InvitationRequest,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    actor = _require_actor(db, case, x_actor_token, "manager")
    token, invitation = create_invitation(
        db,
        case.id,
        payload.email,
        payload.role,
        actor.id if actor else None,
    )
    append_audit(
        db,
        case,
        "participant_invited",
        {"email": invitation.email, "role": invitation.role, "invitation_id": invitation.id},
    )
    db.commit()
    create_notification(
        db,
        case.id,
        payload.role,
        "invitation_created",
        "Convite para participar do procedimento",
        f"Você foi convidado para atuar como {payload.role} no caso {case.title}.",
    )
    result = invitation_to_dict(invitation)
    result["acceptance_token"] = token
    result["acceptance_path"] = f"/ui/?invite={token}"
    return result


@router.post("/invitations/accept")
def accept_case_invitation(
    payload: AcceptInvitationRequest,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    user = _session_user_or_401(db, x_session_token)
    try:
        invitation = accept_invitation(db, payload.token, user)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    case = _case_or_404(db, invitation.case_id)
    append_audit(
        db,
        case,
        "invitation_accepted",
        {"user_id": user.id, "role": invitation.role, "invitation_id": invitation.id},
    )
    db.commit()
    return {"case_id": case.id, "role": invitation.role, "message": "Convite aceito"}


@router.get("/cases/{case_id}/deadlines")
def get_deadlines(
    case_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    return [deadline_to_dict(item) for item in case.deadlines]


@router.post("/cases/{case_id}/deadlines", status_code=201)
def add_deadline(
    case_id: str,
    payload: DeadlineRequest,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_actor(db, case, x_actor_token, "manager")
    try:
        due_at = datetime.fromisoformat(payload.due_at.replace("Z", "+00:00"))
        if due_at.tzinfo is None:
            due_at = due_at.astimezone()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Data do prazo inválida") from exc
    deadline = create_deadline(
        db, case.id, payload.label, payload.kind, payload.assigned_to, due_at
    )
    append_audit(
        db,
        case,
        "deadline_created",
        {"deadline_id": deadline.id, "assigned_to": deadline.assigned_to, "due_at": deadline.due_at.isoformat()},
    )
    db.commit()
    for party in ({"claimant", "respondent", "manager"} if payload.assigned_to == "all" else {payload.assigned_to}):
        create_notification(
            db,
            case.id,
            party,
            "deadline_created",
            "Novo prazo no procedimento",
            f"{deadline.label}: até {deadline.due_at.isoformat()}.",
        )
    return deadline_to_dict(deadline)


@router.post("/cases/{case_id}/deadlines/{deadline_id}/complete")
def complete_deadline(
    case_id: str,
    deadline_id: str,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_actor(db, case, x_actor_token, "manager")
    deadline = db.query(Deadline).filter(
        Deadline.case_id == case.id, Deadline.id == deadline_id
    ).one_or_none()
    if not deadline:
        raise HTTPException(status_code=404, detail="Prazo não encontrado")
    deadline.completed_at = datetime.now().astimezone()
    append_audit(db, case, "deadline_completed", {"deadline_id": deadline.id})
    db.commit()
    return deadline_to_dict(deadline)


@router.post("/cases/{case_id}/consent")
def set_case_consent(
    case_id: str,
    payload: ConsentRequest,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_actor(db, case, x_actor_token, payload.party)
    if case.manifest_locked:
        raise HTTPException(
            status_code=409,
            detail="O consentimento não pode ser alterado após a trava do processo",
        )
    updated = record_consent(
        db,
        case,
        party=payload.party,
        accepted=payload.accepted,
        terms_version=payload.terms_version,
    )
    return case_to_dict(updated, include_content=False, include_embeddings=False)[
        "consent"
    ]
