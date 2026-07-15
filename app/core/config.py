import os
from dataclasses import dataclass
from functools import lru_cache
from typing import List

from dotenv import load_dotenv


load_dotenv()


def _split_csv(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_url: str
    openai_api_key: str
    openai_model: str
    openai_review_model: str
    embedding_model: str
    platform_signing_secret: str
    data_encryption_key: str
    cors_origins: List[str]
    max_upload_bytes: int
    auth_required: bool
    allow_legacy_case_tokens: bool
    expose_auth_tokens: bool
    secure_cookies: bool
    session_cookie_name: str
    rate_limit_per_minute: int
    email_verification_required: bool
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    public_base_url: str

    @property
    def openai_enabled(self) -> bool:
        return bool(
            self.openai_api_key
            and self.openai_api_key != "your_key_here"
        )

    @property
    def using_development_signing_secret(self) -> bool:
        return self.platform_signing_secret == "development-only-secret-change-me"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def validate_for_startup(self) -> None:
        if not self.is_production:
            return
        errors = []
        if not self.auth_required:
            errors.append("AUTH_REQUIRED deve ser true")
        if self.allow_legacy_case_tokens:
            errors.append("ALLOW_LEGACY_CASE_TOKENS deve ser false")
        if self.expose_auth_tokens:
            errors.append("EXPOSE_AUTH_TOKENS deve ser false")
        if not self.secure_cookies:
            errors.append("SECURE_COOKIES deve ser true")
        if self.using_development_signing_secret:
            errors.append("PLATFORM_SIGNING_SECRET deve ser definido")
        if not self.data_encryption_key:
            errors.append("DATA_ENCRYPTION_KEY deve ser definida")
        if not self.openai_review_model:
            errors.append("OPENAI_REVIEW_MODEL deve ser definido")
        if not self.openai_enabled:
            errors.append("OPENAI_API_KEY deve ser definida")
        if self.openai_review_model == self.openai_model:
            errors.append("OPENAI_REVIEW_MODEL deve ser diferente de OPENAI_MODEL")
        if not self.email_verification_required:
            errors.append("EMAIL_VERIFICATION_REQUIRED deve ser true")
        if not self.smtp_host or not self.smtp_from:
            errors.append("SMTP_HOST e SMTP_FROM devem ser definidos")
        if not self.public_base_url.startswith("https://"):
            errors.append("PUBLIC_BASE_URL deve usar HTTPS")
        if errors:
            raise RuntimeError("Configuração de produção inválida: " + "; ".join(errors))


@lru_cache
def get_settings() -> Settings:
    signing_secret = os.getenv("PLATFORM_SIGNING_SECRET", "").strip()
    if not signing_secret or signing_secret == "replace-with-a-long-random-secret":
        signing_secret = "development-only-secret-change-me"

    return Settings(
        app_env=os.getenv("APP_ENV", "development").strip().lower(),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./data/arbitragem.db"),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        openai_review_model=os.getenv("OPENAI_REVIEW_MODEL", "").strip(),
        embedding_model=os.getenv(
            "OPENAI_EMBEDDING_MODEL",
            "text-embedding-3-small",
        ),
        platform_signing_secret=signing_secret,
        data_encryption_key=os.getenv("DATA_ENCRYPTION_KEY", "").strip(),
        cors_origins=_split_csv(
            os.getenv(
                "CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173",
            )
        ),
        max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024))),
        auth_required=os.getenv("AUTH_REQUIRED", "true").strip().lower()
        in {"1", "true", "yes", "on"},
        allow_legacy_case_tokens=os.getenv(
            "ALLOW_LEGACY_CASE_TOKENS", "false"
        ).strip().lower() in {"1", "true", "yes", "on"},
        expose_auth_tokens=os.getenv("EXPOSE_AUTH_TOKENS", "false").strip().lower()
        in {"1", "true", "yes", "on"},
        secure_cookies=os.getenv("SECURE_COOKIES", "false").strip().lower()
        in {"1", "true", "yes", "on"},
        session_cookie_name=os.getenv("SESSION_COOKIE_NAME", "valinor_session").strip(),
        rate_limit_per_minute=max(
            10, int(os.getenv("RATE_LIMIT_PER_MINUTE", "120"))
        ),
        email_verification_required=os.getenv(
            "EMAIL_VERIFICATION_REQUIRED", "false"
        ).strip().lower() in {"1", "true", "yes", "on"},
        smtp_host=os.getenv("SMTP_HOST", "").strip(),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_user=os.getenv("SMTP_USER", "").strip(),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        smtp_from=os.getenv("SMTP_FROM", "").strip(),
        public_base_url=os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
    )
