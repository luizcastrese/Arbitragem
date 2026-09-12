"""Identificação do cliente atrás de proxy e poda do rate limiter.

O que estes testes protegem: a chave de rate limit precisa ser o cliente e não
o balanceador, sem que um cliente direto consiga escolher a própria chave
mandando um `X-Forwarded-For`.
"""

import pytest

from app.core.client_ip import UNKNOWN_CLIENT, parse_trusted_proxies, resolve_client_ip
from app.core.ratelimit import SlidingWindowRateLimiter


PRIVATE = parse_trusted_proxies(["private"])
ANY_PROXY = parse_trusted_proxies(["*"])


def test_sem_proxy_confiavel_o_cabecalho_e_ignorado():
    """Um cliente direto não escolhe a própria chave de rate limit."""
    assert resolve_client_ip("203.0.113.5", "1.2.3.4", []) == "203.0.113.5"


def test_par_nao_confiavel_nao_habilita_o_cabecalho():
    assert resolve_client_ip("203.0.113.5", "1.2.3.4", PRIVATE) == "203.0.113.5"


def test_proxy_confiavel_entrega_o_cliente_real():
    assert resolve_client_ip("10.0.0.7", "203.0.113.9", PRIVATE) == "203.0.113.9"


def test_cadeia_descarta_saltos_confiaveis_da_direita_para_a_esquerda():
    trusted = parse_trusted_proxies(["private", "198.51.100.0/24"])
    resolved = resolve_client_ip(
        "10.0.0.7",
        "203.0.113.9, 198.51.100.4, 10.0.0.7",
        trusted,
    )
    assert resolved == "203.0.113.9"


def test_cliente_nao_forja_a_propria_chave_prefixando_a_cadeia():
    """O valor forjado fica à esquerda do endereço real e é descartado: o
    primeiro salto não confiável, lido da direita, é o que o proxy escreveu."""
    resolved = resolve_client_ip(
        "10.0.0.7",
        "9.9.9.9, 203.0.113.9",
        PRIVATE,
    )
    assert resolved == "203.0.113.9"


def test_entrada_ilegivel_interrompe_a_cadeia():
    resolved = resolve_client_ip("10.0.0.7", "203.0.113.9, _oculto", PRIVATE)
    assert resolved == "10.0.0.7"


def test_ipv4_com_porta_e_ipv6_entre_colchetes():
    assert resolve_client_ip("10.0.0.7:5555", "203.0.113.9:443", PRIVATE) == "203.0.113.9"
    assert resolve_client_ip("[::1]", "[2001:db8::1]", PRIVATE) == "2001:db8::1"


def test_sem_par_conhecido_a_chave_e_unknown():
    assert resolve_client_ip(None, "203.0.113.9", ANY_PROXY) == UNKNOWN_CLIENT


def test_curinga_confia_em_qualquer_par():
    assert resolve_client_ip("203.0.113.5", "198.51.100.1", ANY_PROXY) == "198.51.100.1"


def test_valor_invalido_e_rejeitado_na_configuracao():
    with pytest.raises(ValueError):
        parse_trusted_proxies(["não-é-um-ip"])


def test_limitador_poda_baldes_expirados():
    limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=10)
    for index in range(50):
        limiter.allow(f"cliente-{index}", now=100.0)
    assert limiter.tracked_keys() == 50

    # Passada a janela, a varredura descarta tudo o que expirou.
    limiter.allow("cliente-novo", now=200.0)
    assert limiter.tracked_keys() == 1


def test_limitador_respeita_o_teto_de_chaves():
    limiter = SlidingWindowRateLimiter(
        max_requests=5,
        window_seconds=3600,
        max_keys=10,
    )
    for index in range(100):
        limiter.allow(f"cliente-{index}", now=100.0 + index)
    assert limiter.tracked_keys() == 10
    # O balde mais recente sobrevive; o mais antigo saiu.
    assert limiter.allow("cliente-99", now=200.0)[0] is True
