"""Termos do procedimento, versionados e endereçáveis por hash.

O consentimento de cada parte não guarda apenas o número da versão: guarda o
SHA-256 do texto exibido. É esse hash que permite provar, depois, exatamente o
que a parte aceitou — e é ele que entra no manifesto assinado do caso.

Os textos ficam em `app/terms/<versão>.md`. Arquivos publicados nunca são
editados; uma mudança de termos é sempre uma versão nova.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Dict, List

from app.core.versioned_docs import (
    DocumentNotFound,
    VersionedDocument,
    load_directory,
    sorted_versions,
)


TERMS_DIR = Path(__file__).resolve().parent.parent / "terms"

# Nome histórico, mantido porque o restante do código e os testes o importam.
Terms = VersionedDocument


class TermsNotFound(DocumentNotFound):
    pass


@lru_cache(maxsize=1)
def _load_all() -> Dict[str, Terms]:
    return load_directory(TERMS_DIR, "termos")


def list_versions() -> List[str]:
    """Versões disponíveis, da mais antiga para a mais recente."""
    return sorted_versions(_load_all())


def current_version() -> str:
    return list_versions()[-1]


def get_terms(version: str | None = None) -> Terms:
    """Devolve a versão pedida (ou a vigente). Versão desconhecida levanta
    TermsNotFound: aceitar termos que a plataforma não conhece não é aceite."""
    available = _load_all()
    resolved = version or current_version()
    if resolved not in available:
        raise TermsNotFound(resolved)
    return available[resolved]


def current_terms() -> Terms:
    return get_terms(None)
