"""Carimbo do tempo do topo da auditoria via OpenTimestamps.

Os testes falam com um calendário local que implementa o protocolo real
(`POST /digest`, `GET /timestamp/<commitment>`) e devolve estruturas montadas
com a própria biblioteca — sem mock do cliente e sem tocar rede externa. É o
mesmo modelo do relay Nostr local já usado na suíte.
"""

import http.server
import os
import threading

import pytest

os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("PLATFORM_SIGNING_SECRET", "test-signing-secret")

from opentimestamps.core.notary import (  # noqa: E402
    BitcoinBlockHeaderAttestation,
    PendingAttestation,
)
from opentimestamps.core.op import OpSHA256
from opentimestamps.core.serialize import BytesSerializationContext  # noqa: E402
from opentimestamps.core.timestamp import Timestamp  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.timestamping import (  # noqa: E402
    describe_proof,
    stamp_head,
    upgrade_proof,
)

HEAD = "b" * 64
BLOCK_HEIGHT = 812_345


def _serialized(timestamp: Timestamp) -> bytes:
    ctx = BytesSerializationContext()
    timestamp.serialize(ctx)
    return ctx.getbytes()


class _CalendarState:
    """Guarda o que o calendário aceitou e se já 'confirmou' em Bitcoin."""

    def __init__(self):
        self.submitted = []
        self.confirmed = False
        self.url = ""


@pytest.fixture()
def calendar():
    state = _CalendarState()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):  # silencia o log do servidor de teste
            pass

        def _send(self, payload: bytes, status=200):
            self.send_response(status)
            self.send_header("Content-Type", "application/vnd.opentimestamps.v1")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            digest = self.rfile.read(length)
            state.submitted.append(digest)
            # Um calendário real devolve o compromisso pendente na hora.
            timestamp = Timestamp(digest)
            timestamp.attestations.add(PendingAttestation(state.url))
            self._send(_serialized(timestamp))

        def do_GET(self):
            if not state.confirmed:
                self._send(b"commitment not found", status=404)
                return
            commitment = bytes.fromhex(self.path.rsplit("/", 1)[-1])
            timestamp = Timestamp(commitment)
            timestamp.attestations.add(BitcoinBlockHeaderAttestation(BLOCK_HEIGHT))
            self._send(_serialized(timestamp))

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield state
    server.shutdown()


def _enabled(monkeypatch, url):
    monkeypatch.setenv("OTS_CALENDARS", url)
    get_settings.cache_clear()


def test_stamping_produces_a_pending_proof_over_the_head(calendar, monkeypatch):
    _enabled(monkeypatch, calendar.url)
    try:
        result = stamp_head(HEAD)

        assert result is not None
        assert result["calendars"] == [calendar.url]
        assert result["status"] == "pending"
        assert result["bitcoin_block_heights"] == []
        assert result["pending_calendars"] == [calendar.url]
        # O que foi carimbado é o sha256 do hash do topo em ASCII — o mesmo
        # digest que o `ots` oficial calcularia sobre um arquivo com esse texto.
        import hashlib

        esperado = hashlib.sha256(HEAD.encode("ascii")).hexdigest()
        assert result["file_digest"] == esperado
        assert calendar.submitted == [bytes.fromhex(esperado)]
        # A prova é autocontida: relê sem depender do servidor.
        assert describe_proof(result["proof_b64"])["status"] == "pending"
    finally:
        get_settings.cache_clear()


def test_upgrade_replaces_the_pending_attestation_with_bitcoin(calendar, monkeypatch):
    _enabled(monkeypatch, calendar.url)
    try:
        stamped = stamp_head(HEAD)

        # Enquanto o calendário não confirmou, não há o que atualizar — e
        # tentar de novo não corrompe a prova nem levanta exceção.
        assert upgrade_proof(stamped["proof_b64"]) is None

        calendar.confirmed = True
        upgraded = upgrade_proof(stamped["proof_b64"])

        assert upgraded is not None
        assert upgraded["status"] == "confirmed"
        assert upgraded["bitcoin_block_heights"] == [BLOCK_HEIGHT]
        # Já confirmada, uma nova tentativa é inócua.
        assert upgrade_proof(upgraded["proof_b64"]) is None
    finally:
        get_settings.cache_clear()


def test_stamping_is_skipped_without_calendars(monkeypatch):
    monkeypatch.setenv("OTS_CALENDARS", "")
    get_settings.cache_clear()
    try:
        assert stamp_head(HEAD) is None
        assert upgrade_proof("qualquer-coisa") is None
    finally:
        get_settings.cache_clear()


def test_unreachable_calendar_never_raises(monkeypatch):
    """O carimbo acontece dentro do ato de uma parte: não pode derrubá-lo."""
    _enabled(monkeypatch, "http://127.0.0.1:1")
    try:
        assert stamp_head(HEAD) is None
    finally:
        get_settings.cache_clear()


def test_upgrade_ignores_calendars_that_are_not_configured(calendar, monkeypatch):
    """A URI do calendário vem de dentro da prova.

    Seguir qualquer endereço que ela indique seria deixar quem entrega a prova
    escolher com quem este servidor vai falar.
    """
    _enabled(monkeypatch, calendar.url)
    try:
        stamped = stamp_head(HEAD)
        calendar.confirmed = True
    finally:
        get_settings.cache_clear()

    # Mesma prova, mas agora aquele calendário não está mais configurado.
    _enabled(monkeypatch, "http://127.0.0.1:1")
    try:
        assert upgrade_proof(stamped["proof_b64"]) is None
    finally:
        get_settings.cache_clear()


def test_upgrade_command_matures_proofs_of_closed_cases(calendar, monkeypatch, tmp_path):
    """O comando de manutenção existe porque o rito não roda sozinho.

    Num caso encerrado ninguém mais age, então nenhuma passada de `advance`
    acontece — e sem isto a prova ficaria para sempre como recibo de
    calendário, sem nunca virar carimbo em blockchain.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db import session as session_module
    from app.db.models import Base
    from app.db.repository import case_to_dict, create_case, get_case, save_audit_anchor
    from app.core.timestamping import upgrade_pending_anchors

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(session_module, "SessionLocal", factory)

    _enabled(monkeypatch, calendar.url)
    try:
        db = factory()
        case = create_case(
            db,
            title="Caso encerrado",
            claimant="A",
            respondent="B",
            claimant_token_hash="h1",
            respondent_token_hash="h2",
            created_by="claimant",
        )
        stamped = stamp_head(HEAD)
        assert stamped["status"] == "pending"
        save_audit_anchor(
            db,
            case,
            {
                "milestone": "case_closed",
                "audit_head_hash": HEAD,
                "event_count": 1,
                "nostr": None,
                "opentimestamps": stamped,
            },
        )
        case_id = case.id
        db.close()

        # Nada a fazer enquanto o calendário não confirmou.
        assert upgrade_pending_anchors() == {"examined": 1, "upgraded": 0}

        calendar.confirmed = True
        assert upgrade_pending_anchors() == {"examined": 1, "upgraded": 1}

        db = factory()
        anchor = case_to_dict(get_case(db, case_id))["audit_anchors"][0]
        assert anchor["opentimestamps"]["status"] == "confirmed"
        assert anchor["opentimestamps"]["bitcoin_block_heights"] == [BLOCK_HEIGHT]
        db.close()

        # Repetir o comando não mexe em nada já confirmado.
        assert upgrade_pending_anchors()["upgraded"] == 0
    finally:
        get_settings.cache_clear()
        Base.metadata.drop_all(bind=engine)
