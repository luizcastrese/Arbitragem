"""Etapas de modelo em segundo plano: agendamento, recuperação de falhas e
emissão do auto ao fim de cada etapa.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.agents.execution import with_drift
from app.api import context as ctx
from app.core.canonical import canonical_hash
from app.core.prompt_registry import detect_drift
from app.db.repository import append_audit, case_to_dict, get_case, save_decision_record
from app.db.session import SessionLocal, get_db
from app.domain.concurrency import PROCESSING_TTL, release_processing
from app.domain.jobs import RUNNING
from app.domain.legacy import public_decision_view
from app.reports.decision_record import (
    build_decision_record,
    outcome_kind,
    record_basis,
)

logger = logging.getLogger("valinor.request")


def _job_session() -> Session:
    """Sessão de banco para uma etapa em segundo plano.

    A sessão do request já foi devolvida quando a thread começa, então a etapa
    precisa da própria. Quando os testes trocam `get_db` por uma base em
    memória, a etapa tem que ir para a mesma base — daí a consulta ao override
    antes de cair no `SessionLocal` do serviço.
    """
    from app.main import app  # import tardio: main importa este módulo

    override = app.dependency_overrides.get(get_db)
    if override is not None:
        return next(override())
    return SessionLocal()


def _release_stage(case_id: str, stage: str, status: Optional[str]):
    """Devolve o caso ao status anterior quando a etapa falha.

    Sem isso o caso ficaria em `processing_*` até o TTL de 10 minutos, sem
    ninguém conseguir repetir a etapa.
    """

    def recover(db: Session, error: str) -> None:
        if status is None:
            return
        case = get_case(db, case_id)
        if case is None:  # pragma: no cover - o caso existia ao reivindicar
            return
        release_processing(db, case, status)
        append_audit(
            db,
            case,
            "stage_failed",
            {"stage": stage, "error": error, "restored_status": status},
        )
        db.commit()

    return recover


def _stage_accepted_response(case_id: str, stage: str, job) -> JSONResponse:
    return JSONResponse(
        status_code=202,
        content={
            "state": RUNNING,
            "case_id": case_id,
            "stage": stage,
            "started_at": job.started_at,
            "poll": f"/cases/{case_id}/stage/{stage}",
            "detail": (
                "A etapa roda em segundo plano porque depende de modelos de "
                "linguagem. Acompanhe em poll, ou repita a chamada com "
                "?wait=<segundos> para aguardar a conclusão na própria "
                "resposta."
            ),
        },
    )


def _run_stage(case_id: str, stage: str, work, wait: float, on_failure=None):
    """Agenda a etapa e responde 202 — ou o resultado, se `wait` for pedido.

    `wait` é a saída para clientes que preferem uma chamada só: a requisição
    bloqueia até o limite pedido e, se a etapa terminar dentro dele, devolve o
    resultado como antes. Estourado o limite, vira 202 e o trabalho segue.
    """
    on_error_status = ctx.ASYNC_STAGES[stage]["on_error_status"]
    recovery = on_failure or _release_stage(case_id, stage, on_error_status)
    job = ctx.stage_runner.submit(
        case_id,
        stage,
        work,
        _job_session,
        on_failure=recovery,
    )
    if wait <= 0:
        return _stage_accepted_response(case_id, stage, job)

    try:
        result = ctx.stage_runner.wait(job, timeout=min(wait, ctx.MAX_STAGE_WAIT_SECONDS))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail=f"A etapa {stage} falhou: {type(exc).__name__}: {exc}",
        ) from exc
    if result is None:
        return _stage_accepted_response(case_id, stage, job)
    return result


def _issue_decision_record(db: Session, case_id: str):
    """Emite o auto quando o procedimento chega a um desfecho.

    Idempotente: só cria nova versão se o que o auto registra mudou (recurso,
    attestation, qualificação). Uma falha aqui não desfaz a etapa que a
    precedeu; o auto pode ser emitido de novo por `POST /decision-record`.
    """
    case = get_case(db, case_id)
    if case is None:
        return None
    case_data = case_to_dict(case, include_content=False, include_embeddings=False)
    if outcome_kind(case_data) is None:
        return None
    current = case_data.get("decision_record")
    basis_hash = canonical_hash(record_basis(case_data))
    if current and (current.get("integrity") or {}).get("basis_hash") == basis_hash:
        return current
    events = case_data["audit_log"]
    record = build_decision_record(
        case_data,
        audit_chain_head=events[-1]["event_hash"] if events else "",
        audit_chain_length=len(events),
        previous=current,
    )
    save_decision_record(db, case, record)
    return record


def _issue_decision_record_safely(db: Session, case_id: str) -> None:
    try:
        _issue_decision_record(db, case_id)
    except Exception:
        db.rollback()
        logger.exception("decision_record_failed case=%s", case_id)


def _record_prompt_provenance(case_data: Dict, agent: str, stage: Dict) -> Dict:
    """Compara o prompt que rodou com o que o manifesto travou e anota a
    divergência na própria etapa. Um prompt trocado depois da trava deixa de
    ser invisível: aparece na etapa, no evento de auditoria e no relatório."""
    drift = detect_drift(case_data.get("locked_manifest"), agent)
    if drift:
        logger.warning(
            "prompt_drift agent=%s case=%s locked=%s running=%s",
            agent,
            case_data.get("id"),
            drift.get("locked_sha256"),
            drift.get("running_sha256"),
        )
        stage["execution"] = with_drift(stage.get("execution", {}), drift)
    return stage


def _claim_is_stale(case) -> bool:
    """Caso preso em `processing_*` além do TTL de reivindicação."""
    if not str(case.status or "").startswith("processing"):
        return False
    started = getattr(case, "processing_started_at", None)
    if started is None:
        return True
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - started > PROCESSING_TTL


def _stage_result(case_data: Dict, stage: str):
    """Resultado já persistido da etapa, ou None se ela ainda não concluiu."""
    if stage == "conciliation":
        rounds = case_data.get("conciliation_rounds") or []
        return rounds[-1] if rounds else None
    if stage == "extract":
        calculation = case_data.get("calculation") or {}
        return calculation if calculation.get("extraction") else None
    if stage == "organize":
        return case_data.get("organized")
    if stage == "decide":
        decision = case_data.get("decision")
        return public_decision_view(decision) if decision else None
    if stage == "review":
        return case_data.get("review")
    if stage == "contest":
        contest = case_data.get("contest") or {}
        if not contest.get("contested"):
            return None
        appeals = case_data.get("appeals") or []
        return {**contest, "appeal": appeals[-1] if appeals else None}
    return None
