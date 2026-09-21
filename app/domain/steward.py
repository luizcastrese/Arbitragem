"""O que o gestor pode fazer agora.

A política é determinística de propósito: o modelo, quando existe, escolhe
dentro desta lista. Uma parte nunca entra aqui como autora da ação.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any, Dict, List

from app.agents.steward import choose_action
from app.core.config import get_settings

PARTIES = ("claimant", "respondent")
MODEL_ACTIONS = ("conciliate", "organize", "decide", "review")
TERMINAL_STATUSES = {"agreement", "reviewed", "attested", "contested"}


def steward_actuator_token() -> str:
    """Credencial do processo, não de uma pessoa.

    Quem tem o segredo de assinatura da plataforma já pode forjar manifesto.
    O token só impede que a sessão de uma parte acione o atuador do gestor.
    """
    secret = get_settings().platform_signing_secret.encode("utf-8")
    return hmac.new(secret, b"valinor-steward-actuator", hashlib.sha256).hexdigest()


def _documents(case_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(case_data.get("documents") or [])


def admissible_document_ids(case_data: Dict[str, Any]) -> List[str]:
    ids: List[str] = []
    for document in _documents(case_data):
        if document.get("admitted"):
            continue
        if not document.get("acknowledged_at"):
            continue
        if document.get("response_status") not in {"answered", "waived", "challenged"}:
            continue
        ids.append(document["id"])
    return ids


def _submission_complete(case_data: Dict[str, Any]) -> bool:
    submission = case_data.get("submission") or {}
    return all((submission.get(party) or {}).get("ready") for party in PARTIES)


def _latest_round(case_data: Dict[str, Any]) -> Dict[str, Any]:
    rounds = case_data.get("conciliation_rounds") or []
    if rounds:
        return rounds[-1]
    conciliation = case_data.get("conciliation") or {}
    return conciliation if conciliation else {}


def _positions(round_data: Dict[str, Any]) -> Dict[str, Any]:
    return round_data.get("party_positions") or {}


def _both_answered(round_data: Dict[str, Any]) -> bool:
    positions = _positions(round_data)
    return all(party in positions for party in PARTIES)


def _both_waived(round_data: Dict[str, Any]) -> bool:
    positions = _positions(round_data)
    return all(bool((positions.get(party) or {}).get("waived")) for party in PARTIES)


def _has_new_material(round_data: Dict[str, Any]) -> bool:
    positions = _positions(round_data)
    return any(
        str((positions.get(party) or {}).get("text") or "").strip()
        for party in PARTIES
    )


def _waiting_parties(case_data: Dict[str, Any]) -> List[str]:
    waiting: List[str] = []
    consent = case_data.get("consent") or {}
    submission = case_data.get("submission") or {}
    for party in PARTIES:
        if not (consent.get(party) or {}).get("accepted"):
            waiting.append(f"{party}:adesao")
        elif not (submission.get(party) or {}).get("ready"):
            waiting.append(f"{party}:apresentacao")
    for document in _documents(case_data):
        if document.get("admitted"):
            continue
        counterparty = document.get("counterparty")
        if not document.get("acknowledged_at"):
            waiting.append(f"{counterparty}:ciencia:{document.get('id')}")
        elif document.get("response_status") == "pending":
            waiting.append(f"{counterparty}:resposta:{document.get('id')}")
    round_data = _latest_round(case_data)
    if round_data and not case_data.get("organized"):
        positions = _positions(round_data)
        for party in PARTIES:
            if party not in positions:
                waiting.append(f"{party}:composicao")
    return waiting


def _another_round(case_data: Dict[str, Any]) -> bool:
    round_data = _latest_round(case_data)
    if not round_data or not _both_answered(round_data) or _both_waived(round_data):
        return False
    if round_data.get("continue_recommended"):
        return True
    return _has_new_material(round_data)


def legal_actions(case_data: Dict[str, Any]) -> Dict[str, Any]:
    """Ações lícitas neste instante, em ordem de prioridade do rito."""
    conclusion = case_data.get("procedure_conclusion") or ""
    status = case_data.get("status") or ""
    if status in TERMINAL_STATUSES:
        return _pack(["hold"], [], ["O procedimento já tem um desfecho."])
    if status.startswith("processing"):
        return _pack(["wait"], [], ["Uma etapa do gestor já está em andamento."])

    admissible = admissible_document_ids(case_data)
    if admissible:
        return _pack(
            ["admit"],
            admissible,
            ["Há material com contraditório fechado que ainda não foi admitido."],
        )

    documents = _documents(case_data)
    contradictory_complete = bool(documents) and bool(
        (case_data.get("contradictory") or {}).get("complete")
    )
    consent_complete = bool((case_data.get("consent") or {}).get("complete"))
    locked = bool(case_data.get("manifest_locked"))

    if not locked:
        if (
            consent_complete
            and contradictory_complete
            and _submission_complete(case_data)
        ):
            return _pack(
                ["lock"],
                [],
                ["As duas partes encerraram a apresentação e o contraditório fechou."],
            )
        return _pack(
            ["wait"],
            [],
            _waiting_parties(case_data) or ["Ainda falta ato de parte antes da trava."],
        )

    if conclusion == "agreement" or status == "agreement":
        return _pack(["hold"], [], ["As partes formaram acordo."])

    organized = bool(case_data.get("organized"))
    decision = case_data.get("decision")
    review = case_data.get("review")
    round_data = _latest_round(case_data)

    if not round_data and not organized:
        return _pack(
            ["conciliate"],
            [],
            ["O conjunto está travado. A composição vem antes do julgamento."],
        )

    if round_data and not organized:
        if not _both_answered(round_data):
            return _pack(
                ["wait"],
                [],
                [
                    item
                    for item in _waiting_parties(case_data)
                    if item.endswith(":composicao")
                ]
                or ["Cada parte precisa dizer sua posição nesta rodada."],
            )
        if _another_round(case_data):
            return _pack(
                ["conciliate", "organize"],
                [],
                [
                    "Há espaço ou fato novo para outra rodada, ou a composição pode encerrar."
                ],
            )
        return _pack(
            ["organize"],
            [],
            ["As posições desta rodada se esgotaram."],
        )

    if organized and not decision:
        return _pack(["decide"], [], ["A composição encerrou. Cabe a decisão."])
    if decision and not review:
        return _pack(["review"], [], ["A decisão precisa da auditoria automática."])
    return _pack(["hold"], [], ["Não há etapa pendente para o gestor."])


def _pack(actions: List[str], document_ids: List[str], reasons: List[str]) -> Dict[str, Any]:
    return {
        "actions": actions,
        "document_ids": document_ids,
        "reasons": reasons,
    }


def deterministic_decision(case_data: Dict[str, Any]) -> Dict[str, Any]:
    legal = legal_actions(case_data)
    action = legal["actions"][0]
    waiting = legal["reasons"] if action == "wait" else []
    return {
        "action": action,
        "document_ids": list(legal["document_ids"]),
        "reason": legal["reasons"][0],
        "waiting_on": waiting,
        "allowed_actions": list(legal["actions"]),
    }


def steward_context(case_data: Dict[str, Any]) -> Dict[str, Any]:
    legal = legal_actions(case_data)
    round_data = _latest_round(case_data)
    return {
        "case_id": case_data.get("id"),
        "status": case_data.get("status"),
        "allowed_actions": legal["actions"],
        "admissible_document_ids": legal["document_ids"],
        "consent_complete": bool((case_data.get("consent") or {}).get("complete")),
        "submission_complete": _submission_complete(case_data),
        "contradictory_complete": bool(
            (case_data.get("contradictory") or {}).get("complete")
        ),
        "manifest_locked": bool(case_data.get("manifest_locked")),
        "latest_round": {
            "round_number": round_data.get("round_number"),
            "continue_recommended": round_data.get("continue_recommended"),
            "stop_reason": round_data.get("stop_reason"),
            "both_answered": _both_answered(round_data) if round_data else False,
            "both_waived": _both_waived(round_data) if round_data else False,
            "has_new_material": _has_new_material(round_data) if round_data else False,
        },
        "waiting_on": _waiting_parties(case_data),
    }


def decide_steward_action(case_data: Dict[str, Any]) -> Dict[str, Any]:
    deterministic = deterministic_decision(case_data)
    context = steward_context(case_data)
    chosen = choose_action(context, deterministic)
    if chosen.get("action") not in context["allowed_actions"]:
        chosen = deterministic
    chosen["allowed_actions"] = list(context["allowed_actions"])
    return chosen
