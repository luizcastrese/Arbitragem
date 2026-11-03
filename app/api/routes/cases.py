"""Casos, convites, prazos e adesão das partes ao procedimento."""

from __future__ import annotations

import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.api import context as ctx
from app.api.common import (
    _assert_procedure_open,
    _case_or_404,
    _hash_token,
    _public_case,
    _require_actor,
    _require_case_view,
    _require_procedure_party,
    _require_verified_email,
    _session_user_or_401,
)
from app.core.email import deliver_invitation_email
from app.core.identifiers import email_reference
from app.core.terms import TermsNotFound, get_terms
from app.db.access_repository import (
    accept_invitation,
    add_member,
    create_deadline,
    create_invitation,
    create_notification,
    deadline_to_dict,
    get_user_by_token,
    invitation_to_dict,
    mark_email_verified,
    reissue_invitation,
    user_case_ids,
)
from app.db.models import Deadline
from app.db.repository import (
    append_audit,
    case_to_dict,
    create_case as persist_case,
    get_case,
    list_cases,
    record_consent,
)
from app.db.session import get_db
from app.domain.frameworks import MATTER, framework_kind, get_framework
from app.domain.pathway import ARBITRATION_TERMS_SINCE, PathwayError, build_pathway
from app.schemas import (
    AcceptInvitationRequest,
    ConsentRequest,
    CreateCaseRequest,
    DeadlineRequest,
    InvitationRequest,
)

router = APIRouter()


