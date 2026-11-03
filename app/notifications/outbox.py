"""Fila de e-mails transacionais: enfileirar, enviar, repetir e expurgar.

O aviso nasce na mesma transação do ato que o originou (ver `rules`). O envio
SMTP acontece depois, fora do request, e uma falha vira nova tentativa com
espera crescente em vez de um aviso perdido.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Callable, Dict, Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.email import _deliver
from app.db.models import EmailOutbox

logger = logging.getLogger("valinor.notifications")

MAX_ATTEMPTS = 5
# Um envio reivindicado e nunca concluído (processo morto no meio) volta à fila.
CLAIM_TTL = timedelta(minutes=5)
# Teto do erro guardado: a fila é lida no painel de operação.
ERROR_LIMIT = 300

FINAL_STATUSES = ("sent", "logged")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def enqueue(
    db: Session,
    *,
    to_email: str,
    kind: str,
    subject: str,
    body: str,
    case_id: Optional[str] = None,
    user_id: Optional[str] = None,
    audience: str = "party",
    dedupe_key: Optional[str] = None,
) -> Optional[EmailOutbox]:
    """Põe um aviso na fila, na transação corrente. Devolve `None` quando o
    mesmo fato já tem aviso (mesma `dedupe_key`)."""
    if dedupe_key:
        pending_here = any(
            isinstance(item, EmailOutbox) and item.dedupe_key == dedupe_key
            for item in db.new
        )
        if pending_here:
            return None
        exists = (
            db.query(EmailOutbox.id).filter(EmailOutbox.dedupe_key == dedupe_key).first()
        )
        if exists:
            return None
    row = EmailOutbox(
        id=str(uuid.uuid4()),
        case_id=case_id,
        user_id=user_id,
        to_email=to_email,
        kind=kind,
        audience=audience,
        subject=subject[:200],
        body=body,
        dedupe_key=dedupe_key,
        status="pending",
        attempts=0,
        next_attempt_at=_now(),
    )
    db.add(row)
    return row


def _message(row: EmailOutbox, sender: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = row.subject
    message["From"] = sender
    message["To"] = row.to_email
    message["Auto-Submitted"] = "auto-generated"
    if row.case_id:
        message["X-Valinor-Case"] = row.case_id
    message.set_content(row.body)
    return message


def _backoff(attempts: int) -> timedelta:
    # 2, 4, 8, 16 minutos: dá tempo de o provedor se recuperar sem insistir.
    return timedelta(minutes=2 ** max(1, attempts))


def _release_stale_claims(db: Session, now: datetime) -> None:
    db.query(EmailOutbox).filter(
        EmailOutbox.status == "sending",
        EmailOutbox.claimed_at < now - CLAIM_TTL,
    ).update({"status": "pending"}, synchronize_session=False)
    db.commit()


def dispatch_pending(
    db: Session,
    *,
    limit: int = 50,
    now: Optional[datetime] = None,
    deliver: Optional[Callable[..., Dict[str, object]]] = None,
) -> Dict[str, int]:
    """Envia os avisos vencidos da fila. Nunca levanta: cada falha fica na
    própria linha. Várias réplicas podem rodar ao mesmo tempo, porque cada
    envio é reivindicado com um UPDATE condicional."""
    settings = get_settings()
    now = now or _now()
    deliver = deliver or _deliver
    counts = {"sent": 0, "logged": 0, "retry": 0, "failed": 0}
    _release_stale_claims(db, now)

    due = (
        db.query(EmailOutbox)
        .filter(EmailOutbox.status == "pending", EmailOutbox.next_attempt_at <= now)
        .order_by(EmailOutbox.created_at)
        .limit(limit)
        .all()
    )
    for row in due:
        claimed = (
            db.query(EmailOutbox)
            .filter(EmailOutbox.id == row.id, EmailOutbox.status == "pending")
            .update({"status": "sending", "claimed_at": now}, synchronize_session=False)
        )
        db.commit()
        if not claimed:
            continue
        db.refresh(row)
        if not settings.email_enabled:
            # Sem SMTP o aviso fica só no registro, como os demais e-mails.
            row.status = "logged"
            row.sent_at = now
            counts["logged"] += 1
            db.commit()
            logger.info("notification kind=%s transport=log to=%s", row.kind, row.to_email)
            continue
        try:
            result = deliver(
                _message(row, settings.smtp_from), kind=row.kind, to_email=row.to_email
            )
        except Exception as exc:  # defesa: _deliver já captura o SMTP
            result = {"delivered": False, "error": type(exc).__name__}
        row.attempts = (row.attempts or 0) + 1
        if result.get("delivered"):
            row.status = "sent"
            row.sent_at = now
            row.last_error = None
            counts["sent"] += 1
        else:
            error = str(result.get("error") or "desconhecido")[:ERROR_LIMIT]
            row.last_error = error
            row.claimed_at = None
            if row.attempts >= MAX_ATTEMPTS:
                row.status = "failed"
                counts["failed"] += 1
                logger.error(
                    "notification_failed kind=%s case=%s attempts=%s error=%s",
                    row.kind,
                    row.case_id,
                    row.attempts,
                    error,
                )
            else:
                row.status = "pending"
                row.next_attempt_at = now + _backoff(row.attempts)
                counts["retry"] += 1
        db.commit()
    return counts


def requeue(db: Session, row: EmailOutbox) -> EmailOutbox:
    """Devolve um aviso falho à fila para uma nova rodada de tentativas."""
    row.status = "pending"
    row.attempts = 0
    row.last_error = None
    row.claimed_at = None
    row.next_attempt_at = _now()
    db.commit()
    return row


def purge_delivered(db: Session, days: int, now: Optional[datetime] = None) -> int:
    """Apaga avisos já entregues depois da janela de retenção. Falhos e
    pendentes ficam: são o que a operação precisa enxergar."""
    if days <= 0:
        return 0
    cutoff = (now or _now()) - timedelta(days=days)
    deleted = (
        db.query(EmailOutbox)
        .filter(EmailOutbox.status.in_(FINAL_STATUSES), EmailOutbox.created_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.commit()
    return int(deleted or 0)


def erase_for_user(db: Session, user_id: str) -> int:
    """Direito de eliminação: some o conteúdo e o endereço dos avisos da conta.

    Não apaga as linhas inteiras para não perder a contagem operacional, mas
    nada que identifique o titular sobrevive."""
    rows = db.query(EmailOutbox).filter(EmailOutbox.user_id == user_id).all()
    for row in rows:
        row.to_email = "removido@anonimizado.invalid"
        row.subject = "(removido)"
        row.body = ""
        if row.status in ("pending", "sending"):
            row.status = "failed"
            row.last_error = "titular removido"
    return len(rows)
