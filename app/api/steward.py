"""Condução do gestor do procedimento (a IA da Valinor): atos formais, trava do
manifesto e encadeamento entre etapas de modelo.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api import context as ctx
from app.api.background import _job_session
from app.core.manifest import lock_case_manifest
from app.core.terms import TermsNotFound, get_terms
from app.db.repository import (
    admit_document as persist_admission,
    append_audit,
    case_to_dict,
    get_case,
    get_document,
    lock_manifest as persist_manifest,
    save_steward_state,
)
from app.domain.concurrency import (
    PROCESSING_TTL,
    STAGE_CLAIM,
    StageBusy,
    claim_case_stage,
    release_processing,
)
from app.domain.jobs import RUNNING
from app.domain.steward import decide_steward_action, steward_actuator_token
from app.domain.steward_chain import arm_steward_chain, armed_before, take_steward_chain
from app.schemas import ConciliationRoundRequest

logger = logging.getLogger("valinor.request")


def _arm_steward_chain(db: Session, case_id: str) -> None:
    arm_steward_chain(db, case_id)


def _take_steward_chain(db: Session, case_id: str) -> bool:
    return take_steward_chain(db, case_id)


def _continue_steward(job_db: Session, case_id: str) -> None:
    """Encadeia a próxima etapa quando foi o gestor que abriu a atual.

    Uma falha aqui não desfaz a etapa que acabou de ser gravada: o caso
    ficaria preso se a recuperação da etapa anterior rodasse de novo.
    """
    if not _take_steward_chain(job_db, case_id):
        return
    try:
        case = get_case(job_db, case_id)
        if case is not None:
            _conduct_steward(job_db, case, wait=0, run_model_stages=True)
    except Exception:
        logger.exception("steward_chain_failed case=%s", case_id)


def _lock_manifest_now(db: Session, case):
    """Trava o manifesto. Exige adesão, contraditório e as duas apresentações."""
    if case.manifest_locked:
        return case_to_dict(case)["locked_manifest"]
    if not case.documents:
        raise HTTPException(
            status_code=400,
            detail="Adicione ao menos um documento antes de travar o manifesto",
        )
    case_data = case_to_dict(case)
    if not case_data["consent"]["complete"]:
        raise HTTPException(
            status_code=409,
            detail="Reclamante e reclamada precisam aceitar o procedimento antes da trava",
        )
    if not case_data["contradictory"]["complete"]:
        pending = ", ".join(case_data["contradictory"]["pending_document_ids"])
        raise HTTPException(
            status_code=409,
            detail=f"Contraditório pendente nos materiais: {pending}",
        )
    if not case_data["submission"]["complete"]:
        raise HTTPException(
            status_code=409,
            detail=(
                "Cada parte precisa declarar que encerrou a apresentação "
                "antes da trava"
            ),
        )
    _assert_consent_terms_reproducible(case_data)

    try:
        claimed = claim_case_stage(db, case, "lock")
    except StageBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not claimed:
        case = get_case(db, case.id)
        if case.manifest_locked:
            return case_to_dict(case)["locked_manifest"]
        raise HTTPException(status_code=409, detail="Trava do manifesto já em andamento")

    try:
        manifest = lock_case_manifest(case_to_dict(case))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    persist_manifest(db, case, manifest)
    return manifest


def _invoke_steward_stage(action: str, case, case_data: Dict, wait: float, db: Session):
    # As etapas de modelo são as próprias rotas, chamadas com a credencial do
    # atuador. Import tardio: as rotas importam este módulo.
    from app.api.routes.stages import (
        assess_case_conciliation,
        decide_case,
        organize_case,
        review_case,
    )

    token = steward_actuator_token()
    if action == "conciliate":
        rounds = case_data.get("conciliation_rounds") or []
        latest = rounds[-1] if rounds else {}
        positions = latest.get("party_positions") or {}
        payload = ConciliationRoundRequest(
            advance=bool(rounds),
            claimant_response=str((positions.get("claimant") or {}).get("text") or ""),
            respondent_response=str((positions.get("respondent") or {}).get("text") or ""),
        )
        return assess_case_conciliation(
            case.id,
            payload,
            wait,
            token,
            db,
        )
    if action == "organize":
        return organize_case(case.id, wait, token, db)
    if action == "decide":
        return decide_case(case.id, wait, token, "", db)
    if action == "review":
        return review_case(case.id, wait, token, "", db)
    raise HTTPException(status_code=500, detail=f"Ação de gestor desconhecida: {action}")


def _conduct_steward(
    db: Session,
    case,
    *,
    wait: float = 0,
    run_model_stages: bool = True,
    depth: int = 0,
) -> None:
    """Uma passada do gestor. Atos formais se encadeiam; etapa de modelo, uma."""
    if depth > 6:
        return
    case = get_case(db, case.id)
    if case is None:
        return
    case_data = case_to_dict(case)
    decision = decide_steward_action(case_data)
    action = decision["action"]

    if action == "admit":
        append_audit(
            db,
            case,
            "steward_conducted",
            {
                "action": "admit",
                "reason": decision.get("reason"),
                "document_ids": decision.get("document_ids") or [],
                "actor": "steward",
            },
        )
        db.commit()
        for document_id in decision.get("document_ids") or []:
            document = get_document(db, case.id, document_id)
            if document is not None and not document.admitted:
                persist_admission(db, case, document)
                case = get_case(db, case.id)
        save_steward_state(db, case, decision, "done")
        _conduct_steward(
            db,
            case,
            wait=wait,
            run_model_stages=run_model_stages,
            depth=depth + 1,
        )
        return

    if action == "lock":
        _lock_manifest_now(db, case)
        case = get_case(db, case.id)
        append_audit(
            db,
            case,
            "steward_conducted",
            {
                "action": "lock",
                "reason": decision.get("reason"),
                "actor": "steward",
            },
        )
        db.commit()
        save_steward_state(db, case, decision, "done")
        _conduct_steward(
            db,
            case,
            wait=wait,
            run_model_stages=run_model_stages,
            depth=depth + 1,
        )
        return

    if action in {"conciliate", "organize", "decide", "review"}:
        state = "processing" if run_model_stages else "paused"
        save_steward_state(db, case, decision, state)
        if not run_model_stages:
            return
        _arm_steward_chain(db, case.id)
        try:
            _invoke_steward_stage(action, case, case_data, wait, db)
        except HTTPException:
            _take_steward_chain(db, case.id)
            raise
        db.expire_all()
        return

    save_steward_state(
        db,
        case,
        decision,
        "waiting" if action == "wait" else "hold",
    )


def _assert_consent_terms_reproducible(case_data: Dict) -> None:
    """Impede travar o caso quando o aceite de alguma parte não pode mais ser
    reproduzido: versão ausente, desconhecida ou com hash diferente do texto
    publicado. Sem isso, o manifesto assinado registraria um consentimento que
    a plataforma não consegue mais exibir."""
    consent = case_data.get("consent") or {}
    for party in ("claimant", "respondent"):
        entry = consent.get(party) or {}
        version = entry.get("terms_version")
        recorded = entry.get("terms_sha256")
        if not version or not recorded:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"O aceite de {party} foi registrado sem versão e hash dos "
                    "termos. Peça um novo aceite antes de travar o caso."
                ),
            )
        try:
            terms = get_terms(version)
        except TermsNotFound as exc:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"O aceite de {party} aponta para a versão de termos "
                    f"{version}, que não existe mais na plataforma."
                ),
            ) from exc
        if terms.sha256 != recorded:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"O texto dos termos {version} mudou depois do aceite de "
                    f"{party}. Publique uma versão nova e colha novo aceite: "
                    "versões publicadas não podem ser editadas."
                ),
            )


# ---------------------------------------------------------------------------
# Retomada da condução depois de um reinício
# ---------------------------------------------------------------------------

# Status de uma etapa reivindicada -> status a restaurar se ela foi abandonada.
_RESTORE_FROM_PROCESSING = {
    processing: expected_from
    for expected_from, processing in STAGE_CLAIM.values()
    if processing.startswith("processing_")
}


def _stage_running_locally(case_id: str) -> bool:
    return any(
        (job := ctx.stage_runner.get(case_id, stage)) is not None
        and job.state == RUNNING
        for stage in ctx.ASYNC_STAGES
    )


def recover_abandoned_steward_chains(
    db: Session,
    now: Optional[datetime] = None,
    limit: int = 50,
) -> List[str]:
    """Retoma a condução de casos cuja etapa de modelo morreu com o processo.

    O gestor arma o encadeamento antes de abrir a etapa e a etapa o consome
    ao terminar. Uma marca mais velha que o TTL de reivindicação significa
    que a etapa não terminou nem falhou de forma tratada — o processo caiu no
    meio. Para cada caso assim:

    1. a marca é tomada com UPDATE condicional (outra réplica que varra ao
       mesmo tempo não conduz o caso de novo);
    2. se o caso ficou em `processing_*`, o status volta ao anterior à etapa
       e o abandono vai para a trilha de auditoria;
    3. o gestor conduz de novo a partir do que está gravado.

    Devolve os casos retomados.
    """
    now = now or datetime.now(timezone.utc)
    resumed: List[str] = []
    for case in armed_before(db, now - PROCESSING_TTL, limit=limit):
        case_id = case.id
        armed_at = case.steward_chain_armed_at
        status = str(case.status or "")
        if _stage_running_locally(case_id):
            continue
        started = case.processing_started_at
        if started is not None and started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if (
            status.startswith("processing")
            and started is not None
            and now - started <= PROCESSING_TTL
        ):
            # Reivindicação recente: a etapa ainda pode estar rodando em
            # outra réplica.
            continue
        if not take_steward_chain(db, case_id, armed_at=armed_at):
            continue
        try:
            case = get_case(db, case_id)
            if case is None:
                continue
            restored = _RESTORE_FROM_PROCESSING.get(str(case.status or ""))
            if restored is not None:
                release_processing(db, case, restored)
            append_audit(
                db,
                case,
                "steward_chain_recovered",
                {
                    "armed_at": armed_at.isoformat() if armed_at else None,
                    "abandoned_status": status,
                    "restored_status": restored,
                    "actor": "steward",
                },
            )
            db.commit()
            logger.warning(
                "steward_chain_recovered case=%s abandoned_status=%s restored=%s",
                case_id,
                status,
                restored,
            )
            _conduct_steward(db, get_case(db, case_id), wait=0, run_model_stages=True)
            resumed.append(case_id)
        except Exception:
            db.rollback()
            logger.exception("steward_chain_recovery_failed case=%s", case_id)
    return resumed


class StewardRecoveryLoop:
    """Roda `recover_abandoned_steward_chains` periodicamente numa thread.

    A primeira passada sai logo no boot: é quando há mais chance de existir
    uma etapa que morreu com o processo anterior. `interval <= 0` desliga.
    """

    def __init__(self, interval: float, session_factory=None) -> None:
        self.interval = interval
        self._session_factory = session_factory
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self.interval <= 0 or self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="valinor-steward-recovery",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def run_once(self) -> List[str]:
        factory = self._session_factory or _job_session
        db = factory()
        try:
            return recover_abandoned_steward_chains(db)
        finally:
            db.close()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                logger.exception("steward_recovery_pass_failed")
            self._stop.wait(self.interval)
