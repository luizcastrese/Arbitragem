"""Rate limiting por janela deslizante.

Dois backends com a mesma interface (`allow`, `reset`, `enabled`,
`max_requests`):

- `SlidingWindowRateLimiter`, em memória, sem dependências externas. Serve a
  uma única instância: cada réplica teria o próprio balde.
- `RedisSlidingWindowRateLimiter`, com o balde num sorted set do Redis. É o
  que permite escalar para mais de uma réplica sem multiplicar o limite.

`build_rate_limiter` escolhe pelo `RATE_LIMIT_BACKEND` das configurações.

O dicionário de baldes é podado a cada chamada: sem isso, cada endereço visto
uma única vez ficaria residente para sempre e uma varredura de IPs viraria um
vazamento de memória. `max_keys` é o teto rígido — atingido o limite, os
baldes mais antigos saem primeiro.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from typing import Any, Deque, Optional, Tuple
import uuid

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


# Janela deslizante atômica: poda o que saiu da janela, conta, e só registra
# a tentativa se ainda houver espaço. Rodar no servidor evita a corrida entre
# duas réplicas que leriam a mesma contagem antes de gravar.
_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  local retry = window
  if oldest[2] then
    retry = window - (now - tonumber(oldest[2]))
  end
  return {0, tostring(retry)}
end
redis.call('ZADD', key, now, member)
redis.call('PEXPIRE', key, math.ceil(window * 1000))
return {1, '0'}
"""


class RedisSlidingWindowRateLimiter:
    """Mesmo contrato do limitador em memória, com o estado no Redis.

    O relógio é o do processo (`time.time`), não o do Redis: réplicas com
    relógios sincronizados por NTP diferem em milissegundos, irrelevante para
    janelas de minutos. Cada chave expira sozinha ao fim da janela, então não
    há poda a fazer aqui e o Redis não cresce com IPs vistos uma vez.
    """

    def __init__(
        self,
        client: Any,
        max_requests: int,
        window_seconds: int,
        enabled: bool = True,
        namespace: str = "general",
        prefix: str = "valinor:ratelimit",
    ) -> None:
        self.client = client
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.enabled = enabled
        self.key_prefix = f"{prefix}:{namespace}:"
        self._script = client.register_script(_SLIDING_WINDOW_LUA)

    def allow(self, key: str, now: Optional[float] = None) -> Tuple[bool, float]:
        now = time.time() if now is None else now
        allowed, retry_after = self._script(
            keys=[self.key_prefix + key],
            args=[now, self.window_seconds, self.max_requests, f"{now}:{uuid.uuid4().hex}"],
        )
        if isinstance(retry_after, bytes):
            retry_after = retry_after.decode("ascii")
        return bool(int(allowed)), max(0.0, float(retry_after))

    def tracked_keys(self) -> int:
        return sum(1 for _ in self.client.scan_iter(match=self.key_prefix + "*"))

    def reset(self) -> None:
        keys = list(self.client.scan_iter(match=self.key_prefix + "*"))
        if keys:
            self.client.delete(*keys)


def build_rate_limiter(
    settings: Any,
    *,
    namespace: str,
    max_requests: int,
    window_seconds: int,
    enabled: bool,
):
    """Escolhe o backend pelas configurações. Redis é carregado sob demanda."""
    if getattr(settings, "rate_limit_backend", "memory") == "redis":
        import redis  # dependência opcional, só com RATE_LIMIT_BACKEND=redis

        client = redis.Redis.from_url(settings.redis_url)
        return RedisSlidingWindowRateLimiter(
            client,
            max_requests=max_requests,
            window_seconds=window_seconds,
            enabled=enabled,
            namespace=namespace,
        )
    return SlidingWindowRateLimiter(
        max_requests=max_requests,
        window_seconds=window_seconds,
        enabled=enabled,
        max_keys=settings.rate_limit_max_keys,
    )
