"""Registro versionado dos prompts dos agentes.

Uma decisão só é auditável se for possível dizer *com o quê* ela foi produzida.
Cada agente registra aqui o texto do seu prompt com uma versão explícita; o
registro deriva o SHA-256 do texto, que entra:

- no manifesto travado (política de prompts fixada antes do julgamento);
- no bloco `execution` de cada etapa executada por IA.

Comparar os dois revela *drift*: o prompt mudou entre a trava e a execução.
Editar um prompt sem subir a versão muda o hash e é detectado do mesmo jeito.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from app.core.hashing import sha256_text


@dataclass(frozen=True)
class PromptVersion:
    agent: str
    version: str
    text: str

    @property
    def sha256(self) -> str:
        return sha256_text(self.text)

    def as_reference(self) -> Dict[str, str]:
        """Identificação sem o corpo do prompt: é o que vai para o manifesto,
        para a auditoria e para o relatório."""
        return {
            "agent": self.agent,
            "version": self.version,
            "sha256": self.sha256,
        }


_REGISTRY: Dict[str, PromptVersion] = {}


def register_prompt(agent: str, version: str, text: str) -> PromptVersion:
    prompt = PromptVersion(agent=agent, version=version, text=text)
    _REGISTRY[agent] = prompt
    return prompt


def get_prompt(agent: str) -> PromptVersion:
    return _REGISTRY[agent]


def prompt_policy() -> Dict[str, Dict[str, str]]:
    """Política de prompts vigente, por agente. Vai para o manifesto no
    momento da trava."""
    return {
        agent: prompt.as_reference()
        for agent, prompt in sorted(_REGISTRY.items())
    }


def detect_drift(manifest: Optional[Dict], agent: str) -> Optional[Dict[str, str]]:
    """Compara o prompt em execução com o que foi travado no manifesto.

    Devolve `None` quando não há divergência (ou quando o manifesto é antigo e
    não fixou prompts) e um resumo da divergência quando há.
    """
    if not manifest:
        return None
    locked = (
        (manifest.get("model_policy") or {}).get("prompts") or {}
    ).get(agent)
    if not locked:
        return None

    try:
        running = get_prompt(agent)
    except KeyError:  # pragma: no cover - agente sempre registra seu prompt
        return None

    if (
        locked.get("version") == running.version
        and locked.get("sha256") == running.sha256
    ):
        return None

    return {
        "agent": agent,
        "locked_version": locked.get("version"),
        "locked_sha256": locked.get("sha256"),
        "running_version": running.version,
        "running_sha256": running.sha256,
    }
