"""Fluxo do cálculo auditável: IA extrai e cita, módulo calcula, partes corrigem,
a proposta carrega a memória e o aceite fica preso a ela."""

import pytest

from app.api.routes import calculation as calculation_routes
from app.api.routes import stages
from app.reports.decision_record import build_decision_record
from tests.test_api import (  # noqa: F401 - fixture `client`
    CASE_CREDENTIALS,
    accept_procedure,
    actor_headers,
    client,
    complete_contradictory,
    declare_submissions_ready,
    steward_headers,
)

CONTRACT = (
    "--- Page 1 ---\nCédula de Crédito Bancário. Credor: Banco Exemplo S.A.\n"
    "--- Page 2 ---\nValor financiado: R$ 10.000,00. Prazo: 24 parcelas mensais.\n"
    "Taxa de juros: 9,80% ao mês.\n"
    "--- Page 3 ---\nTarifa de abertura de crédito (TAC): R$ 450,00.\n"
    "Seguro prestamista: R$ 610,00.\n"
)
STATEMENT = "--- Page 1 ---\nExtrato: parcelas 1 a 12 pagas em dia.\n"

AVERAGE = {
    "average_rate_monthly": "5,40%",
    "average_rate_source": {
        "name": "BACEN, crédito pessoal não consignado (PF)",
        "series": "SGS 25464",
        "reference_date": "2024-03",
    },
}


def _cite(document_id, quote, page=None):
    return {"document_id": document_id, "page": page, "quote": quote}


def _extraction(document_id, **overrides):
    value = {
        "in_scope": True,
        "abstention_reason": None,
        "principal": {"value": "R$ 10.000,00", "citation": _cite(document_id, "Valor financiado: R$ 10.000,00", 2)},
        "installments": {"value": "24", "citation": _cite(document_id, "Prazo: 24 parcelas mensais", 2)},
        "contract_rate_monthly": {"value": "9,80%", "citation": _cite(document_id, "Taxa de juros: 9,80% ao mês", 2)},
        "contract_rate_annual": {"value": None, "citation": None},
        "paid_installments": {"value": "12", "citation": _cite(document_id, "parcelas 1 a 12 pagas", 7)},
        "fees": [
            {
                "name": "TAC", "amount": "R$ 450,00", "category": "tarifa",
                "citation": _cite(document_id, "Tarifa de abertura de crédito (TAC): R$ 450,00", 3),
                "questionable": True, "reason": "Sem previsão regulatória para esta operação.",
            },
            {
                "name": "Seguro prestamista", "amount": "R$ 610,00", "category": "seguro",
                "citation": _cite(document_id, "Seguro prestamista: R$ 610,00", 3),
                "questionable": True, "reason": "Sem contratação expressa e autônoma.",
            },
        ],
        "missing_information": [],
        "confidence": 0.9,
        "execution": {"mode": "fake", "model": "fake-model"},
    }
    value.update(overrides)
    return value


@pytest.fixture()
def banking_case(client, monkeypatch):
    created = client.post(
        "/cases",
        json={
            "title": "Revisional de empréstimo",
            "claimant": "Maria da Silva",
            "respondent": "Banco Exemplo S.A.",
            "matter_framework_id": "consumer_banking_v1",
        },
    )
    assert created.status_code == 201, created.text
    case = created.json()
    CASE_CREDENTIALS[case["id"]] = case.pop("access_credentials")
    case_id = case["id"]
    accept_procedure(client, case_id)
    documents = {}
    for name, content in (("contrato.pdf.txt", CONTRACT), ("extrato.txt", STATEMENT)):
        added = client.post(
            f"/cases/{case_id}/documents/text",
            json={"name": name, "content": content, "submitted_by": "claimant", "material_type": "evidence", "purpose": "Comprovar a operação."},
            headers=actor_headers(case_id, "claimant"),
        )
        assert added.status_code == 201, added.text
        documents[name] = added.json()["document"]["id"]
        complete_contradictory(client, case_id, documents[name])
    contract_id = documents["contrato.pdf.txt"]
    statement_id = documents["extrato.txt"]
    scripted = _extraction(contract_id)
    scripted["paid_installments"]["citation"] = _cite(statement_id, "parcelas 1 a 12 pagas", 7)
    monkeypatch.setattr(calculation_routes, "extract_calculation_data", lambda context: dict(scripted))
    return client, case_id, scripted


