"""Ancoragem pública das Decision Attestations em relays Nostr (NIP-78).

Publica um evento parametrizado-substituível (kind 30078) contendo apenas
hash + assinatura + identificadores da attestation — nunca o outcome da
decisão, o split ou qualquer dado das partes. O caso continua sigiloso; só a
existência e o instante de emissão da attestation ficam publicamente
verificáveis, de forma independente do servidor da Valinor ficar no ar.

Sem NOSTR_PRIVATE_KEY_HEX e NOSTR_RELAYS configurados, a publicação é
pulada. Falha de rede ou de relay nunca derruba a emissão da attestation —
é uma camada complementar, não uma dependência crítica do fluxo de escrow.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from nostr_sdk import Client, EventBuilder, Keys, Kind, NostrSigner, RelayUrl, Tag

from app.core.config import get_settings

logger = logging.getLogger("valinor.nostr")

ANCHOR_KIND = 30078
ANCHOR_TAG = "valinor-attestation"
AUDIT_ANCHOR_TAG = "valinor-audit"
PUBLISH_TIMEOUT_SECONDS = 10


def build_anchor_payload(attestation: Dict[str, Any]) -> Dict[str, Any]:
    """Monta o payload mínimo da âncora: hash + assinatura + identificadores.

    Nunca inclui `decision`/`review` (outcome, split, teor) — só o suficiente
    para um terceiro que já tenha a attestation completa (recebida por um
    canal apropriado) confirmar que ela não foi alterada nem re-emitida com
    outra data.
    """
    platform = attestation.get("platform") or {}
    return {
        "v": 1,
        "case_id": attestation.get("case_id"),
        "escrow_id": attestation.get("escrow_id"),
        "attestation_hash": attestation.get("attestation_hash"),
        "signature": attestation.get("signature"),
        "signature_algorithm": attestation.get("signature_algorithm"),
        "platform_key_id": platform.get("key_id"),
        "issued_at_utc": attestation.get("issued_at_utc"),
        "contest_window_ends_utc": attestation.get("contest_window_ends_utc"),
    }


def build_audit_anchor_payload(
    case_id: str,
    events: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Monta a âncora do topo da cadeia de auditoria.

    A cadeia é encadeada por SHA-256 sem segredo: ela pega adulteração parcial
    — reescrever um evento quebra o `previous_hash` do seguinte —, mas quem
    tiver escrita no banco pode reescrever a cadeia inteira, recalcular todos
    os hashes e a verificação local volta a passar. Publicar o hash do topo
    fora do servidor fecha essa porta: o topo de então fica registrado em
    relays que a plataforma não controla, e qualquer reescrita posterior passa
    a divergir de uma cópia pública.

    Vai só o hash do topo e a contagem de eventos. Nem tipo de evento, nem
    payload, nem carimbo de ato — a existência do procedimento já é pública
    pela âncora da attestation; o que ele contém continua fora do relay.
    """
    if not events:
        return None
    head = events[-1]
    return {
        "v": 1,
        "kind": "audit_chain",
        "case_id": case_id,
        "audit_head_hash": head.get("event_hash"),
        "event_count": len(events),
    }


def generate_private_key_hex() -> str:
    """Gera uma nova chave privada secp256k1 (formato Nostr) em hex."""
    return Keys.generate().secret_key().to_hex()


async def _publish(
    payload: Dict[str, Any],
    identifier: str,
    keys: Keys,
    relays: List[str],
    hashtag: str = ANCHOR_TAG,
) -> Dict[str, Any]:
    client = Client(NostrSigner.keys(keys))
    for url in relays:
        await client.add_relay(RelayUrl.parse(url))
    await client.connect()
    try:
        builder = EventBuilder(
            Kind(ANCHOR_KIND), json.dumps(payload, ensure_ascii=False)
        ).tags([Tag.identifier(identifier), Tag.hashtag(hashtag)])
        output = await asyncio.wait_for(
            client.send_event_builder(builder), timeout=PUBLISH_TIMEOUT_SECONDS
        )
        accepted = [str(url) for url in output.success]
        if not accepted:
            # O envio pode "concluir" sem que relay nenhum tenha aceitado o
            # evento — a assinatura local sempre funciona. Registrar isso como
            # âncora seria o pior resultado possível: um comprovante público
            # que não existe em lugar público nenhum.
            raise ValueError("nenhum relay aceitou o evento")
        return {
            "event_id": output.id.to_hex(),
            "relays": accepted,
            "published_at_utc": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        await client.disconnect()


def publish_attestation_anchor(attestation: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Tenta publicar a âncora da attestation em Nostr. Melhor esforço: nunca
    levanta exceção — configuração ausente ou falha de rede só retornam
    `None`, sem afetar o restante do fluxo de emissão da attestation."""
    settings = get_settings()
    if not settings.nostr_anchor_enabled:
        return None
    case_id = attestation.get("case_id")
    if not case_id:
        return None
    try:
        keys = Keys.parse(settings.nostr_private_key_hex)
        payload = build_anchor_payload(attestation)
        return asyncio.run(_publish(payload, case_id, keys, settings.nostr_relays))
    except Exception:  # noqa: BLE001 - publicação é best-effort
        logger.warning(
            "Falha ao publicar âncora Nostr para o caso %s", case_id, exc_info=True
        )
        return None


def publish_audit_anchor(
    case_id: str,
    events: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Tenta publicar a âncora do topo da cadeia de auditoria. Melhor esforço:
    nunca levanta exceção, para que uma falha de relay não trave o rito.

    O identificador carrega a contagem de eventos, de modo que cada âncora seja
    um registro próprio. Sem isso, um evento parametrizado-substituível de
    mesmo `d` sobrescreveria a âncora anterior no relay — e a âncora da
    attestation, que usa o `case_id` puro, seria a primeira vítima.
    """
    settings = get_settings()
    if not settings.nostr_anchor_enabled:
        return None
    if not case_id:
        return None
    payload = build_audit_anchor_payload(case_id, events)
    if not payload:
        return None
    try:
        keys = Keys.parse(settings.nostr_private_key_hex)
        result = asyncio.run(
            _publish(
                payload,
                f"{case_id}:audit:{payload['event_count']}",
                keys,
                settings.nostr_relays,
                hashtag=AUDIT_ANCHOR_TAG,
            )
        )
        return {**result, **payload}
    except Exception:  # noqa: BLE001 - publicação é best-effort
        logger.warning(
            "Falha ao publicar âncora da auditoria do caso %s", case_id, exc_info=True
        )
        return None


if __name__ == "__main__":  # pragma: no cover
    print(generate_private_key_hex())
