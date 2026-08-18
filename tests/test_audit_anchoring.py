"""A cadeia de auditoria prova encadeamento, não origem.

`verify_audit_chain` pega adulteração parcial: reescrever um evento quebra o
`previous_hash` do seguinte. Mas o encadeamento é SHA-256 puro, sem segredo —
quem tiver escrita no banco reescreve todos os eventos, recalcula todos os
hashes e a verificação local volta a passar.

A âncora pública fecha essa porta: o topo de um momento fica registrado em
relays que a plataforma não controla, e a cadeia de hoje passa a ter de bater
com o que já foi publicado.
"""

import asyncio
import os
import threading
import time

import pytest

os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("PLATFORM_SIGNING_SECRET", "test-signing-secret")

# `tests.test_api` prepara o ambiente e importa `app.main` com ele já posto.
# Importar antes daqui evita que `app.main` capture settings de outro ambiente.
from tests.test_timestamping import BLOCK_HEIGHT, calendar  # noqa: E402,F401

from tests.test_api import (  # noqa: E402,F401 - a fixture `client` vem daqui
    accept_procedure,
    actor_headers,
    add_contract,
    client,
    close_submissions,
    complete_contradictory,
    create_case,
)

from app.core.audit import build_audit_event, verify_audit_chain  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.nostr_anchor import build_audit_anchor_payload  # noqa: E402
from app.main import _anchors_consistent  # noqa: E402
from nostr_sdk import Keys, LocalRelay, RelayBuilder  # noqa: E402


def _chain(length, marker="original"):
    events = []
    previous = ""
    for index in range(length):
        event = build_audit_event(f"event_{index}", {"step": index, "m": marker}, previous)
        events.append(event)
        previous = event["event_hash"]
    return events


@pytest.fixture()
def local_relay():
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


def test_a_full_chain_rewrite_still_verifies_but_breaks_the_anchor():
    """O ataque que a verificação local não pega, e que a âncora pega."""
    original = _chain(6)
    anchor = build_audit_anchor_payload("case-1", original[:4])
    anchors = [{**anchor, "milestone": "manifest_locked"}]

    # Cadeia íntegra: encadeamento válido e coerente com o que foi ancorado.
    assert verify_audit_chain(original)[0] is True
    assert _anchors_consistent(original, anchors) is True

    # Adversário reescreve tudo e reencadeia do zero.
    forjada = _chain(6, marker="reescrito")

    # A verificação local não vê problema nenhum: os hashes fecham entre si.
    assert verify_audit_chain(forjada)[0] is True
    # Mas o evento na posição ancorada não exibe mais o hash publicado.
    assert _anchors_consistent(forjada, anchors) is False


def test_anchor_detects_truncation_and_ignores_anchors_without_a_head():
    original = _chain(6)
    anchors = [{**build_audit_anchor_payload("case-1", original[:5]), "milestone": "x"}]

    # Cadeia encurtada abaixo da posição ancorada.
    assert _anchors_consistent(original[:3], anchors) is False
    # Âncora malformada não derruba a conferência das demais.
    assert _anchors_consistent(original, [{"milestone": "sem-hash"}]) is True


def test_procedure_anchors_the_chain_at_its_milestones(client, local_relay, monkeypatch):
    """De ponta a ponta: o rito ancora sozinho, e a API expõe o que foi ancorado."""
    monkeypatch.setenv("NOSTR_PRIVATE_KEY_HEX", Keys.generate().secret_key().to_hex())
    monkeypatch.setenv("NOSTR_RELAYS", local_relay)
    get_settings.cache_clear()
    try:
        case_id = create_case(client)["id"]
        accept_procedure(client, case_id)
        document = add_contract(client, case_id)["document"]
        complete_contradictory(client, case_id, document["id"])

        # Antes da trava não há o que ancorar: a produção ainda está aberta.
        assert client.get(f"/cases/{case_id}/audit").json()["anchors"] == []

        close_submissions(client, case_id)
        audit = client.get(f"/cases/{case_id}/audit").json()

        assert audit["valid"] is True
        assert audit["anchors_consistent"] is True
        assert audit["head_hash"] == audit["events"][-1]["event_hash"]

        milestones = [item["milestone"] for item in audit["anchors"]]
        # Em modo seguro o caso corre até o fim: a trava e o encerramento são
        # ancorados separadamente, e cada topo se compromete com todo o que
        # veio antes dele.
        assert milestones == ["manifest_locked", "case_closed"]
        for anchor in audit["anchors"]:
            assert anchor["nostr"]["event_id"]
            assert anchor["nostr"]["relays"] == [local_relay]
            # Sem calendário configurado neste teste, o carimbo não acontece —
            # e a âncora existe assim mesmo, porque basta um publicador.
            assert anchor["opentimestamps"] is None
            posicao = anchor["event_count"]
            assert audit["events"][posicao - 1]["event_hash"] == anchor["audit_head_hash"]

        # A ancoragem entra na própria cadeia, como ato do rito.
        anchored = [
            item for item in audit["events"] if item["event_type"] == "audit_chain_anchored"
        ]
        assert len(anchored) == 2
        assert all(item["payload"]["actor"] == "procedure" for item in anchored)

        # E é idempotente: chamar o rito de novo não reancora nada.
        reavanco = client.post(
            f"/cases/{case_id}/advance", headers=actor_headers(case_id, "claimant")
        )
        assert reavanco.status_code == 200
        depois = client.get(f"/cases/{case_id}/audit").json()
        assert len(depois["anchors"]) == 2
        assert depois["event_count"] == audit["event_count"]
    finally:
        get_settings.cache_clear()


