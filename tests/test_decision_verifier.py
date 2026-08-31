"""Testes unitários do verificador determinístico. Sem IA e sem rede."""

from __future__ import annotations

from copy import deepcopy

from app.core.hashing import sha256_text
from app.domain.decision_verifier import verify_decision
from app.domain.frameworks import get_framework
from app.domain.legacy import normalize_legacy_decision
from app.domain.models import (
    CalculationInput,
    DecisionOutput,
    EvidenceReference,
    MaterialFinding,
    RemedyCalculation,
    RuleApplication,
)

FRAMEWORK = get_framework("digital_services_b2b_v1")

DOC_TEXT = (
    "A Fornecedora entregará o site institucional até 30 de junho. "
    "O preço do contrato é 8000000 centavos de real. "
    "Foi entregue apenas a home, equivalente à metade do escopo."
)
DOC_ID = "case0001-D1"
CHUNK_ID = "case0001-D1-C1"
DOC_HASH = sha256_text(DOC_TEXT)
CHUNK_HASH = sha256_text(DOC_TEXT)
QUOTE = "O preço do contrato é 8000000 centavos de real."
QUOTE_HASH = sha256_text(QUOTE)


def _ref(**overrides) -> dict:
    payload = {
        "document_id": DOC_ID,
        "document_sha256": DOC_HASH,
        "chunk_id": CHUNK_ID,
        "chunk_sha256": CHUNK_HASH,
        "quoted_text": QUOTE,
        "quoted_text_sha256": QUOTE_HASH,
        "support_type": "direct",
        "start_offset": DOC_TEXT.find(QUOTE),
        "end_offset": DOC_TEXT.find(QUOTE) + len(QUOTE),
    }
    payload.update(overrides)
    return payload


def _manifest():
    return {
        "documents": [
            {"id": DOC_ID, "sha256": DOC_HASH, "admitted": True, "name": "contrato.txt"}
        ],
        "chunks": [{"id": CHUNK_ID, "document_id": DOC_ID, "sha256": CHUNK_HASH}],
        "framework": {"id": FRAMEWORK.id, "version": FRAMEWORK.version},
    }


def _chunks():
    return [{"id": CHUNK_ID, "document_id": DOC_ID, "sha256": CHUNK_HASH, "text": DOC_TEXT}]


def _admitted():
    return [{"id": DOC_ID, "admitted": True, "sha256": DOC_HASH}]


def _valid_decision(**overrides) -> dict:
    payload = {
        "framework_id": FRAMEWORK.id,
        "framework_version": FRAMEWORK.version,
        "framework": FRAMEWORK.name,
        "outcome": "partial",
        "partial_claimant_bps": 5000,
        "decision": "Pagamento proporcional à metade entregue.",
        "material_findings": [
            {
                "finding_id": "f-delivery",
                "proposition": "Apenas metade do escopo foi entregue.",
                "status": "established",
                "evidence": [_ref()],
                "counterevidence": [],
                "reasoning": "O trecho admite entrega parcial da home.",
                "confidence": 0.8,
            },
            {
                "finding_id": "f-price",
                "proposition": "O preço contratual é 8000000 minor units BRL.",
                "status": "established",
                "evidence": [_ref()],
                "counterevidence": [],
                "reasoning": "O contrato fixa o preço.",
                "confidence": 0.9,
            },
        ],
        "rule_applications": [
            {
                "rule_id": "digital_services_b2b_v1:delivery:partial",
                "rule_version": "1.0.0",
                "findings_used": ["f-delivery"],
                "application_reasoning": "Entrega parcial documentada.",
                "conclusion": "Pagamento proporcional.",
            },
            {
                "rule_id": "digital_services_b2b_v1:payment:proportional",
                "rule_version": "1.0.0",
                "findings_used": ["f-delivery", "f-price"],
                "application_reasoning": "Fração estabelecida de 50%.",
                "conclusion": "4000000 minor units ao reclamante.",
            },
        ],
        "remedy_calculation": {
            "formula": "contract_price * established_bps / 10000",
            "inputs": [
                {
                    "name": "contract_price",
                    "value_minor_units": 8_000_000,
                    "currency": "BRL",
                    "evidence_refs": [_ref()],
                },
                {
                    "name": "established_bps",
                    "value_minor_units": 5000,
                    "currency": "BRL",
                    "evidence_refs": [_ref()],
                },
            ],
            "result_minor_units": 4_000_000,
            "currency": "BRL",
        },
        "confidence": 0.82,
        "limitations": [],
        "abstention_reasons": [],
    }
    payload.update(overrides)
    return payload


