"""Identificação do cliente real atrás de proxies reversos.

Rate limit e lockout de credencial só valem se a chave for o cliente, não o
balanceador. Atrás de um proxy `request.client.host` é sempre o endereço do
proxy: todo mundo cai no mesmo balde e a plataforma inteira é trancada pela
tentativa de um único atacante — ou o limite é afrouxado e deixa de proteger.

`X-Forwarded-For` é um cabeçalho que o cliente pode forjar, então ele só é
lido quando o par TCP imediato está na lista de proxies confiáveis
(``TRUSTED_PROXY_IPS``). A lista é percorrida da direita para a esquerda,
descartando os saltos confiáveis, e o primeiro endereço não confiável é o
cliente. Sem configuração, nada é lido do cabeçalho e o comportamento é o
mesmo de antes: o par TCP.
"""

from __future__ import annotations

import ipaddress
from typing import List, Optional, Sequence, Union


Network = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]

# Redes privadas: o caso comum de um proxy no mesmo host ou na mesma VPC.
PRIVATE_NETWORK_ALIASES = {
    "private": (
        "127.0.0.0/8",
        "::1/128",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "fc00::/7",
    ),
}

UNKNOWN_CLIENT = "unknown"


def parse_trusted_proxies(values: Sequence[str]) -> List[Network]:
    """Converte a configuração em redes. Aceita IP, CIDR, `private` e `*`.

    `*` vira 0.0.0.0/0 e ::/0: confia em qualquer par TCP. Só é correto
    quando a aplicação não é alcançável diretamente, apenas pelo proxy.
    """
    networks: List[Network] = []
    for raw in values:
        value = raw.strip().lower()
        if not value:
            continue
        if value in {"*", "all", "any"}:
            networks.append(ipaddress.ip_network("0.0.0.0/0"))
            networks.append(ipaddress.ip_network("::/0"))
            continue
        if value in PRIVATE_NETWORK_ALIASES:
            for alias in PRIVATE_NETWORK_ALIASES[value]:
                networks.append(ipaddress.ip_network(alias))
            continue
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError as exc:
            raise ValueError(
                f"TRUSTED_PROXY_IPS contém um valor inválido: {raw!r}. "
                "Use IP, CIDR, 'private' ou '*'."
            ) from exc
    return networks


def _address(value: Optional[str]):
    if not value:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    # IPv6 entre colchetes, com ou sem porta: [::1]:443
    if candidate.startswith("["):
        candidate = candidate[1:].split("]", 1)[0]
    elif candidate.count(":") == 1:
        # IPv4 com porta. IPv6 puro tem mais de um ":" e não é fatiado aqui.
        candidate = candidate.split(":", 1)[0]
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        return None


def _is_trusted(address, trusted: Sequence[Network]) -> bool:
    return any(address in network for network in trusted)


def resolve_client_ip(
    peer: Optional[str],
    forwarded_for: Optional[str],
    trusted_proxies: Sequence[Network],
) -> str:
    """Devolve o endereço do cliente como texto, ou `unknown`.

    Sem proxies confiáveis configurados, ou com um par TCP fora da lista, o
    cabeçalho é ignorado por inteiro — um cliente direto não escolhe a própria
    chave de rate limit.
    """
    peer_address = _address(peer)
    if peer_address is None:
        return UNKNOWN_CLIENT
    if not trusted_proxies or not _is_trusted(peer_address, trusted_proxies):
        return str(peer_address)
    if not forwarded_for:
        return str(peer_address)

    hops = [_address(item) for item in forwarded_for.split(",")]
    for candidate in reversed(hops):
        if candidate is None:
            # Entrada ilegível (por exemplo um identificador obfuscado ou um
            # valor forjado): a cadeia deixa de ser interpretável e o par TCP
            # é a única informação que ainda podemos afirmar.
            return str(peer_address)
        if not _is_trusted(candidate, trusted_proxies):
            return str(candidate)
    # Todos os saltos são proxies confiáveis: o cliente é o salto mais à
    # esquerda, e na falta de qualquer salto legível o próprio par.
    if hops and hops[0] is not None:
        return str(hops[0])
    return str(peer_address)