def test_without_nostr_configured_the_procedure_runs_and_simply_does_not_anchor(client):
    """A âncora é camada complementar: sem relay, o rito corre igual."""
    get_settings.cache_clear()
    case_id = create_case(client)["id"]
    accept_procedure(client, case_id)
    document = add_contract(client, case_id)["document"]
    complete_contradictory(client, case_id, document["id"])
    final = close_submissions(client, case_id)

    assert final["manifest_locked"] is True
    audit = client.get(f"/cases/{case_id}/audit").json()
    assert audit["valid"] is True
    assert audit["anchors"] == []
    # Sem âncora nenhuma, nada a contradizer.
    assert audit["anchors_consistent"] is True


def test_the_procedure_stamps_the_head_and_later_upgrades_the_proof(
    client, calendar, monkeypatch
):
    """Os dois publicadores convivem, e o carimbo amadurece depois.

    A prova nasce pendente — é assim que OpenTimestamps funciona — e só vira
    confirmação em Bitcoin horas depois. O rito tenta atualizar a cada passada
    de `advance`, sem repetir nada quando não há o que atualizar.
    """
    monkeypatch.setenv("OTS_CALENDARS", calendar.url)
    get_settings.cache_clear()
    try:
        case_id = create_case(client)["id"]
        accept_procedure(client, case_id)
        document = add_contract(client, case_id)["document"]
        complete_contradictory(client, case_id, document["id"])
        close_submissions(client, case_id)

        audit = client.get(f"/cases/{case_id}/audit").json()
        anchors = audit["anchors"]
        assert [item["milestone"] for item in anchors] == [
            "manifest_locked",
            "case_closed",
        ]
        for anchor in anchors:
            ots = anchor["opentimestamps"]
            assert ots["status"] == "pending"
            assert ots["calendars"] == [calendar.url]
            # Sem Nostr configurado, o carimbo sozinho já sustenta a âncora.
            assert anchor["nostr"] is None

        antes = audit["event_count"]

        # O calendário confirma; a próxima passada do rito atualiza as provas.
        calendar.confirmed = True
        avanco = client.post(
            f"/cases/{case_id}/advance", headers=actor_headers(case_id, "claimant")
        )
        assert avanco.status_code == 200
        depois = client.get(f"/cases/{case_id}/audit").json()

        for anchor in depois["anchors"]:
            assert anchor["opentimestamps"]["status"] == "confirmed"
            assert anchor["opentimestamps"]["bitcoin_block_heights"] == [BLOCK_HEIGHT]

        # Amadurecer a prova não pode mexer na cadeia: um evento novo mudaria
        # justamente o topo que essas âncoras comprometem.
        assert depois["event_count"] == antes
        assert depois["head_hash"] == audit["head_hash"]
        assert depois["anchors_consistent"] is True

        # E é idempotente: nada muda numa terceira passada.
        client.post(
            f"/cases/{case_id}/advance", headers=actor_headers(case_id, "claimant")
        )
        final = client.get(f"/cases/{case_id}/audit").json()
        assert final["event_count"] == antes
        assert final["anchors"] == depois["anchors"]
    finally:
        get_settings.cache_clear()
