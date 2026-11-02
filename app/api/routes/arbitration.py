"""Árbitro pessoa física, sentença arbitral e opção pela via judicial."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.api.background import _issue_decision_record
from app.api.common import (
    _assert_procedure_open,
    _case_or_404,
    _require_actor,
    _require_verified_email,
)
from app.core.canonical import canonical_hash
from app.db.access_repository import get_user_by_token, user_has_role
from app.db.repository import (
    case_to_dict,
    get_case,
    record_withdrawal,
    save_arbitral_award,
    save_arbitrator_acceptance,
    save_arbitrator_confirmation,
)
from app.db.session import get_db
from app.domain.arbitration import (
    ARBITRATOR_ROLE,
    ArbitrationError,
    arbitrator_designated,
    decision_is_final,
)
from app.domain.concurrency import TERMINAL_STATUSES as CONCURRENCY_TERMINAL_STATUSES
from app.domain.pathway import ARBITRATION, resolution_track
from app.reports.decision_record import outcome_kind
from app.schemas import (
    ArbitralAwardRequest,
    ArbitratorAcceptRequest,
    ArbitratorConfirmRequest,
    WithdrawToCourtRequest,
)

router = APIRouter()


def _require_arbitrator(db: Session, case, token: str):
    user = get_user_by_token(db, token)
    if not user or not user_has_role(db, case.id, user.id, ARBITRATOR_ROLE):
        raise HTTPException(
            status_code=403, detail="Somente o árbitro convidado para o caso pode fazer isto"
        )
    _require_verified_email(user)
    return user


def _assert_arbitrator_designation_open(case) -> None:
    _assert_procedure_open(case)
    if not case.pathway_json:
        raise HTTPException(
            status_code=409,
            detail="Este caso foi aberto antes da via arbitral e não tem árbitro",
        )
    if case.manifest_locked:
        raise HTTPException(
            status_code=409,
            detail=(
                "A designação do árbitro fecha na trava do caso: o compromisso "
                "precisa nomear o árbitro antes da decisão"
            ),
        )


@router.post("/cases/{case_id}/arbitrator/accept")
def accept_arbitrator_nomination(
    case_id: str,
    payload: ArbitratorAcceptRequest,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """O árbitro aceita a nomeação, se qualifica e revela o que houver
    (Lei 9.307/96, arts. 13 e 14, §1º). Aceitar de novo zera as confirmações."""
    case = _case_or_404(db, case_id)
    user = _require_arbitrator(db, case, x_actor_token)
    _assert_arbitrator_designation_open(case)
    if any(user_has_role(db, case.id, user.id, party) for party in ("claimant", "respondent")):
        raise HTTPException(
            status_code=409,
            detail="Quem é parte no caso não pode ser árbitro dele (Lei 9.307/96, art. 14)",
        )
    updated = save_arbitrator_acceptance(
        db,
        case,
        user_id=user.id,
        display_name=user.display_name,
        tax_id=payload.tax_id,
        qualification=payload.qualification,
        disclosure=payload.disclosure,
    )
    return case_to_dict(updated, include_content=False, include_embeddings=False)["pathway"]


@router.post("/cases/{case_id}/arbitrator/confirm")
def confirm_arbitrator(
    case_id: str,
    payload: ArbitratorConfirmRequest,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """A parte confirma o árbitro aceito, com a declaração que ele fez."""
    case = _case_or_404(db, case_id)
    _require_actor(db, case, x_actor_token, payload.party)
    _assert_arbitrator_designation_open(case)
    pathway = case_to_dict(case, include_content=False, include_embeddings=False)["pathway"] or {}
    election = (pathway.get("arbitration_elections") or {}).get(payload.party) or {}
    if not election.get("elected"):
        raise HTTPException(
            status_code=409,
            detail="Escolha a arbitragem no seu aceite antes de confirmar o árbitro",
        )
    try:
        updated = save_arbitrator_confirmation(
            db,
            case,
            party=payload.party,
            terms_version=getattr(case, f"{payload.party}_terms_version") or "",
        )
    except ArbitrationError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return case_to_dict(updated, include_content=False, include_embeddings=False)["pathway"]


@router.post("/cases/{case_id}/arbitral-award")
def sign_arbitral_award(
    case_id: str,
    payload: ArbitralAwardRequest,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """O árbitro designado adota e assina a decisão final como sentença
    arbitral, ou recusa adotá-la. Não há reescrita da decisão aqui dentro."""
    case = _case_or_404(db, case_id)
    user = _require_arbitrator(db, case, x_actor_token)
    case_data = case_to_dict(case, include_content=False, include_embeddings=False)
    locked = (case_data.get("locked_manifest") or {}).get("pathway") or {}
    if (
        resolution_track(locked) != ARBITRATION
        or not arbitrator_designated(locked)
        or (locked.get("arbitrator") or {}).get("user_id") != user.id
    ):
        raise HTTPException(
            status_code=403,
            detail="Você não é o árbitro designado pelas duas partes neste caso",
        )
    if case_data.get("arbitral_award"):
        raise HTTPException(status_code=409, detail="O árbitro já se manifestou neste caso")
    if outcome_kind(case_data) != "decision":
        raise HTTPException(status_code=409, detail="Não há decisão de mérito para assinar")
    final, reason = decision_is_final(case_data)
    if not final:
        raise HTTPException(status_code=409, detail=reason)
    current = _issue_decision_record(db, case_id)
    if not current:
        raise HTTPException(status_code=409, detail="O auto da decisão ainda não foi emitido")
    arbitrator = locked.get("arbitrator") or {}
    save_arbitral_award(
        db,
        get_case(db, case_id),
        adopted=payload.adopt,
        payload={
            "arbitrator_user_id": user.id,
            "arbitrator_name": arbitrator.get("display_name"),
            "arbitrator_identity_sha256": arbitrator.get("identity_sha256"),
            "place": payload.place,
            "statement": payload.statement,
            "adopted_record_hash": current.get("record_hash"),
            "decision_hash": canonical_hash(case_data.get("decision") or {}),
            "attestation_hash": (case_data.get("attestation") or {}).get("attestation_hash"),
        },
    )
    db.expire_all()
    return _issue_decision_record(db, case_id)


@router.post("/cases/{case_id}/withdraw-to-court")
def withdraw_to_court(
    case_id: str,
    payload: WithdrawToCourtRequest,
    x_actor_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """A parte deixa a Valinor e leva o conflito ao Judiciário.

    Adesão voluntária vale nos dois sentidos: qualquer parte sai a qualquer
    momento antes do desfecho, sem depender da outra. O caso encerra e o auto
    com todo o histórico até ali fica disponível às duas partes, para auditar
    e, se quiserem, juntar ao processo.
    """
    case = _case_or_404(db, case_id)
    _require_actor(db, case, x_actor_token, payload.party)
    if case.status == "withdrawn":
        record = _issue_decision_record(db, case_id)
        return {"status": "withdrawn", "decision_record": record}
    if (case.status or "").startswith("processing") or case.status == "locking":
        raise HTTPException(
            status_code=409,
            detail=(
                "Há uma etapa em andamento. Aguarde a conclusão dela para "
                "registrar a opção pela via judicial."
            ),
        )
    case_data = case_to_dict(case, include_content=False, include_embeddings=False)
    if case.status in {"agreement", *CONCURRENCY_TERMINAL_STATUSES} or outcome_kind(case_data):
        raise HTTPException(
            status_code=409,
            detail=(
                "O procedimento já tem um desfecho e um auto emitido. Para "
                "levar o conflito ao Judiciário, use esse auto."
            ),
        )
    updated = record_withdrawal(db, case, payload.party, payload.reason)
    if updated is None:
        raise HTTPException(
            status_code=409,
            detail="O caso mudou de estado agora. Recarregue e tente de novo.",
        )
    # A trilha carregada antes da saída está velha: o auto precisa do evento.
    db.expire_all()
    record = _issue_decision_record(db, case_id)
    return {"status": "withdrawn", "decision_record": record}
