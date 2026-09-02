import secrets
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.auth import hash_access_token, hash_password, verify_password
from app.core.config import get_settings
from app.db.models import (
    AuthSession,
    AuthToken,
    CaseMember,
    Deadline,
    Invitation,
    Notification,
    User,
)


EMAIL_VERIFICATION = "email_verification"
PASSWORD_RESET = "password_reset"
PRINCIPAL_ROLES = ("claimant", "respondent")
SUBSIDIARY_ROLE = "subsidiary"
MEMBER_ROLES = (*PRINCIPAL_ROLES, SUBSIDIARY_ROLE)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def user_to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "email_verified": user.email_verified_at is not None,
        "email_verified_at": (
            user.email_verified_at.isoformat() if user.email_verified_at else None
        ),
        "created_at": user.created_at.isoformat(),
    }


def register_user(db: Session, display_name: str, email: str, password: str) -> User:
    normalized_email = email.strip().lower()
    if db.query(User).filter(User.email == normalized_email).first():
        raise ValueError("Já existe uma conta com este e-mail")
    user = User(
        id=str(uuid.uuid4()),
        email=normalized_email,
        display_name=display_name.strip(),
        password_hash=hash_password(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class AccountLocked(Exception):
    """Conta temporariamente bloqueada por excesso de tentativas de senha."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("Conta temporariamente bloqueada")
        self.retry_after_seconds = retry_after_seconds


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    """Hash descartável usado quando o e-mail não existe: mantém o custo da
    verificação parecido com o de uma conta real e evita descobrir contas
    cadastradas pelo tempo de resposta."""
    return hash_password("conta-inexistente-valinor")


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email.strip().lower()).one_or_none()


def lock_seconds_remaining(user: User) -> int:
    if not user.locked_until:
        return 0
    remaining = (_as_utc(user.locked_until) - utc_now()).total_seconds()
    return int(remaining) + 1 if remaining > 0 else 0


def register_failed_login(db: Session, user: User) -> int:
    """Conta a tentativa e bloqueia a conta ao atingir o limite. Devolve os
    segundos de bloqueio (0 quando ainda não bloqueou)."""
    settings = get_settings()
    user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
    locked_for = 0
    if user.failed_login_attempts >= settings.login_max_attempts:
        locked_for = settings.login_lockout_seconds
        user.locked_until = utc_now() + timedelta(seconds=locked_for)
        user.failed_login_attempts = 0
    db.commit()
    return locked_for


def clear_failed_logins(db: Session, user: User) -> None:
    if user.failed_login_attempts or user.locked_until:
        user.failed_login_attempts = 0
        user.locked_until = None
        db.commit()


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    """Autentica respeitando o bloqueio por tentativas. Levanta AccountLocked
    quando a conta está (ou acabou de ser) bloqueada."""
    user = get_user_by_email(db, email)
    if not user or not user.active:
        verify_password(password, _dummy_password_hash())
        return None

    remaining = lock_seconds_remaining(user)
    if remaining:
        raise AccountLocked(remaining)

    if not verify_password(password, user.password_hash):
        locked_for = register_failed_login(db, user)
        if locked_for:
            raise AccountLocked(locked_for)
        return None

    clear_failed_logins(db, user)
    return user


def issue_auth_token(
    db: Session,
    user: User,
    purpose: str,
    ttl: timedelta,
) -> tuple[str, AuthToken]:
    """Emite um token de uso único e invalida os anteriores da mesma
    finalidade: um novo pedido sempre cancela o link antigo."""
    now = utc_now()
    for previous in (
        db.query(AuthToken)
        .filter(
            AuthToken.user_id == user.id,
            AuthToken.purpose == purpose,
            AuthToken.used_at.is_(None),
        )
        .all()
    ):
        previous.used_at = now

    token = secrets.token_urlsafe(40)
    record = AuthToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        purpose=purpose,
        token_hash=hash_access_token(token),
        expires_at=now + ttl,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return token, record


def consume_auth_token(db: Session, token: str, purpose: str) -> User:
    record = (
        db.query(AuthToken)
        .filter(
            AuthToken.token_hash == hash_access_token(token),
            AuthToken.purpose == purpose,
        )
        .one_or_none()
    )
    if not record or record.used_at:
        raise ValueError("Link inválido ou já utilizado")
    if _as_utc(record.expires_at) <= utc_now():
        raise ValueError("Este link expirou")
    user = db.query(User).filter(User.id == record.user_id).one_or_none()
    if not user or not user.active:
        raise ValueError("Conta indisponível")
    record.used_at = utc_now()
    db.commit()
    return user


def mark_email_verified(db: Session, user: User) -> User:
    if not user.email_verified_at:
        user.email_verified_at = utc_now()
        db.commit()
        db.refresh(user)
    return user


def revoke_user_sessions(db: Session, user: User) -> int:
    now = utc_now()
    sessions = (
        db.query(AuthSession)
        .filter(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .all()
    )
    for session in sessions:
        session.revoked_at = now
    if sessions:
        db.commit()
    return len(sessions)


def set_password(db: Session, user: User, password: str) -> User:
    """Troca a senha, derruba todas as sessões abertas e libera o bloqueio.

    Concluir a redefinição prova o controle do e-mail, então a conta também
    passa a valer como verificada.
    """
    user.password_hash = hash_password(password)
    user.failed_login_attempts = 0
    user.locked_until = None
    if not user.email_verified_at:
        user.email_verified_at = utc_now()
    db.commit()
    revoke_user_sessions(db, user)
    db.refresh(user)
    return user


def create_session(db: Session, user: User, duration_days: int = 7) -> tuple[str, AuthSession]:
    token = secrets.token_urlsafe(40)
    session = AuthSession(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash=hash_access_token(token),
        expires_at=utc_now() + timedelta(days=duration_days),
    )
    db.add(session)
    db.commit()
    return token, session


def get_user_by_token(db: Session, token: str) -> Optional[User]:
    if not token:
        return None
    session = (
        db.query(AuthSession)
        .filter(AuthSession.token_hash == hash_access_token(token))
        .one_or_none()
    )
    if not session or session.revoked_at or _as_utc(session.expires_at) <= utc_now():
        return None
    return db.query(User).filter(User.id == session.user_id, User.active.is_(True)).one_or_none()


def revoke_session(db: Session, token: str) -> bool:
    session = (
        db.query(AuthSession)
        .filter(AuthSession.token_hash == hash_access_token(token))
        .one_or_none()
    )
    if not session:
        return False
    session.revoked_at = utc_now()
    db.commit()
    return True


def resolve_member_party(role: str, party: Optional[str] = None) -> str:
    if role in PRINCIPAL_ROLES:
        return role
    if role == SUBSIDIARY_ROLE:
        if party not in PRINCIPAL_ROLES:
            raise ValueError("Subsidiário precisa estar vinculado a um lado")
        return party
    raise ValueError(f"Papel não suportado: {role}")


def add_member(
    db: Session,
    case_id: str,
    user_id: str,
    role: str,
    party: Optional[str] = None,
) -> CaseMember:
    resolved_party = resolve_member_party(role, party)
    existing = (
        db.query(CaseMember)
        .filter(
            CaseMember.case_id == case_id,
            CaseMember.user_id == user_id,
            CaseMember.role == role,
        )
        .one_or_none()
    )
    if existing:
        if not existing.party:
            existing.party = resolved_party
            db.commit()
            db.refresh(existing)
        return existing
    member = CaseMember(
        id=str(uuid.uuid4()),
        case_id=case_id,
        user_id=user_id,
        role=role,
        party=resolved_party,
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


def user_has_role(db: Session, case_id: str, user_id: str, role: str) -> bool:
    return (
        db.query(CaseMember)
        .filter(
            CaseMember.case_id == case_id,
            CaseMember.user_id == user_id,
            CaseMember.role == role,
        )
        .first()
        is not None
    )


def list_memberships(db: Session, case_id: str, user_id: str) -> List[CaseMember]:
    return (
        db.query(CaseMember)
        .filter(CaseMember.case_id == case_id, CaseMember.user_id == user_id)
        .all()
    )


def user_is_principal(db: Session, case_id: str, user_id: str, party: Optional[str] = None) -> bool:
    query = db.query(CaseMember).filter(
        CaseMember.case_id == case_id,
        CaseMember.user_id == user_id,
        CaseMember.role.in_(PRINCIPAL_ROLES),
    )
    if party:
        query = query.filter(CaseMember.role == party)
    return query.first() is not None


def user_on_party_side(db: Session, case_id: str, user_id: str, party: str) -> bool:
    """Parte principal daquele lado ou subsidiário a ele vinculado."""
    return (
        db.query(CaseMember)
        .filter(
            CaseMember.case_id == case_id,
            CaseMember.user_id == user_id,
        )
        .filter(
            or_(
                CaseMember.role == party,
                (CaseMember.role == SUBSIDIARY_ROLE) & (CaseMember.party == party),
            )
        )
        .first()
        is not None
    )


def principal_of(db: Session, case_id: str, party: str) -> Optional[CaseMember]:
    return (
        db.query(CaseMember)
        .filter(
            CaseMember.case_id == case_id,
            CaseMember.role == party,
        )
        .first()
    )


def user_case_ids(db: Session, user_id: str) -> list[str]:
    return [row.case_id for row in db.query(CaseMember).filter(CaseMember.user_id == user_id)]


def create_invitation(
    db: Session,
    case_id: str,
    email: str,
    role: str,
    invited_by_user_id: Optional[str],
    party: Optional[str] = None,
) -> tuple[str, Invitation]:
    resolved_party = resolve_member_party(role, party)
    token = secrets.token_urlsafe(40)
    invitation = Invitation(
        id=str(uuid.uuid4()),
        case_id=case_id,
        email=email.strip().lower(),
        role=role,
        party=resolved_party,
        token_hash=hash_access_token(token),
        expires_at=utc_now() + timedelta(days=7),
        invited_by_user_id=invited_by_user_id,
    )
    db.add(invitation)
    db.commit()
    db.refresh(invitation)
    return token, invitation


def invitation_to_dict(invitation: Invitation) -> dict:
    return {
        "id": invitation.id,
        "email": invitation.email,
        "role": invitation.role,
        "party": invitation.party or (
            invitation.role if invitation.role in PRINCIPAL_ROLES else None
        ),
        "status": invitation.status,
        "expires_at": invitation.expires_at.isoformat(),
        "accepted_at": invitation.accepted_at.isoformat() if invitation.accepted_at else None,
        "created_at": invitation.created_at.isoformat(),
    }


def accept_invitation(db: Session, token: str, user: User) -> Invitation:
    invitation = (
        db.query(Invitation)
        .filter(Invitation.token_hash == hash_access_token(token))
        .one_or_none()
    )
    if not invitation or invitation.status != "pending":
        raise ValueError("Convite inválido ou já utilizado")
    if _as_utc(invitation.expires_at) <= utc_now():
        invitation.status = "expired"
        db.commit()
        raise ValueError("Este convite expirou")
    if invitation.email != user.email:
        raise ValueError("O convite pertence a outro endereço de e-mail")
    if list_memberships(db, invitation.case_id, user.id):
        raise ValueError("Esta conta já participa deste caso")
    if invitation.role in PRINCIPAL_ROLES and principal_of(
        db, invitation.case_id, invitation.role
    ):
        raise ValueError("Este lado já tem uma parte principal no caso")
    add_member(
        db,
        invitation.case_id,
        user.id,
        invitation.role,
        party=invitation.party,
    )
    invitation.status = "accepted"
    invitation.accepted_at = utc_now()
    db.commit()
    db.refresh(invitation)
    return invitation


def create_deadline(
    db: Session,
    case_id: str,
    label: str,
    kind: str,
    assigned_to: str,
    due_at: datetime,
) -> Deadline:
    deadline = Deadline(
        id=str(uuid.uuid4()),
        case_id=case_id,
        label=label.strip(),
        kind=kind.strip(),
        assigned_to=assigned_to,
        due_at=due_at,
    )
    db.add(deadline)
    db.commit()
    db.refresh(deadline)
    return deadline


def deadline_to_dict(deadline: Deadline) -> dict:
    now = utc_now()
    if deadline.completed_at:
        status = "completed"
    elif _as_utc(deadline.due_at) < now:
        status = "overdue"
    else:
        status = "open"
    return {
        "id": deadline.id,
        "label": deadline.label,
        "kind": deadline.kind,
        "assigned_to": deadline.assigned_to,
        "due_at": deadline.due_at.isoformat(),
        "completed_at": deadline.completed_at.isoformat() if deadline.completed_at else None,
        "status": status,
    }


def create_notification(
    db: Session,
    case_id: str,
    party: str,
    event_type: str,
    title: str,
    message: str,
) -> Notification:
    membership = (
        db.query(CaseMember)
        .filter(CaseMember.case_id == case_id, CaseMember.role == party)
        .first()
    )
    notification = Notification(
        id=str(uuid.uuid4()),
        case_id=case_id,
        user_id=membership.user_id if membership else None,
        party=party,
        event_type=event_type,
        title=title,
        message=message,
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return notification


def notification_to_dict(notification: Notification) -> dict:
    return {
        "id": notification.id,
        "party": notification.party,
        "event_type": notification.event_type,
        "title": notification.title,
        "message": notification.message,
        "read_at": notification.read_at.isoformat() if notification.read_at else None,
        "created_at": notification.created_at.isoformat(),
    }
