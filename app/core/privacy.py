"""Política de privacidade, versionada e endereçável por hash.

Mesma disciplina dos termos do procedimento: cada versão publicada é imutável
e identificada pelo SHA-256 do texto. Assim o titular consegue verificar
depois qual política estava vigente quando os dados foram coletados.

Os textos ficam em `app/privacy/<versão>.md`.
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


PRIVACY_DIR = Path(__file__).resolve().parent.parent / "privacy"

PrivacyPolicy = VersionedDocument


class PrivacyPolicyNotFound(DocumentNotFound):
    pass


@lru_cache(maxsize=1)
def _load_all() -> Dict[str, PrivacyPolicy]:
    return load_directory(PRIVACY_DIR, "política de privacidade")


def list_versions() -> List[str]:
    return sorted_versions(_load_all())


def current_version() -> str:
    return list_versions()[-1]


def get_policy(version: str | None = None) -> PrivacyPolicy:
    available = _load_all()
    resolved = version or current_version()
    if resolved not in available:
        raise PrivacyPolicyNotFound(resolved)
    return available[resolved]


def current_policy() -> PrivacyPolicy:
    return get_policy(None)
