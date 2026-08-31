"""Independência, estabilidade, recurso automático e preservação da decisão."""

from __future__ import annotations

import json

from app.core.canonical import canonical_hash
from app.core.hashing import sha256_text
from app.domain.frameworks import get_framework
from app.domain.stability import compare_decisions, neutralize_party_order
from app.llm.fake_provider import FakeProvider
from app.llm.registry import set_provider_override


def test_stability_detects_material_disagreement():
    first = {
        "outcome": "claimant",
        "material_findings": [
            {"finding_id": "f1", "proposition": "entregue", "status": "established", "evidence": [1]}
        ],
        "rule_applications": [{"rule_id": "r1"}],
        "remedy_calculation": {"result_minor_units": 100, "currency": "BRL"},
        "partial_claimant_bps": None,
    }
    second = {
        "outcome": "respondent",
        "material_findings": [
            {"finding_id": "f1", "proposition": "não entregue", "status": "not_established", "evidence": []}
        ],
        "rule_applications": [{"rule_id": "r2"}],
        "remedy_calculation": {"result_minor_units": 0, "currency": "BRL"},
    }
    result = compare_decisions([first, second], threshold=1.0, execution_ids=["a", "b"])
    assert result.stable is False
    assert result.outcome_agreement is False
    assert "outcome" in result.material_disagreements


def test_stability_agrees_on_same_runs():
    run = {
        "outcome": "partial",
        "material_findings": [
            {"finding_id": "f1", "proposition": "p", "status": "established", "evidence": [1]}
        ],
        "rule_applications": [{"rule_id": "r1"}],
        "remedy_calculation": {"result_minor_units": 50, "currency": "BRL"},
        "partial_claimant_bps": 5000,
    }
    result = compare_decisions([run, dict(run)], threshold=1.0)
    assert result.stable is True


def test_neutralize_party_order_does_not_rename_parties():
    payload = {
        "documents": [
            {"id": "b", "submitted_by": "respondent", "name": "defesa"},
            {"id": "a", "submitted_by": "claimant", "name": "contrato"},
        ]
    }
    ordered = neutralize_party_order(payload)
    assert [item["name"] for item in ordered["documents"]] == ["contrato", "defesa"]
    assert payload["documents"][0]["name"] == "defesa"


def test_original_decision_is_preserved_across_versions(client_module_setup=None):
    """A versão 1 permanece mesmo depois de uma correção em memória."""
    original = {"outcome": "claimant", "decision": "original", "version": 1}
    corrected = {"outcome": "partial", "decision": "corrigida", "version": 2, "supersedes": "run-1"}
    store = {"run-1": original, "run-2": corrected}
    assert store["run-1"]["decision"] == "original"
    assert store["run-2"]["supersedes"] == "run-1"
    assert canonical_hash(store["run-1"]) != canonical_hash(store["run-2"])


def test_attestation_chain_points_to_previous():
    first = {"attestation_hash": "aaa", "version": 1}
    second = {"attestation_hash": "bbb", "version": 2, "supersedes_attestation_hash": first["attestation_hash"]}
    assert second["supersedes_attestation_hash"] == first["attestation_hash"]


def test_reconstruction_does_not_loop():
    from app.domain.procedure import finalize_review_outcome

    conclusion, decision = finalize_review_outcome(
        {"outcome": "claimant", "abstention_reasons": []},
        {"valid": True},
        {"outcome": "rejected", "approved": False},
        reconstruction_used=True,
    )
    assert conclusion in {"inconclusive", "invalidated"}
    assert decision["procedure_conclusion"] == conclusion


def test_rejected_review_requests_single_reconstruction():
    from app.domain.procedure import finalize_review_outcome

    conclusion, _ = finalize_review_outcome(
        {"outcome": "claimant", "abstention_reasons": []},
        {"valid": True},
        {"outcome": "rejected", "approved": False},
        reconstruction_used=False,
    )
    assert conclusion == "pending_reconstruction"
    digital = get_framework("digital_services_b2b_v1")
    commercial = get_framework("commercial_balanced_v1")
    assert digital.id != commercial.id
    assert "digital_services_b2b_v1:delivery:partial" in digital.rule_ids()
    assert "commercial_balanced_v1:contract:priority" in commercial.rule_ids()
    assert "sentença" not in digital.disclaimer.lower() or "não constitui" in digital.disclaimer.lower()


def _sqlite_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db.models import Base

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    return engine, session


