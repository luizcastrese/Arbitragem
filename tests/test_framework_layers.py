"""Abordagem e matéria: todo caso novo trava as duas camadas de framework.

O que estes testes protegem: a abordagem (`commercial_balanced_v1`) não
concorre com a matéria, ela se soma a ela; os frameworks publicados não mudam
de hash por causa da composição; e manifestos travados antes dela continuam
resolvidos só pela matéria que fixaram.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.core.config import get_settings, validate_runtime_policy
from app.domain.frameworks import (
    compose_framework,
    framework_from_lock,
    get_framework,
    resolve_case_framework,
)
from tests.test_decision_verifier import _manifest, _valid_decision, _verify

MATTER_ID = "digital_services_b2b_v1"
APPROACH_ID = "commercial_balanced_v1"


def test_published_frameworks_keep_their_hashes():
    # Hashes fixados em manifestos travados: mudar o conteúdo exige um id novo.
    assert get_framework(MATTER_ID).hash() == (
        "c656f69b917495eda40ad5ab168502ebc3f309c5c3ddaa59c5b509d3fb2cdd05"
    )
    assert get_framework(APPROACH_ID).hash() == (
        "df7804282506bb7e74a333cb6ecd89a976b4b5f49434b80f6fd57e7dd8a04adf"
    )


def test_case_framework_is_matter_plus_approach():
    matter = get_framework(MATTER_ID)
    approach = get_framework(APPROACH_ID)
    composed = resolve_case_framework()

    assert composed.id == matter.id
    assert composed.version == matter.version
    assert composed.case_value_limit_minor_units == matter.case_value_limit_minor_units
    assert set(matter.rule_ids()) | set(approach.rule_ids()) == set(composed.rule_ids())
    assert set(approach.principles) <= set(composed.principles)
    assert composed.approach == {
        "id": approach.id,
        "name": approach.name,
        "version": approach.version,
        "hash": approach.hash(),
    }
    assert composed.lock_summary()["approach"]["id"] == APPROACH_ID


def test_layers_cannot_be_swapped():
    with pytest.raises(ValueError):
        compose_framework(get_framework(APPROACH_ID), get_framework(MATTER_ID))
    with pytest.raises(ValueError):
        resolve_case_framework(APPROACH_ID)


def test_lock_without_approach_resolves_only_the_matter():
    legacy = framework_from_lock({"id": MATTER_ID, "version": "1.0.0"})
    assert legacy.approach is None
    assert legacy.hash() == get_framework(MATTER_ID).hash()

    composed = resolve_case_framework()
    assert framework_from_lock(composed.lock_summary()).hash() == composed.hash()


def _decision_applying_good_faith():
    decision = _valid_decision()
    decision["rule_applications"].append(
        {
            "rule_id": f"{APPROACH_ID}:good_faith",
            "rule_version": "1.0.0",
            "findings_used": ["f-delivery"],
            "application_reasoning": "Entrega parcial comunicada de boa-fé.",
            "conclusion": "Sem penalidade adicional.",
        }
    )
    return decision


def test_verifier_accepts_approach_rule_only_on_composed_lock():
    from app.domain.decision_verifier import verify_decision
    from tests.test_decision_verifier import _admitted, _chunks

    decision = _decision_applying_good_faith()
    composed = verify_decision(
        decision, _manifest(), _admitted(), _chunks(), resolve_case_framework()
    )
    assert composed.valid is True, composed.errors

    legacy = _verify(decision)
    assert legacy.valid is False
    assert any(item.code == "unknown_rule" for item in legacy.errors)


@pytest.mark.parametrize(
    "changes",
    [
        {"framework_id": APPROACH_ID},
        {"approach_framework_id": MATTER_ID},
        {"framework_id": "inexistente_v1"},
    ],
)
def test_boot_refuses_misplaced_framework(changes):
    settings = dataclasses.replace(get_settings(), **changes)
    with pytest.raises(RuntimeError):
        validate_runtime_policy(settings)
