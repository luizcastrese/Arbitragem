"""Política de privacidade, versionada e endereçável por hash.

Mesma disciplina dos termos do procedimento: cada versão publicada é
identificada pelo SHA-256 do texto, para o titular verificar depois qual
política estava vigente quando os dados foram coletados.

Os textos ficam em `app/privacy/<versão>.md` e podem trazer marcadores
`{{nome}}` (controlador, contato e prazo de retenção). Eles são preenchidos com
os valores da configuração **no momento de servir** o texto, e o hash é
calculado sobre o texto já preenchido: é o que a pessoa leu. Trocar o
controlador, o contato ou o prazo muda o texto e, portanto, o hash.

Valor não configurado vira uma frase neutra, nunca o nome da variável.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from app.core.config import Settings, get_settings
from app.core.hashing import sha256_text
from app.core.versioned_docs import (
    DocumentNotFound,
    VersionedDocument,
    load_directory,
    sorted_versions,
)


PRIVACY_DIR = Path(__file__).resolve().parent.parent / "privacy"

PrivacyPolicy = VersionedDocument

PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")

# Texto usado quando o controlador não está configurado.
NEUTRAL_CONTROLLER = "a organização que opera esta plataforma"
NEUTRAL_RETENTION = (
    "enquanto a plataforma os mantiver: o apagamento automático do conteúdo "
    "não está ativado"
)


class PrivacyPolicyNotFound(DocumentNotFound):
    pass


@lru_cache(maxsize=1)
def _load_all() -> Dict[str, PrivacyPolicy]:
    """Modelos de texto, como publicados (ainda com os marcadores)."""
    return load_directory(PRIVACY_DIR, "política de privacidade")


def placeholder_values(settings: Settings) -> Dict[str, str]:
    contact = settings.privacy_contact
    days = settings.document_retention_days
    return {
        "controlador": settings.data_controller_name or NEUTRAL_CONTROLLER,
        # Link de e-mail: o leitor de markdown da interface o torna clicável.
        "contato": f"[{contact}](mailto:{contact})",
        "prazo_documentos": (
            f"{days} {'dia' if days == 1 else 'dias'} depois do encerramento do caso"
            if days > 0
            else NEUTRAL_RETENTION
        ),
    }


def render(template: str, settings: Settings) -> str:
    values = placeholder_values(settings)

    def fill(match: "re.Match[str]") -> str:
        value = values.get(match.group(1), match.group(0))
        # "Alugaí Ltda." seguido do ponto final da frase não vira "Ltda..".
        if value.endswith(".") and match.string[match.end() : match.end() + 1] == ".":
            value = value[:-1]
        return value

    return PLACEHOLDER.sub(fill, template)


def list_versions() -> List[str]:
    return sorted_versions(_load_all())


def current_version() -> str:
    return list_versions()[-1]


def get_policy(
    version: Optional[str] = None, settings: Optional[Settings] = None
) -> PrivacyPolicy:
    available = _load_all()
    resolved = version or current_version()
    if resolved not in available:
        raise PrivacyPolicyNotFound(resolved)
    text = render(available[resolved].text, settings or get_settings())
    return VersionedDocument(version=resolved, text=text, sha256=sha256_text(text))


def current_policy(settings: Optional[Settings] = None) -> PrivacyPolicy:
    return get_policy(None, settings)
