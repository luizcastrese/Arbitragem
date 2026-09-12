"""Rate limiting em memória por janela deslizante.

Implementação sem dependências externas, adequada a uma única instância.
Para múltiplas réplicas em produção, troque o armazenamento por um backend
compartilhado (por exemplo Redis) mantendo a mesma interface `allow`.

O dicionário de baldes é podado a cada chamada: sem isso, cada endereço visto
uma única vez ficaria residente para sempre e uma varredura de IPs viraria um
vazamento de memória. `max_keys` é o teto rígido — atingido o limite, os
baldes mais antigos saem primeiro.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from typing import Deque, Optional, Tuple

DEFAULT_MAX_KEYS = 100_000


class SlidingWindowRateLimiter:
    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        enabled: bool = True,
        max_keys: int = DEFAULT_MAX_KEYS,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.enabled = enabled
        self.max_keys = max(1, max_keys)
        # OrderedDict em ordem de último acesso: a poda por excesso remove o
        # balde tocado há mais tempo.
        self._hits: "OrderedDict[str, Deque[float]]" = OrderedDict()
        self._lock = threading.Lock()
        self._last_sweep = 0.0

    def allow(self, key: str, now: Optional[float] = None) -> Tuple[bool, float]:
        """Registra uma tentativa. Retorna (permitido, segundos_para_retry)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            cutoff = now - self.window_seconds
            bucket = self._hits.get(key)
            if bucket is None:
                bucket = deque()
                self._hits[key] = bucket
            self._hits.move_to_end(key)

            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= self.max_requests:
                retry_after = self.window_seconds - (now - bucket[0])
                return False, max(0.0, retry_after)

            bucket.append(now)
            self._evict(now, cutoff)
            return True, 0.0

    def _evict(self, now: float, cutoff: float) -> None:
        """Descarta baldes expirados. Chamado com o lock.

        A varredura completa é O(n), então roda no máximo uma vez por janela.
        O teto de chaves é aplicado sempre, porque é ele que garante o limite
        de memória entre duas varreduras.
        """
        if now - self._last_sweep >= self.window_seconds:
            self._last_sweep = now
            stale = [
                key
                for key, bucket in self._hits.items()
                if not bucket or bucket[-1] <= cutoff
            ]
            for key in stale:
                self._hits.pop(key, None)

        while len(self._hits) > self.max_keys:
            self._hits.popitem(last=False)

    def tracked_keys(self) -> int:
        with self._lock:
            return len(self._hits)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
