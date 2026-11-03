"""Despachante de e-mails e varredura de lembretes, em segundo plano."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Dict, Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.notifications.outbox import dispatch_pending, purge_delivered
from app.notifications.reminders import scan_reminders

logger = logging.getLogger("valinor.notifications")


class NotificationWorker:
    """A cada `interval` segundos envia a fila; a cada `reminder_interval`,
    varre os lembretes e expurga avisos antigos. `interval <= 0` desliga.

    Várias réplicas podem rodar ao mesmo tempo: o envio é reivindicado por
    UPDATE condicional e os lembretes têm chave de deduplicação.
    """

    def __init__(
        self,
        interval: float,
        reminder_interval: float,
        session_factory: Optional[Callable[[], Session]] = None,
    ) -> None:
        self.interval = interval
        self.reminder_interval = reminder_interval
        self._session_factory = session_factory
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_reminder_scan = 0.0

    def start(self) -> None:
        if self.interval <= 0 or self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="valinor-notifications", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def run_once(self, *, scan: bool = False) -> Dict[str, object]:
        """Uma passada. Exposto para testes e para a operação."""
        if self._session_factory is not None:
            factory = self._session_factory
        else:
            from app.api.background import _job_session

            factory = _job_session
        db = factory()
        try:
            result: Dict[str, object] = {"dispatch": dispatch_pending(db)}
            if scan:
                result["reminders"] = scan_reminders(db)
                result["purged"] = purge_delivered(
                    db, get_settings().outbox_retention_days
                )
            return result
        finally:
            db.close()

    def _run(self) -> None:
        while not self._stop.is_set():
            due_scan = (
                self.reminder_interval > 0
                and time.monotonic() - self._last_reminder_scan >= self.reminder_interval
            )
            try:
                self.run_once(scan=due_scan)
                if due_scan:
                    self._last_reminder_scan = time.monotonic()
            except Exception:
                logger.exception("notification_worker_pass_failed")
            self._stop.wait(self.interval)
