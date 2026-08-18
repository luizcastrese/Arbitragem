"""Ancoragem da attestation em Nostr: o payload publicado nunca pode conter
o teor da decisão (outcome, split) — só hash, assinatura e identificadores.
Usa `nostr_sdk.LocalRelay`, um relay Nostr real rodando em processo (loopback,
sem tocar infraestrutura externa), para validar publicação de ponta a ponta
sem depender de rede ou mocks da biblioteca."""

import asyncio
import os
import threading
import time

import pytest

os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("PLATFORM_SIGNING_SECRET", "test-signing-secret")

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.core import nostr_anchor as nostr_anchor_module  # noqa: E402
from app.core.attestation import (  # noqa: E402
    build_decision_attestation,
    generate_private_key_b64,
    load_private_key,
)
from app.core.audit import build_audit_event  # noqa: E402
from app.core.nostr_anchor import (  # noqa: E402
    build_anchor_payload,
    generate_private_key_hex,
    publish_attestation_anchor,
)
from nostr_sdk import Keys, LocalRelay, RelayBuilder  # noqa: E402

TEST_ED25519_KEY_B64 = generate_private_key_b64()


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
        "id": "case-nostr-1",
        "escrow_id": "escrow-nostr-1",
        "locked_manifest": {
            "manifest_hash": "f" * 64,
            "platform_version": "0.5.0",
            "procedure_version": "mvp-procedure-0.4",
        },
        "decision": {
            "outcome": "respondent",
            "confidence": 0.91,
            "requires_human_review": False,
            "execution": {"mode": "openai"},
        },
        "review": {
            "approved": True,
            "requires_human_review": False,
            "execution": {"mode": "openai"},
        },
    }


@pytest.fixture()
def attestation():
    events = _audit_chain()
    return build_decision_attestation(
        case_data=_approved_case_data(),
        audit_chain_head=events[-1]["event_hash"],
        audit_chain_length=len(events),
        private_key=load_private_key(TEST_ED25519_KEY_B64),
    )


@pytest.fixture()
def local_relay():
    """Sobe um relay Nostr real, local e efêmero, numa thread própria — o
    mesmo modelo de execução de um endpoint síncrono do FastAPI rodando no
    threadpool do Starlette (sem event loop no thread chamador)."""
    holder = {}

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def _start():
            relay = LocalRelay(RelayBuilder())
            holder["relay"] = relay
            holder["url"] = await relay.url()
            await relay.run()

        loop.run_until_complete(_start())

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    for _ in range(200):
        if "url" in holder:
            break
        time.sleep(0.02)
    else:
        raise RuntimeError("Local relay não iniciou a tempo")

    yield str(holder["url"])
    holder["relay"].shutdown()


def test_anchor_payload_never_contains_decision_content(attestation):
    payload = build_anchor_payload(attestation)

    assert set(payload.keys()) == {
        "v",
        "case_id",
        "escrow_id",
        "attestation_hash",
        "signature",
        "signature_algorithm",
        "platform_key_id",
        "issued_at_utc",
        "contest_window_ends_utc",
    }
    assert payload["case_id"] == "case-nostr-1"
    assert payload["attestation_hash"] == attestation["attestation_hash"]
    assert payload["signature"] == attestation["signature"]
    # O outcome/split da decisão nunca pode vazar no payload público.
    serialized = str(payload)
    assert "respondent" not in serialized
    assert "outcome" not in serialized
    assert "decision" not in payload
    assert "review" not in payload


def test_disabled_by_default_without_config(attestation, monkeypatch):
    monkeypatch.delenv("NOSTR_PRIVATE_KEY_HEX", raising=False)
    monkeypatch.delenv("NOSTR_RELAYS", raising=False)
    get_settings.cache_clear()
    try:
        assert publish_attestation_anchor(attestation) is None
    finally:
        get_settings.cache_clear()


def test_publish_anchor_end_to_end_via_local_relay(attestation, local_relay, monkeypatch):
    monkeypatch.setenv("NOSTR_PRIVATE_KEY_HEX", Keys.generate().secret_key().to_hex())
    monkeypatch.setenv("NOSTR_RELAYS", local_relay)
    get_settings.cache_clear()
    try:
        result = publish_attestation_anchor(attestation)
        assert result is not None
        assert result["event_id"]
        assert result["relays"] == [local_relay]
        assert result["published_at_utc"]
    finally:
        get_settings.cache_clear()


def test_publish_anchor_fails_gracefully_when_relay_unreachable(attestation, monkeypatch):
    monkeypatch.setenv("NOSTR_PRIVATE_KEY_HEX", Keys.generate().secret_key().to_hex())
    # Porta sem nada escutando: a conexão falha rápido em vez de esperar
    # o timeout inteiro de publicação.
    monkeypatch.setenv("NOSTR_RELAYS", "ws://127.0.0.1:1")
    monkeypatch.setattr(nostr_anchor_module, "PUBLISH_TIMEOUT_SECONDS", 2)
    get_settings.cache_clear()
    try:
        # Nunca levanta exceção — best-effort.
        assert publish_attestation_anchor(attestation) is None
    finally:
        get_settings.cache_clear()


