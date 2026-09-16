"""Rotação da chave de assinatura.

O que estes testes protegem: uma attestation emitida antes de uma rotação
precisa continuar verificável depois dela. Se este arquivo quebrar, a rotação
passou a invalidar decisões já emitidas — que é exatamente o que executores
externos não podem sofrer.
"""

import os

import pytest

from app.core.attestation import (
    AttestationError,
    build_decision_attestation,
    generate_private_key_b64,
    key_id_for,
    key_set,
    load_private_key,
    public_key_info,
    retired_public_keys,
    verify_attestation,
)
from app.core.config import get_settings
from tests.test_attestation import _approved_case_data, _audit_chain


def _issue_with(private_key_b64: str):
    events = _audit_chain()
    return build_decision_attestation(
        _approved_case_data(),
        audit_chain_head=events[-1]["event_hash"],
        audit_chain_length=len(events),
        private_key=load_private_key(private_key_b64),
    )


@pytest.fixture()
def rotating_env(monkeypatch):
    """Emite com a chave antiga, depois roda com a nova ativa e a antiga
    aposentada."""
    old_private = generate_private_key_b64()
    new_private = generate_private_key_b64()
    old_public = public_key_info(load_private_key(old_private))["public_key_b64"]

    monkeypatch.setenv("PLATFORM_ED25519_PRIVATE_KEY", old_private)
    monkeypatch.setenv("PLATFORM_ED25519_RETIRED_PUBLIC_KEYS", "")
    get_settings.cache_clear()
    attestation = _issue_with(old_private)

    monkeypatch.setenv("PLATFORM_ED25519_PRIVATE_KEY", new_private)
    monkeypatch.setenv("PLATFORM_ED25519_RETIRED_PUBLIC_KEYS", old_public)
    get_settings.cache_clear()

    yield attestation, old_private, new_private, old_public

    get_settings.cache_clear()


def test_attestation_antiga_continua_valida_apos_rotacao(rotating_env):
    attestation, _old, _new, old_public = rotating_env

    valid, checks = verify_attestation(attestation)

    assert valid is True
    assert checks["signature_valid"] is True
    assert checks["key_status"] == "retired"
    assert checks["key_id"] == key_id_for(old_public)


def test_attestation_nova_e_verificada_pela_chave_ativa(rotating_env):
    _antiga, _old, new_private, _old_public = rotating_env

    nova = _issue_with(new_private)
    valid, checks = verify_attestation(nova)

    assert valid is True
    assert checks["key_status"] == "active"
    assert checks["key_id"] == public_key_info()["key_id"]
    assert nova["platform"]["key_id"] == checks["key_id"]


def test_chave_desconhecida_nao_verifica(rotating_env):
    """Sem a antiga na lista de aposentadas, a verificação falha: é isso que
    o operador perde se rotacionar sem registrar a chave anterior."""
    _attestation, old_private, _new, _old_public = rotating_env
    antiga = _issue_with(old_private)

    os.environ["PLATFORM_ED25519_RETIRED_PUBLIC_KEYS"] = ""
    get_settings.cache_clear()

    valid, checks = verify_attestation(antiga)

    assert valid is False
    assert checks["signature_valid"] is False
    assert checks["key_id"] is None


def test_key_set_publica_ativa_e_aposentadas(rotating_env):
    _attestation, _old, _new, old_public = rotating_env

    published = key_set()

    assert published["active"]["status"] == "active"
    assert published["active"]["public_key_b64"] == public_key_info()["public_key_b64"]
    assert [item["public_key_b64"] for item in published["retired"]] == [old_public]
    assert len(published["keys"]) == 2


def test_chave_aposentada_malformada_e_recusada(monkeypatch):
    monkeypatch.setenv("PLATFORM_ED25519_RETIRED_PUBLIC_KEYS", "nao-e-base64!!")
    get_settings.cache_clear()
    with pytest.raises(AttestationError):
        retired_public_keys()
    get_settings.cache_clear()
