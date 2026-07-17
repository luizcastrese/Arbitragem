"""Rotas de casos: listagem, detalhe e criação."""

import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import (
    _case_or_404,
    _hash_token,
    _public_case,
    _require_case_view,
    get_db,
    settings,
)
from app.db.access_repository import add_member, get_user_by_token, user_case_ids
from app.db.repository import (
    case_to_dict,
    create_case as persist_case,
    get_case,
    list_cases,
)
from app.schemas import CreateCaseRequest

router = APIRouter(prefix="/cases", tags=["casos"])


@router.get("")
def get_cases(
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    cases = list_cases(db)
    user = get_user_by_token(db, x_session_token)
    if settings.auth_required and not user:
        raise HTTPException(status_code=401, detail="Entre para acessar seus casos")
    if user:
        allowed_ids = set(user_case_ids(db, user.id))
        cases = [case for case in cases if case.id in allowed_ids]
    return [_public_case(case) for case in cases]


@router.get("/{case_id}")
def get_case_detail(
    case_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    return case_to_dict(case, include_content=False, include_embeddings=False)


@router.post("", status_code=201)
def create_case(
    payload: CreateCaseRequest,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
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
    )
    user = get_user_by_token(db, x_session_token)
    if user:
        add_member(db, case.id, user.id, "manager")
        db.expire_all()
        case = get_case(db, case.id)
    result = case_to_dict(case, include_content=False, include_embeddings=False)
    result["access_credentials"] = credentials
    return result
