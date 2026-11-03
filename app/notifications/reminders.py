"""Lembretes por prazo e por inércia.

Os avisos de `rules` respondem a um ato. Estes respondem à falta dele: um
material sem resposta, um prazo perto de vencer, o fim do prazo de recurso, um
convite que vai expirar. A varredura é idempotente: cada fato tem uma chave, e
rodar de novo (ou em outra réplica) não duplica o e-mail.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import AuditEvent, Case, CaseMember, Deadline, Document, Invitation, User
from app.domain.concurrency import TERMINAL_STATUSES
from app.notifications.outbox import enqueue
from app.notifications.rules import (
    PARTIES,
    Notice,
    deliver_notice,
    format_deadline,
    other_party,
    render_body,
)

logger = logging.getLogger("valinor.notifications")

CONTEST_CLOSING_WINDOW = timedelta(hours=48)
DEADLINE_DUE_SOON = timedelta(hours=24)
DEADLINE_OVERDUE_LIMIT = timedelta(days=7)
INVITATION_EXPIRING_WINDOW = timedelta(hours=48)
SCAN_LIMIT = 500


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _parse(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return _aware(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None


def _attestation(case: Case) -> Optional[Dict]:
    if not case.attestation_json:
        return None
    try:
        return json.loads(case.attestation_json)
    except ValueError:
        return None


def _acceptances(db: Session, case_id: str) -> int:
    return (
        db.query(AuditEvent.id)
        .filter(AuditEvent.case_id == case_id, AuditEvent.event_type == "decision_accepted")
        .count()
    )


def _scan_attestations(db: Session, now: datetime) -> int:
    queued = 0
    cases = (
        db.query(Case)
        .filter(Case.status == "attested", Case.attestation_json.isnot(None))
        .limit(SCAN_LIMIT)
        .all()
    )
    reflection = timedelta(hours=get_settings().acceptance_reflection_hours)
    for case in cases:
        attestation = _attestation(case) or {}
        ident = attestation.get("attestation_hash") or "-"
        window_end = _parse(attestation.get("contest_window_ends_utc"))
        issued = _parse(attestation.get("issued_at_utc"))
        if window_end is None or now >= window_end:
            continue
        if case.contested_at or _acceptances(db, case.id) >= 2:
            continue
        window = format_deadline(window_end)
        if window_end - now <= CONTEST_CLOSING_WINDOW:
            queued += deliver_notice(
                db,
                case,
                Notice(
                    roles=PARTIES,
                    subject="O prazo de recurso está terminando",
                    headline="O prazo para recorrer da decisão termina em breve.",
                    action=(
                        "Se pretende recorrer, faça-o antes do fim do prazo. "
                        "Depois dele, a decisão fica estável."
                    ),
                    deadline=window,
                ),
                kind="reminder_contest_closing",
                key=f"reminder:contest_closing:{case.id}:{ident}",
            )
        if issued is not None and now >= issued + reflection:
            queued += deliver_notice(
                db,
                case,
                Notice(
                    roles=PARTIES,
                    subject="Já é possível acatar a decisão como acordo",
                    headline="O prazo de reflexão terminou: as partes já podem acatar a decisão como acordo.",
                    details=[
                        "Acatar é um ato irrevogável e afasta o recurso. "
                        "Só vale como acordo se as duas partes acatarem."
                    ],
                    action="Se concorda com a decisão, acate-a no painel. Caso contrário, nada precisa ser feito.",
                    deadline=f"recurso até {window}",
                ),
                kind="reminder_reflection_over",
                key=f"reminder:reflection_over:{case.id}:{ident}",
            )
    return queued


def _scan_deadlines(db: Session, now: datetime) -> int:
    queued = 0
    open_deadlines = (
        db.query(Deadline)
        .filter(
            Deadline.completed_at.is_(None),
            Deadline.due_at <= now + DEADLINE_DUE_SOON,
        )
        .limit(SCAN_LIMIT)
        .all()
    )
    for deadline in open_deadlines:
        due = _aware(deadline.due_at)
        if due is None or now - due > DEADLINE_OVERDUE_LIMIT:
            continue
        case = db.get(Case, deadline.case_id)
        if case is None or case.status in TERMINAL_STATUSES or case.status == "agreement":
            continue
        roles = (
            list(PARTIES) if deadline.assigned_to == "all" else [deadline.assigned_to]
        )
        overdue = due <= now
        queued += deliver_notice(
            db,
            case,
            Notice(
                roles=roles,
                subject=(
                    "Prazo vencido no procedimento"
                    if overdue
                    else "Prazo vence em breve no procedimento"
                ),
                headline=(
                    f"O prazo \"{deadline.label}\" venceu e ainda não foi cumprido."
                    if overdue
                    else f"O prazo \"{deadline.label}\" vence em menos de 24 horas."
                ),
                deadline=format_deadline(due),
                action="Abra o caso e cumpra o prazo; se já cumpriu, marque-o como concluído.",
            ),
            kind="reminder_deadline_overdue" if overdue else "reminder_deadline_due",
            key=f"reminder:deadline:{'overdue' if overdue else 'due'}:{deadline.id}",
        )
    return queued


def _scan_stalled_material(db: Session, now: datetime) -> int:
    hours = get_settings().reminder_stalled_hours
    if hours <= 0:
        return 0
    cutoff = now - timedelta(hours=hours)
    queued = 0
    rows = (
        db.query(Document, Case)
        .join(Case, Case.id == Document.case_id)
        .filter(
            Document.response_status == "pending",
            Document.disclosed_at.isnot(None),
            Document.admitted.is_(False),
            Case.manifest_locked.is_(False),
            Case.status.notin_(list(TERMINAL_STATUSES)),
        )
        .limit(SCAN_LIMIT)
        .all()
    )
    for document, case in rows:
        disclosed = _parse(document.disclosed_at)
        if disclosed is None or disclosed > cutoff:
            continue
        target = other_party(document.submitted_by)
        if target not in PARTIES:
            continue
        queued += deliver_notice(
            db,
            case,
            Notice(
                roles=[target],
                subject="Material aguardando a sua manifestação",
                headline=(
                    f"Um material apresentado pela outra parte está sem resposta "
                    f"há mais de {hours // 24 if hours >= 48 else hours} "
                    f"{'dias' if hours >= 48 else 'horas'}."
                ),
                action=(
                    "Leia o material, confirme a ciência e responda ou renuncie "
                    "expressamente. O procedimento só avança com o contraditório completo."
                ),
            ),
            kind="reminder_stalled_material",
            key=f"reminder:stalled:{document.id}",
        )
    return queued


def _scan_invitations(db: Session, now: datetime) -> int:
    queued = 0
    invitations = (
        db.query(Invitation)
        .filter(
            Invitation.status == "pending",
            Invitation.expires_at > now,
            Invitation.expires_at <= now + INVITATION_EXPIRING_WINDOW,
            Invitation.invited_by_user_id.isnot(None),
        )
        .limit(SCAN_LIMIT)
        .all()
    )
    for invitation in invitations:
        inviter = db.get(User, invitation.invited_by_user_id)
        case = db.get(Case, invitation.case_id)
        if inviter is None or case is None or not inviter.active:
            continue
        notice = Notice(
            roles=[],
            subject="O convite enviado está perto de expirar",
            headline="O convite que você enviou ainda não foi aceito e expira em breve.",
            action="Reenvie o convite pelo painel ou combine por outro meio com a pessoa convidada.",
            deadline=format_deadline(invitation.expires_at),
        )
        member = (
            db.query(CaseMember.role)
            .filter(CaseMember.case_id == case.id, CaseMember.user_id == inviter.id)
            .first()
        )
        role = member[0] if member else "claimant"
        if (
            get_settings().email_verification_required and not inviter.email_verified_at
        ):
            continue
        row = enqueue(
            db,
            to_email=inviter.email,
            kind="reminder_invitation_expiring",
            subject=notice.subject,
            body=render_body(case, inviter, role, notice),
            case_id=case.id,
            user_id=inviter.id,
            dedupe_key=f"reminder:invite_expiring:{invitation.id}",
        )
        if row is not None:
            queued += 1
    return queued


def scan_reminders(db: Session, now: Optional[datetime] = None) -> Dict[str, int]:
    """Roda todas as varreduras. Cada uma é isolada: se uma falhar, as outras
    seguem e a transação da que falhou é desfeita."""
    now = now or datetime.now(timezone.utc)
    result: Dict[str, int] = {}
    for name, scan in (
        ("attestations", _scan_attestations),
        ("deadlines", _scan_deadlines),
        ("stalled_material", _scan_stalled_material),
        ("invitations", _scan_invitations),
    ):
        try:
            result[name] = scan(db, now)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("reminder_scan_failed scan=%s", name)
            result[name] = 0
    return result
