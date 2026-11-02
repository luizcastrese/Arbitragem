"""Cadastro, login, verificação de e-mail, redefinição de senha e sessão."""

from __future__ import annotations

from datetime import timedelta
from typing import Dict

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy.orm import Session

from app.api import context as ctx
from app.api.common import _session_user_or_401, _set_session_cookie
from app.core.email import deliver_password_reset_email, deliver_verification_email
from app.db.access_repository import (
    EMAIL_VERIFICATION,
    PASSWORD_RESET,
    AccountLocked,
    authenticate_user,
    consume_auth_token,
    create_session,
    get_user_by_email,
    issue_auth_token,
    mark_email_verified,
    register_user,
    revoke_session,
    set_password,
    user_to_dict,
)
from app.db.session import get_db
from app.schemas import (
    LoginRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    RegisterRequest,
    VerifyEmailRequest,
)

router = APIRouter()


def _send_verification(db: Session, user) -> Dict:
    """Emite e envia um novo link de verificação. No modo local (sem produção)
    o token volta na resposta para permitir testar sem SMTP configurado."""
    token, record = issue_auth_token(
        db,
        user,
        EMAIL_VERIFICATION,
        timedelta(hours=ctx.settings.email_verification_ttl_hours),
    )
    delivery = deliver_verification_email(
        to_email=user.email,
        display_name=user.display_name,
        token=token,
    )
    result = {
        "required": ctx.settings.email_verification_required,
        "verified": user.email_verified_at is not None,
        "expires_at": record.expires_at.isoformat(),
        "delivery": delivery,
    }
    if ctx.settings.allow_role_tokens:
        result["verification_token"] = token
        result["verification_path"] = f"/ui/?verify={token}"
    return result


@router.post("/auth/register", status_code=201)
def register(
    payload: RegisterRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        user = register_user(db, payload.display_name, payload.email, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    verification = _send_verification(db, user)
    token, session = create_session(db, user)
    _set_session_cookie(response, token)
    return {
        "user": user_to_dict(user),
        "expires_at": session.expires_at.isoformat(),
        "email_verification": verification,
    }


@router.post("/auth/login")
def login(
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        user = authenticate_user(db, payload.email, payload.password)
    except AccountLocked as locked:
        minutes = max(1, round(locked.retry_after_seconds / 60))
        raise HTTPException(
            status_code=429,
            detail=(
                "Conta temporariamente bloqueada por tentativas de senha "
                f"malsucedidas. Tente novamente em cerca de {minutes} min ou "
                "redefina a senha."
            ),
            headers={"Retry-After": str(locked.retry_after_seconds)},
        ) from locked
    if not user:
        raise HTTPException(status_code=401, detail="E-mail ou senha inválidos")
    token, session = create_session(db, user)
    _set_session_cookie(response, token)
    return {
        "user": user_to_dict(user),
        "expires_at": session.expires_at.isoformat(),
    }


@router.post("/auth/verify-email")
def verify_email(
    payload: VerifyEmailRequest,
    db: Session = Depends(get_db),
):
    try:
        user = consume_auth_token(db, payload.token, EMAIL_VERIFICATION)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    user = mark_email_verified(db, user)
    return {"message": "E-mail verificado", "user": user_to_dict(user)}


@router.post("/auth/verify-email/resend")
def resend_verification(
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    user = _session_user_or_401(db, x_session_token)
    if user.email_verified_at:
        return {
            "message": "Este e-mail já está verificado",
            "email_verification": {"required": ctx.settings.email_verification_required, "verified": True},
        }
    return {
        "message": "Novo link de verificação enviado",
        "email_verification": _send_verification(db, user),
    }


@router.post("/auth/password-reset", status_code=202)
def request_password_reset(
    payload: PasswordResetRequest,
    db: Session = Depends(get_db),
):
    """Sempre responde igual, exista ou não a conta: a resposta não pode
    servir para descobrir quais e-mails estão cadastrados."""
    generic = {
        "message": (
            "Se existir uma conta com este e-mail, o link de redefinição foi "
            "enviado para ele."
        )
    }
    user = get_user_by_email(db, payload.email)
    if not user or not user.active:
        return generic

    token, _ = issue_auth_token(
        db,
        user,
        PASSWORD_RESET,
        timedelta(minutes=ctx.settings.password_reset_ttl_minutes),
    )
    deliver_password_reset_email(
        to_email=user.email,
        display_name=user.display_name,
        token=token,
    )
    if ctx.settings.allow_role_tokens:
        # Modo local: sem SMTP configurado o link precisa sair por algum
        # canal. Em produção isso nunca é exposto.
        return {**generic, "reset_token": token, "reset_path": f"/ui/?reset={token}"}
    return generic


@router.post("/auth/password-reset/confirm")
def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        user = consume_auth_token(db, payload.token, PASSWORD_RESET)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    user = set_password(db, user, payload.password)
    response.delete_cookie(
        ctx.SESSION_COOKIE_NAME,
        path="/",
        secure=ctx.settings.is_production,
        httponly=True,
        samesite="lax",
    )
    return {
        "message": (
            "Senha redefinida. Todas as sessões abertas foram encerradas: "
            "entre novamente com a nova senha."
        ),
        "user": user_to_dict(user),
    }


@router.get("/auth/me")
def current_user(
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    return user_to_dict(_session_user_or_401(db, x_session_token))


@router.post("/auth/logout")
def logout(
    response: Response,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    if not revoke_session(db, x_session_token):
        raise HTTPException(status_code=401, detail="Sessão inválida")
    response.delete_cookie(
        ctx.SESSION_COOKIE_NAME,
        path="/",
        secure=ctx.settings.is_production,
        httponly=True,
        samesite="lax",
    )
    return {"message": "Sessão encerrada"}
