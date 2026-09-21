"""Gestor do procedimento.

Não é uma parte e não julga o mérito. Conduz o rito: admite material cujo
contraditório já se fechou, trava o conjunto quando as duas partes declararam
a apresentação encerrada, abre a composição e, esgotada ela, leva o caso à
organização, à decisão e à auditoria.

O código calcula o que é lícito. O modelo só escolhe quando o rito deixa mais
de um caminho. Sem chave, ou quando só há um caminho, vale a política
determinística — o gestor continua existindo, apenas sem margem de juízo.
"""

from typing import Dict, List, Literal

from pydantic import BaseModel, Field

from app.agents.execution import fallback_execution, openai_execution
from app.core.llm import call_openai_structured, llm_configured
from app.core.prompt_registry import register_prompt


class StewardOutput(BaseModel):
    action: Literal[
        "admit",
        "lock",
        "conciliate",
        "organize",
        "decide",
        "review",
        "wait",
        "hold",
    ]
    document_ids: List[str] = Field(default_factory=list)
    reason: str
    waiting_on: List[str] = Field(default_factory=list)


SYSTEM_PROMPT = """
Você é o gestor do procedimento Valinor. Você é uma IA. Não é o cliente, não
é a empresa e não fala por nenhuma das partes.

Você recebe o estado do caso e a lista de ações lícitas. Escolha exatamente
uma ação dessa lista.

Regras:
- Não decida o mérito, não sugira quem tem razão e não invente fatos.
- Não aceite acordo, não apresente documento e não confirme ciência no lugar
  de uma parte.
- "admit" só para os document_ids que já passaram por ciência e resposta.
- "lock" só quando as duas partes declararam encerrada a própria apresentação
  e o contraditório está completo.
- "conciliate" abre ou continua uma rodada de composição.
- "organize" encerra a composição e prepara o julgamento.
- "decide" e "review" são as etapas seguintes, nunca um atalho.
- "wait" quando a próxima palavra é de uma parte. Diga de quem, em waiting_on.
- "hold" quando o procedimento já chegou a um fim.
- Se a composição foi recusada ou as posições estão esgotadas, prefira
  "organize" a repetir a mesma rodada.
- Se uma parte trouxe fato ou posição nova, "conciliate" é preferível a
  encerrar a composição.
- Responda em português do Brasil. A razão deve caber em uma frase.
"""

PROMPT = register_prompt("steward", "1.0.0", SYSTEM_PROMPT)


def _fallback(decision: Dict, reason: str) -> Dict:
    decision = dict(decision)
    decision["execution"] = fallback_execution(PROMPT, reason)
    return decision


def choose_action(context: Dict, deterministic: Dict) -> Dict:
    """Devolve a ação do gestor. `deterministic` já é uma ação lícita."""
    allowed = list(context.get("allowed_actions") or [])
    if not allowed:
        return _fallback(deterministic, "nenhuma ação lícita")
    if len(allowed) == 1 or not llm_configured():
        why = (
            "rito sem margem de escolha"
            if len(allowed) == 1
            else "análise por IA indisponível"
        )
        return _fallback(deterministic, why)

    try:
        result = call_openai_structured(
            system_prompt=PROMPT.text,
            user_payload=context,
            response_model=StewardOutput,
            agent="steward",
        )
    except Exception as exc:
        return _fallback(deterministic, type(exc).__name__)

    chosen = dict(result.data)
    if chosen.get("action") not in allowed:
        return _fallback(deterministic, "ação fora do conjunto lícito")
    admissible = set(context.get("admissible_document_ids") or [])
    if chosen["action"] == "admit":
        chosen["document_ids"] = [
            document_id
            for document_id in chosen.get("document_ids") or []
            if document_id in admissible
        ] or list(deterministic.get("document_ids") or [])
    chosen["execution"] = openai_execution(PROMPT, result)
    return chosen
