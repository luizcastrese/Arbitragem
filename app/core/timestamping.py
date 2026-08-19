"""Carimbo do tempo do topo da cadeia de auditoria via OpenTimestamps.

A âncora Nostr prova que um topo foi publicado, mas não *quando*: o
`created_at` de um evento Nostr é preenchido pelo próprio autor, isto é, pela
plataforma. Num litígio a pergunta que importa é justamente a segunda — "esse
registro já existia antes da decisão?" —, e uma data auto-declarada não a
responde.

OpenTimestamps agrega o hash em uma transação Bitcoin. O instante deixa de ser
declaração e passa a ser consenso, e a prova resultante é autocontida: quem
precisar conferir daqui a anos não depende de nenhum servidor da Valinor
continuar no ar, só do arquivo `.ots` e da blockchain.

A prova nasce *pendente*: o calendário devolve um compromisso na hora e a
confirmação em Bitcoin leva horas. Por isso `upgrade_proof` existe e precisa
ser chamado depois — enquanto pendente, a prova vale como recibo do calendário,
não como carimbo em blockchain.

Publicação e upgrade são best-effort: nenhuma falha de rede interrompe o rito.
"""

import base64
import logging
from io import BytesIO
from typing import Any, Dict, List, Optional

from opentimestamps.calendar import CommitmentNotFoundError, RemoteCalendar
from opentimestamps.core.notary import (
    BitcoinBlockHeaderAttestation,
    PendingAttestation,
)
from opentimestamps.core.op import OpSHA256
from opentimestamps.core.serialize import (
    BytesDeserializationContext,
    BytesSerializationContext,
)
from opentimestamps.core.timestamp import DetachedTimestampFile

from app.core.config import get_settings

logger = logging.getLogger("valinor.opentimestamps")

# Curto de propósito: o carimbo acontece dentro do ato de uma parte, e um
# calendário fora do ar não pode transformar um clique em espera longa. Com
# rede saudável a resposta vem em bem menos que isso.
SUBMIT_TIMEOUT_SECONDS = 5
UPGRADE_TIMEOUT_SECONDS = 5


def _detached_for(head_hash: str) -> DetachedTimestampFile:
    """Monta o objeto carimbado a partir do topo da cadeia.

    O que se carimba são os bytes ASCII do hash em hexadecimal — não os bytes
    binários dele. É uma escolha de verificabilidade: quem confere reproduz o
    arquivo com um `printf '%s' <head_hash> > head.txt` e roda o `ots` oficial
    contra ele, sem precisar de nenhuma ferramenta nossa nem saber como a
    plataforma serializa evento.
    """
    return DetachedTimestampFile.from_fd(OpSHA256(), BytesIO(head_hash.encode("ascii")))


def _serialize(detached: DetachedTimestampFile) -> str:
    ctx = BytesSerializationContext()
    detached.serialize(ctx)
    return base64.b64encode(ctx.getbytes()).decode("ascii")


def _deserialize(proof_b64: str) -> DetachedTimestampFile:
    ctx = BytesDeserializationContext(base64.b64decode(proof_b64))
    return DetachedTimestampFile.deserialize(ctx)


def describe_proof(proof_b64: str) -> Dict[str, Any]:
    """Lê o estado de uma prova: ainda pendente, ou já confirmada em Bitcoin."""
    detached = _deserialize(proof_b64)
    pending: List[str] = []
    heights: List[int] = []
    for _, attestation in detached.timestamp.all_attestations():
        if isinstance(attestation, PendingAttestation):
            pending.append(attestation.uri)
        elif isinstance(attestation, BitcoinBlockHeaderAttestation):
            heights.append(attestation.height)
    return {
        "status": "confirmed" if heights else "pending",
        "bitcoin_block_heights": sorted(heights),
        "pending_calendars": pending,
    }


