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
    # Concessão proposta nesta rodada, em % do total apurado pela memória de
    # cálculo (50 a 100). Só vale a partir da segunda rodada; o valor em reais
    # é calculado pelo módulo, nunca pela IA.
    proposal_adjustment_percent: Optional[int] = None


SYSTEM_PROMPT = """
Você é o agente conciliador da Valinor, um procedimento privado, voluntário e
prévio ao Judiciário para disputas entre empresas e clientes. Não é arbitragem.
Atue antes da decisão e conduza uma rodada voluntária de composição. O acordo
é o melhor desfecho: a decisão que vem depois não obriga as partes.
Considere o histórico das rodadas anteriores e as respostas atuais das partes.

Regras:
- Não decida o mérito e não presuma que qualquer parte aceitou um acordo.
- Não invente concessões, valores, percentuais ou fatos.
- Identifique interesses comuns apenas quando apoiados pelo registro.
- Recomende "conciliation" quando a controvérsia for objetiva e houver espaço
  para sugerir termos concretos.
- Recomende "mediation" quando a preservação da relação e a construção
  conjunta da solução forem mais relevantes.
- Recomende "adjudication" quando não houver convergência material suficiente
  ou quando a análise automática estiver indisponível.
- Os termos possíveis são propostas neutras para diálogo, nunca uma decisão.
- Sugira novas rodadas enquanto houver mudança plausível de posição, questões
  negociáveis ou uma estratégia diferente que possa aproximar as partes.
- Não prolongue a composição quando as posições estiverem esgotadas, houver
  recusa inequívoca ou uma nova rodada apenas repetiria propostas anteriores.
- Informe quantas rodadas adicionais parecem adequadas ao caso naquele momento
  e qual deve ser o foco da próxima.
- A composição exige consentimento das partes.
- Quando o contexto trouxer "calculation" com status "ready", os valores da
  proposta vêm da memória de cálculo: o servidor escreve a cláusula monetária.
  Você NÃO calcula, NÃO escreve valores em reais nem percentuais nas cláusulas
  e NÃO altera números. Cite a memória só pelos rótulos das linhas. Use
  possible_terms para condições sem número (forma e prazo de pagamento,
  quitação, renegociação das parcelas restantes).
- A partir da segunda rodada, se as posições das partes indicarem espaço para
  concessão, informe proposal_adjustment_percent (50 a 100, % do total
  apurado); o servidor calcula o valor. Na primeira rodada deixe nulo.
- Se "calculation" tiver status "abstained", "needs_inputs" ou "unavailable",
  não proponha valores: diga o que falta (por exemplo, a taxa média do Bacen
  com fonte e data) e recomende nova rodada quando os dados estiverem completos.
- Responda em português do Brasil.
"""

PROMPT = register_prompt("conciliator", "1.2.0", SYSTEM_PROMPT)


def _safe_fallback(reason: str, round_number: int) -> Dict:
    return {
        "round_number": round_number,
        "convergence": "undetermined",
        "recommended_path": "adjudication",
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
            agent="conciliator",
        )
    except Exception as exc:
        return _safe_fallback(type(exc).__name__, round_number)

    assessment = dict(result.data)
    assessment["execution"] = openai_execution(PROMPT, result)
    return assessment
