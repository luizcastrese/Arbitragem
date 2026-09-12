"""Formas indiretas de registrar quem é alguém.

A cadeia de auditoria é encadeada por hash e sustenta attestations que
terceiros podem ter usado: nenhum evento pode ser reescrito depois. Isso torna
a auditoria o pior lugar possível para guardar um identificador direto — um
e-mail gravado ali fica legível para todos os participantes do caso e não pode
mais ser apagado quando o titular pedir a eliminação.

A saída é não gravar o identificador. O par (máscara, impressão) mantém a
auditoria útil — dá para reconhecer o endereço quando já se sabe qual é, e
comparar dois eventos entre si — sem reter o endereço em si.
"""

from __future__ import annotations

from typing import Dict

from app.core.hashing import sha256_text


def mask_email(email: str) -> str:
    """`carlos@empresa.com.br` vira `c****@empresa.com.br`.

    O domínio fica: ele quase nunca identifica uma pessoa e é o que dá
    sentido ao evento ("convidamos alguém da empresa reclamada").
    """
    value = (email or "").strip()
    if "@" not in value:
        return "****" if value else ""
    local, _, domain = value.partition("@")
    if not local:
        return f"****@{domain}"
    return f"{local[0]}****@{domain}"


def email_fingerprint(email: str) -> str:
    """Impressão estável do endereço normalizado, para comparar sem revelar."""
    return sha256_text((email or "").strip().lower())


def email_reference(email: str) -> Dict[str, str]:
    """Como um e-mail entra em um registro que não pode ser apagado."""
    return {
        "email_masked": mask_email(email),
        "email_sha256": email_fingerprint(email),
    }
