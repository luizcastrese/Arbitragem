"""Auto da decisão: o documento final do procedimento.

A Valinor profere uma decisão, mas não tem como obrigar ninguém a cumpri-la.
O que sai do procedimento é este auto: um registro autocontido, assinado e
verificável do que foi decidido (ou acordado, ou por que não houve decisão de
mérito), com a qualificação das partes, o percurso do contraditório, as
tentativas de composição, a fundamentação com as provas citadas e o
dispositivo. É o documento que a parte leva a um advogado, ao Procon ou ao
Judiciário.

Desfechos possíveis (`outcome.kind`):

- ``agreement``: as duas partes aceitaram a mesma proposta de composição;
- ``decision``: houve decisão de mérito, auditada e aprovada;
- ``no_merit_decision``: o procedimento terminou sem decisão de mérito
  (inconclusivo, inadmissível, invalidado ou falha do sistema), e o auto diz
  por quê.

Cada auto tem ``record_hash`` (SHA-256 do conteúdo canônico) e assinatura:
Ed25519 quando a chave da plataforma está configurada — verificável por
qualquer terceiro com a chave pública — e HMAC-SHA256 caso contrário, que só a
própria plataforma confere.
"""

from __future__ import annotations

import base64
import hmac
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.core.attestation import load_private_key, match_signing_key, public_key_info
from app.core.canonical import canonical_hash, canonical_json
from app.core.config import get_settings
from app.core.signing import sign_payload
from app.core.tax_id import describe_tax_id

RECORD_VERSION = "1.0"
RECORD_TYPE = "auto_da_decisao"
PARTIES = ("claimant", "respondent")
PARTY_LABELS = {"claimant": "Cliente reclamante", "respondent": "Empresa reclamada"}

LEGAL_NOTICE = (
    "Este auto registra a decisão proferida no procedimento Valinor, um "
    "procedimento privado, voluntário e prévio ao Judiciário. A decisão não "
    "constitui sentença judicial nem sentença arbitral e não obriga as partes "
    "a cumpri-la. Nenhuma parte renuncia a direitos: qualquer delas pode "
    "recorrer ao Poder Judiciário, aos órgãos de defesa do consumidor ou a "
    "outros meios. O auto pode ser apresentado como prova documental do "
    "procedimento — do material trocado, das tentativas de acordo e da "
    "fundamentação — cabendo ao juízo competente avaliá-lo livremente. Hashes "
    "e assinaturas comprovam integridade e origem do registro, não a verdade "
    "material das alegações."
)

OUTCOME_LABELS = {
    "claimant": "Procedente em favor do cliente reclamante",
    "respondent": "Improcedente: prevalece a posição da empresa reclamada",
    "partial": "Parcialmente procedente",
    "inconclusive": "Sem decisão de mérito",
}

CONCLUSION_LABELS = {
    "agreement": "Acordo entre as partes",
    "decided": "Decisão de mérito proferida",
    "inconclusive": "Inconclusivo: não houve condições seguras para decidir o mérito",
    "inadmissible": "Inadmissível: a matéria está fora do escopo do procedimento",
    "invalidated": "Invalidado: a decisão não passou nas verificações de integridade",
    "system_failure": "Falha do sistema: a etapa decisória não pôde ser concluída",
}

ABSTENTION_LABELS = {
    "insufficient_evidence": "provas insuficientes",
    "contradictory_material_evidence": "provas materiais contraditórias",
    "missing_mandatory_document": "falta de documento obrigatório",
    "unsupported_calculation": "cálculo sem lastro documental",
    "material_model_disagreement": "divergência material entre modelos",
    "framework_not_applicable": "regras do procedimento não aplicáveis",
    "technical_expertise_required": "necessidade de perícia técnica",
    "procedure_integrity_failure": "falha de integridade do procedimento",
    "prompt_injection_detected": "tentativa de manipulação detectada no material",
    "provider_unavailable": "provedor de IA indisponível",
    "out_of_scope": "matéria fora do escopo",
    "unsupported_claim": "pedido sem sustentação",
    "unstable_decision": "decisão instável entre execuções",
    "system_failure": "falha do sistema",
}

