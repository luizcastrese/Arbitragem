"""Agendador automático de prazos.

Roda como uma tarefa de background dentro do próprio serviço: em intervalos
regulares varre os prazos abertos e dispara notificações (que agora saem por
e-mail) quando um prazo se aproxima do vencimento ou quando vence sem conclusão.

O disparo é idempotente: cada prazo carrega `reminder_sent_at` e
`overdue_sent_at`, de modo que cada aviso é enviado uma única vez, mesmo que o
loop rode a cada poucos minutos.

As notificações NÃO tocam a cadeia de auditoria encadeada por hash — esta
permanece dirigida apenas por atos processuais explícitos, evitando qualquer
condição de corrida entre o loop e os handlers da API.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.access_repository import create_notification
from app.db.models import Deadline
from app.db.session import SessionLocal


logger = logging.getLogger("valinor.scheduler")


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _targets(assigned_to: str):
    if assigned_to == "all":
        return ("claimant", "respondent", "manager")
    return (assigned_to,)


def _notify(db: Session, deadline: Deadline, event_type: str, title: str, message: str) -> None:
    for party in _targets(deadline.assigned_to):
        create_notification(db, deadline.case_id, party, event_type, title, message)


def dispatch_due_deadlines(db: Session, now: Optional[datetime] = None) -> Dict[str, int]:
    """Verifica os prazos abertos e dispara os avisos pendentes.

    Devolve um resumo com a contagem de lembretes e vencimentos notificados.
    """

    settings = get_settings()
    moment = now or datetime.now(timezone.utc)
    lead = timedelta(hours=settings.deadline_reminder_lead_hours)

    open_deadlines = (
        db.query(Deadline).filter(Deadline.completed_at.is_(None)).all()
    )

    reminders = 0
    overdue = 0
    for deadline in open_deadlines:
        due_at = _as_utc(deadline.due_at)

        if due_at <= moment:
            if deadline.overdue_sent_at is None:
                _notify(
                    db,
                    deadline,
                    "deadline_overdue",
                    "Prazo vencido",
                    f"O prazo '{deadline.label}' venceu em "
                    f"{due_at.isoformat()} sem conclusão registrada.",
                )
                deadline.overdue_sent_at = moment
                overdue += 1
            continue

        if deadline.reminder_sent_at is None and due_at - moment <= lead:
            _notify(
                db,
                deadline,
                "deadline_reminder",
                "Prazo se aproximando",
                f"O prazo '{deadline.label}' vence em {due_at.isoformat()}. "
                "Registre a conclusão ou tome as providências necessárias.",
            )
            deadline.reminder_sent_at = moment
            reminders += 1

    if reminders or overdue:
        db.commit()

    return {
        "checked": len(open_deadlines),
        "reminders": reminders,
        "overdue": overdue,
    }


def _tick_once() -> None:
    db = SessionLocal()
    try:
        summary = dispatch_due_deadlines(db)
        if summary["reminders"] or summary["overdue"]:
            logger.info(
                "[SCHEDULER] lembretes=%s vencidos=%s (verificados=%s)",
                summary["reminders"],
                summary["overdue"],
                summary["checked"],
            )
    finally:
        db.close()


async def run_scheduler_loop() -> None:
    """Loop infinito que despacha prazos no intervalo configurado.

    Nunca deixa uma exceção pontual derrubar o loop; apenas registra e segue.
    """

    settings = get_settings()
    interval = max(1, settings.deadline_scheduler_interval_seconds)
    logger.info("[SCHEDULER] iniciado (intervalo=%ss)", interval)
    while True:
        try:
            await asyncio.to_thread(_tick_once)
        except asyncio.CancelledError:
            logger.info("[SCHEDULER] encerrado")
            raise
        except Exception as exc:  # noqa: BLE001 - o loop precisa sobreviver
            logger.warning("[SCHEDULER] falha no ciclo: %s", type(exc).__name__)
        await asyncio.sleep(interval)
