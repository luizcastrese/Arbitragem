"""Etapas de modelo: conciliação, organização, decisão, revisão, contestação e
polling.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.agents.conciliator import assess_conciliation
from app.agents.organizer import organize_case as organizer_organize_case
from app.api import context as ctx
from app.api.background import (
    _claim_is_stale,
    _issue_decision_record_safely,
    _record_prompt_provenance,
    _run_stage,
    _stage_result,
)
from app.api.common import (
    _assert_procedure_open,
    _case_or_404,
    _require_actor,
    _require_case_view,
    _require_steward_actuator,
    _retrieve,
)
from app.api.steward import _conduct_steward, _continue_steward, _take_steward_chain
from app.core.canonical import canonical_hash
from app.db.repository import (
    append_audit,
    case_to_dict,
    count_appeals,
    find_appeal_by_id,
    find_appeal_by_idempotency,
    get_case,
    persist_appeal,
    register_contest,
    revert_contest,
    save_stage,
    save_steward_state,
)
from app.db.session import get_db
from app.domain.acceptance import acceptance_status
from app.domain.concurrency import StageBusy, claim_case_stage
from app.domain.jobs import COMPLETED, FAILED, RUNNING
from app.domain.legacy import public_decision_view
from app.domain.procedure import (
    alternate_judge_available,
    finalize_review_outcome,
    generate_and_verify_decision,
    maybe_run_stability,
    reconstruct_once,
    run_appeal,
    run_automatic_review,
)
from app.schemas import (
    AgreementResponseRequest,
    ConciliationPositionRequest,
    ConciliationRoundRequest,
    ContestRequest,
)

router = APIRouter()


@router.post("/cases/{case_id}/conciliation")
def assess_case_conciliation(
    case_id: str,
    payload: ConciliationRoundRequest = ConciliationRoundRequest(),
    wait: float = Query(
        0,
        ge=0,
        le=ctx.MAX_STAGE_WAIT_SECONDS,
        description=(
            "Segundos a aguardar a conclusão na própria resposta. 0 (padrão) "
            "responde 202 e a etapa segue em segundo plano."
        ),
    ),
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _assert_procedure_open(case)
    _require_steward_actuator(x_actor_token)
    case_data = case_to_dict(case)
    if not case.manifest_locked:
        raise HTTPException(
            status_code=409,
            detail="Trave o manifesto antes da triagem de composição",
        )
    rounds = case_data["conciliation_rounds"]
    if rounds and not payload.advance:
        _take_steward_chain(db, case_id)
        return rounds[-1]
    if case_data["organized"]:
        raise HTTPException(
            status_code=409,
            detail="A fase de composição foi encerrada porque o julgamento já começou",
        )

    previous_round = rounds[-1] if rounds else None
    has_new_input = any(
        [
            payload.claimant_response,
            payload.respondent_response,
            payload.new_information,
        ]
    )
    if (
        previous_round
        and not previous_round.get("continue_recommended", False)
        and not has_new_input
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "A última rodada não recomendou nova tentativa. "
                "Informe fatos ou posições novas para reavaliar."
            ),
        )

    # A triagem de composição não passa por claim_case_stage: rodadas podem se
    # repetir legitimamente, então não há "etapa concluída" a reivindicar. O
    # registro de jobs faz as vezes de trava contra duas rodadas simultâneas
    # no mesmo processo.
    running = ctx.stage_runner.get(case_id, "conciliation")
    if running is not None and running.state == RUNNING:
        raise HTTPException(
            status_code=409,
            detail="Já existe uma rodada de composição em processamento",
        )

    context = {
        "round_number": len(rounds) + 1,
        "manifest": case_data["locked_manifest"],
        "parties": {
            "claimant": case_data["claimant"],
            "respondent": case_data["respondent"],
        },
        "documents": [
            {
                "id": document["id"],
                "name": document["name"],
                "content": document.get("content", "")[:8000],
            }
            for document in case_data["documents"]
        ],
        "previous_rounds": rounds,
        "current_party_responses": {
            "claimant": payload.claimant_response,
            "respondent": payload.respondent_response,
            "new_information": payload.new_information,
        },
        "retrieved_evidence": {
            "shared_interests": _retrieve(
                case_data,
                "interesses comuns continuidade da relação acordo solução consensual",
            ),
            "possible_concessions": _retrieve(
                case_data,
                "propostas concessões negociação pagamento prazo entrega",
            ),
        },
    }
    round_number = len(rounds) + 1

    def work(job_db: Session):
        job_case = get_case(job_db, case_id)
        conciliation = _record_prompt_provenance(
            case_data,
            "conciliator",
            assess_conciliation(context, round_number),
        )
        updated_rounds = [*rounds, conciliation]
        save_stage(
            job_db,
            job_case,
            field="conciliation_json",
            value=updated_rounds,
            status="conciliation",
            event_type=(
                "conciliation_screened"
                if round_number == 1
                else "conciliation_round_generated"
            ),
            event_payload={
                "round_number": round_number,
                "convergence": conciliation.get("convergence"),
                "recommended_path": conciliation.get("recommended_path"),
                "confidence": conciliation.get("confidence"),
                "continue_recommended": conciliation.get("continue_recommended"),
                "recommended_additional_rounds": conciliation.get(
                    "recommended_additional_rounds"
                ),
                "execution": conciliation.get("execution", {}),
            },
        )
        _continue_steward(job_db, case_id)
        return conciliation

    return _run_stage(case_id, "conciliation", work, wait)


@router.post("/cases/{case_id}/conciliation/{round_number}/agreement")
def respond_to_conciliation_agreement(
    case_id: str,
    round_number: int,
    payload: AgreementResponseRequest,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """Registra aceite ou recusa individual da proposta de uma rodada.

    Acordo só existe depois de dois aceites independentes sobre exatamente a
    mesma proposta. O hash impede que a proposta seja alterada entre as duas
    manifestações. Uma parte não pode falar pela outra.
    """
    case = _case_or_404(db, case_id)
    _require_actor(db, case, x_actor_token, payload.party)
    _assert_procedure_open(case)
    if case.organized_json or case.decision_json:
        raise HTTPException(
            status_code=409,
            detail="A fase consensual já foi encerrada",
        )

    rounds = case_to_dict(case)["conciliation_rounds"]
    if round_number < 1 or round_number > len(rounds):
        raise HTTPException(status_code=404, detail="Rodada de composição não encontrada")
    index = round_number - 1
    selected = dict(rounds[index])
    terms = selected.get("possible_terms") or []
    if not terms:
        raise HTTPException(
            status_code=409,
            detail="Esta rodada não contém proposta que possa ser aceita",
        )

    proposal_sha256 = canonical_hash(
        {"round_number": round_number, "possible_terms": terms}
    )
    agreement = dict(selected.get("agreement") or {})
    recorded_hash = agreement.get("proposal_sha256")
    if recorded_hash and recorded_hash != proposal_sha256:
        raise HTTPException(
            status_code=409,
            detail="A proposta mudou depois da primeira manifestação",
        )
    responses = dict(agreement.get("responses") or {})
    responses[payload.party] = {
        "accepted": payload.accepted,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    complete = all(
        (responses.get(party) or {}).get("accepted") is True
        for party in ("claimant", "respondent")
    )
    selected["agreement"] = {
        "proposal_sha256": proposal_sha256,
        "responses": responses,
        "complete": complete,
    }
    rounds[index] = selected
    case.conciliation_json = json.dumps(rounds, ensure_ascii=False)
    if complete:
        case.status = "agreement"
        case.procedure_conclusion = "agreement"
    append_audit(
        db,
        case,
        "conciliation_agreement_completed" if complete else "conciliation_agreement_response",
        {
            "round_number": round_number,
            "party": payload.party,
            "accepted": payload.accepted,
            "proposal_sha256": proposal_sha256,
        },
    )
    db.commit()
    if complete:
        save_steward_state(
            db,
            get_case(db, case_id),
            {
                "action": "hold",
                "reason": "As duas partes aceitaram a mesma proposta.",
                "waiting_on": [],
                "allowed_actions": ["hold"],
            },
            "hold",
        )
        _issue_decision_record_safely(db, case_id)
    return selected["agreement"]


@router.post("/cases/{case_id}/conciliation/{round_number}/position")
def file_conciliation_position(
    case_id: str,
    round_number: int,
    payload: ConciliationPositionRequest,
    wait: float = Query(0, ge=0, le=ctx.MAX_STAGE_WAIT_SECONDS),
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """Registra a posição de uma parte. O gestor decide o próximo passo."""
    case = _case_or_404(db, case_id)
    _require_actor(db, case, x_actor_token, payload.party)
    _assert_procedure_open(case)
    if case.organized_json or case.decision_json:
        raise HTTPException(
            status_code=409,
            detail="A fase consensual já foi encerrada",
        )
    if payload.waived is False and not payload.text.strip():
        raise HTTPException(
            status_code=422,
            detail="Informe a posição ou renuncie a acrescentar algo nesta rodada",
        )
    rounds = case_to_dict(case)["conciliation_rounds"]
    if round_number < 1 or round_number > len(rounds):
        raise HTTPException(status_code=404, detail="Rodada de composição não encontrada")
    index = round_number - 1
    selected = dict(rounds[index])
    positions = dict(selected.get("party_positions") or {})
    positions[payload.party] = {
        "text": "" if payload.waived else payload.text,
        "waived": payload.waived,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    selected["party_positions"] = positions
    rounds[index] = selected
    case.conciliation_json = json.dumps(rounds, ensure_ascii=False)
    append_audit(
        db,
        case,
        "conciliation_position_recorded",
        {
            "round_number": round_number,
            "party": payload.party,
            "waived": payload.waived,
        },
    )
    db.commit()
    _conduct_steward(db, get_case(db, case_id), wait=wait, run_model_stages=True)
    db.expire_all()
    refreshed = case_to_dict(get_case(db, case_id), include_content=False)
    latest = (refreshed.get("conciliation_rounds") or [selected])[-1]
    return {
        "position": positions[payload.party],
        "round": latest,
        "steward": refreshed.get("steward"),
        "status": refreshed.get("status"),
    }


@router.post("/cases/{case_id}/organize")
def organize_case(
    case_id: str,
    wait: float = Query(
        0,
        ge=0,
        le=ctx.MAX_STAGE_WAIT_SECONDS,
        description=(
            "Segundos a aguardar a conclusão na própria resposta. 0 (padrão) "
            "responde 202 e a etapa segue em segundo plano."
        ),
    ),
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _assert_procedure_open(case)
    _require_steward_actuator(x_actor_token)
    case_data = case_to_dict(case)
    if case_data.get("procedure_conclusion") == "agreement":
        raise HTTPException(
            status_code=409,
            detail="O procedimento foi encerrado por acordo bilateral",
        )
    if not case.manifest_locked:
        raise HTTPException(
            status_code=409,
            detail="Trave o manifesto antes de organizar o caso",
        )
    if not case_data["conciliation"]:
        raise HTTPException(
            status_code=409,
            detail="Faça a triagem de conciliação ou mediação antes do julgamento",
        )
    if case_data["organized"]:
        _take_steward_chain(db, case_id)
        return case_data["organized"]
    try:
        claimed = claim_case_stage(
            db,
            case,
            "organize",
            extra_from_statuses=("conciliation", "locked"),
        )
    except StageBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not claimed:
        case = get_case(db, case_id)
        organized = case_to_dict(case).get("organized")
        if organized:
            _take_steward_chain(db, case_id)
            return organized
        raise HTTPException(status_code=409, detail="Organização já em andamento")

    def work(job_db: Session):
        job_case = get_case(job_db, case_id)
        job_data = case_to_dict(job_case)
        organized = _record_prompt_provenance(
            job_data,
            "organizer",
            organizer_organize_case(
                documents=job_data["documents"],
                chunks=job_data["chunks"],
                manifest=job_data.get("locked_manifest"),
            ),
        )
        save_stage(
            job_db,
            job_case,
            field="organized_json",
            value=organized,
            status="organized",
            event_type="case_organized",
            event_payload={"execution": organized.get("execution", {})},
        )
        _continue_steward(job_db, case_id)
        return organized

    return _run_stage(case_id, "organize", work, wait)


@router.post("/cases/{case_id}/decide")
def decide_case(
    case_id: str,
    wait: float = Query(
        0,
        ge=0,
        le=ctx.MAX_STAGE_WAIT_SECONDS,
        description=(
            "Segundos a aguardar a conclusão na própria resposta. 0 (padrão) "
            "responde 202 e a etapa segue em segundo plano."
        ),
    ),
    x_actor_token: str = Header(default=""),
    idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _assert_procedure_open(case)
    _require_steward_actuator(x_actor_token)
    case_data = case_to_dict(case)
    if not case_data["organized"]:
        raise HTTPException(
            status_code=409,
            detail="Organize o caso antes de proferir a decisão",
        )
    if case_data["decision"]:
        _take_steward_chain(db, case_id)
        return case_data["decision"]
    try:
        claimed = claim_case_stage(
            db,
            case,
            "decide",
            extra_from_statuses=("organized",),
        )
    except StageBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not claimed:
        case = get_case(db, case_id)
        existing = case_to_dict(case).get("decision")
        if existing:
            _take_steward_chain(db, case_id)
            return existing
        raise HTTPException(status_code=409, detail="Decisão já em processamento")

    def work(job_db: Session):
        job_case = get_case(job_db, case_id)
        job_data = case_to_dict(job_case)
        decision_context = {
            "manifest": job_data["locked_manifest"],
            "conciliation_rounds": job_data["conciliation_rounds"],
            "organized_case": job_data["organized"],
            "retrieved_evidence": {
                "delivery": _retrieve(
                    job_data,
                    "obrigações de entrega e cumprimento parcial",
                ),
                "payment": _retrieve(
                    job_data,
                    "condições de pagamento e proporcionalidade",
                ),
                "deadline": _retrieve(
                    job_data,
                    "cumprimento de prazo e atraso",
                ),
            },
        }
        decision, verification, conclusion = generate_and_verify_decision(
            job_db,
            job_case,
            job_data,
            decision_context,
            role="judge",
            idempotency_key=idempotency_key or None,
        )
        decision = _record_prompt_provenance(job_data, "judge", decision)
        stability = maybe_run_stability(
            job_db, job_case, job_data, decision_context, decision
        )
        if stability and not stability.get("stable"):
            decision["outcome"] = "inconclusive"
            decision["procedure_conclusion"] = "inconclusive"
            decision.setdefault("abstention_reasons", [])
            if "unstable_decision" not in decision["abstention_reasons"]:
                decision["abstention_reasons"].append("unstable_decision")
            if "material_model_disagreement" not in decision["abstention_reasons"]:
                decision["abstention_reasons"].append("material_model_disagreement")
            conclusion = "inconclusive"
            append_audit(
                job_db,
                job_case,
                "decision_unstable",
                {"disagreements": stability.get("material_disagreements") or []},
            )
        job_case.procedure_conclusion = conclusion
        job_case.stability_json = (
            json.dumps(stability, ensure_ascii=False)
            if stability
            else job_case.stability_json
        )
        status = "invalidated" if conclusion == "invalidated" else "decided"
        save_stage(
            job_db,
            job_case,
            field="decision_json",
            value=decision,
            status=status,
            event_type="decision_generated",
            event_payload={
                "outcome": decision.get("outcome"),
                "confidence": decision.get("confidence"),
                "procedure_conclusion": conclusion,
                "verification_valid": verification.get("valid"),
                "execution": decision.get("execution", {}),
            },
        )
        _continue_steward(job_db, case_id)
        return public_decision_view(decision)

    return _run_stage(case_id, "decide", work, wait)


@router.post("/cases/{case_id}/review")
def review_case(
    case_id: str,
    wait: float = Query(
        0,
        ge=0,
        le=ctx.MAX_STAGE_WAIT_SECONDS,
        description=(
            "Segundos a aguardar a conclusão na própria resposta. 0 (padrão) "
            "responde 202 e a etapa segue em segundo plano."
        ),
    ),
    x_actor_token: str = Header(default=""),
    idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _assert_procedure_open(case)
    _require_steward_actuator(x_actor_token)
    case_data = case_to_dict(case)
    if not case_data["decision"]:
        raise HTTPException(
            status_code=409,
            detail="Profira a decisão antes da auditoria",
        )
    if case_data["review"]:
        _take_steward_chain(db, case_id)
        return case_data["review"]
    try:
        claimed = claim_case_stage(
            db,
            case,
            "review",
            extra_from_statuses=("decided", "invalidated", "inconclusive"),
        )
    except StageBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not claimed:
        case = get_case(db, case_id)
        existing = case_to_dict(case).get("review")
        if existing:
            _take_steward_chain(db, case_id)
            return existing
        raise HTTPException(status_code=409, detail="Auditoria já em processamento")

    def work(job_db: Session):
        job_case = get_case(job_db, case_id)
        job_data = case_to_dict(job_case)
        verification = job_data.get("verification") or {}
        review = _record_prompt_provenance(
            job_data,
            "reviewer",
            run_automatic_review(
                job_db, job_case, job_data, job_data["decision"], verification
            ),
        )

        reconstruction_used = False
        decision = job_data["decision"]
        conclusion, decision = finalize_review_outcome(
            decision, verification, review, reconstruction_used
        )
        if conclusion == "pending_reconstruction":
            if not alternate_judge_available():
                conclusion, decision = finalize_review_outcome(
                    decision, verification, review, reconstruction_used=True
                )
            else:
                reconstruction_used = True
                new_input = {
                    "manifest": job_data["locked_manifest"],
                    "conciliation_rounds": job_data["conciliation_rounds"],
                    "organized_case": job_data["organized"],
                    "retrieved_evidence": {
                        "delivery": _retrieve(
                            job_data, "obrigações de entrega e cumprimento parcial"
                        ),
                        "payment": _retrieve(
                            job_data, "condições de pagamento e proporcionalidade"
                        ),
                        "deadline": _retrieve(
                            job_data, "cumprimento de prazo e atraso"
                        ),
                    },
                    "reconstruction": True,
                }
                decision, verification, _conclusion, review = reconstruct_once(
                    job_db,
                    job_case,
                    job_data,
                    new_input,
                    job_case.current_decision_run_id,
                )
                review = _record_prompt_provenance(job_data, "reviewer", review)
                conclusion, decision = finalize_review_outcome(
                    decision, verification, review, reconstruction_used=True
                )
                save_stage(
                    job_db,
                    job_case,
                    field="decision_json",
                    value=decision,
                    status="invalidated" if conclusion == "invalidated" else "decided",
                    event_type="decision_reconstructed",
                    event_payload={
                        "outcome": decision.get("outcome"),
                        "procedure_conclusion": conclusion,
                        "supersedes_id": job_case.current_decision_run_id,
                    },
                )

        job_case.procedure_conclusion = (
            conclusion
            if conclusion != "pending_reconstruction"
            else decision.get("procedure_conclusion")
        )
        save_stage(
            job_db,
            job_case,
            field="review_json",
            value=review,
            status="reviewed",
            event_type="review_generated",
            event_payload={
                "approved": review.get("approved"),
                "outcome": review.get("outcome"),
                "procedure_conclusion": job_case.procedure_conclusion,
                "reconstruction_used": reconstruction_used,
                "execution": review.get("execution", {}),
            },
        )
        _issue_decision_record_safely(job_db, case_id)
        _continue_steward(job_db, case_id)
        return review

    return _run_stage(case_id, "review", work, wait)


@router.post("/cases/{case_id}/contest")
def contest_case(
    case_id: str,
    payload: ContestRequest,
    wait: float = Query(
        0,
        ge=0,
        le=ctx.MAX_STAGE_WAIT_SECONDS,
        description=(
            "Segundos a aguardar a conclusão na própria resposta. 0 (padrão) "
            "responde 202 e o recurso automático segue em segundo plano."
        ),
    ),
    x_actor_token: str = Header(default=""),
    idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    actor_role = None
    for role in ("claimant", "respondent"):
        try:
            _require_actor(db, case, x_actor_token, role)
            actor_role = role
            break
        except HTTPException:
            continue
    if actor_role is None:
        raise HTTPException(
            status_code=403,
            detail="Apenas a parte reclamante ou a parte reclamada podem contestar",
        )

    case_data = case_to_dict(case)
    attestation = case_data["attestation"]
    if not attestation:
        raise HTTPException(
            status_code=409,
            detail="Não há attestation emitida para contestar",
        )
    accepted = acceptance_status(case_data)
    if accepted["parties"].get(actor_role) or accepted["complete"]:
        raise HTTPException(
            status_code=409,
            detail=(
                "A decisão foi acatada como acordo. O acatamento é irrevogável e "
                "afasta o recurso automático."
            ),
        )
    if case_data["contest"]["contested"] or case.contested_at:
        existing = find_appeal_by_idempotency(db, case.id, idempotency_key)
        if existing:
            return {
                **case_data["contest"],
                "appeal": existing.result_json and json.loads(existing.result_json),
                "appeal_id": existing.id,
            }
        return {
            **case_data["contest"],
            "appeal": (case_data.get("appeals") or [None])[-1],
        }

    try:
        claimed = claim_case_stage(
            db,
            case,
            "appeal",
            extra_from_statuses=("reviewed",),
        )
    except StageBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not claimed:
        case = get_case(db, case_id)
        refreshed = case_to_dict(case)
        return {
            **refreshed["contest"],
            "appeal": (refreshed.get("appeals") or [None])[-1],
        }

    window_ends = datetime.fromisoformat(attestation["contest_window_ends_utc"])
    if datetime.now(window_ends.tzinfo) > window_ends:
        raise HTTPException(
            status_code=409,
            detail="A janela de contestação já se encerrou",
        )

    explanation = payload.resolved_explanation()
    grounds = payload.resolved_grounds()
    if ctx.settings.max_appeals_per_attestation <= count_appeals(db, case.id):
        raise HTTPException(
            status_code=409,
            detail="O limite de recursos automáticos deste caso já foi atingido",
        )

    findings = {
        item.get("finding_id")
        for item in (case_data.get("decision") or {}).get("material_findings") or []
        if isinstance(item, dict)
    }
    unknown_findings = [
        item for item in payload.challenged_finding_ids if item not in findings
    ]
    if unknown_findings and findings:
        raise HTTPException(
            status_code=422,
            detail="Finding impugnado não existe na decisão",
        )
    manifest_doc_ids = {
        item.get("id")
        for item in (case_data.get("locked_manifest") or {}).get("documents") or []
    }
    for ref in payload.evidence_refs:
        document_id = ref.get("document_id") if isinstance(ref, dict) else None
        if document_id and manifest_doc_ids and document_id not in manifest_doc_ids:
            raise HTTPException(
                status_code=422,
                detail="Evidência do recurso não pertence ao manifesto",
            )

    original_hash = ((case_data.get("decision") or {}).get("provenance") or {}).get(
        "decision_payload_hash"
    ) or canonical_hash(case_data.get("decision") or {})
    appeal = persist_appeal(
        db,
        case,
        filed_by=actor_role,
        grounds=grounds,
        original_decision_hash=original_hash,
        idempotency_key=idempotency_key or None,
        status="processing",
    )
    updated = register_contest(db, case, actor_role, explanation)
    contest_payload = {
        "grounds": grounds,
        "explanation": explanation,
        "challenged_finding_ids": payload.challenged_finding_ids,
        "evidence_refs": payload.evidence_refs,
        "requested_correction": payload.requested_correction,
        "filed_by": actor_role,
    }
    db.commit()
    appeal_id = appeal.id

    def on_contest_failure(job_db: Session, error: str) -> None:
        job_case = get_case(job_db, case_id)
        if job_case is None:  # pragma: no cover - o caso existia ao reivindicar
            return
        revert_contest(job_db, job_case, appeal_id, "attested", error)

    def work(job_db: Session):
        job_case = get_case(job_db, case_id)
        job_appeal = find_appeal_by_id(job_db, case_id, appeal_id)
        result = run_appeal(
            job_db,
            job_case,
            case_to_dict(job_case),
            job_appeal,
            contest_payload,
        )
        job_db.commit()
        _issue_decision_record_safely(job_db, case_id)
        refreshed = case_to_dict(get_case(job_db, case_id))
        return {
            **refreshed["contest"],
            "appeal": result,
            "grounds": grounds,
        }

    return _run_stage(case_id, "contest", work, wait, on_failure=on_contest_failure)


@router.get("/cases/{case_id}/stage/{stage}")
def get_stage_status(
    case_id: str,
    stage: str,
    x_session_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """Andamento de uma etapa que roda em segundo plano.

    A fonte da verdade é o banco: se o resultado já está gravado, a etapa
    concluiu — mesmo que o serviço tenha reiniciado no meio e o registro em
    memória tenha se perdido. O registro só acrescenta o motivo de uma falha.
    """
    if stage not in ctx.ASYNC_STAGES:
        raise HTTPException(
            status_code=404,
            detail=f"Etapa desconhecida: {stage}. "
            f"Etapas assíncronas: {', '.join(sorted(ctx.ASYNC_STAGES))}.",
        )
    case = _case_or_404(db, case_id)
    _require_case_view(db, case, x_session_token)
    case_data = case_to_dict(case, include_content=False, include_embeddings=False)

    job = ctx.stage_runner.get(case_id, stage)
    result = _stage_result(case_data, stage)
    body = {
        "case_id": case_id,
        "stage": stage,
        "case_status": case.status,
        "started_at": job.started_at if job else None,
        "finished_at": job.finished_at if job else None,
    }

    if job is not None and job.state == FAILED:
        return {
            **body,
            "state": FAILED,
            "error": job.error,
            "detail": (
                "A etapa falhou e o caso voltou ao estado anterior. "
                "É possível repetir a chamada."
            ),
        }
    # Concluída é só quando o resultado está gravado E não há outra execução
    # da mesma etapa em voo (a composição admite rodadas sucessivas).
    if result is not None and (job is None or job.state != RUNNING):
        return {**body, "state": COMPLETED, "result": result}
    if _claim_is_stale(case) and job is None:
        # O processo morreu entre a reivindicação da etapa e o fim dela: o
        # registro em memória sumiu junto e no banco sobrou um `processing_*`
        # que ninguém vai concluir. Passado o TTL a etapa pode ser
        # reivindicada de novo, e é isso que o cliente precisa saber — sem
        # este ramo o polling responderia `processing` para sempre.
        return {
            **body,
            "state": FAILED,
            "error": "stage_abandoned",
            "detail": (
                "A etapa foi interrompida (provavelmente por reinício do "
                "serviço) e o prazo de reivindicação expirou. Repita a "
                "chamada para executá-la de novo."
            ),
        }
    if job is not None or str(case.status or "").startswith("processing"):
        # Inclui o caso de um job já concluído cujo resultado ainda não
        # aparece nesta leitura. Reportar "pending" aqui seria dizer que a
        # etapa nunca começou, e um cliente que trata `pending` como fim
        # desistiria justamente no instante entre o commit e a leitura. O
        # estado só anda para frente: quem está em polling continua.
        return {**body, "state": RUNNING}
    return {
        **body,
        "state": "pending",
        "detail": "A etapa ainda não foi iniciada para este caso.",
    }
