import os

import pytest

os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("PLATFORM_SIGNING_SECRET", "test-signing-secret")

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.core.attestation import (  # noqa: E402
    AttestationError,
    build_decision_attestation,
    generate_private_key_b64,
    load_private_key,
    public_key_info,
    verify_attestation,
)
from app.core.audit import build_audit_event, verify_audit_chain  # noqa: E402


TEST_KEY_B64 = generate_private_key_b64()


@pytest.fixture()
def attestation_env(monkeypatch):
    monkeypatch.setenv("PLATFORM_ED25519_PRIVATE_KEY", TEST_KEY_B64)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _audit_chain(length=3):
    events = []
    previous = ""
    for index in range(length):
        event = build_audit_event(f"event_{index}", {"step": index}, previous)
        events.append(event)
        previous = event["event_hash"]
    return events


def _approved_case_data():
    return {
        "id": "case-123",
        "escrow_id": "escrow-abc",
        "locked_manifest": {
            "manifest_hash": "f" * 64,
            "platform_version": "0.5.0",
            "procedure_version": "mvp-procedure-0.4",
        },
        "decision": {
            "outcome": "partial",
            "partial_claimant_bps": 6500,
            "confidence": 0.83,
            "requires_human_review": False,
            "execution": {"mode": "openai"},
        },
        "review": {
            "approved": True,
            "requires_human_review": False,
            "execution": {"mode": "openai"},
        },
    }


def test_attestation_roundtrip_signature_and_split(attestation_env):
    events = _audit_chain()
    attestation = build_decision_attestation(
        _approved_case_data(),
        audit_chain_head=events[-1]["event_hash"],
        audit_chain_length=len(events),
    )

    assert attestation["decision"]["split"] == {
        "claimant_bps": 6500,
        "respondent_bps": 3500,
    }
    assert attestation["signature_algorithm"] == "Ed25519"
    assert attestation["platform"]["key_id"] == public_key_info()["key_id"]

    valid, checks = verify_attestation(attestation)
    assert valid is True
    assert checks == {"hash_valid": True, "signature_valid": True}

    # Verificação por terceiro, apenas com a chave pública
    public_b64 = public_key_info()["public_key_b64"]
    valid_external, _ = verify_attestation(attestation, public_key_b64=public_b64)
    assert valid_external is True


def test_tampered_attestation_is_rejected(attestation_env):
    events = _audit_chain()
    attestation = build_decision_attestation(
        _approved_case_data(),
        audit_chain_head=events[-1]["event_hash"],
        audit_chain_length=len(events),
    )

    # Adversário tenta inverter o split a favor do reclamante
    tampered = dict(attestation)
    tampered["decision"] = dict(attestation["decision"])
    tampered["decision"]["split"] = {"claimant_bps": 10000, "respondent_bps": 0}

    valid, checks = verify_attestation(tampered)
    assert valid is False
    assert checks["hash_valid"] is False

    # Adversário recalcula o hash mas não tem a chave privada
    from app.core.canonical import canonical_hash

    rehashed = {
        k: v for k, v in tampered.items()
        if k not in ("attestation_hash", "signature", "signature_algorithm")
    }
    tampered["attestation_hash"] = canonical_hash(rehashed)
    valid, checks = verify_attestation(tampered)
    assert valid is False
    assert checks["hash_valid"] is True
    assert checks["signature_valid"] is False


def test_wrong_public_key_fails_verification(attestation_env):
    events = _audit_chain()
    attestation = build_decision_attestation(
        _approved_case_data(),
        audit_chain_head=events[-1]["event_hash"],
        audit_chain_length=len(events),
    )
    other_key = generate_private_key_b64()
    other_public = public_key_info(load_private_key(other_key))["public_key_b64"]
    valid, checks = verify_attestation(attestation, public_key_b64=other_public)
    assert valid is False
    assert checks["signature_valid"] is False


@pytest.mark.parametrize(
    "mutation, message_part",
    [
        (lambda d: d["decision"].update(outcome="inconclusive"), "inconclusiva"),
        (lambda d: d["review"].update(approved=False), "não aprovou"),
        (
            lambda d: d["decision"].update(requires_human_review=True),
            "revisão humana",
        ),
        (
            lambda d: d["review"].update(requires_human_review=True),
            "revisão humana",
        ),
        (
            lambda d: d["decision"].update(execution={"mode": "safe_fallback"}),
            "modo seguro",
        ),
        (
            lambda d: d["review"].update(execution={"mode": "safe_fallback"}),
            "modo seguro",
        ),
        (
            lambda d: d["decision"].update(partial_claimant_bps=None),
            "partial_claimant_bps",
        ),
        (
            lambda d: d["decision"].update(partial_claimant_bps=20000),
            "partial_claimant_bps",
        ),
        (lambda d: d.update(locked_manifest=None), "manifesto"),
    ],
)
def test_non_executable_states_never_produce_attestation(
    attestation_env, mutation, message_part
):
    case_data = _approved_case_data()
    mutation(case_data)
    with pytest.raises(AttestationError) as excinfo:
        build_decision_attestation(case_data, "a" * 64, 1)
    assert message_part in str(excinfo.value)


def test_missing_key_disables_issuance(monkeypatch):
    monkeypatch.delenv("PLATFORM_ED25519_PRIVATE_KEY", raising=False)
    get_settings.cache_clear()
    with pytest.raises(AttestationError):
        build_decision_attestation(_approved_case_data(), "a" * 64, 1)
    get_settings.cache_clear()


def test_tampered_audit_chain_is_detected():
    events = _audit_chain(5)
    valid, errors = verify_audit_chain(events)
    assert valid is True and errors == []

    # Adversário reescreve o payload de um evento antigo
    events[1]["payload"]["step"] = 999
    valid, errors = verify_audit_chain(events)
    assert valid is False
    assert any("Event 2" in error for error in errors)

    # Mesmo recalculando o hash do evento adulterado, o elo seguinte quebra
    from app.core.canonical import canonical_hash

    rebuilt = {
        "event_type": events[1]["event_type"],
        "timestamp_utc": events[1]["timestamp_utc"],
        "payload": events[1]["payload"],
        "previous_hash": events[1]["previous_hash"],
    }
    events[1]["event_hash"] = canonical_hash(rebuilt)
    valid, errors = verify_audit_chain(events)
    assert valid is False
    assert any("Event 3" in error for error in errors)
