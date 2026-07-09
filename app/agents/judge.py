from typing import Dict, List, Literal

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.llm import call_openai_structured


class DecisionOutput(BaseModel):
    framework: str
    outcome: Literal["claimant", "respondent", "partial", "inconclusive"]
    decision: str
    reasoning: List[str]
    evidence_cited: List[str]
    principles_applied: List[str]
    confidence: float = Field(ge=0, le=1)
    limitations: List[str]
    requires_human_review: bool


SYSTEM_PROMPT = """
Você é o agente julgador de um sistema de auditoria decisória por IA.
Sua função é proferir a decisão computacional do caso aplicando exclusivamente
o framework Comercial Equilibrado e o manifesto previamente fixado.

Regras obrigatórias:
- Não invente fatos, valores, percentuais, cláusulas ou provas.
- Toda conclusão material deve citar evidência recuperada.
- Se a evidência for insuficiente ou contraditória, use outcome "inconclusive".
- Quando o outcome não for "inconclusive", apresente uma decisão clara sobre
  o pedido e seus fundamentos, sem tratá-la como mera recomendação.
- Não chame o resultado de sentença judicial ou sentença arbitral com eficácia
  jurídica automática. Ele é uma decisão computacional do procedimento.
- Marque requires_human_review como true diante de baixa confiança, lacunas
  materiais ou impossibilidade de aplicar o framework com segurança.
- Responda em português do Brasil.
"""


def _safe_fallback(reason: str) -> Dict:
    return {
        "framework": "Comercial Equilibrado",
        "outcome": "inconclusive",
        "decision": (
            "A IA não pôde proferir uma decisão de mérito com segurança. "
            "O caso permaneceu inconclusivo por indisponibilidade da etapa decisória."
        ),
        "reasoning": [
            "O agente julgador não concluiu a etapa decisória."
        ],
        "evidence_cited": [],
        "principles_applied": [],
        "confidence": 0.0,
        "limitations": [
            "Nenhuma decisão financeira automática foi produzida.",
            f"Motivo técnico: {reason}.",
        ],
        "requires_human_review": True,
        "execution": {
            "mode": "safe_fallback",
            "model": None,
            "reason": reason,
        },
    }


def decide_case(decision_context: Dict) -> Dict:
    try:
        result = call_openai_structured(
            system_prompt=SYSTEM_PROMPT,
            user_payload=decision_context,
            response_model=DecisionOutput,
        )
    except Exception as exc:
        return _safe_fallback(type(exc).__name__)

    result["execution"] = {
        "mode": "openai",
        "model": get_settings().openai_model,
        "reason": None,
    }
    return result
