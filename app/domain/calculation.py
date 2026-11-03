"""Cálculo determinístico da revisional bancária, com memória linha a linha.

A IA extrai dados dos documentos e negocia, mas **nenhum número da proposta
nasce dela**: toda conta passa por este módulo. Ele é puro (sem rede, sem
banco, sem modelo), usa ``Decimal`` e inteiros em centavos, e devolve a
memória de cálculo com fórmula, entradas, valor e fonte de cada linha, mais um
hash do conjunto. Mesmas entradas, mesmo resultado, em qualquer máquina.

Método (tabela Price, parcelas fixas, juros compostos):

1. parcela contratada = PMT(valor financiado, taxa do contrato, prazo);
2. parcela à taxa média = PMT(valor financiado, taxa média BACEN, prazo);
3. diferença por parcela = (1) − (2), sobre as parcelas já pagas;
4. tarifas e seguros questionados, a restituir;
5. total proposto = (3) pagas + (4).

As parcelas são arredondadas ao centavo (meio para cima) antes da diferença,
para que o que está na memória feche com a conta de quem a confere à mão.

Este módulo não decide se a taxa é abusiva nem se uma cobrança é devida: isso
vem como entrada (``interest_adjustment_applies`` e ``questionable`` de cada
tarifa), com quem decidiu registrado em ``origins``.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.core.canonical import canonical_hash

CALCULATION_VERSION = "1.0.0"
METHOD = "tabela_price"

# Piso da concessão que a IA pode propor numa rodada de negociação. Abaixo
# disso a proposta deixa de ser um acordo plausível e vira renúncia.
MIN_SETTLEMENT_PERCENT = 50
MAX_INSTALLMENTS = 600
MAX_MONTHLY_RATE = Decimal("100")

_CENT = Decimal("0.01")
_RATE_Q = Decimal("0.0001")


class CalculationError(ValueError):
    """Entrada inválida ou incompleta. A mensagem vai para o usuário."""


# --------------------------------------------------------------------------
# Conversões
# --------------------------------------------------------------------------

def parse_decimal(raw: Any, label: str = "valor") -> Decimal:
    """Aceita ``9.8``, ``"9,80%"``, ``"R$ 10.000,00"`` e ``"10000.00"``."""
    if isinstance(raw, bool):
        raise CalculationError(f"{label} inválido")
    if isinstance(raw, Decimal):
        return raw
    if isinstance(raw, int):
        return Decimal(raw)
    if isinstance(raw, float):
        return Decimal(str(raw))
    text = re.sub(r"[R$\s%]|a\.m\.", "", str(raw or ""), flags=re.IGNORECASE)
    if not text:
        raise CalculationError(f"{label} não informado")
    if "," in text and "." in text:
        # Ponto de milhar e vírgula decimal (formato brasileiro).
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", text):
        text = text.replace(".", "")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise CalculationError(f"{label} inválido: {raw}") from exc


def to_minor(value: Decimal) -> int:
    """Reais para centavos inteiros, meio para cima."""
    return int((value / _CENT).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def money_minor(raw: Any, label: str = "valor") -> int:
    value = parse_decimal(raw, label)
    if value < 0:
        raise CalculationError(f"{label} não pode ser negativo")
    return to_minor(value)


def format_brl(minor: int) -> str:
    sign = "-" if minor < 0 else ""
    reais, cents = divmod(abs(int(minor)), 100)
    return f"{sign}R$ {reais:,}".replace(",", ".") + f",{cents:02d}"


def format_rate(rate: Decimal) -> str:
    return f"{rate.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):f}".replace(".", ",") + "%"


# --------------------------------------------------------------------------
# Matemática financeira
# --------------------------------------------------------------------------

def price_installment_minor(principal_minor: int, monthly_rate_percent: Decimal, n: int) -> int:
    """Parcela da tabela Price: PMT = PV · i / (1 − (1 + i)^−n), em centavos."""
    with localcontext() as context:
        context.prec = 40
        principal = Decimal(principal_minor) / 100
        i = monthly_rate_percent / 100
        if i == 0:
            payment = principal / n
        else:
            payment = principal * i / (1 - (1 + i) ** (-n))
        return to_minor(payment)


def monthly_from_annual(annual_percent: Decimal) -> Decimal:
    """Taxa mensal equivalente à anual (juros compostos), com 4 casas."""
    with localcontext() as context:
        context.prec = 40
        monthly = ((1 + annual_percent / 100) ** (Decimal(1) / 12) - 1) * 100
        return monthly.quantize(_RATE_Q, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------
# Entradas
# --------------------------------------------------------------------------

_DATE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?$")


def _text(raw: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(raw or "")).strip()[:limit]


def _citation(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    page = raw.get("page")
    return {
        "document_id": _text(raw.get("document_id"), 80),
        "document_name": _text(raw.get("document_name"), 200),
        "page": page if isinstance(page, int) and page > 0 else None,
        "quote": _text(raw.get("quote"), 400),
        "verified": bool(raw.get("verified")),
    }


def normalize_inputs(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Valida e normaliza as entradas. Tudo em tipos exatos (int e Decimal-str)."""
    principal = money_minor(raw.get("principal"), "Valor financiado")
    if principal <= 0:
        raise CalculationError("O valor financiado deve ser maior que zero")

    installments = parse_decimal(raw.get("installments"), "Prazo")
    if installments != installments.to_integral_value() or not 1 <= installments <= MAX_INSTALLMENTS:
        raise CalculationError(f"O prazo deve ser um número inteiro de 1 a {MAX_INSTALLMENTS} parcelas")
    n = int(installments)

    monthly_raw = raw.get("contract_rate_monthly")
    annual_raw = raw.get("contract_rate_annual")
    rate_note = ""
    if monthly_raw not in (None, ""):
        contract_rate = parse_decimal(monthly_raw, "Taxa do contrato")
    elif annual_raw not in (None, ""):
        annual = parse_decimal(annual_raw, "Taxa anual do contrato")
        contract_rate = monthly_from_annual(annual)
        rate_note = f"taxa mensal equivalente à anual de {format_rate(annual)}"
    else:
        raise CalculationError("Informe a taxa de juros do contrato (mensal ou anual)")
    if not Decimal(0) < contract_rate <= MAX_MONTHLY_RATE:
        raise CalculationError("A taxa mensal do contrato deve estar entre 0% e 100%")

    average_rate = parse_decimal(raw.get("average_rate_monthly"), "Taxa média BACEN")
    if not Decimal(0) < average_rate <= MAX_MONTHLY_RATE:
        raise CalculationError("A taxa média BACEN deve estar entre 0% e 100% ao mês")
    source_raw = raw.get("average_rate_source") or {}
    source = {
        "name": _text(source_raw.get("name"), 200),
        "series": _text(source_raw.get("series"), 40),
        "reference_date": _text(source_raw.get("reference_date"), 10),
        "url": _text(source_raw.get("url"), 300),
    }
    if not source["name"]:
        raise CalculationError("Informe a fonte da taxa média BACEN (nome da série ou modalidade)")
    if not _DATE.match(source["reference_date"]):
        raise CalculationError("Informe a data de referência da taxa média (AAAA-MM ou AAAA-MM-DD)")

    paid_raw = parse_decimal(raw.get("paid_installments", 0), "Parcelas pagas")
    if paid_raw != paid_raw.to_integral_value() or not 0 <= paid_raw <= n:
        raise CalculationError("As parcelas pagas devem ser um inteiro entre 0 e o prazo")

    fees: List[Dict[str, Any]] = []
    for index, item in enumerate(raw.get("fees") or []):
        name = _text(item.get("name"), 160)
        if not name:
            raise CalculationError(f"Tarifa {index + 1}: informe o nome")
        fees.append(
            {
                "name": name,
                "amount_minor": money_minor(item.get("amount"), f"Valor de {name}"),
                "questionable": bool(item.get("questionable", False)),
                "reason": _text(item.get("reason"), 400),
                "citation": _citation(item.get("citation")),
            }
        )

    origins_raw = raw.get("origins") if isinstance(raw.get("origins"), dict) else {}
    origins = {
        key: ("parte" if origins_raw.get(key) == "parte" else "ia")
        for key in ("principal", "installments", "contract_rate", "paid_installments", "fees")
    }
    origins["average_rate"] = "parte"  # a taxa média nunca vem da IA

    citations_raw = raw.get("citations") if isinstance(raw.get("citations"), dict) else {}
    citations = {
        key: _citation(citations_raw.get(key))
        for key in ("principal", "installments", "contract_rate", "paid_installments")
    }
    return {
        "principal_minor": principal,
        "installments": n,
        "contract_rate_monthly": f"{contract_rate:f}",
        "contract_rate_note": rate_note,
        "average_rate_monthly": f"{average_rate:f}",
        "average_rate_source": source,
        "paid_installments": int(paid_raw),
        "interest_adjustment_applies": bool(raw.get("interest_adjustment_applies", True)),
        "fees": fees,
        "origins": origins,
        "citations": citations,
    }


