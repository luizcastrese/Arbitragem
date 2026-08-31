"""Controle de concorrência e idempotência das etapas do procedimento.

Não basta `if case.decision: return`: dois workers podem passar por esse
teste ao mesmo tempo. A reivindicação da etapa é um UPDATE condicional.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.db.models import Case

PROCESSING_TTL = timedelta(minutes=10)

STAGE_CLAIM = {
    "lock": ("draft", "locking"),
    "organize": ("conciliation", "processing_organize"),
    "decide": ("organized", "processing_decision"),
    "review": ("decided", "processing_review"),
    "attestation": ("reviewed", "processing_attestation"),
    "appeal": ("attested", "processing_appeal"),
}

TERMINAL_STATUSES = {
    "inconclusive",
    "inadmissible",
    "invalidated",
    "system_failure",
    "contested",
    "attested",
    "reviewed",
}


class StageBusy(RuntimeError):
    def __init__(self, stage: str):
        super().__init__(f"Etapa {stage} já está em processamento")
        self.stage = stage


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def claim_case_stage(
    db: Session,
    case: Case,
    stage: str,
    *,
    extra_from_statuses: Tuple[str, ...] = (),
    allow_retry_from: Tuple[str, ...] = (),
) -> bool:
    """Tenta reivindicar a etapa. Devolve True se este worker deve executá-la.

    False significa que a etapa já foi concluída (o chamador deve reler o caso).
    StageBusy significa que outro worker está no meio da execução.
    """
    now = datetime.now(timezone.utc)
    expected_from, processing_status = STAGE_CLAIM[stage]
    from_statuses = (expected_from, *extra_from_statuses, *allow_retry_from)

    stale_cutoff = now - PROCESSING_TTL
    processing_started = _aware(getattr(case, "processing_started_at", None))
    if case.status == processing_status and processing_started and processing_started > stale_cutoff:
        raise StageBusy(stage)

    query = db.query(Case).filter(Case.id == case.id)
    if case.status == processing_status:
        query = query.filter(Case.status == processing_status)
    else:
        query = query.filter(Case.status.in_(from_statuses))

    updated = query.update(
        {
            Case.status: processing_status,
            Case.processing_started_at: now,
            Case.row_version: Case.row_version + 1,
        },
        synchronize_session=False,
    )
    if updated == 0:
        db.refresh(case)
        if _stage_already_done(case, stage):
            return False
        if case.status == processing_status:
            raise StageBusy(stage)
        return False
    db.commit()
    db.refresh(case)
    return True


def _stage_already_done(case: Case, stage: str) -> bool:
    if stage == "lock":
        return bool(case.manifest_locked)
    if stage == "organize":
        return bool(case.organized_json)
    if stage == "decide":
        return bool(case.decision_json)
    if stage == "review":
        return bool(case.review_json)
    if stage == "attestation":
        return bool(case.attestation_json)
    if stage == "appeal":
        return bool(case.contested_at)
    return False


def release_processing(db: Session, case: Case, status: str) -> None:
    case.status = status
    case.processing_started_at = None
    case.row_version = (case.row_version or 1) + 1
    db.add(case)
