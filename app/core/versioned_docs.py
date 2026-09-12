"""Documentos publicados versionados e endereçáveis por hash.

Base comum dos termos do procedimento e da política de privacidade: cada
arquivo `<AAAA-MM-DD>.md` de um diretório é uma versão completa e imutável, e
o SHA-256 do texto normalizado é o que permite provar depois exatamente o que
foi publicado — e, no caso dos termos, o que a parte aceitou.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from app.core.hashing import sha256_text


class DocumentNotFound(LookupError):
    pass


@dataclass(frozen=True)
class VersionedDocument:
    version: str
    text: str
    sha256: str

    def as_reference(self) -> Dict[str, str]:
        """Identificação sem o corpo do texto, para gravar em consentimento,
        auditoria e manifesto."""
        return {"version": self.version, "sha256": self.sha256}

    def as_dict(self) -> Dict[str, str]:
        return {**self.as_reference(), "text": self.text}


def normalize(raw: str) -> str:
    """Normaliza para que o mesmo texto produza o mesmo hash em qualquer
    sistema: quebras de linha `\\n` e um único `\\n` no fim."""
    return raw.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n"


def load_directory(directory: Path, kind: str) -> Dict[str, VersionedDocument]:
    versions: Dict[str, VersionedDocument] = {}
    for path in sorted(directory.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        text = normalize(path.read_text(encoding="utf-8"))
        versions[path.stem] = VersionedDocument(
            version=path.stem,
            text=text,
            sha256=sha256_text(text),
        )
    if not versions:  # pragma: no cover - o repositório sempre traz uma versão
        raise RuntimeError(
            f"Nenhum texto de {kind} encontrado em {directory}: a plataforma "
            "não pode operar sem o texto publicado correspondente."
        )
    return versions


def sorted_versions(versions: Dict[str, VersionedDocument]) -> List[str]:
    """Versões disponíveis, da mais antiga para a mais recente."""
    return sorted(versions)