def _verify(decision, manifest=None, admitted=None, chunks=None):
    return verify_decision(
        decision,
        manifest if manifest is not None else _manifest(),
        admitted if admitted is not None else _admitted(),
        chunks if chunks is not None else _chunks(),
        FRAMEWORK,
    )


def test_valid_structured_decision_passes():
    result = _verify(_valid_decision())
    assert result.valid is True
    assert result.errors == []
    assert result.verified_evidence_count >= 1
    assert result.verified_findings_count >= 1
    assert result.verified_rule_applications_count >= 1
    assert result.verified_calculations_count == 1


def test_unknown_document_is_rejected():
    decision = _valid_decision()
    decision["material_findings"][0]["evidence"][0]["document_id"] = "ghost-doc"
    result = _verify(decision)
    assert result.valid is False
    assert any(item.code == "unknown_document" for item in result.errors)


def test_unknown_chunk_is_rejected():
    decision = _valid_decision()
    decision["material_findings"][0]["evidence"][0]["chunk_id"] = "ghost-chunk"
    result = _verify(decision)
    assert result.valid is False
    assert any(item.code == "unknown_chunk" for item in result.errors)


def test_wrong_document_hash_is_rejected():
    decision = _valid_decision()
    decision["material_findings"][0]["evidence"][0]["document_sha256"] = "a" * 64
    result = _verify(decision)
    assert result.valid is False
    assert any(item.code == "document_hash_mismatch" for item in result.errors)


def test_chunk_linked_to_wrong_document():
    decision = _valid_decision()
    decision["material_findings"][0]["evidence"][0]["document_id"] = "other-doc"
    manifest = _manifest()
    manifest["documents"].append(
        {"id": "other-doc", "sha256": DOC_HASH, "admitted": True}
    )
    result = _verify(decision, manifest=manifest)
    assert result.valid is False
    assert any(item.code == "chunk_document_mismatch" for item in result.errors)


def test_document_not_admitted():
    result = _verify(_valid_decision(), admitted=[])
    assert result.valid is False
    assert any(item.code == "document_not_admitted" for item in result.errors)


def test_empty_admission_does_not_backfill_from_manifest():
    manifest = _manifest()
    manifest["contradictory"] = {"admitted_document_ids": [DOC_ID]}
    result = _verify(_valid_decision(), manifest=manifest, admitted=[])
    assert result.valid is False
    assert any(item.code == "document_not_admitted" for item in result.errors)


def test_runtime_text_must_match_locked_chunk_hash():
    chunks = _chunks()
    chunks[0] = {**chunks[0], "text": DOC_TEXT + " adulterado"}
    result = _verify(_valid_decision(), chunks=chunks)
    assert result.valid is False
    assert any(item.code == "chunk_hash_mismatch" for item in result.errors)


def test_quoted_text_missing():
    decision = _valid_decision()
    decision["material_findings"][0]["evidence"][0]["quoted_text"] = "texto que não existe"
    decision["material_findings"][0]["evidence"][0].pop("quoted_text_sha256", None)
    result = _verify(decision)
    assert result.valid is False
    assert any(item.code == "quoted_text_missing" for item in result.errors)


def test_quoted_text_hash_mismatch_is_caught_at_schema():
    try:
        EvidenceReference.model_validate(
            {**_ref(), "quoted_text_sha256": "b" * 64}
        )
        raised = False
    except Exception:
        raised = True
    assert raised is True


def test_established_finding_without_evidence():
    decision = _valid_decision()
    decision["material_findings"][0]["evidence"] = []
    result = _verify(decision)
    assert result.valid is False
    assert any(item.code == "established_without_evidence" for item in result.errors)


def test_unknown_rule_is_rejected():
    decision = _valid_decision()
    decision["rule_applications"][0]["rule_id"] = "no-such-rule"
    result = _verify(decision)
    assert result.valid is False
    assert any(item.code == "unknown_rule" for item in result.errors)


