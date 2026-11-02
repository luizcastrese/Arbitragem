"""Estado do processo compartilhado pelas rotas.

Fica num módulo só para que haja um único ponto a trocar: as rotas leem
`ctx.settings`, `ctx.stage_runner` etc. no momento da chamada, e um teste que
substitui `context.settings` afeta todas elas de uma vez.

O que mora aqui é, por natureza, local ao processo: os limitadores de taxa
(a não ser que `RATE_LIMIT_BACKEND=redis`) e o registro em memória das etapas
em segundo plano. O estado que importa para o procedimento fica no banco.
"""

from __future__ import annotations

import os

from app.core.config import get_settings
from app.core.ratelimit import build_rate_limiter
from app.domain.jobs import StageRunner

APP_VERSION = "0.6.0"

settings = get_settings()
SESSION_COOKIE_NAME = "valinor_session"

TRUSTED_PROXY_NETWORKS = settings.trusted_proxy_networks

# Os webhooks chegam de IPs do Stripe e são autenticados por assinatura.
STRIPE_WEBHOOK_PATH = "/stripe/webhook"

rate_limiter = build_rate_limiter(
    settings,
    namespace="general",
    max_requests=settings.rate_limit_max_requests,
    window_seconds=settings.rate_limit_window_seconds,
    enabled=settings.rate_limit_enabled,
)

# As rotas de credencial (login, cadastro, verificação e redefinição) têm um
# limite próprio e bem mais estreito que o limite geral: são elas que um
# atacante repete para adivinhar senha ou varrer e-mails cadastrados. Fica
# ligado sempre, inclusive em desenvolvimento.
auth_rate_limiter = build_rate_limiter(
    settings,
    namespace="auth",
    max_requests=settings.auth_rate_limit_max_requests,
    window_seconds=settings.auth_rate_limit_window_seconds,
    enabled=True,
)

AUTH_RATE_LIMITED_PATHS = {
    "/auth/register",
    "/auth/login",
    "/auth/verify-email",
    "/auth/verify-email/resend",
    "/auth/password-reset",
    "/auth/password-reset/confirm",
}


# Etapas de modelo rodam aqui, fora do request. O tamanho da fila é o teto de
# etapas simultâneas no processo; cada uma segura uma conexão de banco
# enquanto roda, então não adianta subir além do pool.
stage_runner = StageRunner(max_workers=int(os.getenv("STAGE_WORKERS", "4")))

# Etapas assíncronas: campo do resultado no caso e status a restaurar se a
# execução falhar no meio.
ASYNC_STAGES = {
    "conciliation": {"claimed": False, "on_error_status": None},
    "organize": {"claimed": True, "on_error_status": "conciliation"},
    "decide": {"claimed": True, "on_error_status": "organized"},
    "review": {"claimed": True, "on_error_status": "decided"},
    "contest": {"claimed": True, "on_error_status": "attested"},
}

MAX_STAGE_WAIT_SECONDS = 300

# Intervalo da varredura que retoma a condução do gestor depois de um
# reinício (ver app.api.steward). 0 desliga a varredura periódica.
STEWARD_RECOVERY_INTERVAL_SECONDS = float(
    os.getenv("STEWARD_RECOVERY_INTERVAL_SECONDS", "60")
)
