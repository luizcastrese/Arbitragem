"""Conferência das citações da IA e montagem das entradas do cálculo.

O modelo devolve dados com documento, página e trecho. Aqui o servidor confere,
sem modelo, se o trecho está mesmo no documento e em qual página, e marca
``verified``. Dado sem citação confirmada continua visível, mas sinalizado:
quem decide se vale é a parte, que pode corrigi-lo antes do cálculo.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

_PAGE_MARK = re.compile(r"---\s*Page\s+(\d+)\s*---", re.IGNORECASE)

# Teto do texto enviado ao extrator: por documento e no total.
MAX_DOC_CHARS = 40_000
MAX_TOTAL_CHARS = 150_000


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _page_at(collapsed_content: str, position: int) -> Optional[int]:
    page = None
    for match in _PAGE_MARK.finditer(collapsed_content):
        if match.start() > position:
            break
        page = int(match.group(1))
    return page


def locate_quote(content: str, quote: str) -> Tuple[bool, Optional[int]]:
    """(achou, página). Compara sem diferenciar espaços e caixa."""
    needle = _collapse(quote).casefold()
    if len(needle) < 3:
        return False, None
    collapsed = _collapse(content)
    index = collapsed.casefold().find(needle)
    if index < 0:
        return False, None
    return True, _page_at(collapsed, index)


def verify_citation(citation: Optional[Dict[str, Any]], documents: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not citation:
        return None
    document = next((item for item in documents if item["id"] == citation.get("document_id")), None)
    result = {
        "document_id": citation.get("document_id") or "",
        "document_name": document["name"] if document else "",
        "page": citation.get("page") if isinstance(citation.get("page"), int) else None,
        "quote": (citation.get("quote") or "")[:400],
        "verified": False,
    }
    if not document:
        return result
    found, page = locate_quote(document.get("content") or "", citation.get("quote") or "")
    result["verified"] = found
    if found:
        # A página que vale é a do texto, não a que o modelo disse.
        result["page"] = page
    return result


def verify_extraction(extraction: Dict[str, Any], documents: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Devolve a extração com todas as citações conferidas contra os documentos."""
    verified = dict(extraction)
    for key in ("principal", "installments", "contract_rate_monthly", "contract_rate_annual", "paid_installments"):
        item = dict(extraction.get(key) or {"value": None, "citation": None})
        item["citation"] = verify_citation(item.get("citation"), documents)
        verified[key] = item
    fees = []
    for fee in extraction.get("fees") or []:
        fee = dict(fee)
        fee["citation"] = verify_citation(fee.get("citation"), documents)
        fees.append(fee)
    verified["fees"] = fees
    return verified


def inputs_from_extraction(extraction: Dict[str, Any]) -> Dict[str, Any]:
    """Entradas editáveis do cálculo, a partir da extração. Tudo com origem IA."""
    def value(key: str):
        return (extraction.get(key) or {}).get("value")

    citations = {
        "principal": (extraction.get("principal") or {}).get("citation"),
        "installments": (extraction.get("installments") or {}).get("citation"),
        "contract_rate": (
            (extraction.get("contract_rate_monthly") or {}).get("citation")
            or (extraction.get("contract_rate_annual") or {}).get("citation")
        ),
        "paid_installments": (extraction.get("paid_installments") or {}).get("citation"),
    }
    return {
        "principal": value("principal"),
        "installments": value("installments"),
        "contract_rate_monthly": value("contract_rate_monthly"),
        "contract_rate_annual": value("contract_rate_annual"),
        "paid_installments": value("paid_installments"),
        # A taxa média BACEN nunca vem da IA: as partes informam, com a fonte.
        "average_rate_monthly": None,
        "average_rate_source": {"name": "", "series": "", "reference_date": "", "url": ""},
        "interest_adjustment_applies": True,
        "fees": [
            {
                "name": fee.get("name"),
                "amount": fee.get("amount"),
                "questionable": bool(fee.get("questionable")),
                "reason": fee.get("reason"),
                "category": fee.get("category"),
                "citation": fee.get("citation"),
            }
            for fee in extraction.get("fees") or []
        ],
        "origins": {
            key: "ia"
            for key in ("principal", "installments", "contract_rate", "paid_installments", "fees")
        },
        "citations": citations,
    }


