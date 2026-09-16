"""Execução das etapas de modelo fora do request HTTP.

Uma etapa como `decide` chama um modelo com timeout de 60s, até
`LLM_MAX_RETRIES` tentativas e, com estabilidade ligada, mais de uma execução.
Dentro do request isso significa uma conexão aberta por minutos: o gateway
derruba antes do fim e o cliente fica sem saber se a decisão saiu. A etapa
roda então em uma thread própria e o endpoint responde `202` na hora.

Três propriedades importam aqui:

- **cada job tem a própria sessão de banco.** A sessão do request morre com a
  resposta; usar a mesma dentro da thread daria erro ou, pior, escrita numa
  conexão já devolvida ao pool.
- **falha não deixa o caso preso.** Se a etapa levanta, o status volta ao que
  era antes da reivindicação e o motivo fica registrado para o polling. Sem
  isso o caso ficaria em `processing_*` até o TTL de 10 minutos.
- **o resultado não vive aqui.** Ele é persistido no caso pela própria etapa;
  o registro em memória guarda só o andamento e o erro, porque é o que se
  perde num restart sem prejuízo — o estado real está no banco.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Tuple

from sqlalchemy.orm import Session


logger = logging.getLogger("valinor.jobs")

# Estados possíveis de uma etapa em segundo plano.
RUNNING = "processing"
COMPLETED = "completed"
FAILED = "failed"

# O registro guarda só o andamento recente. O estado que importa está no
# banco, então descartar entradas antigas não perde informação — e sem teto o
# dicionário cresceria com um StageJob (e o Future com o resultado inteiro)
# por par caso/etapa já executado, para sempre.
DEFAULT_MAX_TRACKED_JOBS = 1000


@dataclass
class StageJob:
    case_id: str
    stage: str
    state: str = RUNNING
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    finished_at: Optional[str] = None
    error: Optional[str] = None
    future: Optional[Future] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "stage": self.stage,
            "state": self.state,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
        }


class StageRunner:
    """Fila de etapas em segundo plano, com um registro do que está em voo."""

    def __init__(
        self,
        max_workers: int = 4,
        max_tracked_jobs: int = DEFAULT_MAX_TRACKED_JOBS,
    ) -> None:
        self._max_workers = max_workers
        self._max_tracked_jobs = max(1, max_tracked_jobs)
        self._executor: Optional[ThreadPoolExecutor] = None
        self._jobs: "OrderedDict[Tuple[str, str], StageJob]" = OrderedDict()
        self._lock = threading.Lock()

    def _ensure_executor(self) -> ThreadPoolExecutor:
        """A fila é criada na primeira etapa e recriada depois de um
        `shutdown`. Sem isso, um ciclo de vida encerrado (o que acontece a cada
        `TestClient`, e num reload em desenvolvimento) deixaria o processo sem
        conseguir agendar mais nada."""
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=self._max_workers,
                    thread_name_prefix="valinor-stage",
                )
            return self._executor

    def submit(
        self,
        case_id: str,
        stage: str,
        work: Callable[[Session], Any],
        session_factory: Callable[[], Session],
        on_failure: Optional[Callable[[Session, str], None]] = None,
    ) -> StageJob:
        """Agenda a etapa. `work` recebe uma sessão nova e devolve o resultado.

        `on_failure` roda em uma sessão limpa quando `work` levanta: é onde o
        caso sai de `processing_*` para não ficar preso.
        """
        job = StageJob(case_id=case_id, stage=stage)
        with self._lock:
            self._jobs[(case_id, stage)] = job
            self._jobs.move_to_end((case_id, stage))
            self._evict()

        def runner() -> Any:
            db = session_factory()
            try:
                result = work(db)
            except BaseException as exc:  # noqa: BLE001 - o motivo vai ao polling
                db.rollback()
                logger.exception(
                    "stage_failed case=%s stage=%s", case_id, stage
                )
                error = f"{type(exc).__name__}: {exc}"
                # A recuperação vem ANTES de marcar o job como falho: quem
                # está no polling trata `failed` como convite a repetir a
                # etapa, e repetir antes de o status voltar bateria em
                # StageBusy.
                if on_failure is not None:
                    recovery = session_factory()
                    try:
                        on_failure(recovery, error)
                    except Exception:  # noqa: BLE001 - a falha original prevalece
                        logger.exception(
                            "stage_recovery_failed case=%s stage=%s",
                            case_id,
                            stage,
                        )
                    finally:
                        recovery.close()
                job.error = error
                job.finished_at = datetime.now(timezone.utc).isoformat()
                job.state = FAILED
                raise
            else:
                job.state = COMPLETED
                job.finished_at = datetime.now(timezone.utc).isoformat()
                return result
            finally:
                db.close()

        job.future = self._ensure_executor().submit(runner)
        return job

    def _evict(self) -> None:
        """Descarta os jobs concluídos mais antigos. Chamado com o lock.

        Um job ainda em execução nunca é descartado: perdê-lo faria o polling
        reportar `pending` para uma etapa que está rodando.
        """
        if len(self._jobs) <= self._max_tracked_jobs:
            return
        for key in list(self._jobs):
            if len(self._jobs) <= self._max_tracked_jobs:
                return
            if self._jobs[key].state != RUNNING:
                del self._jobs[key]

    def tracked_jobs(self) -> int:
        with self._lock:
            return len(self._jobs)

    def get(self, case_id: str, stage: str) -> Optional[StageJob]:
        with self._lock:
            return self._jobs.get((case_id, stage))

    def wait(self, job: StageJob, timeout: float) -> Optional[Any]:
        """Espera o resultado por no máximo `timeout` segundos.

        Devolve o resultado, ou None se ainda estiver rodando. Exceções da
        etapa são repropagadas para o chamador traduzir em resposta HTTP.
        """
        if job.future is None:  # pragma: no cover - só se submit falhar
            return None
        try:
            return job.future.result(timeout=timeout)
        except TimeoutError:
            return None
        except Exception:
            raise

    def forget(self, case_id: str, stage: str) -> None:
        with self._lock:
            self._jobs.pop((case_id, stage), None)

    def reset(self) -> None:
        """Limpa o registro. Usado entre testes."""
        with self._lock:
            self._jobs.clear()

    def shutdown(self, wait: bool = True) -> None:
        with self._lock:
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=wait)
