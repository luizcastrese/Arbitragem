import os
from dataclasses import dataclass
from functools import lru_cache
from typing import List

from dotenv import load_dotenv


load_dotenv()


def _split_csv(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    openai_api_key: str
    openai_model: str
    embedding_model: str
    platform_signing_secret: str
    platform_ed25519_private_key: str
    contest_window_days: int
    app_env: str
    cors_origins: List[str]
    max_upload_bytes: int
    auth_required: bool
    rate_limit_enabled: bool
    rate_limit_max_requests: int
    rate_limit_window_seconds: int
    public_base_url: str
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_from: str
    smtp_use_tls: bool
    download_url_ttl_seconds: int

    @property
    def openai_enabled(self) -> bool:
        return bool(
            self.openai_api_key
            and self.openai_api_key != "your_key_here"
        )

    @property
    def allow_role_tokens(self) -> bool:
        """Tokens por papel são um atalho de operação local. Em produção o
        acesso deve depender exclusivamente de conta autenticada."""
        return not self.is_production

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    @property
    def using_development_signing_secret(self) -> bool:
        return self.platform_signing_secret == "development-only-secret-change-me"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def attestation_enabled(self) -> bool:
        return bool(self.platform_ed25519_private_key)


@lru_cache
def get_settings() -> Settings:
    app_env = os.getenv("APP_ENV", "development").strip().lower()

    signing_secret = os.getenv("PLATFORM_SIGNING_SECRET", "").strip()
    if not signing_secret or signing_secret == "replace-with-a-long-random-secret":
        if app_env == "production":
            raise RuntimeError(
                "PLATFORM_SIGNING_SECRET é obrigatório em produção: toda a "
                "garantia de assinatura do manifesto depende desse segredo. "
                "Gere um valor longo e aleatório antes de subir o serviço."
            )
        signing_secret = "development-only-secret-change-me"

    is_production = app_env == "production"
    # Em produção a autenticação por conta é obrigatória em todas as rotas;
    # o modo de tokens por papel só existe para operação local.
    auth_required = _env_flag("AUTH_REQUIRED", False) or is_production
    # Rate limiting fica ligado por padrão em produção; em desenvolvimento só
    # entra se explicitamente configurado, para não atrapalhar os testes.
    rate_limit_enabled = _env_flag("RATE_LIMIT_ENABLED", is_production)

    return Settings(
        database_url=os.getenv("DATABASE_URL", "sqlite:///./data/arbitragem.db"),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        embedding_model=os.getenv(
            "OPENAI_EMBEDDING_MODEL",
            "text-embedding-3-small",
        ),
        platform_signing_secret=signing_secret,
        platform_ed25519_private_key=os.getenv(
            "PLATFORM_ED25519_PRIVATE_KEY", ""
        ).strip(),
        contest_window_days=int(os.getenv("CONTEST_WINDOW_DAYS", "7")),
        app_env=app_env,
        cors_origins=_split_csv(
            os.getenv(
                "CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173",
            )
        ),
        max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024))),
        auth_required=auth_required,
        rate_limit_enabled=rate_limit_enabled,
        rate_limit_max_requests=int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "120")),
        rate_limit_window_seconds=int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")),
        public_base_url=os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/"),
        smtp_host=os.getenv("SMTP_HOST", "").strip(),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_username=os.getenv("SMTP_USERNAME", "").strip(),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        smtp_from=os.getenv("SMTP_FROM", "").strip(),
        smtp_use_tls=_env_flag("SMTP_USE_TLS", True),
        download_url_ttl_seconds=int(os.getenv("DOWNLOAD_URL_TTL_SECONDS", "300")),
    )