# --------------------------------------------------------------------------
# Memória de cálculo
# --------------------------------------------------------------------------

def _line(key: str, label: str, formula: str, inputs: Dict[str, str], minor: int, source: str = "") -> Dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "formula": formula,
        "inputs": inputs,
        "value_minor": int(minor),
        "display": format_brl(minor),
        "source": source,
    }


def _cite(citation: Optional[Dict[str, Any]]) -> str:
    if not citation or not citation.get("document_name") and not citation.get("document_id"):
        return ""
    name = citation.get("document_name") or citation.get("document_id")
    page = f", p. {citation['page']}" if citation.get("page") else ""
    return f"{name}{page}"


def build_calculation(raw_inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza as entradas e devolve a memória de cálculo completa."""
    inputs = normalize_inputs(raw_inputs)
    principal = inputs["principal_minor"]
    n = inputs["installments"]
    paid = inputs["paid_installments"]
    contract_rate = Decimal(inputs["contract_rate_monthly"])
    average_rate = Decimal(inputs["average_rate_monthly"])
    applies = inputs["interest_adjustment_applies"]
    citations = inputs["citations"]
    rate_source = inputs["average_rate_source"]
    rate_source_text = (
        f"{rate_source['name']}"
        + (f" (série {rate_source['series']})" if rate_source["series"] else "")
        + f", ref. {rate_source['reference_date']}"
    )

    contract_installment = price_installment_minor(principal, contract_rate, n)
    average_installment = price_installment_minor(principal, average_rate, n)
    gap = max(0, contract_installment - average_installment) if applies else 0
    interest_above = gap * paid

    lines: List[Dict[str, Any]] = []
    base_inputs = {
        "VF": format_brl(principal),
        "n": str(n),
    }
    lines.append(
        _line(
            "contract_installment",
            "Parcela contratada",
            "PMT = VF · i ÷ (1 − (1 + i)^−n)",
            {**base_inputs, "i": f"{format_rate(contract_rate)} a.m."},
            contract_installment,
            "; ".join(
                part
                for part in (
                    _cite(citations.get("principal")),
                    _cite(citations.get("contract_rate")),
                    inputs["contract_rate_note"],
                )
                if part
            ),
        )
    )
    lines.append(
        _line(
            "average_installment",
            "Parcela à taxa média BACEN",
            "PMT = VF · i ÷ (1 − (1 + i)^−n)",
            {**base_inputs, "i": f"{format_rate(average_rate)} a.m."},
            average_installment,
            rate_source_text,
        )
    )
    gap_formula = "diferença = parcela contratada − parcela à taxa média"
    if not applies:
        gap_formula += " (não aplicada: a revisão dos juros não foi admitida)"
    lines.append(
        _line(
            "installment_gap",
            "Diferença por parcela",
            gap_formula,
            {
                "parcela contratada": format_brl(contract_installment),
                "parcela à taxa média": format_brl(average_installment),
            },
            gap,
        )
    )
    lines.append(
        _line(
            "interest_above_average",
            "Diferença paga a mais nas parcelas já quitadas",
            "diferença por parcela × parcelas pagas",
            {"diferença por parcela": format_brl(gap), "parcelas pagas": str(paid)},
            interest_above,
            _cite(citations.get("paid_installments")),
        )
    )

    fees_total = 0
    fee_keys: List[str] = []
    for index, fee in enumerate(inputs["fees"]):
        counted = fee["amount_minor"] if fee["questionable"] else 0
        fees_total += counted
        key = f"fee_{index + 1}"
        fee_keys.append(key)
        lines.append(
            _line(
                key,
                f"{fee['name']}" + ("" if fee["questionable"] else " (não questionada)"),
                "valor cobrado, se a cobrança é questionada; senão 0",
                {"valor cobrado": format_brl(fee["amount_minor"])},
                counted,
                _cite(fee.get("citation")),
            )
        )
    lines.append(
        _line(
            "fees_to_refund",
            "Tarifas e seguros a restituir",
            "soma das tarifas questionadas",
            {"tarifas": ", ".join(fee_keys) or "nenhuma"},
            fees_total,
        )
    )
    total = interest_above + fees_total
    lines.append(
        _line(
            "total_proposed",
            "Total apurado a restituir",
            "diferença paga a mais + tarifas e seguros a restituir",
            {"diferença paga a mais": format_brl(interest_above), "tarifas": format_brl(fees_total)},
            total,
        )
    )
    remaining = n - paid
    remaining_installment = average_installment if applies else contract_installment
    lines.append(
        _line(
            "remaining_installment",
            f"Parcela recalculada das {remaining} restantes",
            "parcela à taxa média" if applies else "parcela contratada (sem revisão dos juros)",
            {"parcelas restantes": str(remaining)},
            remaining_installment,
        )
    )

    result = {
        "contract_installment_minor": contract_installment,
        "average_installment_minor": average_installment,
        "gap_per_installment_minor": gap,
        "interest_above_average_minor": interest_above,
        "fees_to_refund_minor": fees_total,
        "total_proposed_minor": total,
        "remaining_installments": remaining,
        "remaining_installment_minor": remaining_installment,
        "rate_above_average_percent": (
            f"{((contract_rate / average_rate - 1) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP):f}"
        ),
    }
    body = {
        "version": CALCULATION_VERSION,
        "method": METHOD,
        "inputs": inputs,
        "lines": lines,
        "result": result,
    }
    return {**body, "sha256": canonical_hash(body)}


# --------------------------------------------------------------------------
# Proposta e guarda de números
# --------------------------------------------------------------------------

def scenario(calculation: Dict[str, Any], percent: Optional[int] = None) -> Dict[str, Any]:
    """Valor da proposta para um percentual do total apurado (100 = integral).

    É o único jeito de a proposta variar entre rodadas: a IA escolhe o
    percentual, o módulo faz a conta.
    """
    chosen = 100 if percent is None else int(percent)
    chosen = max(MIN_SETTLEMENT_PERCENT, min(100, chosen))
    total = calculation["result"]["total_proposed_minor"]
    amount = (total * chosen + 50) // 100
    return {
        "percent": chosen,
        "amount_minor": amount,
        "display": format_brl(amount),
        "formula": f"{chosen}% × {format_brl(total)} (total apurado)",
        "calculation_sha256": calculation["sha256"],
    }


def proposal_term(
    calculation: Dict[str, Any],
    scenario_data: Dict[str, Any],
    consumer_name: str,
) -> str:
    """Cláusula monetária da proposta, escrita pelo servidor a partir da memória."""
    result = calculation["result"]
    source = calculation["inputs"]["average_rate_source"]
    parts = [
        f"Restituição de {scenario_data['display']} a {consumer_name}, "
        f"correspondente a {scenario_data['percent']}% do total apurado de "
        f"{format_brl(result['total_proposed_minor'])}",
        f"({format_brl(result['fees_to_refund_minor'])} de tarifas e seguros + "
        f"{format_brl(result['interest_above_average_minor'])} de juros pagos acima da taxa média)",
    ]
    text = " ".join(parts) + "."
    if result["remaining_installments"] and calculation["inputs"]["interest_adjustment_applies"]:
        text += (
            f" As {result['remaining_installments']} parcelas restantes passam a "
            f"{format_brl(result['remaining_installment_minor'])}, calculadas à taxa média de "
            f"{format_rate(Decimal(calculation['inputs']['average_rate_monthly']))} a.m. "
            f"({source['name']}, ref. {source['reference_date']})."
        )
    return text + f" Memória de cálculo {calculation['sha256'][:12]}."


_AMOUNT = re.compile(r"R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?|R\$\s?\d+(?:,\d{1,2})?")
_PERCENT = re.compile(r"\d+(?:[.,]\d+)?\s?%")


def allowed_figures(calculation: Optional[Dict[str, Any]], extra_percents: Iterable[int] = ()) -> Tuple[set, set]:
    """Valores e percentuais que uma proposta pode citar."""
    amounts: set = set()
    percents: set = {f"{p}%" for p in extra_percents}
    if calculation:
        for line in calculation["lines"]:
            amounts.add(_norm_amount(line["display"]))
        amounts.add(_norm_amount(format_brl(calculation["result"]["total_proposed_minor"])))
        amounts.add(_norm_amount(format_brl(calculation["result"]["remaining_installment_minor"])))
        inputs = calculation["inputs"]
        amounts.add(_norm_amount(format_brl(inputs["principal_minor"])))
        percents.add(_norm_percent(format_rate(Decimal(inputs["contract_rate_monthly"]))))
        percents.add(_norm_percent(format_rate(Decimal(inputs["average_rate_monthly"]))))
        percents.add(_norm_percent(f"{calculation['result']['rate_above_average_percent']}%"))
    return amounts, percents


def _norm_amount(text: str) -> str:
    cleaned = re.sub(r"\s", "", text)
    if "," not in cleaned:
        cleaned += ",00"
    elif re.search(r",\d$", cleaned):
        cleaned += "0"
    return cleaned


def _norm_percent(text: str) -> str:
    return re.sub(r"\s", "", text).replace(",00%", "%").replace(".", ",")


def guard_terms(
    terms: Iterable[str],
    calculation: Optional[Dict[str, Any]],
    allowed_percents: Iterable[int] = (),
) -> Tuple[List[str], List[Dict[str, str]]]:
    """Remove das cláusulas da IA qualquer valor ou percentual fora da memória.

    Devolve (cláusulas mantidas, violações). Sem cálculo, nenhuma cláusula
    pode citar valor em reais: não há de onde ele ter vindo.
    """
    amounts, percents = allowed_figures(calculation, allowed_percents)
    percents = {_norm_percent(item) for item in percents}
    kept: List[str] = []
    violations: List[Dict[str, str]] = []
    for term in terms:
        offending = [
            found for found in _AMOUNT.findall(term) if _norm_amount(found) not in amounts
        ] + [
            found for found in _PERCENT.findall(term) if _norm_percent(found) not in percents
        ]
        if offending:
            violations.append({"term": term, "figures": ", ".join(offending)})
        else:
            kept.append(term)
    return kept, violations