@router.get("/cases")
def get_cases(
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    cases = list_cases(db)
    user = get_user_by_token(db, x_session_token)
    if ctx.settings.auth_required and not user:
        raise HTTPException(status_code=401, detail="Entre para acessar seus casos")
    if user:
        allowed_ids = set(user_case_ids(db, user.id))
        cases = [case for case in cases if case.id in allowed_ids]
    return [_public_case(case) for case in cases]


@router.get("/cases/{case_id}")
def get_case_detail(
    case_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    return case_to_dict(case, include_content=False, include_embeddings=False)


@router.post("/cases", status_code=201)
def create_case(
    payload: CreateCaseRequest,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    user = get_user_by_token(db, x_session_token)
    if ctx.settings.auth_required and not user:
        raise HTTPException(status_code=401, detail="Entre para criar um caso")
    _require_verified_email(user)
    matter_id = payload.matter_framework_id or ctx.settings.framework_id
    try:
        if framework_kind(matter_id) != MATTER:
            raise LookupError(matter_id)
        matter = get_framework(matter_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=422, detail=f"Matéria desconhecida: {matter_id}"
        ) from exc
    try:
        pathway = build_pathway(
            entry_point=payload.entry_point,
            matter_framework_id=matter.id,
            consumer_relation=matter.consumer_relation,
            lawsuit_number=payload.lawsuit_number,
            court=payload.court,
            consumer_party=payload.consumer_party,
            creator_role=payload.creator_role,
            counsel_bar_number=(
                payload.counsel_bar_number if payload.acting_as_counsel else None
            ),
        )
    except PathwayError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    credentials = {
        "claimant": secrets.token_urlsafe(24),
        "respondent": secrets.token_urlsafe(24),
        "manager": secrets.token_urlsafe(24),
    }
    case = persist_case(
        db,
        title=payload.title,
        claimant=payload.claimant,
        respondent=payload.respondent,
        claimant_token_hash=_hash_token(credentials["claimant"]),
        respondent_token_hash=_hash_token(credentials["respondent"]),
        manager_token_hash=_hash_token(credentials["manager"]),
        pathway=pathway,
    )
    if user:
        # Quem abre o caso entra na parte que escolheu (reclamante por padrão);
        # o convidado recebe a oposta. O gestor é a IA.
        add_member(db, case.id, user.id, payload.creator_role)
        db.expire_all()
        case = get_case(db, case.id)
    result = case_to_dict(case, include_content=False, include_embeddings=False)
    if not ctx.settings.auth_required:
        result["access_credentials"] = credentials
    return result


@router.get("/cases/{case_id}/invitations")
def get_invitations(
    case_id: str,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_procedure_party(db, case, x_actor_token)
    return [invitation_to_dict(item) for item in case.invitations]


@router.post("/cases/{case_id}/invitations", status_code=201)
def invite_participant(
    case_id: str,
    payload: InvitationRequest,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_procedure_party(db, case, x_actor_token)
    actor = get_user_by_token(db, x_actor_token)
    try:
        token, invitation = create_invitation(
            db,
            case.id,
            payload.email,
            payload.role,
            actor.id if actor else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    append_audit(
        db,
        case,
        "participant_invited",
        # Máscara e impressão, nunca o endereço: a auditoria é imutável e
        # legível por todos os participantes do caso, então um e-mail gravado
        # aqui não poderia mais ser removido no pedido de eliminação.
        {
            **email_reference(invitation.email),
            "role": invitation.role,
            "invitation_id": invitation.id,
        },
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
    return _invitation_delivery_payload(invitation, token, case)


def _invitation_delivery_payload(invitation, token: str, case) -> dict:
    email_delivery = deliver_invitation_email(
        to_email=invitation.email,
        role=invitation.role,
        case_title=case.title,
        token=token,
    )
    result = invitation_to_dict(invitation)
    result["email_delivery"] = email_delivery
    # O token de aceite só é exposto na resposta no modo local. Em produção o
    # convite chega exclusivamente pelo e-mail transacional, evitando que o
    # segredo trafegue por outro canal.
    if ctx.settings.allow_role_tokens:
        result["acceptance_token"] = token
        result["acceptance_path"] = f"/ui/?invite={token}"
    return result


@router.post("/cases/{case_id}/invitations/{invitation_id}/resend")
def resend_invitation(
    case_id: str,
    invitation_id: str,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """Reemite um convite pendente: o token anterior deixa de valer.

    Sem isto, um convite perdido ou um e-mail que não chegou deixa a
    contraparte sem entrada — e um segundo POST /invitations colide com o
    pendente.
    """
    case = _case_or_404(db, case_id)
    actor_role = _require_procedure_party(db, case, x_actor_token)
    invitation = next(
        (item for item in case.invitations if item.id == invitation_id),
        None,
    )
    if invitation is None:
        raise HTTPException(status_code=404, detail="Convite não encontrado")
    try:
        token, invitation = reissue_invitation(db, invitation)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    append_audit(
        db,
        case,
        "invitation_reissued",
        {
            **email_reference(invitation.email),
            "role": invitation.role,
            "invitation_id": invitation.id,
            "actor": actor_role,
        },
    )
    db.commit()
    return _invitation_delivery_payload(invitation, token, case)


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
    # O convite é entregue exclusivamente por e-mail e vinculado ao endereço:
    # apresentá-lo prova o controle da caixa, o mesmo que a verificação faria.
    if not ctx.settings.allow_role_tokens:
        user = mark_email_verified(db, user)
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
    _require_procedure_party(db, case, x_actor_token)
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
    _require_procedure_party(db, case, x_actor_token)
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
    _assert_procedure_open(case)
    if case.manifest_locked:
        raise HTTPException(
            status_code=409,
            detail="O consentimento não pode ser alterado após a trava do processo",
        )
    try:
        terms = get_terms(payload.terms_version)
    except TermsNotFound as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Versão de termos desconhecida: {payload.terms_version}. "
                "Recarregue os termos vigentes em /terms antes de aceitar."
            ),
        ) from exc
    if payload.elects_arbitration:
        if not payload.accepted:
            raise HTTPException(
                status_code=422,
                detail="A escolha pela arbitragem exige o aceite do procedimento",
            )
        if not case.pathway_json:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Este caso foi aberto antes da via arbitral e segue com "
                    "decisão não vinculante"
                ),
            )
        if terms.version < ARBITRATION_TERMS_SINCE:
            raise HTTPException(
                status_code=422,
                detail=(
                    "A escolha pela arbitragem exige os termos vigentes, que "
                    "descrevem a via arbitral. Recarregue os termos em /terms."
                ),
            )
    updated = record_consent(
        db,
        case,
        party=payload.party,
        accepted=payload.accepted,
        terms_version=terms.version,
        terms_sha256=terms.sha256,
        tax_id=payload.tax_id,
        elects_arbitration=payload.elects_arbitration,
    )
    return case_to_dict(updated, include_content=False, include_embeddings=False)[
        "consent"
    ]
