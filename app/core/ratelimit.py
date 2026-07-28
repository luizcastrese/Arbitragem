"""Rate limiting em memória por janela deslizante.

Implementação sem dependências externas, adequada a uma única instância.
Para múltiplas réplicas em produção, troque o armazenamento por um backend
compartilhado (por exemplo Redis) mantendo a mesma interface `allow`.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple


class SlidingWindowRateLimiter:
    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        enabled: bool = True,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.enabled = enabled
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> Tuple[bool, float]:
        """Registra uma tentativa. Retorna (permitido, segundos_para_retry)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            bucket = self._hits[key]
            cutoff = now - self.window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.max_requests:
                retry_after = self.window_seconds - (now - bucket[0])
                return False, max(0.0, retry_after)
            bucket.append(now)
            return True, 0.0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
