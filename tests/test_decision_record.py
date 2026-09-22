"""Auto da decisão: o documento final do procedimento.

A decisão não obriga ninguém; o que sai do procedimento é o auto, que a parte
leva ao Judiciário. Por isso ele precisa qualificar as partes, dizer o
desfecho (acordo, decisão ou por que não houve mérito) e ser verificável.
"""

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.attestation import generate_private_key_b64, public_key_info, load_private_key
from app.core.config import get_settings
from app.core.tax_id import InvalidTaxId, format_tax_id, normalize_tax_id
from app.db.models import Base, Case
from app.db.session import get_db
from app.main import app
from app.reports.decision_record import (
    DecisionRecordNotReady,
    build_decision_record,
    outcome_kind,
    verify_record,
)
from app.reports.decision_record_docx import build_decision_record_docx

CPF = "529.982.247-25"
CNPJ = "11.222.333/0001-81"
TEST_KEY_B64 = generate_private_key_b64()


def _docx_text(content: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        parts = [
            archive.read(name).decode("utf-8")
            for name in archive.namelist()
            if name.startswith("word/") and name.endswith(".xml")
        ]
    return "\n".join(parts)


@pytest.fixture()
def locked_case():
    """Caso já travado, na composição, com as duas partes qualificadas."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)

    def override_get_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        created = client.post(
            "/cases",
            json={"title": "Cobrança indevida", "claimant": "Ana Souza", "respondent": "Beta Telecom"},
        ).json()
        credentials = created["access_credentials"]
        for party, tax_id in (("claimant", CPF), ("respondent", CNPJ)):
            response = client.post(
                f"/cases/{created['id']}/consent",
                json={"party": party, "accepted": True, "tax_id": tax_id},
                headers={"X-Actor-Token": credentials[party]},
            )
            assert response.status_code == 200, response.text
        with sessions.begin() as db:
            case = db.get(Case, created["id"])
            case.manifest_locked = True
            case.status = "conciliation"
            case.conciliation_json = json.dumps(
                [{"round_number": 1, "possible_terms": ["Estorno de R$ 180,00 em 10 dias"]}]
            )
        yield client, created["id"], credentials
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def test_tax_id_accepts_cpf_cnpj_and_alphanumeric_cnpj():
    assert normalize_tax_id(CPF) == "52998224725"
    assert normalize_tax_id(CNPJ) == "11222333000181"
    # Exemplo oficial da Receita para o CNPJ alfanumérico.
    assert normalize_tax_id("12.ABC.345/01DE-35") == "12ABC34501DE35"
    assert format_tax_id("11222333000181") == CNPJ
    assert normalize_tax_id("  ") is None
    for invalid in ("111.111.111-11", "529.982.247-24", "11222333000182", "abc"):
        with pytest.raises(InvalidTaxId):
            normalize_tax_id(invalid)


def test_consent_records_tax_id_and_audits_only_its_hash(locked_case):
    client, case_id, credentials = locked_case
    case = client.get(f"/cases/{case_id}").json()
    assert case["consent"]["claimant"]["tax_id"] == "52998224725"
    assert case["consent"]["respondent"]["tax_id"] == "11222333000181"
    events = [
        event
        for event in client.get(f"/cases/{case_id}/audit").json()["events"]
        if event["event_type"] == "consent_accepted"
    ]
    assert all("tax_id_sha256" in event["payload"] for event in events)
    assert "52998224725" not in json.dumps(events)


def test_invalid_tax_id_is_rejected(locked_case):
    client, case_id, credentials = locked_case
    response = client.post(
        f"/cases/{case_id}/consent",
        json={"party": "claimant", "accepted": True, "tax_id": "123.456.789-00"},
        headers={"X-Actor-Token": credentials["claimant"]},
    )
    assert response.status_code == 422


def test_no_record_before_the_procedure_ends(locked_case):
    client, case_id, credentials = locked_case
    assert client.get(f"/cases/{case_id}/decision-record").status_code == 404
    response = client.post(
        f"/cases/{case_id}/decision-record",
        headers={"X-Actor-Token": credentials["claimant"]},
    )
    assert response.status_code == 409


def test_agreement_issues_record_with_the_accepted_terms(locked_case):
    client, case_id, credentials = locked_case
    for party in ("claimant", "respondent"):
        response = client.post(
            f"/cases/{case_id}/conciliation/1/agreement",
            json={"party": party, "accepted": True},
            headers={"X-Actor-Token": credentials[party]},
        )
        assert response.status_code == 200

    record = client.get(f"/cases/{case_id}/decision-record").json()
    assert record["outcome"]["kind"] == "agreement"
    assert record["agreement"]["terms"] == ["Estorno de R$ 180,00 em 10 dias"]
    assert record["agreement"]["accepted_at"]["claimant"]
    assert record["decision"] is None
    assert record["parties"]["claimant"]["tax_id"]["formatted"] == CPF
    assert record["parties"]["respondent"]["tax_id"]["kind"] == "cnpj"
    assert record["signature_algorithm"] == "HMAC-SHA256"

    verified = client.post("/decision-records/verify", json={"record": record}).json()
    assert verified["valid"] is True

    tampered = {**record, "agreement": {**record["agreement"], "terms": ["Estorno de R$ 1,00"]}}
    rejected = client.post("/decision-records/verify", json={"record": tampered}).json()
    assert rejected["valid"] is False
    assert rejected["hash_valid"] is False

    # Pedir de novo não cria outra versão: nada mudou no que o auto registra.
    again = client.post(
        f"/cases/{case_id}/decision-record",
        headers={"X-Actor-Token": credentials["respondent"]},
    ).json()
    assert again["record_hash"] == record["record_hash"]
    case = client.get(f"/cases/{case_id}").json()
    assert [item["record_number"] for item in case["decision_records"]] == [1]

    download = client.get(f"/cases/{case_id}/decision-record.docx")
    assert download.status_code == 200
    assert "auto-valinor" in download.headers["content-disposition"]
    text = _docx_text(download.content)
    assert "Termo de acordo" in text
    assert "Estorno de R$ 180,00 em 10 dias" in text
    assert CPF in text
    assert record["record_hash"] in text


def _decided_case_data():
    evidence = {
        "document_id": "doc-1",
        "document_sha256": "a" * 64,
        "chunk_id": "chunk-1",
        "chunk_sha256": "b" * 64,
        "quoted_text": "A cobrança de R$ 180,00 foi lançada após o cancelamento.",
        "support_type": "direct",
    }
    return {
        "id": "case-decided",
        "title": "Cobrança após cancelamento",
        "claimant": "Ana Souza",
        "respondent": "Beta Telecom",
        "status": "reviewed",
        "procedure_conclusion": "decided",
        "consent": {
            "claimant": {"accepted_at": "2026-09-01T10:00:00+00:00", "terms_version": "2026-09-22", "terms_sha256": "c" * 64, "tax_id": "52998224725"},
            "respondent": {"accepted_at": "2026-09-01T11:00:00+00:00", "terms_version": "2026-09-22", "terms_sha256": "c" * 64, "tax_id": None},
        },
        "documents": [{"id": "doc-1", "name": "fatura.pdf", "sha256": "a" * 64, "submitted_by": "claimant", "response_status": "challenged", "admitted": True}],
        "conciliation_rounds": [{"round_number": 1, "possible_terms": ["Estorno parcial"], "agreement": {"responses": {"claimant": {"accepted": False}}, "complete": False}}],
        "organized": {"summary": "Cobrança lançada depois do cancelamento.", "claimant_requests": ["Estorno de R$ 180,00"]},
        "locked_manifest": {"manifest_hash": "d" * 64, "platform_signature": "sig"},
        "decision": {
            "framework_id": "commercial_balanced_v1",
            "framework_version": "1.0.0",
            "outcome": "claimant",
            "procedure_conclusion": "decided",
            "decision": "Procede o pedido de estorno de R$ 180,00.",
            "material_findings": [
                {"finding_id": "F1", "proposition": "A cobrança ocorreu após o cancelamento.", "status": "established", "evidence": [evidence], "counterevidence": [], "reasoning": "A fatura data de depois do protocolo.", "confidence": 0.9}
            ],
            "rule_applications": [{"rule_id": "R1", "rule_version": "1.0.0", "findings_used": ["F1"], "application_reasoning": "Cobrança sem contraprestação.", "conclusion": "Estorno devido."}],
            "remedy_calculation": {"formula": "valor cobrado", "inputs": [{"name": "valor cobrado", "value_minor_units": 18000, "currency": "BRL", "evidence_refs": []}], "result_minor_units": 18000, "currency": "BRL"},
            "confidence": 0.9,
            "abstention_reasons": [],
        },
        "review": {"outcome": "approved", "approved": True, "issues": []},
        "verification": {"valid": True},
        "appeals": [],
        "attestation": None,
        "contest": {"contested": False},
    }


def test_decided_record_carries_grounds_and_operative_part():
    case_data = _decided_case_data()
    assert outcome_kind(case_data) == "decision"
    record = build_decision_record(case_data, audit_chain_head="e" * 64, audit_chain_length=12)
    assert record["decision"]["outcome_label"].startswith("Procedente")
    assert record["decision"]["material_findings"][0]["evidence"][0]["document_name"] == "fatura.pdf"
    assert "R$ 180,00" in record["outcome"]["summary"]
    assert record["parties"]["respondent"]["qualified"] is False
    assert record["integrity"]["audit_chain_length"] == 12

    text = _docx_text(build_decision_record_docx(record).getvalue())
    assert "Fundamentação" in text
    assert "Dispositivo" in text
    assert "A cobrança de R$ 180,00 foi lançada após o cancelamento." in text
    assert "Não informado pela parte" in text
    assert "não obriga as partes" in text


def test_no_merit_record_explains_the_abstention():
    case_data = _decided_case_data()
    case_data["procedure_conclusion"] = "inconclusive"
    case_data["decision"] = {
        **case_data["decision"],
        "outcome": "inconclusive",
        "procedure_conclusion": "inconclusive",
        "material_findings": [],
        "remedy_calculation": None,
        "abstention_reasons": ["insufficient_evidence"],
    }
    record = build_decision_record(case_data, audit_chain_head="", audit_chain_length=0)
    assert record["outcome"]["kind"] == "no_merit_decision"
    assert "provas insuficientes" in record["outcome"]["summary"]
    text = _docx_text(build_decision_record_docx(record).getvalue())
    assert "provas insuficientes" in text


def test_unfinished_case_has_no_record():
    case_data = _decided_case_data()
    case_data["review"] = None
    assert outcome_kind(case_data) is None
    with pytest.raises(DecisionRecordNotReady):
        build_decision_record(case_data, audit_chain_head="", audit_chain_length=0)


def test_new_version_points_to_the_previous_one():
    case_data = _decided_case_data()
    first = build_decision_record(case_data, audit_chain_head="", audit_chain_length=0)
    second = build_decision_record(case_data, audit_chain_head="", audit_chain_length=1, previous=first)
    assert second["record_number"] == 2
    assert second["supersedes_record_hash"] == first["record_hash"]


def test_ed25519_record_is_verifiable_with_the_public_key(monkeypatch):
    monkeypatch.setenv("PLATFORM_ED25519_PRIVATE_KEY", TEST_KEY_B64)
    get_settings.cache_clear()
    try:
        record = build_decision_record(_decided_case_data(), audit_chain_head="", audit_chain_length=0)
        assert record["signature_algorithm"] == "Ed25519"
        public = public_key_info(load_private_key(TEST_KEY_B64))
        assert record["key_id"] == public["key_id"]
        valid, checks = verify_record(record, public_key_b64=public["public_key_b64"])
        assert valid and checks["key_status"] == "provided"
        valid, checks = verify_record(record)
        assert valid and checks["key_status"] == "active"

        forged = {**record, "outcome": {**record["outcome"], "binding": True}}
        forged_valid, _ = verify_record(forged, public_key_b64=public["public_key_b64"])
        assert forged_valid is False
    finally:
        get_settings.cache_clear()
