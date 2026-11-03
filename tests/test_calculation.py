"""Cálculo determinístico: o exemplo da landing precisa fechar no centavo."""

import pytest

from app.domain.calculation import (
    CalculationError,
    allowed_figures,
    build_calculation,
    format_brl,
    guard_terms,
    monthly_from_annual,
    money_minor,
    parse_decimal,
    price_installment_minor,
    proposal_term,
    scenario,
)
from decimal import Decimal

# O mesmo caso fictício da landing: R$ 10.000, 24x, 9,80% contra 5,40% a.m.,
# 12 parcelas pagas, TAC de R$ 450 e seguro de R$ 610.
EXAMPLE = {
    "principal": "R$ 10.000,00",
    "installments": 24,
    "contract_rate_monthly": "9,80%",
    "average_rate_monthly": "5,40%",
    "average_rate_source": {
        "name": "BACEN, taxa média de juros do crédito pessoal não consignado (PF)",
        "series": "SGS 25464",
        "reference_date": "2024-03",
    },
    "paid_installments": 12,
    "fees": [
        {"name": "TAC", "amount": "450,00", "questionable": True, "reason": "sem previsão regulatória"},
        {"name": "Seguro prestamista", "amount": 610, "questionable": True, "reason": "sem contratação expressa"},
    ],
}


def _line(calc, key):
    return next(item for item in calc["lines"] if item["key"] == key)


def test_landing_example_reaches_the_expected_total():
    calc = build_calculation(EXAMPLE)
    result = calc["result"]
    assert result["contract_installment_minor"] == 109627  # R$ 1.096,27
    assert result["average_installment_minor"] == 75316  # R$ 753,16
    assert result["gap_per_installment_minor"] == 34311  # R$ 343,11
    assert result["interest_above_average_minor"] == 411732  # 12 × R$ 343,11
    assert result["fees_to_refund_minor"] == 106000  # R$ 1.060,00
    assert result["total_proposed_minor"] == 517732
    assert format_brl(result["total_proposed_minor"]) == "R$ 5.177,32"
    assert result["remaining_installments"] == 12
    assert result["remaining_installment_minor"] == 75316
    assert result["rate_above_average_percent"] == "81"


def test_memory_has_formula_inputs_value_and_source_per_line():
    calc = build_calculation(EXAMPLE)
    assert [item["key"] for item in calc["lines"]] == [
        "contract_installment",
        "average_installment",
        "installment_gap",
        "interest_above_average",
        "fee_1",
        "fee_2",
        "fees_to_refund",
        "total_proposed",
        "remaining_installment",
    ]
    for item in calc["lines"]:
        assert item["formula"] and item["label"]
        assert item["display"] == format_brl(item["value_minor"])
    average = _line(calc, "average_installment")
    assert average["inputs"]["i"] == "5,40% a.m."
    assert "SGS 25464" in average["source"] and "2024-03" in average["source"]
    assert _line(calc, "total_proposed")["display"] == "R$ 5.177,32"


def test_calculation_is_deterministic_and_hash_changes_with_inputs():
    first = build_calculation(EXAMPLE)
    again = build_calculation(dict(EXAMPLE))
    assert first["sha256"] == again["sha256"]
    changed = build_calculation({**EXAMPLE, "paid_installments": 11})
    assert changed["sha256"] != first["sha256"]
    assert changed["result"]["total_proposed_minor"] == 34311 * 11 + 106000


def test_rate_adjustment_can_be_declined_and_fees_filtered():
    calc = build_calculation({**EXAMPLE, "interest_adjustment_applies": False})
    assert calc["result"]["interest_above_average_minor"] == 0
    assert calc["result"]["total_proposed_minor"] == 106000
    assert calc["result"]["remaining_installment_minor"] == 109627
    only_tac = build_calculation(
        {**EXAMPLE, "fees": [{"name": "TAC", "amount": 450, "questionable": True},
                             {"name": "Seguro", "amount": 610, "questionable": False}]}
    )
    assert only_tac["result"]["fees_to_refund_minor"] == 45000
    assert "(não questionada)" in _line(only_tac, "fee_2")["label"]


def test_contract_below_average_never_goes_negative():
    calc = build_calculation({**EXAMPLE, "contract_rate_monthly": "3,00%"})
    assert calc["result"]["gap_per_installment_minor"] == 0
    assert calc["result"]["interest_above_average_minor"] == 0


def test_annual_rate_is_converted_to_monthly_with_a_note():
    annual = {**EXAMPLE}
    annual.pop("contract_rate_monthly")
    annual["contract_rate_annual"] = "210,0%"
    calc = build_calculation(annual)
    assert "taxa mensal equivalente" in _line(calc, "contract_installment")["source"]
    assert Decimal(calc["inputs"]["contract_rate_monthly"]) == monthly_from_annual(Decimal("210"))


