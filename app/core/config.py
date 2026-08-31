import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional

from dotenv import load_dotenv

from app.core.encryption import load_key as load_document_encryption_key


load_dotenv()


def _split_csv(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_or(name: str, fallback: str) -> str:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return fallback
    return raw.strip()


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
    email_verification_required: bool
    email_verification_ttl_hours: int
    password_reset_ttl_minutes: int
    login_max_attempts: int
    login_lockout_seconds: int
    rate_limit_enabled: bool
    rate_limit_max_requests: int
    rate_limit_window_seconds: int
    auth_rate_limit_max_requests: int
    auth_rate_limit_window_seconds: int
    public_base_url: str
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_from: str
    smtp_use_tls: bool
    download_url_ttl_seconds: int
    nostr_private_key_hex: str
    nostr_relays: List[str]
    llm_default_provider: str
    openrouter_api_key: str
    openrouter_base_url: str
    llm_request_timeout_seconds: float
    llm_max_retries: int
    llm_allowed_providers: List[str]
    llm_allowed_models: List[str]
    conciliator_provider: str
    conciliator_model: str
    organizer_provider: str
    organizer_model: str
    judge_provider: str
    judge_model: str
    reviewer_provider: str
    reviewer_model: str
    appeal_provider: str
    appeal_model: str
    embedding_provider: str
    decision_stability_enabled: bool
    decision_stability_runs: int
    decision_stability_threshold: float
    framework_id: str
    max_appeals_per_attestation: int
    case_value_limit_minor_units: int
    llm_fallback_provider: str
    llm_fallback_model: str

    @property
    def openai_enabled(self) -> bool:
        return bool(
            self.openai_api_key
            and self.openai_api_key != "your_key_here"
        )

    @property
    def openrouter_enabled(self) -> bool:
        return bool(self.openrouter_api_key)

    @property
    def llm_enabled(self) -> bool:
        return self.openai_enabled or self.openrouter_enabled

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

    @property
    def nostr_anchor_enabled(self) -> bool:
        return bool(self.nostr_private_key_hex and self.nostr_relays)

    @property
    def model_independence_satisfied(self) -> bool:
        return (self.judge_provider, self.judge_model) != (
            self.reviewer_provider,
            self.reviewer_model,
        )

    @property
    def demo_non_decisional(self) -> bool:
        """Sem independência julgador/revisor a instância não emite attestation
        de mérito. Em produção com LLM ligado isso nem chega a subir."""
        return not self.model_independence_satisfied

    @property
    def llm_explicit_fallback(self) -> Optional[Dict[str, str]]:
        if not self.llm_fallback_provider or not self.llm_fallback_model:
            return None
        return {
            "provider": self.llm_fallback_provider,
            "model": self.llm_fallback_model,
            "reason": "configured_fallback",
        }

    def agent_model_policy(self) -> Dict[str, object]:
        return {
            "default_provider": self.llm_default_provider,
            "conciliator": {
                "provider": self.conciliator_provider,
                "model": self.conciliator_model,
            },
            "organizer": {
                "provider": self.organizer_provider,
                "model": self.organizer_model,
            },
            "judge": {
                "provider": self.judge_provider,
                "model": self.judge_model,
            },
            "reviewer": {
                "provider": self.reviewer_provider,
                "model": self.reviewer_model,
            },
            "appeal": {
                "provider": self.appeal_provider,
                "model": self.appeal_model,
            },
            "embedding": {
                "provider": self.embedding_provider,
                "model": self.embedding_model,
            },
            "fallback": self.llm_explicit_fallback,
            "openai_enabled_at_lock": self.llm_enabled,
            "model_independence_satisfied": self.model_independence_satisfied,
            "demo_non_decisional": self.demo_non_decisional,
            "user_configurable_private_instructions": False,
            "stability": {
                "enabled": self.decision_stability_enabled,
                "runs": self.decision_stability_runs,
                "threshold": self.decision_stability_threshold,
            },
            "appeal_policy": {
                "max_appeals_per_attestation": self.max_appeals_per_attestation,
                "automatic": True,
            },
        }


def validate_runtime_policy(settings: Settings) -> None:
    """Em produção, julgador e revisor iguais com LLM ligado derrubam o boot."""
    if (
        settings.is_production
        and settings.llm_enabled
        and not settings.model_independence_satisfied
    ):
        raise RuntimeError(
            "Em produção o julgador e o revisor devem usar modelos distintos "
            "(preferencialmente provedores ou famílias diferentes). "
            "Configure JUDGE_MODEL e REVIEWER_MODEL (e/ou os providers) com "
            "valores diferentes, ou a instância entra em modo de demonstração "
            "não decisório apenas fora de produção."
        )


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

    if is_production:
        try:
            document_key = load_document_encryption_key()
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        if document_key is None:
            raise RuntimeError(
                "DOCUMENT_ENCRYPTION_KEY é obrigatório em produção: sem ele os "
                "documentos são gravados sem criptografia. Gere uma chave com "
                "`python -m app.core.encryption` antes de subir o serviço."
            )

    auth_required = True if is_production else _env_flag("AUTH_REQUIRED", True)
    rate_limit_enabled = _env_flag("RATE_LIMIT_ENABLED", is_production)
    email_verification_required = (
        True if is_production else _env_flag("EMAIL_VERIFICATION_REQUIRED", False)
    )

    default_model = _env_or("OPENAI_MODEL", "gpt-5-mini")
    default_provider = _env_or("LLM_DEFAULT_PROVIDER", "openai")
    allowed_providers = _split_csv(
        os.getenv("LLM_ALLOWED_PROVIDERS", "openai,openrouter,fake")
    )
    allowed_models = _split_csv(os.getenv("LLM_ALLOWED_MODELS", ""))

    settings = Settings(
        database_url=os.getenv("DATABASE_URL", "sqlite:///./data/arbitragem.db"),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=default_model,
        embedding_model=_env_or(
            "EMBEDDING_MODEL",
            _env_or("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
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
        email_verification_required=email_verification_required,
        email_verification_ttl_hours=int(
            os.getenv("EMAIL_VERIFICATION_TTL_HOURS", "48")
        ),
        password_reset_ttl_minutes=int(
            os.getenv("PASSWORD_RESET_TTL_MINUTES", "60")
        ),
        login_max_attempts=int(os.getenv("LOGIN_MAX_ATTEMPTS", "5")),
        login_lockout_seconds=int(os.getenv("LOGIN_LOCKOUT_SECONDS", "900")),
        rate_limit_enabled=rate_limit_enabled,
        rate_limit_max_requests=int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "120")),
        rate_limit_window_seconds=int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")),
        auth_rate_limit_max_requests=int(
            os.getenv("AUTH_RATE_LIMIT_MAX_REQUESTS", "12")
        ),
        auth_rate_limit_window_seconds=int(
            os.getenv("AUTH_RATE_LIMIT_WINDOW_SECONDS", "300")
        ),
        public_base_url=os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/"),
        smtp_host=os.getenv("SMTP_HOST", "").strip(),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_username=os.getenv("SMTP_USERNAME", "").strip(),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        smtp_from=os.getenv("SMTP_FROM", "").strip(),
        smtp_use_tls=_env_flag("SMTP_USE_TLS", True),
        download_url_ttl_seconds=int(os.getenv("DOWNLOAD_URL_TTL_SECONDS", "300")),
        nostr_private_key_hex=os.getenv("NOSTR_PRIVATE_KEY_HEX", "").strip(),
        nostr_relays=_split_csv(os.getenv("NOSTR_RELAYS", "")),
        llm_default_provider=default_provider,
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", "").strip(),
        openrouter_base_url=_env_or(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ),
        llm_request_timeout_seconds=float(
            os.getenv("LLM_REQUEST_TIMEOUT_SECONDS", "60")
        ),
        llm_max_retries=int(os.getenv("LLM_MAX_RETRIES", "2")),
        llm_allowed_providers=allowed_providers,
        llm_allowed_models=allowed_models,
        conciliator_provider=_env_or("CONCILIATOR_PROVIDER", default_provider),
        conciliator_model=_env_or("CONCILIATOR_MODEL", default_model),
        organizer_provider=_env_or("ORGANIZER_PROVIDER", default_provider),
        organizer_model=_env_or("ORGANIZER_MODEL", default_model),
        judge_provider=_env_or("JUDGE_PROVIDER", default_provider),
        judge_model=_env_or("JUDGE_MODEL", default_model),
        reviewer_provider=_env_or("REVIEWER_PROVIDER", default_provider),
        reviewer_model=_env_or("REVIEWER_MODEL", default_model),
        appeal_provider=_env_or("APPEAL_PROVIDER", default_provider),
        appeal_model=_env_or("APPEAL_MODEL", default_model),
        embedding_provider=_env_or("EMBEDDING_PROVIDER", default_provider),
        decision_stability_enabled=_env_flag("DECISION_STABILITY_ENABLED", False),
        decision_stability_runs=max(2, int(os.getenv("DECISION_STABILITY_RUNS", "2"))),
        decision_stability_threshold=float(
            os.getenv("DECISION_STABILITY_THRESHOLD", "1.0")
        ),
        framework_id=_env_or("FRAMEWORK_ID", "digital_services_b2b_v1"),
        max_appeals_per_attestation=int(os.getenv("MAX_APPEALS_PER_ATTESTATION", "1")),
        case_value_limit_minor_units=int(
            os.getenv("CASE_VALUE_LIMIT_MINOR_UNITS", "500000000")
        ),
        llm_fallback_provider=os.getenv("LLM_FALLBACK_PROVIDER", "").strip(),
        llm_fallback_model=os.getenv("LLM_FALLBACK_MODEL", "").strip(),
    )
    validate_runtime_policy(settings)
    return settings
