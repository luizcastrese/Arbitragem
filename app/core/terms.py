"""Termos do procedimento, versionados e endereçáveis por hash.

O consentimento de cada parte não guarda apenas o número da versão: guarda o
SHA-256 do texto exibido. É esse hash que permite provar, depois, exatamente o
que a parte aceitou — e é ele que entra no manifesto assinado do caso.

Os textos ficam em `app/terms/<versão>.md`. Arquivos publicados nunca são
editados; uma mudança de termos é sempre uma versão nova.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

from app.core.hashing import sha256_text


TERMS_DIR = Path(__file__).resolve().parent.parent / "terms"


class TermsNotFound(LookupError):
    pass


@dataclass(frozen=True)
class Terms:
    version: str
    text: str
    sha256: str

    def as_reference(self) -> Dict[str, str]:
        """Identificação sem o corpo do texto, para gravar em consentimento,
        auditoria e manifesto."""
        return {"version": self.version, "sha256": self.sha256}

    def as_dict(self) -> Dict[str, str]:
        return {**self.as_reference(), "text": self.text}


def _normalize(raw: str) -> str:
    """Normaliza para que o mesmo texto produza o mesmo hash em qualquer
    sistema: quebras de linha `\\n` e um único `\\n` no fim."""
    return raw.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n"


@lru_cache(maxsize=1)
def _load_all() -> Dict[str, Terms]:
    versions: Dict[str, Terms] = {}
    for path in sorted(TERMS_DIR.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        text = _normalize(path.read_text(encoding="utf-8"))
        versions[path.stem] = Terms(
            version=path.stem,
            text=text,
            sha256=sha256_text(text),
        )
    if not versions:  # pragma: no cover - o repositório sempre traz uma versão
        raise RuntimeError(
            "Nenhum texto de termos encontrado em app/terms: o consentimento "
            "não pode ser registrado sem o texto correspondente."
        )
    return versions


def list_versions() -> List[str]:
    """Versões disponíveis, da mais antiga para a mais recente."""
    return sorted(_load_all())


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
