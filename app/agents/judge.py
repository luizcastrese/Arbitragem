from typing import Dict, List, Optional

from pydantic import Field

from app.agents.execution import fallback_execution, openai_execution
from app.core.llm import call_openai_structured
from app.core.prompt_registry import register_prompt
from app.domain.legacy import infer_procedure_conclusion
from app.domain.models import DecisionOutput


SYSTEM_PROMPT = """
Você é o agente julgador de um sistema autônomo de resolução privada de
disputas documentais B2B. Não há julgador humano interno. Quando não houver
condições seguras para uma decisão de mérito, abstenha-se.

Aplique exclusivamente o framework e o manifesto fixados. Não invente fatos,
valores, percentuais, cláusulas, IDs, hashes ou provas.

Regras obrigatórias:
- Toda conclusão material aponta para ao menos um MaterialFinding.
- Todo MaterialFinding com status "established" precisa de EvidenceReference
  válida (documento e chunk do manifesto, hashes corretos, trecho citado
  presente no chunk).
- Não aceite evidência só porque você a gerou: IDs, hashes e citações
  inventados são inválidos.
- Valores monetários usam minor units inteiros, moeda explícita, origem
  documental e fórmula determinística. Nunca use float para dinheiro.
- Toda RuleApplication referencia uma regra existente no framework fixado.
- Se a evidência for insuficiente, use outcome "inconclusive" e
  abstention_reasons contendo "insufficient_evidence".
- Se a matéria estiver fora do escopo, use outcome "inconclusive" e
  abstention_reasons contendo "out_of_scope" (o procedimento encerrará como
  inadmissible).
- Se houver violação de integridade, use "procedure_integrity_failure".
- Quando o outcome for "partial", preencha partial_claimant_bps (0–10000)
  lastreado nas evidências. Se a proporção não puder ser sustentada, abstenha-se.
- O sistema nunca é obrigado a declarar um vencedor.
- Não chame o resultado de sentença judicial ou arbitral. É uma decisão
  computacional do procedimento.
- Responda em português do Brasil.
"""

PROMPT = register_prompt("judge", "2.0.0", SYSTEM_PROMPT)


def _safe_fallback(reason: str, framework_id: str = "digital_services_b2b_v1") -> Dict:
    decision = {
        "framework_id": framework_id,
        "framework_version": "1.0.0",
        "framework": framework_id,
        "outcome": "inconclusive",
        "procedure_conclusion": "system_failure",
        "decision": (
            "A IA não pôde proferir uma decisão de mérito com segurança. "
            "O caso permaneceu inconclusivo por indisponibilidade da etapa decisória."
        ),
        "material_findings": [],
        "rule_applications": [],
        "remedy_calculation": None,
        "confidence": 0.0,
        "limitations": [
            "Nenhuma decisão financeira automática foi produzida.",
            f"Motivo técnico: {reason}.",
        ],
        "abstention_reasons": ["provider_unavailable"],
        "execution": fallback_execution(PROMPT, reason),
        "verification_summary": {},
    }
    decision["procedure_conclusion"] = infer_procedure_conclusion(decision)
    return decision


def decide_case(decision_context: Dict, agent: str = "judge") -> Dict:
    manifest = decision_context.get("manifest") or {}
    framework = manifest.get("framework") or {}
    framework_id = framework.get("id") or "digital_services_b2b_v1"
    try:
        result = call_openai_structured(
            system_prompt=PROMPT.text,
            user_payload=decision_context,
            response_model=DecisionOutput,
            agent=agent,
        )
    except Exception as exc:
        return _safe_fallback(type(exc).__name__, framework_id=framework_id)

    decision = dict(result.data)
    decision.setdefault("framework_id", framework_id)
    decision.setdefault("framework_version", framework.get("version") or "1.0.0")
    decision.setdefault("framework", framework.get("name") or framework_id)
    decision.setdefault("abstention_reasons", [])
    decision.setdefault("material_findings", [])
    decision.setdefault("rule_applications", [])
    decision.setdefault("limitations", [])
    decision["execution"] = openai_execution(PROMPT, result)
    if not decision.get("procedure_conclusion"):
        decision["procedure_conclusion"] = infer_procedure_conclusion(decision)
    return decision
