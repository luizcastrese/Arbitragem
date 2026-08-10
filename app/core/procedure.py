"""O rito: o procedimento executando a si mesmo.

Todo ato que antes exigia um gestor humano — admitir material, travar o
manifesto, abrir e fechar prazos, conduzir as rodadas de composição,
organizar, julgar, auditar e emitir a attestation — passa a ser executado por
este módulo, em nome do próprio procedimento.

Nenhuma pré-condição foi relaxada. As mesmas verificações que antes rodavam
antes de o gestor apertar o botão continuam aqui, e cada passo só executa
quando já está satisfeito. O que muda é quem executa: não há terceiro humano
no caso, apenas as duas partes e o rito.

Cada passo é idempotente — reexecutar `advance` não repete o que já foi feito
— e registra na cadeia de auditoria um evento com `actor: "procedure"`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from app.agents.conciliator import assess_conciliation
from app.agents.judge import decide_case as judge_decide_case
from app.agents.organizer import organize_case as organizer_organize_case
from app.agents.reviewer import review_decision
from app.core.attestation import AttestationError, build_decision_attestation
from app.core.audit import verify_audit_chain
from app.core.config import get_settings
from app.core.manifest import lock_case_manifest
from app.core.nostr_anchor import publish_attestation_anchor
from app.db.access_repository import (
    complete_deadlines_for_reference,
    create_deadline,
    create_notification,
    deadline_exists_for_reference,
)
from app.db.repository import (
    admit_document,
    append_audit,
    case_to_dict,
    consume_composition_inputs,
    get_case,
    get_document,
    lock_manifest as persist_manifest,
    save_nostr_anchor,
    save_stage,
)
from app.documents.embeddings import retrieve_by_embedding
from app.documents.retrieval import retrieve_relevant_chunks


PARTIES = ("claimant", "respondent")
RESPONDED_STATUSES = {"answered", "waived", "challenged"}
RESPONSE_DEADLINE_KIND = "contradictory"

# Teto de passos por invocação. Protege contra um agente que insista em
# recomendar novas rodadas indefinidamente.
_MAX_STEPS = 32


def counterparty(party: str) -> str:
    return "respondent" if party == "claimant" else "claimant"


def retrieve_admitted_chunks(
    case_data: Dict[str, Any],
    query: str,
    method: str = "embedding",
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Recuperação restrita ao material admitido. Nada que não tenha passado
    pelo contraditório completo chega a qualquer agente."""
    admitted_document_ids = {
        document["id"]
        for document in case_data["documents"]
        if document.get("admitted")
    }
    chunks = [
        chunk
        for chunk in case_data["chunks"]
        if chunk.get("document_id") in admitted_document_ids
    ]
    if method == "embedding":
        try:
            results = retrieve_by_embedding(query=query, chunks=chunks, limit=limit)
            if results:
                return results
        except Exception:
            pass
    return retrieve_relevant_chunks(query=query, chunks=chunks, limit=limit)


def _notify_parties(db: Session, case_id: str, event_type: str, title: str, message: str) -> None:
    for party in PARTIES:
        create_notification(db, case_id, party, event_type, title, message)


# ---------------------------------------------------------------------------
# Passos do rito
#
# Cada função devolve um dicionário quando executou algo, ou None quando as
# pré-condições ainda não estão satisfeitas. Nenhuma delas levanta exceção por
# "ainda não é hora": o rito simplesmente espera.
# ---------------------------------------------------------------------------


def _admit_ready_material(db: Session, case, data: Dict[str, Any]) -> Optional[Dict]:
    """Admite o material cujo contraditório se completou. A admissão deixa de
    ser um juízo do gestor e passa a ser a consequência automática de ciência
    mais resposta (ou renúncia) da contraparte."""
    if case.manifest_locked:
        return None
    admitted: List[str] = []
    for document_data in data["documents"]:
        if document_data["admitted"]:
            continue
        if not document_data["disclosed_at"] or not document_data["acknowledged_at"]:
            continue
        if document_data["response_status"] not in RESPONDED_STATUSES:
            continue
        document = get_document(db, case.id, document_data["id"])
        if document is None:
            continue
        admit_document(db, case, document)
        admitted.append(document_data["id"])
    if not admitted:
        return None
    return {"step": "material_admitted", "document_ids": admitted}