@pytest.mark.parametrize(
    "mutation,message",
    [
        ({"principal": 0}, "maior que zero"),
        ({"installments": 0}, "prazo"),
        ({"installments": 12.5}, "inteiro"),
        ({"paid_installments": 25}, "parcelas pagas"),
        ({"average_rate_monthly": ""}, "Taxa média"),
        ({"average_rate_source": {"name": "", "reference_date": "2024-03"}}, "fonte"),
        ({"average_rate_source": {"name": "BACEN", "reference_date": "março"}}, "data de referência"),
        ({"contract_rate_monthly": "250%"}, "entre 0% e 100%"),
        ({"fees": [{"name": "", "amount": 10}]}, "nome"),
    ],
)
def test_invalid_inputs_are_rejected_with_a_clear_message(mutation, message):
    with pytest.raises(CalculationError, match=message):
        build_calculation({**EXAMPLE, **mutation})


def test_the_average_rate_never_counts_as_ai_provided():
    calc = build_calculation({**EXAMPLE, "origins": {"average_rate": "ia", "principal": "ia"}})
    assert calc["inputs"]["origins"]["average_rate"] == "parte"
    assert calc["inputs"]["origins"]["principal"] == "ia"


def test_money_and_decimal_parsing():
    assert money_minor("R$ 1.234,56") == 123456
    assert money_minor("1234.56") == 123456
    assert money_minor("1.234") == 123400
    assert money_minor(450) == 45000
    assert parse_decimal("9,80%") == Decimal("9.80")
    assert format_brl(517732) == "R$ 5.177,32"
    assert format_brl(100) == "R$ 1,00"
    assert price_installment_minor(1_000_000, Decimal("0"), 10) == 100000


def test_scenario_is_the_only_way_to_vary_the_amount():
    calc = build_calculation(EXAMPLE)
    assert scenario(calc)["amount_minor"] == 517732
    eighty = scenario(calc, 80)
    assert eighty["amount_minor"] == 414186  # 80% de R$ 5.177,32, meio para cima
    assert eighty["calculation_sha256"] == calc["sha256"]
    assert scenario(calc, 10)["percent"] == 50  # piso da concessão
    assert scenario(calc, 130)["percent"] == 100


def test_proposal_term_is_written_from_the_memory():
    calc = build_calculation(EXAMPLE)
    text = proposal_term(calc, scenario(calc), "Maria da Silva")
    for expected in ("R$ 5.177,32", "R$ 1.060,00", "R$ 4.117,32", "R$ 753,16", "Maria da Silva", calc["sha256"][:12]):
        assert expected in text


def test_guard_drops_numbers_the_module_did_not_produce():
    calc = build_calculation(EXAMPLE)
    kept, violations = guard_terms(
        [
            "Pagamento em até 10 dias úteis, por depósito na conta da parte.",
            "Restituição de R$ 5.177,32 conforme a memória de cálculo.",
            "Desconto adicional de R$ 1.000,00 por liberalidade.",
            "Juros de 12% ao ano sobre o saldo.",
            "Taxa contratada de 9,80% a.m. contra 5,40% a.m.",
        ],
        calc,
    )
    assert len(kept) == 3
    assert {item["figures"] for item in violations} == {"R$ 1.000,00", "12%"}


def test_guard_without_calculation_allows_no_money_at_all():
    kept, violations = guard_terms(
        ["Prazo de 5 dias.", "Valor de R$ 100,00 à vista."], None
    )
    assert kept == ["Prazo de 5 dias."]
    assert violations[0]["figures"] == "R$ 100,00"


def test_guard_accepts_the_scenario_percentage():
    calc = build_calculation(EXAMPLE)
    kept, violations = guard_terms(["Acordo em 80% do total apurado."], calc, allowed_percents=[80])
    assert kept and not violations
    kept, violations = guard_terms(["Acordo em 80% do total apurado."], calc)
    assert violations and not kept


def test_decision_carries_the_memory_and_flags_a_divergent_remedy():
    from app.domain.legacy import public_decision_view
    from app.domain.proposal import attach_calculation_to_decision

    calc = build_calculation(EXAMPLE)
    state = {"status": "ready", "calculation": calc}
    matching = attach_calculation_to_decision(
        {"outcome": "claimant", "remedy_calculation": {"result_minor_units": 517732}}, state
    )
    assert matching["calculation"]["remedy_matches_calculation"] is True
    assert public_decision_view(matching)["calculation"]["sha256"] == calc["sha256"]

    divergent = attach_calculation_to_decision(
        {"outcome": "claimant", "remedy_calculation": {"result_minor_units": 600000}, "limitations": []}, state
    )
    assert divergent["calculation"]["remedy_matches_calculation"] is False
    assert "prevalece a memória" in divergent["limitations"][0]
    # Sem memória pronta, a decisão não é tocada.
    untouched = attach_calculation_to_decision({"outcome": "inconclusive"}, {"status": "needs_inputs"})
    assert "calculation" not in untouched