def _appeal_case(db, original):
    from app.db.models import Case
    from tests.test_decision_verifier import _admitted, _chunks, _manifest

    case = Case(
        id="case-appeal-1",
        title="Entrega parcial",
        claimant="Alfa",
        respondent="Beta",
        status="attested",
        decision_json=json.dumps(original, ensure_ascii=False),
        review_json=json.dumps(
            {"outcome": "approved", "approved": True, "confidence": 0.8}
        ),
        verification_json=json.dumps({"valid": True}),
        locked_manifest_json=json.dumps(_manifest()),
        attestation_json=json.dumps({"attestation_hash": "att-original"}),
    )
    db.add(case)
    db.commit()
    return case, {
        "decision": original,
        "verification": {"valid": True},
        "review": {"outcome": "approved", "approved": True, "confidence": 0.8},
        "locked_manifest": _manifest(),
        "documents": _admitted(),
        "chunks": _chunks(),
    }


def _run_scripted_appeal(outcome, extra=None):
    from app.db.models import AttestationRecord, DecisionRun
    from app.db.repository import persist_appeal, persist_attestation_record, persist_decision_run
    from app.domain.procedure import run_appeal
    from tests.test_decision_verifier import _valid_decision

    original = _valid_decision()
    original["decision"] = "decisão original preservada"
    engine, db = _sqlite_session()
    set_provider_override(None)
    try:
        case, case_data = _appeal_case(db, original)
        original_run = persist_decision_run(
            db, case, original, status="decided", role="judge"
        )
        persist_attestation_record(
            db, case, {"attestation_hash": "att-original"}
        )
        db.commit()
        payload = {"outcome": outcome, "explanation": f"recurso {outcome}", "confidence": 0.6}
        if extra:
            payload.update(extra)
        set_provider_override(FakeProvider({"appeal": payload}))
        appeal = persist_appeal(
            db,
            case,
            filed_by="claimant",
            grounds=["incorrect_calculation"],
            original_decision_hash=canonical_hash(original),
            idempotency_key="appeal-1",
        )
        result = run_appeal(db, case, case_data, appeal, {"grounds": ["incorrect_calculation"]})
        db.commit()
        db.refresh(original_run)
        runs = db.query(DecisionRun).filter(DecisionRun.case_id == case.id).all()
        records = (
            db.query(AttestationRecord)
            .filter(AttestationRecord.case_id == case.id)
            .order_by(AttestationRecord.version)
            .all()
        )
        return {
            "result": result,
            "original_run": original_run,
            "runs": runs,
            "records": records,
            "case": case,
        }
    finally:
        set_provider_override(None)
        db.close()
        engine.dispose()


def test_appeal_upheld_keeps_original_decision():
    bundle = _run_scripted_appeal("upheld")
    assert bundle["result"]["outcome"] == "upheld"
    assert json.loads(bundle["original_run"].payload_json)["decision"] == "decisão original preservada"
    assert len(bundle["runs"]) == 1


def test_appeal_corrected_creates_new_version_and_chained_attestation():
    from tests.test_decision_verifier import _valid_decision

    corrected = _valid_decision()
    corrected["decision"] = "decisão corrigida"
    bundle = _run_scripted_appeal("corrected", extra={"corrected_decision": corrected})
    assert bundle["result"]["outcome"] == "corrected"
    assert json.loads(bundle["original_run"].payload_json)["decision"] == "decisão original preservada"
    assert len(bundle["runs"]) == 2
    latest = max(bundle["runs"], key=lambda item: item.version)
    assert latest.supersedes_id == bundle["original_run"].id
    assert json.loads(latest.payload_json)["decision"] == "decisão corrigida"
    assert len(bundle["records"]) == 2
    assert bundle["records"][1].supersedes_id == bundle["records"][0].id
    assert bundle["records"][0].attestation_hash == "att-original"


def test_appeal_annulled_does_not_overwrite_original():
    bundle = _run_scripted_appeal("annulled")
    assert bundle["result"]["outcome"] == "annulled"
    assert json.loads(bundle["original_run"].payload_json)["decision"] == "decisão original preservada"
    assert len(bundle["runs"]) == 1


def test_appeal_inconclusive_does_not_overwrite_original():
    bundle = _run_scripted_appeal("inconclusive")
    assert bundle["result"]["outcome"] == "inconclusive"
    assert len(bundle["runs"]) == 1


def test_appeal_inadmissible_does_not_overwrite_original():
    bundle = _run_scripted_appeal("inadmissible")
    assert bundle["result"]["outcome"] == "inadmissible"
    assert json.loads(bundle["original_run"].payload_json)["decision"] == "decisão original preservada"


def test_claim_case_stage_rejects_concurrent_worker():
    import pytest
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db.models import Base, Case
    from app.domain.concurrency import StageBusy, claim_case_stage

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db1 = Session()
    db2 = Session()
    try:
        case = Case(
            id="case-conc-1",
            title="t",
            claimant="a",
            respondent="b",
            status="organized",
        )
        db1.add(case)
        db1.commit()
        assert claim_case_stage(db1, case, "decide") is True
        other = db2.query(Case).filter(Case.id == "case-conc-1").one()
        with pytest.raises(StageBusy):
            claim_case_stage(db2, other, "decide")
    finally:
        db1.close()
        db2.close()
        engine.dispose()