def _open_response_deadlines(db: Session, case, data: Dict[str, Any]) -> Optional[Dict]:
    """Abre o prazo de ciência e resposta da contraparte assim que um material
    é disponibilizado."""
    if case.manifest_locked:
        return None
    settings = get_settings()
    opened: List[str] = []
    for document_data in data["documents"]:
        if document_data["response_status"] in RESPONDED_STATUSES:
            continue
        if deadline_exists_for_reference(
            db, case.id, document_data["id"], RESPONSE_DEADLINE_KIND
        ):
            continue
        expected = counterparty(document_data["submitted_by"])
        deadline = create_deadline(
            db,
            case.id,
            label=f"Ciência e resposta ao material {document_data['name']}",
            kind=RESPONSE_DEADLINE_KIND,
            assigned_to=expected,
            due_at=datetime.now(timezone.utc)
            + timedelta(days=settings.contradictory_response_days),
            reference_id=document_data["id"],
        )
        append_audit(
            db,
            case,
            "deadline_created",
            {
                "deadline_id": deadline.id,
                "assigned_to": deadline.assigned_to,
                "reference_id": document_data["id"],
                "due_at": deadline.due_at.isoformat(),
                "actor": "procedure",
            },
        )
        create_notification(
            db,
            case.id,
            expected,
            "deadline_created",
            "Novo material aguardando sua manifestação",
            f"{deadline.label}: até {deadline.due_at.isoformat()}.",
        )
        opened.append(document_data["id"])
    if not opened:
        return None
    db.commit()
    return {"step": "response_deadlines_opened", "document_ids": opened}


def _close_met_deadlines(db: Session, case, data: Dict[str, Any]) -> Optional[Dict]:
    """Dá baixa nos prazos cujo ato esperado já aconteceu."""
    open_references = {
        deadline["reference_id"]
        for deadline in data["deadlines"]
        if deadline["status"] != "completed" and deadline["reference_id"]
    }
    if not open_references:
        return None
    closed: List[str] = []
    for document_data in data["documents"]:
        if document_data["id"] not in open_references:
            continue
        if document_data["response_status"] not in RESPONDED_STATUSES:
            continue
        completed = complete_deadlines_for_reference(db, case.id, document_data["id"])
        if not completed:
            continue
        for deadline in completed:
            append_audit(
                db,
                case,
                "deadline_completed",
                {
                    "deadline_id": deadline.id,
                    "reference_id": document_data["id"],
                    "actor": "procedure",
                },
            )
        closed.append(document_data["id"])
    if not closed:
        return None
    db.commit()
    return {"step": "deadlines_completed", "document_ids": closed}


def _lock_manifest(db: Session, case, data: Dict[str, Any]) -> Optional[Dict]:
    """Trava o registro documental. As pré-condições são as mesmas de antes,
    acrescidas do encerramento de produção declarado pelas duas partes — que é
    o sinal que substitui o juízo do gestor sobre o acervo estar completo."""
    if case.manifest_locked:
        return None
    if not data["documents"]:
        return None
    if not data["consent"]["complete"]:
        return None
    if not data["submission"]["complete"]:
        return None
    if not data["contradictory"]["complete"]:
        return None

    manifest = lock_case_manifest(data)
    persist_manifest(db, case, manifest)
    _notify_parties(
        db,
        case.id,
        "manifest_locked",
        "Registro documental travado",
        "O material foi fixado e não aceita mais alterações. "
        "A fase de composição começa agora.",
    )
    return {"step": "manifest_locked", "manifest_hash": manifest["manifest_hash"]}