def stamp_head(head_hash: str) -> Optional[Dict[str, Any]]:
    """Submete o topo da cadeia aos calendários configurados.

    Basta um calendário responder para haver prova. Exigir todos entregaria a
    ancoragem à disponibilidade do pior deles.
    """
    settings = get_settings()
    if not settings.opentimestamps_enabled or not head_hash:
        return None

    detached = _detached_for(head_hash)
    accepted: List[str] = []
    for url in settings.opentimestamps_calendars:
        try:
            calendar = RemoteCalendar(url)
            result = calendar.submit(
                detached.timestamp.msg, timeout=SUBMIT_TIMEOUT_SECONDS
            )
            detached.timestamp.merge(result)
            accepted.append(url)
        except Exception:  # noqa: BLE001 - carimbo é best-effort
            logger.warning("Calendário OpenTimestamps indisponível: %s", url)
    if not accepted:
        return None

    proof_b64 = _serialize(detached)
    return {
        "proof_b64": proof_b64,
        "file_digest": detached.file_digest.hex(),
        "calendars": accepted,
        **describe_proof(proof_b64),
    }


def upgrade_proof(proof_b64: str) -> Optional[Dict[str, Any]]:
    """Tenta trocar as atestações pendentes pela confirmação em Bitcoin.

    Devolve `None` quando nada mudou — prova já confirmada, calendário ainda
    sem a confirmação, ou rede fora. É o que torna a chamada repetível sem
    efeito colateral.
    """
    settings = get_settings()
    if not settings.opentimestamps_enabled or not proof_b64:
        return None

    detached = _deserialize(proof_b64)
    if describe_proof(proof_b64)["status"] == "confirmed":
        return None

    upgraded = False
    for msg, attestation in list(detached.timestamp.all_attestations()):
        if not isinstance(attestation, PendingAttestation):
            continue
        url = attestation.uri
        if url not in settings.opentimestamps_calendars:
            # Só se conversa com calendário configurado: a URI vem de dentro da
            # prova, e seguir qualquer endereço que ela indique seria deixar um
            # terceiro escolher com quem o servidor fala.
            continue
        try:
            calendar = RemoteCalendar(url)
            result = calendar.get_timestamp(msg, timeout=UPGRADE_TIMEOUT_SECONDS)
        except CommitmentNotFoundError:
            continue
        except Exception:  # noqa: BLE001 - upgrade é best-effort
            logger.warning("Falha ao atualizar prova em %s", url)
            continue
        _merge_into(detached, msg, result)
        upgraded = True

    if not upgraded:
        return None
    proof = _serialize(detached)
    return {"proof_b64": proof, **describe_proof(proof)}


def _merge_into(detached: DetachedTimestampFile, msg: bytes, result) -> None:
    """Costura o resultado do calendário no ponto certo da árvore da prova."""
    for timestamp in _walk(detached.timestamp):
        if timestamp.msg == msg:
            timestamp.merge(result)
            return


def _walk(timestamp):
    yield timestamp
    for child in timestamp.ops.values():
        yield from _walk(child)


def upgrade_pending_anchors() -> Dict[str, int]:
    """Percorre os casos e amadurece as provas ainda pendentes.

    A confirmação em Bitcoin leva horas, e o rito só avança quando uma parte
    age — num caso já encerrado, ninguém mais age. Sem alguém chamando isto de
    tempos em tempos, as provas ficam para sempre no estado de recibo de
    calendário e nunca viram carimbo em blockchain, que é justamente o que
    OpenTimestamps acrescenta.

    Feito para rodar em cron: `python -m app.core.timestamping upgrade`.
    """
    from app.db.repository import get_case, list_cases, replace_audit_anchors
    from app.db.session import SessionLocal

    db = SessionLocal()
    examined = 0
    upgraded = 0
    try:
        for summary in list_cases(db):
            case = get_case(db, summary.id)
            anchors = []
            changed = False
            for anchor in _anchors_of(case):
                proof = (anchor.get("opentimestamps") or {}).get("proof_b64")
                examined += 1 if proof else 0
                result = upgrade_proof(proof) if proof else None
                if result:
                    anchors.append(
                        {**anchor, "opentimestamps": {**anchor["opentimestamps"], **result}}
                    )
                    changed = True
                    upgraded += 1
                else:
                    anchors.append(anchor)
            if changed:
                replace_audit_anchors(db, case, anchors)
    finally:
        db.close()
    return {"examined": examined, "upgraded": upgraded}


def _anchors_of(case) -> List[Dict[str, Any]]:
    import json

    return json.loads(case.audit_anchors_json) if case.audit_anchors_json else []


if __name__ == "__main__":  # pragma: no cover
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "upgrade":
        print(upgrade_pending_anchors())
    else:
        print("uso: python -m app.core.timestamping upgrade")
