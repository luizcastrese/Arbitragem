"""Ambiente compartilhado dos testes.

O `conftest` roda antes de qualquer módulo de teste, então é aqui que o
ambiente precisa ser fixado: `app.main` lê as configurações uma vez, no
import, e quem importasse primeiro definiria o comportamento de toda a
sessão de testes.
"""

import os

import pytest


# Armazenamento de documentos em memória, sem tocar o disco.
os.environ["DOCUMENT_STORAGE_BACKEND"] = "memory"
# Sem chave: os agentes seguem pelo caminho de contingência.
os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("PLATFORM_SIGNING_SECRET", "test-signing-secret")
# Modo local: os testes usam tokens por papel além das contas.
os.environ.setdefault("AUTH_REQUIRED", "false")

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()


@pytest.fixture(autouse=True)
def reset_rate_limiters():
    """Os limitadores são objetos de módulo e sobreviveriam de um teste para o
    outro: sem zerar, o limite estreito das rotas de credencial acabaria
    barrando testes que apenas criam contas."""
    from app import main

    main.rate_limiter.reset()
    main.auth_rate_limiter.reset()
    yield