def _run_composition_round(db: Session, case, data: Dict[str, Any]) -> Optional[Dict]:
    """Conduz uma rodada de composição. A primeira sai automaticamente depois
    da trava; as seguintes só quando as duas partes registram sua posição."""
    if not case.manifest_locked:
        return None
    if data["organized"]:
        return None
    if data["contest"]["contested"]:
        return None

    rounds = data["conciliation_rounds"]
    composition = data["composition"]
    settings = get_settings()

    if rounds:
        if composition["closed"]:
            return None
        last_round = rounds[-1]
        if not last_round.get("continue_recommended", False):
            return None
        if len(rounds) >= settings.composition_max_rounds:
            return None
        if not composition["complete"]:
            return None

    positions = consume_composition_inputs(db, case)
    round_number = len(rounds) + 1
    context = {
        "round_number": round_number,
        "manifest": data["locked_manifest"],
        "parties": {
            "claimant": data["claimant"],
            "respondent": data["respondent"],
        },
        "documents": [
            {
                "id": document["id"],
                "name": document["name"],
                "content": document.get("content", "")[:8000],
            }
            for document in data["documents"]
        ],
        "previous_rounds": rounds,
        "current_party_responses": {
            "claimant": positions.get("claimant", ""),
            "respondent": positions.get("respondent", ""),
            "new_information": "",
        },
        "retrieved_evidence": {
            "shared_interests": retrieve_admitted_chunks(
                data,
                "interesses comuns continuidade da relação acordo solução consensual",
            ),
            "possible_concessions": retrieve_admitted_chunks(
                data,
                "propostas concessões negociação pagamento prazo entrega",
            ),
        },
    }
    conciliation = assess_conciliation(context, round_number)
    save_stage(
        db,
        case,
        field="conciliation_json",
        value=[*rounds, conciliation],
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
    _notify_parties(
        db,
        case.id,
        "conciliation_round",
        f"Rodada de composição {round_number}",
        conciliation.get("neutral_summary", "")
        or "Nova rodada de composição disponível no caso.",
    )
    return {"step": "composition_round", "round_number": round_number}


def _composition_exhausted(data: Dict[str, Any]) -> bool:
    rounds = data["conciliation_rounds"]
    if not rounds:
        return False
    if data["composition"]["closed"]:
        return True
    if len(rounds) >= get_settings().composition_max_rounds:
        return True
    return not rounds[-1].get("continue_recommended", False)


def _organize(db: Session, case, data: Dict[str, Any]) -> Optional[Dict]:
    if not case.manifest_locked or data["organized"]:
        return None
    if not _composition_exhausted(data):
        return None
    organized = organizer_organize_case(
        documents=data["documents"],
        chunks=data["chunks"],
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
    return {"step": "case_organized"}


def _decide(db: Session, case, data: Dict[str, Any]) -> Optional[Dict]:
    if not data["organized"] or data["decision"]:
        return None
    decision = judge_decide_case(
        {
            "manifest": data["locked_manifest"],
            "conciliation_rounds": data["conciliation_rounds"],
            "organized_case": data["organized"],
            "retrieved_evidence": {
                "delivery": retrieve_admitted_chunks(
                    data, "obrigações de entrega e cumprimento parcial"
                ),
                "payment": retrieve_admitted_chunks(
                    data, "condições de pagamento e proporcionalidade"
                ),
                "deadline": retrieve_admitted_chunks(
                    data, "cumprimento de prazo e atraso"
                ),
            },
        }
    )
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
    return {"step": "decision_generated", "outcome": decision.get("outcome")}


def _review(db: Session, case, data: Dict[str, Any]) -> Optional[Dict]:
    if not data["decision"] or data["review"]:
        return None
    review = review_decision(
        {
            "manifest": data["locked_manifest"],
            "conciliation_rounds": data["conciliation_rounds"],
            "organized_case": data["organized"],
            "decision": data["decision"],
        }
    )
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
    _notify_parties(
        db,
        case.id,
        "review_generated",
        "Decisão auditada",
        "A decisão passou pela auditoria independente. "
        "O relatório completo já está disponível no caso.",
    )
    return {"step": "review_generated", "approved": review.get("approved")}


def _issue_attestation(db: Session, case, data: Dict[str, Any]) -> Optional[Dict]:
    """Emite a attestation executável quando ela é cabível. Um caso
    inconclusivo, reprovado na auditoria ou que exige revisão humana
    simplesmente não gera attestation — e isso não é uma falha do rito."""
    if not data["review"] or data["attestation"]:
        return None
    if data["contest"]["contested"]:
        return None
    if not get_settings().attestation_enabled:
        return None

    audit_events = data["audit_log"]
    chain_valid, _ = verify_audit_chain(audit_events)
    if not chain_valid:
        return None
    audit_chain_head = audit_events[-1]["event_hash"] if audit_events else ""

    try:
        attestation = build_decision_attestation(
            case_data=data,
            audit_chain_head=audit_chain_head,
            audit_chain_length=len(audit_events),
        )
    except AttestationError:
        return None

    save_stage(
        db,
        case,
        field="attestation_json",
        value=attestation,
        status="attested",
        event_type="attestation_issued",
        event_payload={
            "attestation_hash": attestation["attestation_hash"],
            "audit_chain_head": audit_chain_head,
            "outcome": attestation["decision"]["outcome"],
            "split": attestation["decision"]["split"],
            "contest_window_ends_utc": attestation["contest_window_ends_utc"],
            "key_id": attestation["platform"]["key_id"],
        },
    )
    anchor = publish_attestation_anchor(attestation)
    if anchor:
        save_nostr_anchor(db, get_case(db, case.id), anchor)
    _notify_parties(
        db,
        case.id,
        "attestation_issued",
        "Attestation emitida",
        "A decisão foi assinada. A janela de contestação vai até "
        f"{attestation['contest_window_ends_utc']}.",
    )
    return {
        "step": "attestation_issued",
        "contest_window_ends_utc": attestation["contest_window_ends_utc"],
    }


STEPS: tuple[Callable[[Session, Any, Dict[str, Any]], Optional[Dict]], ...] = (
    _admit_ready_material,
    _close_met_deadlines,
    _open_response_deadlines,
    _lock_manifest,
    _run_composition_round,
    _organize,
    _decide,
    _review,
    _issue_attestation,
)


# ---------------------------------------------------------------------------
# Estado: o que o rito espera, e de quem
# ---------------------------------------------------------------------------


def pending_actions(data: Dict[str, Any]) -> List[Dict[str, str]]:
    """O que falta, atribuído à parte responsável. Enquanto houver pendência
    aqui, o rito está esperando uma parte — nunca um terceiro."""
    pending: List[Dict[str, str]] = []

    if data["contest"]["contested"]:
        return pending

    if not data["manifest_locked"]:
        for party in PARTIES:
            if not data["consent"][party]["accepted"]:
                pending.append(
                    {
                        "party": party,
                        "action": "consent",
                        "detail": "Aceitar os termos do procedimento.",
                    }
                )
        for document in data["documents"]:
            expected = document["counterparty"]
            if not document["acknowledged_at"]:
                pending.append(
                    {
                        "party": expected,
                        "action": "acknowledge",
                        "reference_id": document["id"],
                        "detail": f"Confirmar ciência do material {document['name']}.",
                    }
                )
            elif document["response_status"] not in RESPONDED_STATUSES:
                pending.append(
                    {
                        "party": expected,
                        "action": "respond",
                        "reference_id": document["id"],
                        "detail": (
                            f"Responder, contestar ou renunciar ao material "
                            f"{document['name']}."
                        ),
                    }
                )
        # O encerramento da produção só vira pendência quando ele é a última
        # coisa que falta: enquanto houver contraditório aberto, a espera é
        # pela manifestação da contraparte.
        if (
            data["consent"]["complete"]
            and data["documents"]
            and data["contradictory"]["complete"]
        ):
            for party in PARTIES:
                if not data["submission"][party]["closed"]:
                    pending.append(
                        {
                            "party": party,
                            "action": "close_submission",
                            "detail": "Encerrar a própria produção de material.",
                        }
                    )
        if not data["documents"]:
            pending.append(
                {
                    "party": "claimant",
                    "action": "add_document",
                    "detail": "Apresentar ao menos um documento ou alegação.",
                }
            )
        return pending

    rounds = data["conciliation_rounds"]
    if rounds and not data["organized"] and not _composition_exhausted(data):
        for party in PARTIES:
            if not data["composition"][party]["submitted"]:
                pending.append(
                    {
                        "party": party,
                        "action": "composition_position",
                        "detail": (
                            "Registrar sua posição para a próxima rodada, ou "
                            "encerrar a composição."
                        ),
                    }
                )
    return pending


def state(data: Dict[str, Any]) -> Dict[str, Any]:
    pending = pending_actions(data)
    return {
        "stage": data["status"],
        "manifest_locked": data["manifest_locked"],
        "composition_rounds": len(data["conciliation_rounds"]),
        "composition_exhausted": _composition_exhausted(data),
        "pending": pending,
        "waiting_on": sorted({item["party"] for item in pending}),
        "attestation_issued": bool(data["attestation"]),
        "contested": data["contest"]["contested"],
    }


def advance(db: Session, case) -> Dict[str, Any]:
    """Leva o caso o mais longe que suas próprias pré-condições permitirem.

    É seguro chamar a qualquer momento e quantas vezes for: quando não há
    passo aplicável, nada acontece.
    """
    performed: List[Dict[str, Any]] = []
    for _ in range(_MAX_STEPS):
        case = get_case(db, case.id)
        data = case_to_dict(case)
        for step in STEPS:
            result = step(db, case, data)
            if result:
                performed.append(result)
                break
        else:
            break

    case = get_case(db, case.id)
    return {"performed": performed, **state(case_to_dict(case))}