def build_extraction_context(
    case_data: Dict[str, Any], framework_summary: Dict[str, Any]
) -> Dict[str, Any]:
    """Material admitido, truncado, mais o escopo da matéria."""
    documents: List[Dict[str, Any]] = []
    remaining = MAX_TOTAL_CHARS
    truncated = False
    for document in case_data["documents"]:
        if not document.get("admitted", True):
            continue
        content = document.get("content") or ""
        limit = min(MAX_DOC_CHARS, remaining)
        if len(content) > limit:
            truncated = True
        documents.append(
            {
                "id": document["id"],
                "name": document["name"],
                "submitted_by": document.get("submitted_by"),
                "material_type": document.get("material_type"),
                "content": content[:limit],
            }
        )
        remaining -= min(len(content), limit)
        if remaining <= 0:
            truncated = True
            break
    return {
        "parties": {"claimant": case_data["claimant"], "respondent": case_data["respondent"]},
        "scope": framework_summary,
        "documents": documents,
        "truncated": truncated,
    }


# --------------------------------------------------------------------------
# Estado do cálculo e correções das partes
# --------------------------------------------------------------------------

_SCALAR_FIELDS = (
    "principal",
    "installments",
    "contract_rate_monthly",
    "contract_rate_annual",
    "paid_installments",
    "average_rate_monthly",
)
_ORIGIN_OF = {
    "principal": "principal",
    "installments": "installments",
    "contract_rate_monthly": "contract_rate",
    "contract_rate_annual": "contract_rate",
    "paid_installments": "paid_installments",
}


def apply_party_edits(inputs: Dict[str, Any], edits: Dict[str, Any]) -> Dict[str, Any]:
    """Aplica as correções de uma parte. Campo corrigido passa a ter origem ``parte``
    e perde o selo da citação (a parte está afirmando, não o documento)."""
    merged = {**inputs, "origins": dict(inputs.get("origins") or {}), "citations": dict(inputs.get("citations") or {})}
    for field in _SCALAR_FIELDS:
        if field not in edits:
            continue
        merged[field] = edits[field]
        origin_key = _ORIGIN_OF.get(field)
        if origin_key:
            merged["origins"][origin_key] = "parte"
        # Informar uma taxa de um tipo substitui a do outro.
        if field == "contract_rate_monthly" and edits[field]:
            merged["contract_rate_annual"] = None
        if field == "contract_rate_annual" and edits[field]:
            merged["contract_rate_monthly"] = None
    if "average_rate_source" in edits and edits["average_rate_source"] is not None:
        merged["average_rate_source"] = dict(edits["average_rate_source"])
    if "interest_adjustment_applies" in edits and edits["interest_adjustment_applies"] is not None:
        merged["interest_adjustment_applies"] = bool(edits["interest_adjustment_applies"])
    if edits.get("fees") is not None:
        previous = {
            (str(item.get("name")), str(item.get("amount"))): item.get("citation")
            for item in inputs.get("fees") or []
        }
        merged["fees"] = [
            {
                "name": fee["name"],
                "amount": fee["amount"],
                "questionable": bool(fee.get("questionable", True)),
                "reason": fee.get("reason", ""),
                # Cobrança que a parte manteve como estava conserva a citação.
                "citation": previous.get((str(fee["name"]), str(fee["amount"]))),
            }
            for fee in edits["fees"]
        ]
        merged["origins"]["fees"] = "parte"
    return merged


def derive_state(
    extraction: Optional[Dict[str, Any]],
    inputs: Dict[str, Any],
) -> Dict[str, Any]:
    """Status e memória de cálculo a partir da extração e das entradas atuais."""
    from app.domain.calculation import CalculationError, build_calculation

    assessment = {
        "in_scope": (extraction or {}).get("in_scope", True),
        "abstention_reason": (extraction or {}).get("abstention_reason"),
        "questionable_charges": [
            {"name": fee.get("name"), "reason": fee.get("reason")}
            for fee in inputs.get("fees") or []
            if fee.get("questionable")
        ],
        "missing_information": list((extraction or {}).get("missing_information") or []),
    }
    if not assessment["in_scope"]:
        return {"status": "abstained", "assessment": assessment, "calculation": None, "error": None}
    try:
        calculation = build_calculation(inputs)
    except CalculationError as exc:
        return {"status": "needs_inputs", "assessment": assessment, "calculation": None, "error": str(exc)}
    return {"status": "ready", "assessment": assessment, "calculation": calculation, "error": None}
