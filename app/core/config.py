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
    cors_origins: List[str]
    max_upload_bytes: int

    @property
    def openai_enabled(self) -> bool:
        return bool(
            self.openai_api_key
            and self.openai_api_key != "your_key_here"
        )

    @property
    def using_development_signing_secret(self) -> bool:
        return self.platform_signing_secret == "development-only-secret-change-me"


@lru_cache
def get_settings() -> Settings:
    signing_secret = os.getenv("PLATFORM_SIGNING_SECRET", "").strip()
    if not signing_secret or signing_secret == "replace-with-a-long-random-secret":
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
        cors_origins=_split_csv(
            os.getenv(
                "CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173",
            )
        ),
        max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024))),
    )
