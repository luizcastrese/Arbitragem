import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.auth import hash_access_token, hash_password, verify_password
from app.db.models import (
    AuthSession,
    CaseMember,
    Deadline,
    Invitation,
    Notification,
    User,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def user_to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
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


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    user = db.query(User).filter(User.email == email.strip().lower()).one_or_none()
    if not user or not user.active or not verify_password(password, user.password_hash):
        return None
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


def user_roles_in_case(db: Session, case_id: str, user_id: str) -> set[str]:
    return {
        row.role
        for row in db.query(CaseMember).filter(
            CaseMember.case_id == case_id,
            CaseMember.user_id == user_id,
        )
    }


def add_member(db: Session, case_id: str, user_id: str, role: str) -> CaseMember:
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
        return existing
    # Invariante do procedimento: as duas partes são pessoas distintas. Sem um
    # terceiro humano observando, é aqui que se impede alguém de litigar
    # consigo mesmo e colher uma decisão assinada de uma disputa inexistente.
    if user_roles_in_case(db, case_id, user_id):
        raise ValueError(
            "Esta conta já é parte neste caso e não pode ocupar também o outro polo"
        )
    member = CaseMember(
        id=str(uuid.uuid4()),
        case_id=case_id,
        user_id=user_id,
        role=role,
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


def user_case_ids(db: Session, user_id: str) -> list[str]:
    return [row.case_id for row in db.query(CaseMember).filter(CaseMember.user_id == user_id)]


def create_invitation(
    db: Session,
    case_id: str,
    email: str,
    role: str,
    invited_by_user_id: Optional[str],
) -> tuple[str, Invitation]:
    token = secrets.token_urlsafe(40)
    invitation = Invitation(
        id=str(uuid.uuid4()),
        case_id=case_id,
        email=email.strip().lower(),
        role=role,
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
    if user_roles_in_case(db, invitation.case_id, user.id):
        raise ValueError(
            "Sua conta já é parte neste caso: as duas partes precisam ser "
            "pessoas distintas"
        )
    add_member(db, invitation.case_id, user.id, invitation.role)
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
    reference_id: Optional[str] = None,
) -> Deadline:
    deadline = Deadline(
        id=str(uuid.uuid4()),
        case_id=case_id,
        label=label.strip(),
        kind=kind.strip(),
        assigned_to=assigned_to,
        reference_id=reference_id,
        due_at=due_at,
    )
    db.add(deadline)
    db.commit()
    db.refresh(deadline)
    return deadline


def open_deadline_for_reference(
    db: Session,
    case_id: str,
    reference_id: str,
    kind: str,
) -> Optional[Deadline]:
    """Prazo ainda aberto para um objeto do procedimento, se houver. Prazos já
    encerrados não contam: um ato que se reabre merece prazo novo."""
    return (
        db.query(Deadline)
        .filter(
            Deadline.case_id == case_id,
            Deadline.reference_id == reference_id,
            Deadline.kind == kind,
            Deadline.completed_at.is_(None),
        )
        .first()
    )


def expired_deadline_for_reference(
    db: Session,
    case_id: str,
    reference_id: str,
    kind: str,
) -> Optional[Deadline]:
    deadline = open_deadline_for_reference(db, case_id, reference_id, kind)
    if deadline and _as_utc(deadline.due_at) <= utc_now():
        return deadline
    return None


def complete_deadlines_for_reference(
    db: Session,
    case_id: str,
    reference_id: str,
) -> list[Deadline]:
    """Fecha os prazos abertos ligados a um objeto do procedimento. É o rito
    dando baixa no próprio prazo assim que o ato esperado acontece."""
    deadlines = (
        db.query(Deadline)
        .filter(
            Deadline.case_id == case_id,
            Deadline.reference_id == reference_id,
            Deadline.completed_at.is_(None),
        )
        .all()
    )
    for deadline in deadlines:
        deadline.completed_at = utc_now()
    if deadlines:
        db.commit()
    return deadlines


def case_roles_taken(db: Session, case_id: str) -> set[str]:
    return {
        row.role
        for row in db.query(CaseMember).filter(CaseMember.case_id == case_id)
    }


def pending_invitation_roles(db: Session, case_id: str) -> set[str]:
    return {
        row.role
        for row in db.query(Invitation).filter(
            Invitation.case_id == case_id,
            Invitation.status == "pending",
        )
    }


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
        "reference_id": deadline.reference_id,
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
