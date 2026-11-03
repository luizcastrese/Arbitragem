"""Extração dos dados do contrato e dos extratos, com a página de cada dado.

A IA **lê e cita; não calcula**. Ela devolve valor financiado, prazo, taxa
contratada, parcelas pagas, tarifas e seguros, cada um com documento, página e
o trecho exato; avalia quais cobranças são questionáveis e por quê; e diz se o
caso está no escopo (senão, se abstém). O servidor confere cada citação contra
o texto do documento (app.domain.extraction) e só então os dados seguem para o
módulo de cálculo determinístico, onde as partes ainda podem corrigi-los.
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel

from app.agents.execution import fallback_execution, openai_execution
from app.core.llm import call_openai_structured
from app.core.prompt_registry import register_prompt


class Citation(BaseModel):
    document_id: str
    # Número da página, conforme os marcadores "--- Page N ---" do texto. Nulo
    # quando o documento não tem páginas (texto colado).
    page: Optional[int]
    # Trecho copiado literalmente do documento.
    quote: str


class ExtractedValue(BaseModel):
    # Número como texto, exatamente como aparece no documento ("R$ 10.000,00",
    # "9,80% a.m."). Nulo se o documento não traz o dado.
    value: Optional[str]
    citation: Optional[Citation]


class ExtractedFee(BaseModel):
    name: str
    amount: str
    citation: Citation
    category: Literal["tarifa", "seguro", "encargo", "outro"]
    questionable: bool
    # Por que a cobrança é (ou não) questionável, em uma ou duas frases.
    reason: str


class ExtractionOutput(BaseModel):
    in_scope: bool
    # Preenchido quando in_scope é falso: por que a IA se abstém.
    abstention_reason: Optional[str]
    principal: ExtractedValue
    installments: ExtractedValue
    contract_rate_monthly: ExtractedValue
    contract_rate_annual: ExtractedValue
    paid_installments: ExtractedValue
    fees: List[ExtractedFee]
    missing_information: List[str]
    confidence: float


SYSTEM_PROMPT = """
Você é o agente extrator da Valinor, em disputas bancárias de consumo
(revisional de contrato, tarifas, seguros e juros). Sua tarefa é ler o material
admitido e extrair dados para um cálculo que será feito por um módulo
determinístico. Você NÃO calcula, NÃO estima e NÃO decide o mérito.

Regras:
- Extraia só o que o documento diz. Se um dado não consta, devolva value nulo e
  liste em missing_information. Nunca complete com suposição.
- Cada dado traz citation: document_id exato do material, page (conforme os
  marcadores "--- Page N ---" do texto; nulo se não houver marcador) e quote,
  um trecho copiado literalmente do documento. Sem trecho literal, sem dado.
- principal é o valor financiado/creditado. installments é o prazo em parcelas.
  contract_rate_monthly e contract_rate_annual são as taxas de juros
  remuneratórios do contrato, como escritas. paid_installments é o número de
  parcelas já pagas, conforme extratos ou demonstrativo.
- fees lista tarifas, seguros e encargos cobrados além do principal e dos juros
  (TAC, tarifa de cadastro, seguro prestamista, tarifa de avaliação etc.), cada
  um com o valor cobrado e a citação.
- Para cada item de fees diga se é questionável (questionable) e por quê
  (reason): tarifa sem previsão no contrato ou na regulamentação do CMN/Bacen,
  seguro sem contratação expressa e autônoma, cobrança em duplicidade. Se o
  contrato prevê e a regulamentação admite, marque questionable falso e diga
  por quê. Na dúvida, explique a dúvida em reason.
- Não informe a taxa média do Bacen: ela vem de fonte oficial, informada pelas
  partes.
- Escopo: se o caso depender de perícia (autenticidade de assinatura),
  superendividamento, dano moral sem parâmetro, financiamento imobiliário,
  tutela de urgência, matéria suspensa ou ação coletiva, ou se o material não
  tratar de contrato bancário de consumo, use in_scope falso e explique em
  abstention_reason. Na dúvida sobre o escopo, abstenha-se.
- confidence (0 a 1) reflete o quanto os documentos sustentam o conjunto.
- Responda em português do Brasil.
"""

PROMPT = register_prompt("extractor", "1.0.0", SYSTEM_PROMPT)

_EMPTY = {"value": None, "citation": None}


def _safe_fallback(reason: str) -> Dict:
    return {
        "in_scope": True,
        "abstention_reason": None,
        "principal": dict(_EMPTY),
        "installments": dict(_EMPTY),
        "contract_rate_monthly": dict(_EMPTY),
        "contract_rate_annual": dict(_EMPTY),
        "paid_installments": dict(_EMPTY),
        "fees": [],
        "missing_information": [
            "A leitura automática dos documentos não pôde ser concluída. "
            "Informe os dados manualmente."
        ],
        "confidence": 0.0,
        "execution": fallback_execution(PROMPT, reason),
    }


def extract_calculation_data(context: Dict) -> Dict:
    try:
        result = call_openai_structured(
            system_prompt=PROMPT.text,
            user_payload=context,
            response_model=ExtractionOutput,
            agent="extractor",
        )
    except Exception as exc:
        return _safe_fallback(type(exc).__name__)
    extraction = dict(result.data)
    extraction["execution"] = openai_execution(PROMPT, result)
    return extraction