_SIGNATURE_FIELDS = ("signature", "signature_algorithm", "key_id")


class DecisionRecordNotReady(RuntimeError):
    """O procedimento ainda não chegou a um desfecho que gere auto."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _agreement(case_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for round_data in case_data.get("conciliation_rounds") or []:
        agreement = round_data.get("agreement") or {}
        if agreement.get("complete"):
            responses = agreement.get("responses") or {}
            return {
                "round_number": round_data.get("round_number"),
                "terms": list(round_data.get("possible_terms") or []),
                "proposal_sha256": agreement.get("proposal_sha256"),
                "accepted_at": {
                    party: (responses.get(party) or {}).get("recorded_at")
                    for party in PARTIES
                },
            }
    return None


def outcome_kind(case_data: Dict[str, Any]) -> Optional[str]:
    """Tipo de desfecho, ou None se o procedimento ainda não terminou."""
    status = str(case_data.get("status") or "")
    if status.startswith("processing"):
        return None
    conclusion = case_data.get("procedure_conclusion") or ""
    if status == "agreement" or conclusion == "agreement":
        return "agreement" if _agreement(case_data) else None
    if not case_data.get("review"):
        return None
    if (case_data.get("contest") or {}).get("contested"):
        appeals = case_data.get("appeals") or []
        if appeals and (appeals[-1].get("status") or "") == "processing":
            return None
    decision = case_data.get("decision") or {}
    effective = conclusion or decision.get("procedure_conclusion") or ""
    if effective == "decided" and decision.get("outcome") != "inconclusive":
        return "decision"
    return "no_merit_decision"


def _party(case_data: Dict[str, Any], party: str) -> Dict[str, Any]:
    consent = (case_data.get("consent") or {}).get(party) or {}
    tax_id = consent.get("tax_id")
    return {
        "role": party,
        "role_label": PARTY_LABELS[party],
        "name": case_data.get(party) or "",
        "tax_id": describe_tax_id(tax_id),
        "qualified": bool(tax_id),
        "consent": {
            "accepted_at": consent.get("accepted_at"),
            "terms_version": consent.get("terms_version"),
            "terms_sha256": consent.get("terms_sha256"),
        },
    }


def _documents(case_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {
            "id": item.get("id"),
            "name": item.get("name"),
            "sha256": item.get("sha256"),
            "submitted_by": item.get("submitted_by"),
            "material_type": item.get("material_type"),
            "purpose": item.get("purpose"),
            "disclosed_at": item.get("disclosed_at"),
            "acknowledged_at": item.get("acknowledged_at"),
            "response_status": item.get("response_status"),
            "response_text": item.get("response_text"),
            "admitted": bool(item.get("admitted")),
            "admitted_at": item.get("admitted_at"),
        }
        for item in case_data.get("documents") or []
    ]


def _rounds(case_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    result = []
    for round_data in case_data.get("conciliation_rounds") or []:
        positions = round_data.get("party_positions") or {}
        agreement = round_data.get("agreement") or {}
        responses = agreement.get("responses") or {}
        result.append(
            {
                "round_number": round_data.get("round_number"),
                "neutral_summary": round_data.get("neutral_summary"),
                "possible_terms": list(round_data.get("possible_terms") or []),
                "positions": {
                    party: {
                        "text": (positions.get(party) or {}).get("text"),
                        "waived": (positions.get(party) or {}).get("waived"),
                    }
                    for party in PARTIES
                    if party in positions
                },
                "proposal_responses": {
                    party: (responses.get(party) or {}).get("accepted")
                    for party in PARTIES
                    if party in responses
                },
                "agreement_reached": bool(agreement.get("complete")),
            }
        )
    return result


def _evidence(refs: List[Dict[str, Any]], names: Dict[str, str]) -> List[Dict[str, Any]]:
    return [
        {
            "document_id": ref.get("document_id"),
            "document_name": names.get(ref.get("document_id") or "", ""),
            "document_sha256": ref.get("document_sha256"),
            "chunk_id": ref.get("chunk_id"),
            "quoted_text": ref.get("quoted_text"),
            "support_type": ref.get("support_type"),
            "page_number": ref.get("page_number"),
        }
        for ref in refs or []
        if isinstance(ref, dict)
    ]


def _decision_section(case_data: Dict[str, Any], kind: str) -> Optional[Dict[str, Any]]:
    decision = case_data.get("decision") or {}
    if not decision or kind == "agreement":
        return None
    names = {item.get("id"): item.get("name") for item in case_data.get("documents") or []}
    outcome = decision.get("outcome")
    remedy = decision.get("remedy_calculation")
    return {
        "outcome": outcome,
        "outcome_label": OUTCOME_LABELS.get(outcome or "", outcome),
        "partial_claimant_bps": decision.get("partial_claimant_bps"),
        "operative_text": decision.get("decision"),
        "framework_id": decision.get("framework_id"),
        "framework_version": decision.get("framework_version"),
        "material_findings": [
            {
                "finding_id": item.get("finding_id"),
                "proposition": item.get("proposition"),
                "status": item.get("status"),
                "reasoning": item.get("reasoning"),
                "evidence": _evidence(item.get("evidence"), names),
                "counterevidence": _evidence(item.get("counterevidence"), names),
            }
            for item in decision.get("material_findings") or []
            if isinstance(item, dict)
        ],
        "rule_applications": [
            {
                "rule_id": item.get("rule_id"),
                "rule_version": item.get("rule_version"),
                "application_reasoning": item.get("application_reasoning"),
                "conclusion": item.get("conclusion"),
            }
            for item in decision.get("rule_applications") or []
            if isinstance(item, dict)
        ],
        "remedy_calculation": (
            {
                "formula": remedy.get("formula"),
                "result_minor_units": remedy.get("result_minor_units"),
                "currency": remedy.get("currency"),
                "inputs": [
                    {
                        "name": item.get("name"),
                        "value_minor_units": item.get("value_minor_units"),
                        "currency": item.get("currency"),
                    }
                    for item in remedy.get("inputs") or []
                    if isinstance(item, dict)
                ],
            }
            if isinstance(remedy, dict)
            else None
        ),
        "limitations": list(decision.get("limitations") or []),
        "abstention_reasons": [
            {"code": code, "label": ABSTENTION_LABELS.get(code, code)}
            for code in decision.get("abstention_reasons") or []
        ],
        "decision_hash": canonical_hash(decision),
        "model": (decision.get("execution") or {}).get("model"),
    }


def _review_section(case_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    review = case_data.get("review") or {}
    if not review:
        return None
    verification = case_data.get("verification") or {}
    approved = review.get("approved")
    if approved is None:
        approved = review.get("outcome") == "approved"
    return {
        "approved": bool(approved),
        "outcome": review.get("outcome"),
        "issues": [
            item.get("message")
            for item in review.get("issues") or []
            if isinstance(item, dict) and item.get("message")
        ],
        "verification_valid": (
            None if not verification else bool(verification.get("valid"))
        ),
        "review_hash": canonical_hash(review),
        "model": (review.get("execution") or {}).get("model"),
    }


def _appeal_section(case_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    appeals = case_data.get("appeals") or []
    attestation = case_data.get("attestation") or {}
    if not appeals and not attestation:
        return None
    latest = appeals[-1] if appeals else {}
    result = latest.get("result") or {}
    return {
        "window_ends_utc": attestation.get("contest_window_ends_utc"),
        "filed": bool(appeals),
        "filed_by": latest.get("filed_by"),
        "grounds": latest.get("grounds") or [],
        "outcome": result.get("outcome"),
        "explanation": result.get("explanation"),
        "result_hash": latest.get("result_hash"),
    }


def _summary(kind: str, case_data: Dict[str, Any], agreement: Optional[Dict[str, Any]]) -> str:
    claimant = case_data.get("claimant") or "o cliente reclamante"
    respondent = case_data.get("respondent") or "a empresa reclamada"
    if kind == "agreement" and agreement:
        return (
            f"{claimant} e {respondent} aceitaram, de forma independente, a proposta "
            f"de composição da rodada {agreement.get('round_number')}. O procedimento "
            "encerrou por acordo."
        )
    decision = case_data.get("decision") or {}
    if kind == "decision":
        outcome = OUTCOME_LABELS.get(decision.get("outcome") or "", "")
        text = f"Sem acordo entre as partes, a Valinor proferiu decisão: {outcome}."
        if decision.get("outcome") == "partial" and decision.get("partial_claimant_bps") is not None:
            percent = int(decision["partial_claimant_bps"]) / 100
            text += f" Proporção reconhecida ao cliente reclamante: {percent:.2f}%."
        remedy = decision.get("remedy_calculation") or {}
        if isinstance(remedy, dict) and remedy.get("result_minor_units") is not None:
            text += (
                f" Valor apurado: {format_money(remedy['result_minor_units'], remedy.get('currency'))}."
            )
        return text
    conclusion = case_data.get("procedure_conclusion") or decision.get("procedure_conclusion") or "inconclusive"
    reasons = [
        ABSTENTION_LABELS.get(code, code) for code in decision.get("abstention_reasons") or []
    ]
    text = (
        "Sem acordo entre as partes, o procedimento terminou sem decisão de mérito: "
        f"{CONCLUSION_LABELS.get(conclusion, conclusion)}."
    )
    if reasons:
        text += f" Motivos: {', '.join(reasons)}."
    return text


def format_money(minor_units: Any, currency: Optional[str]) -> str:
    try:
        value = int(minor_units)
    except (TypeError, ValueError):
        return str(minor_units)
    sign = "-" if value < 0 else ""
    whole, cents = divmod(abs(value), 100)
    whole_text = f"{whole:,}".replace(",", ".")
    prefix = "R$ " if (currency or "BRL").upper() == "BRL" else f"{(currency or '').upper()} "
    return f"{sign}{prefix}{whole_text},{cents:02d}"


def record_basis(case_data: Dict[str, Any]) -> Dict[str, Any]:
    """O que, se mudar, exige um novo auto. Datas de leitura não entram."""
    appeals = case_data.get("appeals") or []
    latest = appeals[-1] if appeals else {}
    consent = case_data.get("consent") or {}
    return {
        "kind": outcome_kind(case_data),
        "procedure_conclusion": case_data.get("procedure_conclusion"),
        "decision_hash": canonical_hash(case_data.get("decision") or {}),
        "review_hash": canonical_hash(case_data.get("review") or {}),
        "agreement": _agreement(case_data),
        "attestation_hash": (case_data.get("attestation") or {}).get("attestation_hash"),
        "appeal": {
            "id": latest.get("id"),
            "status": latest.get("status"),
            "result_hash": latest.get("result_hash"),
        },
        "tax_ids": {party: (consent.get(party) or {}).get("tax_id") for party in PARTIES},
    }


def build_decision_record(
    case_data: Dict[str, Any],
    audit_chain_head: str,
    audit_chain_length: int,
    previous: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    kind = outcome_kind(case_data)
    if kind is None:
        raise DecisionRecordNotReady(
            "O procedimento ainda não terminou: o auto só é emitido depois do "
            "acordo ou da auditoria da decisão"
        )
    manifest = case_data.get("locked_manifest") or {}
    agreement = _agreement(case_data) if kind == "agreement" else None
    organized = case_data.get("organized") or {}
    decision = case_data.get("decision") or {}
    conclusion = (
        "agreement"
        if kind == "agreement"
        else case_data.get("procedure_conclusion")
        or decision.get("procedure_conclusion")
        or ("decided" if kind == "decision" else "inconclusive")
    )
    body: Dict[str, Any] = {
        "record_version": RECORD_VERSION,
        "record_type": RECORD_TYPE,
        "record_number": int((previous or {}).get("record_number") or 0) + 1,
        "supersedes_record_hash": (previous or {}).get("record_hash"),
        "case_id": case_data.get("id"),
        "case_title": case_data.get("title"),
        "issued_at_utc": _now().isoformat(),
        "parties": {party: _party(case_data, party) for party in PARTIES},
        "object": {
            "summary": organized.get("summary") or organized.get("factual_overview"),
            "claimant_requests": list(organized.get("claimant_requests") or []),
            "respondent_arguments": list(organized.get("respondent_arguments") or []),
            "undisputed_facts": list(organized.get("undisputed_facts") or []),
            "disputed_facts": list(organized.get("disputed_facts") or []),
        },
        "procedure": {
            "created_at": case_data.get("created_at"),
            "framework_id": manifest.get("framework_id") or decision.get("framework_id"),
            "documents": _documents(case_data),
            "conciliation_rounds": _rounds(case_data),
        },
        "outcome": {
            "kind": kind,
            "procedure_conclusion": conclusion,
            "conclusion_label": CONCLUSION_LABELS.get(conclusion, conclusion),
            "summary": _summary(kind, case_data, agreement),
            "binding": False,
        },
        "agreement": agreement,
        "decision": _decision_section(case_data, kind),
        "review": _review_section(case_data) if kind != "agreement" else None,
        "appeal": _appeal_section(case_data) if kind != "agreement" else None,
        "integrity": {
            "manifest_hash": manifest.get("manifest_hash"),
            "manifest_signature": manifest.get("platform_signature"),
            "audit_chain_head": audit_chain_head,
            "audit_chain_length": audit_chain_length,
            "attestation_hash": (case_data.get("attestation") or {}).get("attestation_hash"),
            "basis_hash": canonical_hash(record_basis(case_data)),
        },
        "legal_notice": LEGAL_NOTICE,
        "platform": {
            "name": "Valinor",
            "platform_version": manifest.get("platform_version"),
            "procedure_version": manifest.get("procedure_version"),
        },
    }
    return sign_record(body)


def sign_record(body: Dict[str, Any]) -> Dict[str, Any]:
    unsigned = {key: value for key, value in body.items() if key not in _SIGNATURE_FIELDS}
    unsigned.pop("record_hash", None)
    unsigned["record_hash"] = canonical_hash(unsigned)
    message = canonical_json(unsigned).encode("utf-8")
    if get_settings().attestation_enabled:
        key = load_private_key()
        return {
            **unsigned,
            "signature": base64.b64encode(key.sign(message)).decode("ascii"),
            "signature_algorithm": "Ed25519",
            "key_id": public_key_info(key)["key_id"],
        }
    return {
        **unsigned,
        "signature": sign_payload(unsigned),
        "signature_algorithm": "HMAC-SHA256",
        "key_id": None,
    }


def verify_record(
    record: Dict[str, Any], public_key_b64: Optional[str] = None
) -> Tuple[bool, Dict[str, Any]]:
    """Confere o hash interno e a assinatura do auto."""
    unsigned = {key: value for key, value in record.items() if key not in _SIGNATURE_FIELDS}
    declared = unsigned.pop("record_hash", None)
    hash_valid = bool(declared) and declared == canonical_hash(unsigned)
    signed_body = {**unsigned, "record_hash": declared}
    algorithm = record.get("signature_algorithm")
    signature = record.get("signature") or ""
    checks: Dict[str, Any] = {
        "hash_valid": hash_valid,
        "signature_valid": False,
        "signature_algorithm": algorithm,
        "key_id": None,
        "key_status": None,
    }
    if algorithm == "Ed25519":
        matched = match_signing_key(signed_body, str(signature), public_key_b64)
        if matched:
            checks.update(
                signature_valid=True,
                key_id=matched["key_id"],
                key_status=matched["status"],
            )
    elif algorithm == "HMAC-SHA256":
        try:
            expected = sign_payload(signed_body)
        except Exception:  # noqa: BLE001
            expected = ""
        checks["signature_valid"] = bool(expected) and hmac.compare_digest(
            str(signature), expected
        )
    return hash_valid and checks["signature_valid"], checks

