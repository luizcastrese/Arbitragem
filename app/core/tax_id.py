"""CPF e CNPJ das partes.

O auto da decisão precisa qualificar quem litiga: sem documento, o texto não
serve de base para uma ação. Aqui só se valida a forma (dígitos verificadores),
não a existência do cadastro na Receita.

O CNPJ alfanumérico (Receita Federal, a partir de julho de 2026) é aceito: os
12 primeiros caracteres podem ser letras maiúsculas ou dígitos, e cada um vale
o código ASCII menos 48 no cálculo dos verificadores. Os dois verificadores
continuam numéricos.
"""

from __future__ import annotations

import re
from typing import Dict, Optional

_SEPARATORS = re.compile(r"[.\-/\s]")
_CPF = re.compile(r"^\d{11}$")
_CNPJ = re.compile(r"^[0-9A-Z]{12}\d{2}$")


class InvalidTaxId(ValueError):
    pass


def _cpf_digit(values: str, weight_start: int) -> int:
    total = sum(int(char) * weight for char, weight in zip(values, range(weight_start, 1, -1)))
    remainder = (total * 10) % 11
    return 0 if remainder == 10 else remainder


def _valid_cpf(value: str) -> bool:
    if len(set(value)) == 1:
        return False
    first = _cpf_digit(value[:9], 10)
    second = _cpf_digit(value[:10], 11)
    return value[9:] == f"{first}{second}"


def _cnpj_digit(values: str) -> int:
    weights = list(range(len(values) - 7, 1, -1)) + list(range(9, 1, -1))
    total = sum((ord(char) - 48) * weight for char, weight in zip(values, weights))
    remainder = total % 11
    return 0 if remainder < 2 else 11 - remainder


def _valid_cnpj(value: str) -> bool:
    if len(set(value)) == 1:
        return False
    first = _cnpj_digit(value[:12])
    second = _cnpj_digit(value[:13])
    return value[12:] == f"{first}{second}"


def normalize_tax_id(raw: Optional[str]) -> Optional[str]:
    """Devolve o documento só com caracteres significativos, ou levanta
    InvalidTaxId. Vazio vira None."""
    if raw is None:
        return None
    value = _SEPARATORS.sub("", str(raw)).upper()
    if not value:
        return None
    if _CPF.match(value):
        if not _valid_cpf(value):
            raise InvalidTaxId("CPF inválido")
        return value
    if _CNPJ.match(value):
        if not _valid_cnpj(value):
            raise InvalidTaxId("CNPJ inválido")
        return value
    raise InvalidTaxId("Informe um CPF (11 dígitos) ou um CNPJ (14 caracteres)")


def tax_id_kind(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return "cpf" if len(value) == 11 else "cnpj"


def format_tax_id(value: Optional[str]) -> str:
    if not value:
        return ""
    if len(value) == 11:
        return f"{value[:3]}.{value[3:6]}.{value[6:9]}-{value[9:]}"
    return f"{value[:2]}.{value[2:5]}.{value[5:8]}/{value[8:12]}-{value[12:]}"


def describe_tax_id(value: Optional[str]) -> Dict[str, Optional[str]]:
    return {
        "kind": tax_id_kind(value),
        "value": value,
        "formatted": format_tax_id(value) or None,
    }
