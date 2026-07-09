from typing import Dict, List

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.llm import call_openai_structured


class ReviewOutput(BaseModel):
    approved: bool
    issues: List[str]
    risks: List[str]
    contradictions: List[str]
    missing_evidence: List[str]
    framework_alignment: str
    confidence_assessment: float = Field(ge=0, le=1)
    requires_human_review: bool


SYSTEM_PROMPT = """
Você é o agente auditor de um sistema de auditoria decisória por IA.
Não produza uma nova decisão. Audite de forma independente a decisão proferida
pelo agente julgador.

Verifique:
- afirmações sem apoio documental;
- evidências ignoradas ou contraditórias;
- violações do framework travado;
- inconsistências lógicas;
- confiança injustificada;
- necessidade de revisão humana.

Uma decisão inconclusiva ou produzida em modo fallback não pode ser aprovada
como decisão final do sistema. Responda em português do Brasil.
"""


def _safe_fallback(review_payload: Dict, reason: str) -> Dict:
    decision = review_payload.get("decision") or {}
    return {
        "approved": False,
        "issues": ["A auditoria independente por IA não foi executada."],
        "risks": ["A decisão não foi validada como resultado final do sistema."],
        "contradictions": [],
        "missing_evidence": decision.get("limitations", []),
        "framework_alignment": "não verificado",
        "confidence_assessment": 0.0,
        "requires_human_review": True,
        "execution": {
            "mode": "safe_fallback",
            "model": None,
            "reason": reason,
        },
    }


def review_decision(review_payload: Dict) -> Dict:
    try:
        result = call_openai_structured(
            system_prompt=SYSTEM_PROMPT,
            user_payload=review_payload,
            response_model=ReviewOutput,
        )
    except Exception as exc:
        return _safe_fallback(review_payload, type(exc).__name__)

    result["execution"] = {
        "mode": "openai",
        "model": get_settings().openai_model,
        "reason": None,
    }
    return result
