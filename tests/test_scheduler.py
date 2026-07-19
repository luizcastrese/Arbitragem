import os
import uuid
from datetime import datetime, timedelta, timezone

os.environ["OPENAI_API_KEY"] = ""
os.environ["PLATFORM_SIGNING_SECRET"] = "test-signing-secret"
os.environ["DEADLINE_SCHEDULER_ENABLED"] = "false"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.core import scheduler  # noqa: E402
from app.db import access_repository  # noqa: E402
from app.db.models import (  # noqa: E402
    Base,
    Case,
    CaseMember,
    Deadline,
    Notification,
    User,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def _seed_case_with_member(db, role="claimant", email="parte@example.com"):
    case = Case(id=str(uuid.uuid4()), title="Caso", claimant="C", respondent="R")
    user = User(
        id=str(uuid.uuid4()),
        email=email,
        display_name="Parte",
        password_hash="x",
    )
    db.add_all([case, user])
    db.flush()
    db.add(
        CaseMember(id=str(uuid.uuid4()), case_id=case.id, user_id=user.id, role=role)
    )
    db.commit()
    return case, user


def _add_deadline(db, case_id, due_at, assigned_to="claimant"):
    deadline = Deadline(
        id=str(uuid.uuid4()),
        case_id=case_id,
        label="Entregar defesa",
        kind="response",
        assigned_to=assigned_to,
        due_at=due_at,
    )
    db.add(deadline)
    db.commit()
    return deadline


def test_overdue_deadline_notifies_once(db, monkeypatch):
    sent = []
    monkeypatch.setattr(
        access_repository, "send_email", lambda **kwargs: sent.append(kwargs)
    )
    case, _ = _seed_case_with_member(db)
    now = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    _add_deadline(db, case.id, now - timedelta(hours=1))

    first = scheduler.dispatch_due_deadlines(db, now=now)
    assert first["overdue"] == 1
    assert db.query(Notification).count() == 1
    assert len(sent) == 1

    # Segundo ciclo não re-notifica: idempotência via overdue_sent_at.
    second = scheduler.dispatch_due_deadlines(db, now=now)
    assert second["overdue"] == 0
    assert db.query(Notification).count() == 1


def test_upcoming_deadline_reminds_within_lead(db, monkeypatch):
    monkeypatch.setattr(access_repository, "send_email", lambda **kwargs: None)
    case, _ = _seed_case_with_member(db)
    now = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    # Vence em 10h, dentro da janela padrão de 24h.
    _add_deadline(db, case.id, now + timedelta(hours=10))

    summary = scheduler.dispatch_due_deadlines(db, now=now)
    assert summary["reminders"] == 1
    assert summary["overdue"] == 0

    again = scheduler.dispatch_due_deadlines(db, now=now)
    assert again["reminders"] == 0


def test_far_deadline_is_untouched(db, monkeypatch):
    monkeypatch.setattr(access_repository, "send_email", lambda **kwargs: None)
    case, _ = _seed_case_with_member(db)
    now = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    _add_deadline(db, case.id, now + timedelta(days=5))

    summary = scheduler.dispatch_due_deadlines(db, now=now)
    assert summary == {"checked": 1, "reminders": 0, "overdue": 0}


def test_completed_deadline_is_ignored(db, monkeypatch):
    monkeypatch.setattr(access_repository, "send_email", lambda **kwargs: None)
    case, _ = _seed_case_with_member(db)
    now = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    deadline = _add_deadline(db, case.id, now - timedelta(hours=2))
    deadline.completed_at = now - timedelta(hours=1)
    db.commit()

    summary = scheduler.dispatch_due_deadlines(db, now=now)
    assert summary["checked"] == 0
    assert db.query(Notification).count() == 0


def test_assigned_to_all_notifies_each_role(db, monkeypatch):
    monkeypatch.setattr(access_repository, "send_email", lambda **kwargs: None)
    case = Case(id=str(uuid.uuid4()), title="Caso", claimant="C", respondent="R")
    db.add(case)
    db.flush()
    for role in ("claimant", "respondent", "manager"):
        user = User(
            id=str(uuid.uuid4()),
            email=f"{role}@example.com",
            display_name=role,
            password_hash="x",
        )
        db.add(user)
        db.flush()
        db.add(
            CaseMember(
                id=str(uuid.uuid4()), case_id=case.id, user_id=user.id, role=role
            )
        )
    db.commit()
    now = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    _add_deadline(db, case.id, now - timedelta(hours=1), assigned_to="all")

    scheduler.dispatch_due_deadlines(db, now=now)
    assert db.query(Notification).count() == 3