def test_incorrect_calculation_is_rejected():
    decision = _valid_decision()
    decision["remedy_calculation"]["result_minor_units"] = 1
    result = _verify(decision)
    assert result.valid is False
    assert any(item.code == "calculation_result_mismatch" for item in result.errors)


def test_monetary_value_without_evidence_ref():
    decision = _valid_decision()
    decision["remedy_calculation"]["inputs"][0]["evidence_refs"] = []
    result = _verify(decision)
    assert result.valid is False
    assert any(item.code == "monetary_value_without_evidence" for item in result.errors)


def test_partial_with_full_bps_is_inconsistent():
    decision = _valid_decision()
    decision["partial_claimant_bps"] = 10000
    result = _verify(decision)
    assert result.valid is False
    assert any(item.code == "partial_inconsistent_bps" for item in result.errors)


def test_valid_inconclusive_decision():
    decision = {
        "framework_id": FRAMEWORK.id,
        "framework_version": FRAMEWORK.version,
        "outcome": "inconclusive",
        "decision": "Evidência insuficiente sobre a extensão da entrega.",
        "material_findings": [
            {
                "finding_id": "f-gap",
                "proposition": "Não há prova da fração entregue.",
                "status": "insufficient",
                "evidence": [],
                "counterevidence": [],
                "reasoning": "O registro não quantifica a entrega.",
                "confidence": 0.2,
            }
        ],
        "rule_applications": [],
        "confidence": 0.2,
        "limitations": ["Prova insuficiente"],
        "abstention_reasons": ["insufficient_evidence"],
    }
    result = _verify(decision)
    assert result.valid is True


def test_out_of_scope_is_schema_valid_and_classified_as_inadmissible():
    decision = {
        "framework_id": FRAMEWORK.id,
        "framework_version": FRAMEWORK.version,
        "outcome": "inconclusive",
        "decision": "Matéria de saúde está fora do escopo.",
        "material_findings": [],
        "rule_applications": [],
        "confidence": 0.1,
        "limitations": ["Fora do escopo"],
        "abstention_reasons": ["out_of_scope"],
    }
    result = _verify(decision)
    assert result.valid is True
    normalized = normalize_legacy_decision(decision)
    assert normalized["procedure_conclusion"] == "inadmissible"


def test_post_lock_chunk_is_rejected():
    extra_chunk = {
        "id": "late-chunk",
        "document_id": DOC_ID,
        "sha256": CHUNK_HASH,
        "text": DOC_TEXT,
    }
    decision = _valid_decision()
    decision["material_findings"][0]["evidence"][0]["chunk_id"] = "late-chunk"
    result = _verify(decision, chunks=_chunks() + [extra_chunk])
    assert result.valid is False
    assert any(
        item.code in {"unknown_chunk", "post_lock_material"} for item in result.errors
    )


def test_orphan_finding_reference():
    decision = _valid_decision()
    decision["rule_applications"][0]["findings_used"] = ["does-not-exist"]
    result = _verify(decision)
    assert result.valid is False
    assert any(item.code == "orphan_finding_reference" for item in result.errors)


def test_invented_ids_are_not_accepted_because_the_model_emitted_them():
    decision = _valid_decision()
    decision["material_findings"][0]["evidence"][0]["document_id"] = "invented-by-model"
    result = _verify(decision)
    assert result.valid is False


def test_float_money_is_rejected_by_schema():
    try:
        CalculationInput.model_validate(
            {
                "name": "price",
                "value_minor_units": 10.5,  # type: ignore[arg-type]
                "currency": "BRL",
                "evidence_refs": [],
            }
        )
        ok = True
    except Exception:
        ok = False
    assert ok is False


def test_legacy_requires_human_review_is_readable_without_mutation():
    original = {
        "outcome": "inconclusive",
        "decision": "legado",
        "requires_human_review": True,
        "execution": {"mode": "openai"},
    }
    snapshot = deepcopy(original)
    normalized = normalize_legacy_decision(original)
    assert original == snapshot
    assert normalized["abstention_reasons"] == ["insufficient_evidence"]
    assert normalized["procedure_conclusion"] == "inconclusive"
    assert "requires_human_review" in original
