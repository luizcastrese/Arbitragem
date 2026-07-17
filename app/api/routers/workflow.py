"""Rotas do fluxo de IA: composição, organização, decisão e auditoria."""

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import _case_or_404, _require_actor, _retrieve, get_db
from app.agents.conciliator import assess_conciliation
from app.agents.judge import decide_case as judge_decide_case
from app.agents.organizer import organize_case as organizer_organize_case
from app.agents.reviewer import review_decision
from app.db.repository import case_to_dict, save_stage
from app.schemas import ConciliationRoundRequest

router = APIRouter(prefix="/cases/{case_id}", tags=["fluxo"])


@router.post("/conciliation")
def assess_case_conciliation(
    case_id: str,
    payload: ConciliationRoundRequest = ConciliationRoundRequest(),
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_actor(db, case, x_actor_token, "manager")
    case_data = case_to_dict(case)
    if not case.manifest_locked:
        raise HTTPException(
            status_code=409,
            detail="Trave o manifesto antes da triagem de composição",
        )
    rounds = case_data["conciliation_rounds"]
    if rounds and not payload.advance:
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
    conciliation = assess_conciliation(context, round_number)
    updated_rounds = [*rounds, conciliation]
    save_stage(
        db,
        case,
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
    return conciliation


@router.post("/organize")
def organize_case(
    case_id: str,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_actor(db, case, x_actor_token, "manager")
    case_data = case_to_dict(case)
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
        return case_data["organized"]

    organized = organizer_organize_case(
        documents=case_data["documents"],
        chunks=case_data["chunks"],
    )
    save_stage(
        db,
        case,
        field="organized_json",
        value=organized,
        status="organized",
        event_type="case_organized",
        event_payload={"execution": organized.get("execution", {})},
    )
    return organized


@router.post("/decide")
def decide_case(
    case_id: str,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_actor(db, case, x_actor_token, "manager")
    case_data = case_to_dict(case)
    if not case_data["organized"]:
        raise HTTPException(
            status_code=409,
            detail="Organize o caso antes de proferir a decisão",
        )
    if case_data["decision"]:
        return case_data["decision"]

    decision_context = {
        "manifest": case_data["locked_manifest"],
        "conciliation_rounds": case_data["conciliation_rounds"],
        "organized_case": case_data["organized"],
        "retrieved_evidence": {
            "delivery": _retrieve(
                case_data,
                "obrigações de entrega e cumprimento parcial",
            ),
            "payment": _retrieve(
                case_data,
                "condições de pagamento e proporcionalidade",
            ),
            "deadline": _retrieve(
                case_data,
                "cumprimento de prazo e atraso",
            ),
        },
    }
    decision = judge_decide_case(decision_context)
    save_stage(
        db,
        case,
        field="decision_json",
        value=decision,
        status="decided",
        event_type="decision_generated",
        event_payload={
            "outcome": decision.get("outcome"),
            "confidence": decision.get("confidence"),
            "requires_human_review": decision.get("requires_human_review"),
            "execution": decision.get("execution", {}),
        },
    )
    return decision


@router.post("/review")
def review_case(
    case_id: str,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    case = _case_or_404(db, case_id)
    _require_actor(db, case, x_actor_token, "manager")
    case_data = case_to_dict(case)
    if not case_data["decision"]:
        raise HTTPException(
            status_code=409,
            detail="Profira a decisão antes da auditoria",
        )
    if case_data["review"]:
        return case_data["review"]

    review_payload = {
        "manifest": case_data["locked_manifest"],
        "conciliation_rounds": case_data["conciliation_rounds"],
        "organized_case": case_data["organized"],
        "decision": case_data["decision"],
    }
    review = review_decision(review_payload)
    save_stage(
        db,
        case,
        field="review_json",
        value=review,
        status="reviewed",
        event_type="review_generated",
        event_payload={
            "approved": review.get("approved"),
            "requires_human_review": review.get("requires_human_review"),
            "execution": review.get("execution", {}),
        },
    )
    return review