def test_publish_anchor_skipped_when_attestation_has_no_case_id(monkeypatch):
    monkeypatch.setenv("NOSTR_PRIVATE_KEY_HEX", Keys.generate().secret_key().to_hex())
    monkeypatch.setenv("NOSTR_RELAYS", "ws://127.0.0.1:1")
    get_settings.cache_clear()
    try:
        assert publish_attestation_anchor({"attestation_hash": "x"}) is None
    finally:
        get_settings.cache_clear()


def test_generate_private_key_hex_roundtrips():
    hex_key = generate_private_key_hex()
    assert Keys.parse(hex_key).secret_key().to_hex() == hex_key


def test_save_nostr_anchor_does_not_touch_case_status():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db.models import Base
    from app.db.repository import case_to_dict, create_case, get_case, save_nostr_anchor

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(
        bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
    )
    Base.metadata.create_all(bind=engine)
    db = session_factory()
    try:
        case = create_case(
            db,
            title="Caso",
            claimant="Cliente",
            respondent="Empresa",
            claimant_token_hash="x",
            respondent_token_hash="y",
            created_by="claimant",
        )
        status_before = case.status

        anchor = {
            "event_id": "abc123",
            "relays": ["ws://127.0.0.1:1"],
            "published_at_utc": "2026-01-01T00:00:00+00:00",
        }
        save_nostr_anchor(db, case, anchor)

        db.expire_all()
        fetched = get_case(db, case.id)
        assert fetched.status == status_before

        full = case_to_dict(fetched)
        assert full["nostr_anchor"] == anchor
        assert any(
            event["event_type"] == "attestation_anchored_nostr"
            for event in full["audit_log"]
        )
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


# --- Âncora do topo da cadeia de auditoria -----------------------------------


def test_audit_anchor_payload_carries_only_the_head_and_the_count():
    """A âncora da auditoria não pode virar um vazamento do procedimento.

    Ela existe para congelar publicamente o topo da cadeia; o que a cadeia
    contém — tipos de ato, carimbos, payloads — continua fora do relay.
    """
    from app.core.nostr_anchor import build_audit_anchor_payload

    events = _audit_chain(4)
    payload = build_audit_anchor_payload("case-audit-1", events)

    assert set(payload.keys()) == {
        "v",
        "kind",
        "case_id",
        "audit_head_hash",
        "event_count",
    }
    assert payload["audit_head_hash"] == events[-1]["event_hash"]
    assert payload["event_count"] == 4
    serialized = str(payload)
    for event in events:
        assert event["event_type"] not in serialized
        assert event["timestamp_utc"] not in serialized

    assert build_audit_anchor_payload("case-audit-1", []) is None


def test_audit_anchor_publishes_end_to_end_and_keeps_its_own_identifier(
    local_relay, monkeypatch
):
    """A âncora da auditoria não pode sobrescrever a da attestation.

    Kind 30078 é parametrizado-substituível: dois eventos com o mesmo `d`
    substituem um ao outro no relay. Se a âncora da auditoria reusasse o
    `case_id` puro, publicá-la apagaria a âncora da attestation.
    """
    from app.core.nostr_anchor import publish_audit_anchor

    monkeypatch.setenv("NOSTR_PRIVATE_KEY_HEX", Keys.generate().secret_key().to_hex())
    monkeypatch.setenv("NOSTR_RELAYS", local_relay)
    get_settings.cache_clear()
    try:
        events = _audit_chain(5)
        result = publish_audit_anchor("case-audit-1", events)
        assert result is not None
        assert result["event_id"]
        assert result["relays"] == [local_relay]
        assert result["audit_head_hash"] == events[-1]["event_hash"]
        assert result["event_count"] == 5

        # Uma segunda âncora, com a cadeia mais adiantada, é um registro novo.
        segunda = publish_audit_anchor("case-audit-1", _audit_chain(9))
        assert segunda["event_id"] != result["event_id"]
    finally:
        get_settings.cache_clear()


def test_audit_anchor_is_skipped_without_configuration(monkeypatch):
    from app.core.nostr_anchor import publish_audit_anchor

    monkeypatch.delenv("NOSTR_PRIVATE_KEY_HEX", raising=False)
    monkeypatch.delenv("NOSTR_RELAYS", raising=False)
    get_settings.cache_clear()
    try:
        assert publish_audit_anchor("case-audit-1", _audit_chain()) is None
    finally:
        get_settings.cache_clear()


def test_audit_anchor_fails_gracefully_when_relay_unreachable(monkeypatch):
    from app.core.nostr_anchor import publish_audit_anchor

    monkeypatch.setenv("NOSTR_PRIVATE_KEY_HEX", Keys.generate().secret_key().to_hex())
    monkeypatch.setenv("NOSTR_RELAYS", "ws://127.0.0.1:1")
    monkeypatch.setattr(nostr_anchor_module, "PUBLISH_TIMEOUT_SECONDS", 2)
    get_settings.cache_clear()
    try:
        # O rito não pode parar porque um relay caiu.
        assert publish_audit_anchor("case-audit-1", _audit_chain()) is None
    finally:
        get_settings.cache_clear()
