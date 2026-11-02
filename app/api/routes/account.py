"""Direitos do titular (LGPD): exportação e eliminação da conta."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy.orm import Session

from app.api import context as ctx
from app.api.common import _session_user_or_401
from app.db.privacy_repository import (
    ErasureBlocked,
    anonymize_user,
    export_user_data,
    open_case_ids,
)
from app.db.session import get_db

router = APIRouter()


@router.get("/account/data-export")
def export_account_data(
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """Acesso e portabilidade (art. 18, II e V da LGPD): tudo o que a
    plataforma guarda sobre a conta, em JSON."""
    user = _session_user_or_401(db, x_session_token)
    return export_user_data(db, user)


@router.post("/account/erasure")
def erase_account(
    response: Response,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """Eliminação (art. 18, VI da LGPD) por anonimização.

    A cadeia de auditoria e as attestations não são apagadas: elas guardam
    hashes e atos, e removê-las invalidaria decisões que terceiros podem ter
    executado. O que sai é a identificação do titular.
    """
    user = _session_user_or_401(db, x_session_token)
    try:
        result = anonymize_user(db, user)
    except ErasureBlocked as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc
    response.delete_cookie(
        ctx.SESSION_COOKIE_NAME,
        path="/",
        secure=ctx.settings.is_production,
        httponly=True,
        samesite="lax",
    )
    return result


@router.get("/account/erasure/preview")
def preview_account_erasure(
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """Diz de antemão se a eliminação seria aceita e o que ela preserva."""
    user = _session_user_or_401(db, x_session_token)
    blocking = open_case_ids(db, user.id)
    return {
        "allowed": not blocking,
        "blocking_case_ids": blocking,
        "detail": (
            "A identificação não pode ser removida enquanto a conta for parte "
            "de um caso em andamento."
            if blocking
            else "A conta pode ser anonimizada agora."
        ),
        "preserved": [
            "cadeia de auditoria dos casos",
            "hashes e metadados dos documentos",
            "attestations emitidas",
        ],
        "removed": [
            "nome de exibição e e-mail",
            "credencial de acesso e sessões",
            "notificações e convites pendentes",
        ],
    }
