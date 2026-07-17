"""Rotas de autenticação: registro, login, sessão atual e logout."""

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import _session_user_or_401, get_db
from app.db.access_repository import (
    authenticate_user,
    create_session,
    register_user,
    revoke_session,
    user_to_dict,
)
from app.schemas import LoginRequest, RegisterRequest

router = APIRouter(prefix="/auth", tags=["autenticação"])


@router.post("/register", status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    try:
        user = register_user(db, payload.display_name, payload.email, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    token, session = create_session(db, user)
    return {
        "user": user_to_dict(user),
        "session_token": token,
        "expires_at": session.expires_at.isoformat(),
    }


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_user(db, payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="E-mail ou senha inválidos")
    token, session = create_session(db, user)
    return {
        "user": user_to_dict(user),
        "session_token": token,
        "expires_at": session.expires_at.isoformat(),
    }


@router.get("/me")
def current_user(
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    return user_to_dict(_session_user_or_401(db, x_session_token))


@router.post("/logout")
def logout(
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    if not revoke_session(db, x_session_token):
        raise HTTPException(status_code=401, detail="Sessão inválida")
    return {"message": "Sessão encerrada"}