def _extract(client, case_id, party="claimant"):
    response = client.post(
        f"/cases/{case_id}/calculation/extract?wait=20",
        json={"party": party},
        headers=actor_headers(case_id, party),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _correct(client, case_id, party="claimant", **fields):
    return client.put(
        f"/cases/{case_id}/calculation/inputs",
        json={"party": party, **fields},
        headers=actor_headers(case_id, party),
    )


def test_extraction_cites_the_page_and_verifies_each_quote(banking_case):
    client, case_id, _ = banking_case
    state = _extract(client, case_id)
    extraction = state["extraction"]
    principal = extraction["principal"]["citation"]
    assert principal["verified"] is True
    assert principal["page"] == 2  # a página vem do texto, não do modelo
    assert principal["document_name"] == "contrato.pdf.txt"
    assert extraction["paid_installments"]["citation"]["page"] == 1  # o modelo disse 7
    tac = extraction["fees"][0]
    assert tac["citation"]["verified"] and tac["citation"]["page"] == 3
    # Sem a taxa média BACEN o módulo ainda não calcula: a IA não a informa.
    assert state["status"] == "needs_inputs"
    assert "Taxa média" in state["error"]


def test_quote_not_in_the_document_is_flagged_not_trusted(banking_case, monkeypatch):
    client, case_id, scripted = banking_case
    scripted["principal"]["citation"]["quote"] = "Valor financiado: R$ 99.999,00"
    state = _extract(client, case_id)
    assert state["extraction"]["principal"]["citation"]["verified"] is False


def test_party_completes_the_rate_and_the_module_reaches_the_total(banking_case):
    client, case_id, _ = banking_case
    _extract(client, case_id)
    response = _correct(client, case_id, **AVERAGE)
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["status"] == "ready"
    calc = state["calculation"]
    assert calc["result"]["total_proposed_minor"] == 517732
    assert state["edits"][0]["fields"] == ["average_rate_monthly", "average_rate_source"]
    assert calc["inputs"]["origins"]["average_rate"] == "parte"
    # A IA continua sendo a origem do que a parte não corrigiu.
    assert calc["inputs"]["origins"]["principal"] == "ia"
    audit = [e["event_type"] for e in client.get(f"/cases/{case_id}").json()["audit_log"]]
    assert "calculation_extracted" in audit and "calculation_corrected" in audit


def test_party_correction_marks_the_origin_and_recomputes(banking_case):
    client, case_id, _ = banking_case
    _extract(client, case_id)
    _correct(client, case_id, **AVERAGE)
    state = _correct(client, case_id, paid_installments="10").json()
    assert state["calculation"]["inputs"]["origins"]["paid_installments"] == "parte"
    assert state["calculation"]["result"]["interest_above_average_minor"] == 34311 * 10
    fees = _correct(
        client, case_id,
        fees=[{"name": "TAC", "amount": "R$ 450,00", "questionable": True, "reason": "sem previsão"}],
    ).json()
    assert fees["calculation"]["result"]["fees_to_refund_minor"] == 45000
    # Cobrança mantida conserva a citação verificada.
    assert fees["inputs"]["fees"][0]["citation"]["verified"] is True


def test_invalid_correction_keeps_the_inputs_and_explains(banking_case):
    client, case_id, _ = banking_case
    _extract(client, case_id)
    state = _correct(client, case_id, **{**AVERAGE, "average_rate_source": {"name": "BACEN", "reference_date": "março"}}).json()
    assert state["status"] == "needs_inputs"
    assert "data de referência" in state["error"]


def test_out_of_scope_makes_the_ai_abstain(banking_case, monkeypatch):
    client, case_id, scripted = banking_case
    scripted["in_scope"] = False
    scripted["abstention_reason"] = "A autenticidade da assinatura depende de perícia."
    state = _extract(client, case_id)
    assert state["status"] == "abstained"
    assert state["calculation"] is None
    corrected = _correct(client, case_id, **AVERAGE).json()
    assert corrected["status"] == "abstained"  # corrigir dados não revoga a abstenção


def test_a_new_reading_cannot_erase_party_corrections(banking_case):
    client, case_id, _ = banking_case
    _extract(client, case_id)
    _correct(client, case_id, **AVERAGE)
    again = client.post(
        f"/cases/{case_id}/calculation/extract?wait=20",
        json={"party": "claimant"},
        headers=actor_headers(case_id, "claimant"),
    )
    assert again.status_code == 409


def test_only_the_parties_and_only_bank_matters(client, monkeypatch):
    created = client.post("/cases", json={"title": "Serviço digital", "claimant": "Alfa", "respondent": "Beta"})
    case = created.json()
    CASE_CREDENTIALS[case["id"]] = case.pop("access_credentials")
    wrong_matter = client.post(
        f"/cases/{case['id']}/calculation/extract",
        json={"party": "claimant"},
        headers=actor_headers(case["id"], "claimant"),
    )
    assert wrong_matter.status_code == 409
    forged = client.post(
        f"/cases/{case['id']}/calculation/extract",
        json={"party": "respondent"},
        headers=actor_headers(case["id"], "claimant"),
    )
    assert forged.status_code == 403


def _lock(client, case_id):
    declare_submissions_ready(client, case_id)
    locked = client.post(f"/cases/{case_id}/lock", headers=steward_headers())
    assert locked.status_code == 200, locked.text


def _round(client, case_id, monkeypatch, assessment):
    monkeypatch.setattr(stages, "assess_conciliation", lambda context, round_number: dict(assessment, round_number=round_number))
    response = client.post(
        f"/cases/{case_id}/conciliation?wait=20",
        headers=steward_headers(),
        json={"advance": True, "new_information": "rodada"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _assessment(**extra):
    base = {
        "convergence": "detected", "recommended_path": "conciliation",
        "neutral_summary": "As partes divergem sobre tarifas e juros.",
        "common_interests": ["Encerrar o conflito"], "negotiable_issues": ["Forma de pagamento"],
        "non_negotiable_issues": [], "possible_terms": ["Pagamento em até 10 dias úteis."],
        "reasoning": ["A taxa contratada supera a média."], "confidence": 0.8,
        "continue_recommended": True, "recommended_additional_rounds": 1,
        "next_round_focus": "Valor", "stop_reason": None, "requires_party_consent": True,
        "execution": {"mode": "fake", "model": "fake-model"},
    }
    base.update(extra)
    return base


def test_proposal_carries_the_memory_and_drops_numbers_the_ai_made_up(banking_case, monkeypatch):
    client, case_id, _ = banking_case
    _extract(client, case_id)
    _correct(client, case_id, **AVERAGE)
    _lock(client, case_id)
    rnd = _round(
        client, case_id, monkeypatch,
        _assessment(
            possible_terms=["Pagamento em até 10 dias úteis.", "Desconto extra de R$ 2.000,00 por liberalidade."],
            neutral_summary="O banco pagaria R$ 7.000,00, segundo a IA.",
            proposal_adjustment_percent=70,  # ignorada na 1ª rodada
        ),
    )
    terms = rnd["possible_terms"]
    assert terms[0].startswith("Restituição de R$ 5.177,32 a Maria da Silva")
    assert "Pagamento em até 10 dias úteis." in terms
    assert not any("2.000,00" in term for term in terms)
    assert "R$ 7.000,00" not in rnd["neutral_summary"]
    calculation = rnd["calculation"]
    assert calculation["status"] == "ready"
    assert calculation["scenario"]["percent"] == 100
    assert {item["figures"] for item in calculation["number_guard"]["removed"]} == {"R$ 2.000,00", "R$ 7.000,00"}
    assert calculation["lines"][0]["label"] == "Parcela contratada"


def test_later_rounds_negotiate_through_the_module(banking_case, monkeypatch):
    client, case_id, _ = banking_case
    _extract(client, case_id)
    _correct(client, case_id, **AVERAGE)
    _lock(client, case_id)
    _round(client, case_id, monkeypatch, _assessment())
    second = _round(client, case_id, monkeypatch, _assessment(proposal_adjustment_percent=80))
    assert second["calculation"]["scenario"] == {
        "percent": 80, "amount_minor": 414186, "display": "R$ 4.141,86",
        "formula": "80% × R$ 5.177,32 (total apurado)",
        "calculation_sha256": second["calculation"]["sha256"],
    }
    assert second["possible_terms"][0].startswith("Restituição de R$ 4.141,86")
    floor = _round(client, case_id, monkeypatch, _assessment(proposal_adjustment_percent=5))
    assert floor["calculation"]["scenario"]["percent"] == 50


def test_without_the_average_rate_the_round_proposes_no_money(banking_case, monkeypatch):
    client, case_id, _ = banking_case
    _extract(client, case_id)
    _lock(client, case_id)
    rnd = _round(
        client, case_id, monkeypatch,
        _assessment(possible_terms=["Pagar R$ 1.000,00 em 5 dias."]),
    )
    assert rnd["calculation"]["status"] == "needs_inputs"
    assert rnd["possible_terms"] == []


def test_acceptance_is_bound_to_the_calculation_and_the_record_carries_it(banking_case, monkeypatch):
    client, case_id, _ = banking_case
    _extract(client, case_id)
    _correct(client, case_id, **AVERAGE)
    _lock(client, case_id)
    rnd = _round(client, case_id, monkeypatch, _assessment())
    sha = rnd["calculation"]["sha256"]
    for party in ("claimant", "respondent"):
        accepted = client.post(
            f"/cases/{case_id}/conciliation/1/agreement",
            json={"party": party, "accepted": True},
            headers=actor_headers(case_id, party),
        )
        assert accepted.status_code == 200, accepted.text
    from app.core.canonical import canonical_hash

    case = client.get(f"/cases/{case_id}").json()
    agreement = case["conciliation_rounds"][0]["agreement"]
    assert agreement["complete"] is True
    assert agreement["proposal_sha256"] == canonical_hash(
        {
            "round_number": 1,
            "possible_terms": rnd["possible_terms"],
            "calculation_sha256": sha,
        }
    )
    assert case["status"] == "agreement"
    # Fechado o acordo, os números não mudam mais.
    late = _correct(client, case_id, paid_installments="3")
    assert late.status_code == 409
    record = case["decision_record"]
    assert record is not None
    memory = record["agreement"]["calculation"]
    assert memory["sha256"] == sha
    assert memory["lines"][-2]["value"] == "R$ 5.177,32"
    assert "SGS 25464" in memory["lines"][1]["source"]


def test_refusing_the_proposal_records_the_position_and_wakes_the_steward(banking_case, monkeypatch):
    client, case_id, _ = banking_case
    _extract(client, case_id)
    _correct(client, case_id, **AVERAGE)
    _lock(client, case_id)
    _round(client, case_id, monkeypatch, _assessment())
    refused = client.post(
        f"/cases/{case_id}/conciliation/1/agreement",
        json={"party": "claimant", "accepted": False, "reason": "O valor não cobre o seguro."},
        headers={**actor_headers(case_id, "claimant"), "X-Steward-Run-Models": "0"},
    )
    assert refused.status_code == 200, refused.text
    assert refused.json()["complete"] is False
    case = client.get(f"/cases/{case_id}").json()
    rnd = case["conciliation_rounds"][0]
    assert rnd["agreement"]["responses"]["claimant"] == {
        "accepted": False,
        "recorded_at": rnd["agreement"]["responses"]["claimant"]["recorded_at"],
        "reason": "O valor não cobre o seguro.",
    }
    assert "Recusou a proposta" in rnd["party_positions"]["claimant"]["text"]
    assert "O valor não cobre o seguro." in rnd["party_positions"]["claimant"]["text"]
    # O gestor passa a esperar só a outra parte.
    assert "respondent:composicao" in (case["steward"]["waiting_on"] or [])
    assert "claimant:composicao" not in (case["steward"]["waiting_on"] or [])


def test_a_refusal_does_not_overwrite_a_position_already_filed(banking_case, monkeypatch):
    client, case_id, _ = banking_case
    _extract(client, case_id)
    _correct(client, case_id, **AVERAGE)
    _lock(client, case_id)
    _round(client, case_id, monkeypatch, _assessment())
    client.post(
        f"/cases/{case_id}/conciliation/1/position",
        json={"party": "claimant", "text": "Quero rever o seguro.", "waived": False},
        headers={**actor_headers(case_id, "claimant"), "X-Steward-Run-Models": "0"},
    )
    client.post(
        f"/cases/{case_id}/conciliation/1/agreement",
        json={"party": "claimant", "accepted": False},
        headers={**actor_headers(case_id, "claimant"), "X-Steward-Run-Models": "0"},
    )
    rnd = client.get(f"/cases/{case_id}").json()["conciliation_rounds"][0]
    assert rnd["party_positions"]["claimant"]["text"] == "Quero rever o seguro."
