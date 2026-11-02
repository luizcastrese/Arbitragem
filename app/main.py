"""Aplicação FastAPI da Valinor: criação do app, middlewares e roteadores.

As rotas vivem em `app/api/routes/`, uma por área. O estado do processo
(configurações, limitadores, fila de etapas) fica em `app/api/context.py`; as
guardas compartilhadas, em `app/api/common.py`; a condução do gestor, em
`app/api/steward.py`; e a execução em segundo plano, em
`app/api/background.py`.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# Os prompts do seletor e do gestor entram no registro de prompts no import.
from app.agents.selector import PROMPT as _SELECTOR_PROMPT  # noqa: F401
from app.agents.steward import PROMPT as _STEWARD_PROMPT  # noqa: F401
from app.api import context as ctx

# Mantidos aqui para quem já importa de `app.main` (testes e operação).
from app.api.context import (  # noqa: F401
    auth_rate_limiter,
    rate_limiter,
    settings,
    stage_runner,
)
from app.api.routes import (
    account,
    arbitration,
    attestation,
    auth,
    cases,
    documents,
    meta,
    payments,
    procedure,
    records,
    stages,
)
from app.api.steward import StewardRecoveryLoop
from app.core.client_ip import resolve_client_ip
from app.db.init_db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("valinor.request")

if ctx.settings.proxy_awareness_missing:
    logger.warning(
        "rate_limit_sem_proxy_declarado: TRUSTED_PROXY_IPS está vazio. Se "
        "houver proxy ou balanceador na frente do serviço, todas as "
        "requisições compartilharão a mesma chave de rate limit."
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    recovery = StewardRecoveryLoop(ctx.STEWARD_RECOVERY_INTERVAL_SECONDS)
    recovery.start()
    try:
        yield
    finally:
        recovery.stop()
        # Dreno: uma etapa cortada no meio deixaria o caso em processing_* até
        # o TTL de 10 minutos.
        ctx.stage_runner.shutdown(wait=True)


app = FastAPI(
    title="Valinor",
    version=ctx.APP_VERSION,
    description=(
        "Procedimento privado, voluntário e prévio ao Judiciário para disputas "
        "de serviços digitais entre empresas e profissionais. A IA busca o "
        "acordo e, sem ele, profere uma decisão fundamentada que não obriga as "
        "partes. A saída é o auto da "
        "decisão: documento assinado e verificável que pode servir de base a "
        "uma ação judicial. O resultado não é sentença judicial nem arbitral."
    ),
    lifespan=lifespan,
    docs_url="/docs" if ctx.settings.expose_api_docs else None,
    redoc_url="/redoc" if ctx.settings.expose_api_docs else None,
    openapi_url="/openapi.json" if ctx.settings.expose_api_docs else None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ctx.settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def observability_and_rate_limit(request: Request, call_next):
    token = request.cookies.get(ctx.SESSION_COOKIE_NAME)
    if token:
        headers = list(request.scope.get("headers", []))
        names = {name.lower() for name, _ in headers}
        if b"x-session-token" not in names:
            headers.append((b"x-session-token", token.encode("utf-8")))
        if b"x-actor-token" not in names:
            headers.append((b"x-actor-token", token.encode("utf-8")))
        request.scope["headers"] = headers

    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    client_key = resolve_client_ip(
        request.client.host if request.client else None,
        request.headers.get("x-forwarded-for"),
        ctx.TRUSTED_PROXY_NETWORKS,
    )

    if request.url.path in ctx.AUTH_RATE_LIMITED_PATHS and request.method == "POST":
        allowed, retry_after = ctx.auth_rate_limiter.allow(f"auth:{client_key}")
        if not allowed:
            logger.warning(
                "auth_rate_limited request_id=%s client=%s path=%s",
                request_id,
                client_key,
                request.url.path,
            )
            response = JSONResponse(
                status_code=429,
                content={
                    "detail": (
                        "Muitas tentativas de acesso a partir deste endereço. "
                        "Aguarde antes de tentar de novo."
                    )
                },
            )
            response.headers["Retry-After"] = str(int(retry_after) + 1)
            response.headers["X-Request-ID"] = request_id
            return response

    if ctx.rate_limiter.enabled and request.url.path != ctx.STRIPE_WEBHOOK_PATH:
        allowed, retry_after = ctx.rate_limiter.allow(client_key)
        if not allowed:
            logger.warning(
                "rate_limited request_id=%s client=%s path=%s",
                request_id,
                client_key,
                request.url.path,
            )
            response = JSONResponse(
                status_code=429,
                content={
                    "detail": "Limite de requisições excedido. Tente novamente em instantes."
                },
            )
            response.headers["Retry-After"] = str(int(retry_after) + 1)
            response.headers["X-Request-ID"] = request_id
            return response

    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.exception(
            "request_failed request_id=%s method=%s path=%s elapsed_ms=%.1f",
            request_id,
            request.method,
            request.url.path,
            elapsed_ms,
        )
        raise
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "request request_id=%s method=%s path=%s status=%s elapsed_ms=%.1f",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    response.headers["X-Request-ID"] = request_id
    return response


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Aplica uma linha de base também a erros e respostas do rate limiter.

    HSTS só é seguro quando a instalação declarou explicitamente que está em
    produção, onde ``PUBLIC_BASE_URL`` já é validada como HTTPS.
    """
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    if ctx.settings.is_production:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


for module in (
    meta,
    auth,
    cases,
    account,
    documents,
    procedure,
    arbitration,
    stages,
    attestation,
    payments,
    records,
):
    app.include_router(module.router)


frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/ui", StaticFiles(directory=frontend_dist, html=True), name="ui")
