from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.agents.execution import fallback_execution, openai_execution
from app.core.llm import call_openai_structured
from app.core.prompt_registry import register_prompt


class ConciliationOutput(BaseModel):
    round_number: int = Field(ge=1)
    convergence: Literal["detected", "not_detected", "undetermined"]
    recommended_path: Literal[
        "conciliation",
        "mediation",
        "adjudication",
        "human_screening",
    ]
    neutral_summary: str
    common_interests: List[str]
    negotiable_issues: List[str]
    non_negotiable_issues: List[str]
    possible_terms: List[str]
    reasoning: List[str]
    confidence: float = Field(ge=0, le=1)
    continue_recommended: bool
    recommended_additional_rounds: int = Field(ge=0)
    next_round_focus: str
    stop_reason: Optional[str]
    requires_party_consent: bool


SYSTEM_PROMPT = """
Você é o agente conciliador de um sistema de arbitragem por IA.
Atue antes do julgamento e conduza uma rodada voluntária de composição.
Considere o histórico das rodadas anteriores e as respostas atuais das partes.

Regras:
- Não decida o mérito e não presuma que qualquer parte aceitou um acordo.
- Não invente concessões, valores, percentuais ou fatos.
- Identifique interesses comuns apenas quando apoiados pelo registro.
- Recomende "conciliation" quando a controvérsia for objetiva e houver espaço
  para sugerir termos concretos.
- Recomende "mediation" quando a preservação da relação e a construção
  conjunta da solução forem mais relevantes.
- Recomende "adjudication" quando não houver convergência material suficiente.
- Os termos possíveis são propostas neutras para diálogo, nunca uma decisão.
- Sugira novas rodadas enquanto houver mudança plausível de posição, questões
  negociáveis ou uma estratégia diferente que possa aproximar as partes.
- Não prolongue a composição quando as posições estiverem esgotadas, houver
  recusa inequívoca ou uma nova rodada apenas repetiria propostas anteriores.
- Informe quantas rodadas adicionais parecem adequadas ao caso naquele momento
  e qual deve ser o foco da próxima.
- A composição exige consentimento das partes.
- Responda em português do Brasil.
"""

PROMPT = register_prompt("conciliator", "1.0.0", SYSTEM_PROMPT)


def _safe_fallback(reason: str, round_number: int) -> Dict:
    return {
        "round_number": round_number,
        "convergence": "undetermined",
        "recommended_path": "human_screening",
        "neutral_summary": (
            "A triagem automática de convergência não pôde ser concluída."
        ),
        "common_interests": [],
        "negotiable_issues": [],
        "non_negotiable_issues": [],
        "possible_terms": [],
        "reasoning": [
            "Não houve análise por IA suficiente para recomendar conciliação ou mediação."
        ],
        "confidence": 0.0,
        "continue_recommended": False,
        "recommended_additional_rounds": 0,
        "next_round_focus": "",
        "stop_reason": "A análise por IA está indisponível.",
        "requires_party_consent": True,
        "execution": fallback_execution(PROMPT, reason),
    }


def assess_conciliation(context: Dict, round_number: int) -> Dict:
    try:
        result = call_openai_structured(
            system_prompt=PROMPT.text,
            user_payload=context,
            response_model=ConciliationOutput,
        )
    except Exception as exc:
        return _safe_fallback(type(exc).__name__, round_number)

    assessment = dict(result.data)
    assessment["execution"] = openai_execution(PROMPT, result)
    return assessment
