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
        auth_required=os.getenv("AUTH_REQUIRED", "false").strip().lower()
        in {"1", "true", "yes", "on"},
    )
