"""Cálculo auditável: a IA extrai e cita, o módulo calcula, as partes corrigem."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.agents.extractor import extract_calculation_data
from app.api import context as ctx
from app.api.background import _record_prompt_provenance, _run_stage
from app.api.common import (
    _assert_procedure_open,
    _case_or_404,
    _require_actor,
    _require_case_view,
)
from app.db.repository import case_to_dict, get_case, save_calculation
from app.db.session import get_db
from app.domain.jobs import RUNNING
from app.domain.extraction import (
    apply_party_edits,
    build_extraction_context,
    derive_state,
    inputs_from_extraction,
    verify_extraction,
)
from app.domain.frameworks import get_framework
from app.schemas import CalculationExtractRequest, CalculationInputsRequest

router = APIRouter()

CALCULATION_MATTERS = {"consumer_banking_v1"}


def _matter_id(case_data: dict) -> str:
    return (case_data.get("pathway") or {}).get("matter_framework_id") or ""


def _assert_calculable(case, case_data: dict) -> None:
    if _matter_id(case_data) not in CALCULATION_MATTERS:
        raise HTTPException(
            status_code=409,
            detail="O cálculo auditável só se aplica a disputas bancárias de consumo.",
        )
    if case.organized_json or case.decision_json:
        raise HTTPException(
            status_code=409,
            detail="A fase consensual já foi encerrada; o cálculo não pode mais mudar.",
        )
    for round_ in case_data["conciliation_rounds"]:
        if (round_.get("agreement") or {}).get("complete"):
            raise HTTPException(
                status_code=409, detail="O acordo já foi fechado; o cálculo não pode mais mudar."
            )


@router.get("/cases/{case_id}/calculation")
def get_calculation(
    case_id: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    return case_to_dict(case, include_content=False, include_embeddings=False).get("calculation")


@router.post("/cases/{case_id}/calculation/extract")
def extract_calculation(
    case_id: str,
    payload: CalculationExtractRequest,
    wait: float = Query(0, ge=0, le=ctx.MAX_STAGE_WAIT_SECONDS),
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """A IA lê os documentos admitidos e extrai os dados, com página e trecho."""
    case = _case_or_404(db, case_id)
    _require_actor(db, case, x_actor_token, payload.party)
    _assert_procedure_open(case)
    case_data = case_to_dict(case)
    _assert_calculable(case, case_data)
    existing = case_data.get("calculation") or {}
    if existing.get("edits"):
        raise HTTPException(
            status_code=409,
            detail="As partes já corrigiram os dados; uma nova leitura apagaria essas correções.",
        )
    if not any(item.get("admitted", True) for item in case_data["documents"]):
        raise HTTPException(status_code=409, detail="Anexe ao menos um documento antes de extrair os dados.")
    running = ctx.stage_runner.get(case_id, "extract")
    if running is not None and running.state == RUNNING:
        raise HTTPException(status_code=409, detail="A leitura dos documentos já está em andamento.")

    framework = get_framework(_matter_id(case_data))
    scope = {
        "matter": framework.name,
        "in_scope": list(framework.in_scope),
        "exclusions": list(framework.exclusions),
    }
    context = build_extraction_context(case_data, scope)

    def work(job_db: Session):
        job_case = get_case(job_db, case_id)
        job_data = case_to_dict(job_case)
        extraction = _record_prompt_provenance(
            job_data, "extractor", extract_calculation_data(context)
        )
        extraction = verify_extraction(extraction, case_data["documents"])
        inputs = inputs_from_extraction(extraction)
        state = derive_state(extraction, inputs)
        value = {
            **state,
            "extraction": extraction,
            "inputs": inputs,
            "edits": [],
            "truncated": context["truncated"],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        save_calculation(
            job_db,
            job_case,
            value,
            "calculation_extracted",
            {
                "status": state["status"],
                "in_scope": state["assessment"]["in_scope"],
                "calculation_sha256": (state["calculation"] or {}).get("sha256"),
                "execution": extraction.get("execution", {}),
            },
        )
        return value

    return _run_stage(case_id, "extract", work, wait)


@router.put("/cases/{case_id}/calculation/inputs")
def correct_calculation_inputs(
    case_id: str,
    payload: CalculationInputsRequest,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """A parte corrige ou completa os dados; o módulo recalcula a memória."""
    case = _case_or_404(db, case_id)
    _require_actor(db, case, x_actor_token, payload.party)
    _assert_procedure_open(case)
    case_data = case_to_dict(case)
    _assert_calculable(case, case_data)
    current = case_data.get("calculation")
    if current is None:
        # Sem leitura prévia da IA a parte pode informar tudo à mão.
        current = {
            "status": "needs_inputs",
            "extraction": None,
            "inputs": inputs_from_extraction({}),
            "edits": [],
        }
    sent = payload.model_dump(exclude={"party"}, exclude_unset=True)
    if not sent:
        raise HTTPException(status_code=422, detail="Nenhum dado a corrigir foi enviado.")
    inputs = apply_party_edits(current["inputs"], sent)
    state = derive_state(current.get("extraction"), inputs)
    edits = [
        *(current.get("edits") or []),
        {
            "party": payload.party,
            "fields": sorted(sent),
            "at": datetime.now(timezone.utc).isoformat(),
        },
    ]
    value = {
        **current,
        **state,
        "inputs": inputs,
        "edits": edits,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    saved = save_calculation(
        db,
        case,
        value,
        "calculation_corrected",
        {
            "party": payload.party,
            "fields": sorted(sent),
            "status": state["status"],
            "calculation_sha256": (state["calculation"] or {}).get("sha256"),
        },
    )
    return case_to_dict(saved, include_content=False, include_embeddings=False)["calculation"]
