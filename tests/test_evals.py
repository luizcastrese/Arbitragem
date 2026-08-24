"""A bateria de avaliação roda no CI em modo offline: determinística, sem
chave e sem rede. Se uma métrica parar de acusar um controle negativo, o teste
quebra — é o que impede a avaliação de virar enfeite."""

import os

import pytest


os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("PLATFORM_SIGNING_SECRET", "test-signing-secret")

from app.core import config  # noqa: E402

config.get_settings.cache_clear()

from evals.checks import (  # noqa: E402
    citations_grounded,
    figures_supported,
    provenance_recorded,
)
from evals.runner import load_scenarios, pass_rate, run_all, run_scenario  # noqa: E402


def test_scenarios_are_loaded():
    scenarios = load_scenarios()
    assert scenarios, "a bateria precisa ter cenários"
    for scenario in scenarios:
        assert scenario["agent"] in {"judge", "reviewer", "organizer", "conciliator"}
        assert scenario["expectations"], f"{scenario['id']} sem expectativas"


@pytest.mark.parametrize("scenario", load_scenarios(), ids=lambda item: item["id"])
def test_scenario_meets_expectations(scenario):
    result = run_scenario(scenario, live=False)
    failures = [check for check in result.checks if not check.passed]
    assert not failures, "; ".join(
        f"{check.name}: obtido {check.value!r}, esperado {check.expected!r} "
        f"({check.detail})"
        for check in failures
    )


def test_offline_battery_is_fully_green():
    assert pass_rate(run_all(live=False)) == 1.0


def test_metrics_detect_fabricated_evidence():
    record = {
        "document_ids": ["doc-1"],
        "chunk_ids": ["chunk-1"],
        "corpus_text": "O contrato prevê R$ 80.000,00 em duas parcelas.",
        "agent": "judge",
    }
    fabricated = {
        "decision": "Devolução de R$ 62.500,00, equivalente a 78% do contrato.",
        "evidence_cited": ["doc-1/chunk-77"],
    }
    assert citations_grounded(fabricated, record).value is False
    assert figures_supported(fabricated, record).value is False

    grounded = {
        "decision": "Devolução limitada ao valor contratado de R$ 80.000,00.",
        "evidence_cited": ["doc-1/chunk-1"],
    }
    assert citations_grounded(grounded, record).value is True
    assert figures_supported(grounded, record).value is True


def test_provenance_metric_requires_prompt_and_model():
    record = {"agent": "judge"}
    assert provenance_recorded({"execution": {}}, record).value is False
    assert provenance_recorded(
        {
            "execution": {
                "mode": "openai",
                "model": None,
                "prompt": {"agent": "judge", "version": "1.0.0", "sha256": "x"},
            }
        },
        record,
    ).value is False
