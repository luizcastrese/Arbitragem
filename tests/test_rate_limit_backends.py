"""Backends do rate limit: memória (uma réplica) e Redis (várias réplicas).

O Redis de verdade não roda nos testes. O cliente falso abaixo implementa só
o que o limitador usa — `register_script`, `scan_iter` e `delete` — e executa
em Python a mesma janela deslizante do script Lua, para cobrir a cola entre o
limitador e o cliente (chaves por namespace, decodificação da resposta).
"""

from __future__ import annotations

import dataclasses
import fnmatch

import pytest

from app.core import config
from app.core.ratelimit import (
    RedisSlidingWindowRateLimiter,
    SlidingWindowRateLimiter,
    build_rate_limiter,
)


class FakeRedis:
    def __init__(self) -> None:
        self.zsets: dict[str, dict[str, float]] = {}

    def register_script(self, _source):
        def run(keys, args):
            key = keys[0]
            now, window, limit, member = float(args[0]), float(args[1]), int(args[2]), args[3]
            bucket = self.zsets.setdefault(key, {})
            for name, score in list(bucket.items()):
                if score <= now - window:
                    del bucket[name]
            if len(bucket) >= limit:
                oldest = min(bucket.values())
                return [0, str(window - (now - oldest)).encode("ascii")]
            bucket[member] = now
            return [1, b"0"]

        return run

    def scan_iter(self, match):
        return [key for key in list(self.zsets) if fnmatch.fnmatch(key, match)]

    def delete(self, *keys):
        for key in keys:
            self.zsets.pop(key, None)


def test_redis_limita_e_informa_o_retry():
    limiter = RedisSlidingWindowRateLimiter(
        FakeRedis(), max_requests=2, window_seconds=60, namespace="general"
    )
    assert limiter.allow("1.2.3.4", now=1000.0) == (True, 0.0)
    assert limiter.allow("1.2.3.4", now=1001.0) == (True, 0.0)
    allowed, retry = limiter.allow("1.2.3.4", now=1010.0)
    assert allowed is False
    assert retry == pytest.approx(50.0)
    # Outra chave tem o próprio balde.
    assert limiter.allow("5.6.7.8", now=1010.0)[0] is True
    # Saída da janela libera de novo.
    assert limiter.allow("1.2.3.4", now=1061.0)[0] is True


def test_redis_separa_namespaces_e_reset_so_limpa_o_proprio():
    client = FakeRedis()
    general = RedisSlidingWindowRateLimiter(client, 1, 60, namespace="general")
    auth = RedisSlidingWindowRateLimiter(client, 1, 60, namespace="auth")
    assert general.allow("ip", now=0.0)[0] is True
    assert auth.allow("ip", now=0.0)[0] is True
    assert general.tracked_keys() == 1
    general.reset()
    assert general.tracked_keys() == 0
    assert auth.tracked_keys() == 1


def test_fabrica_usa_memoria_por_padrao():
    settings = config.get_settings()
    limiter = build_rate_limiter(
        settings, namespace="general", max_requests=5, window_seconds=60, enabled=True
    )
    assert isinstance(limiter, SlidingWindowRateLimiter)


def test_fabrica_usa_redis_quando_configurado(monkeypatch):
    import redis

    created = {}

    def from_url(url):
        created["url"] = url
        return FakeRedis()

    monkeypatch.setattr(redis.Redis, "from_url", staticmethod(from_url))
    settings = dataclasses.replace(
        config.get_settings(),
        rate_limit_backend="redis",
        redis_url="redis://cache:6379/0",
    )
    limiter = build_rate_limiter(
        settings, namespace="auth", max_requests=5, window_seconds=60, enabled=True
    )
    assert isinstance(limiter, RedisSlidingWindowRateLimiter)
    assert created["url"] == "redis://cache:6379/0"
    assert limiter.key_prefix == "valinor:ratelimit:auth:"


def test_redis_sem_url_derruba_o_boot(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "redis")
    monkeypatch.delenv("REDIS_URL", raising=False)
    config.get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="REDIS_URL"):
            config.validate_runtime_policy(config.get_settings())
    finally:
        monkeypatch.undo()
        config.get_settings.cache_clear()


def test_backend_desconhecido_derruba_o_boot(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "memcached")
    config.get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="RATE_LIMIT_BACKEND"):
            config.validate_runtime_policy(config.get_settings())
    finally:
        monkeypatch.undo()
        config.get_settings.cache_clear()
