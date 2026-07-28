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


def generate_private_key_hex() -> str:
    """Gera uma nova chave privada secp256k1 (formato Nostr) em hex."""
    return Keys.generate().secret_key().to_hex()


async def _publish(
    payload: Dict[str, Any],
    case_id: str,
    keys: Keys,
    relays: List[str],
) -> Dict[str, Any]:
    client = Client(NostrSigner.keys(keys))
    for url in relays:
        await client.add_relay(RelayUrl.parse(url))
    await client.connect()
    try:
        builder = EventBuilder(
            Kind(ANCHOR_KIND), json.dumps(payload, ensure_ascii=False)
        ).tags([Tag.identifier(case_id), Tag.hashtag(ANCHOR_TAG)])
        output = await asyncio.wait_for(
            client.send_event_builder(builder), timeout=PUBLISH_TIMEOUT_SECONDS
        )
        return {
            "event_id": output.id.to_hex(),
            "relays": [str(url) for url in output.success],
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


if __name__ == "__main__":  # pragma: no cover
    print(generate_private_key_hex())
