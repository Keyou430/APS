from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Hermes Enterprise Platform API"
    app_env: str = "development"
    debug: bool = False
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    expose_docs: bool = True
    database_url: str = "sqlite+aiosqlite:///./agent_platform.db"
    jwt_secret_key: str = "development-only-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    hermes_profiles_root: Path = Path("./data/hermes-profiles")
    hermes_api_url: str = "http://127.0.0.1:8642"
    hermes_knowledge_api_url: str = "http://127.0.0.1:8643"
    hermes_api_key: SecretStr | None = None
    hermes_use_http: bool = False
    hermes_http_timeout_seconds: float = 30.0
    hermes_http_connect_timeout_seconds: float = 5.0
    hermes_http_max_retries: int = 1
    memory_extraction_enabled: bool = False
    memory_extraction_provider: str = "platform-disabled"
    memory_extraction_provider_version: str = "v1"
    memory_capture_ttl_hours: int = Field(default=24, gt=0, le=168)
    memory_worker_poll_seconds: float = Field(default=1.0, gt=0, le=60)
    memory_worker_lease_seconds: float = Field(default=300.0, gt=0)
    pipeline_worker_lease_seconds: float = Field(default=300.0, gt=0)
    pipeline_worker_max_attempts: int = Field(default=3, gt=0, le=10)
    feishu_app_id: str | None = None
    feishu_app_secret: SecretStr | None = None
    feishu_delivery_configured: bool = False
    feishu_read_configured: bool = False
    feishu_read_allowed_organization_ids: str = ""
    feishu_read_allowed_document_tokens: str = ""
    feishu_read_allowed_base_tables: str = ""
    feishu_read_allowed_chat_ids: str = ""
    feishu_api_domain: str = "https://open.feishu.cn"
    platform_public_base_url: str | None = None
    delivery_worker_lease_seconds: float = Field(default=120.0, gt=0)
    delivery_worker_interval_seconds: float = Field(default=1.0, gt=0, le=60)
    delivery_worker_max_attempts: int = Field(default=5, gt=0, le=20)
    delivery_worker_backoff_base_seconds: int = Field(default=5, gt=0)
    work_item_archive_enabled: bool = False
    work_item_archive_poll_seconds: float = Field(default=60.0, gt=0, le=3600)
    work_item_archive_batch_size: int = Field(default=100, gt=0, le=1000)
    memory_embedding_enabled: bool = False
    memory_embedding_api_url: str | None = None
    memory_embedding_api_key: SecretStr | None = None
    memory_embedding_model: Literal["text-embedding-v4"] = "text-embedding-v4"
    memory_embedding_timeout_seconds: float = Field(default=30.0, gt=0)
    sandbox_runner_enabled: bool = False
    sandbox_runner_url: str = "https://192.168.3.107:9443"
    sandbox_runner_ca_certificate: Path = Path("/run/hermes-runner-control/ca.crt")
    sandbox_runner_client_certificate: Path = Path("/run/hermes-runner-control/client.crt")
    sandbox_runner_client_private_key: Path = Path("/run/hermes-runner-control/client.key")
    sandbox_runner_timeout_seconds: float = 10.0
    sandbox_max_active_runs_global: int = Field(default=8, gt=0)
    sandbox_max_active_runs_per_organization: int = Field(default=4, gt=0)
    sandbox_max_active_runs_per_user: int = Field(default=2, gt=0)
    rag_embedding_enabled: bool = False
    rag_embedding_api_url: str | None = None
    rag_embedding_api_key: SecretStr | None = None
    rag_embedding_model: Literal["text-embedding-v4"] = "text-embedding-v4"
    rag_embedding_dimensions: Literal[1024] = 1024
    rag_embedding_timeout_seconds: float = Field(default=30.0, gt=0)
    rag_worker_poll_seconds: float = Field(default=1.0, gt=0)
    rag_query_embedding_url: str | None = None
    rag_query_embedding_token: SecretStr | None = None
    rag_query_embedding_timeout_seconds: float = Field(default=10.0, gt=0)
    rag_query_audit_hmac_key: SecretStr | None = None
    rag_query_audit_hmac_version: int = Field(default=1, gt=0)
    rag_query_embedding_host: str = "0.0.0.0"
    rag_query_embedding_port: int = Field(default=8091, gt=0, le=65535)
    feature_external_guests: bool = False
    guest_invitation_delivery_adapter: Literal["test", "smtp"] = "test"
    guest_invitation_public_base_url: str | None = None
    guest_invitation_recipient_allowlist: str = ""
    smtp_host: str | None = None
    smtp_port: int = Field(default=465, gt=0, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from_email: str | None = None
    smtp_timeout_seconds: float = Field(default=10.0, gt=0)
    upload_dir: Path = Path("./uploads")
    cors_origins: list[str] = ["http://localhost:5173"]
    admin_username: str = "admin"
    admin_password: str = "admin123"
    admin_email: str = "admin@example.com"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @model_validator(mode="before")
    @classmethod
    def normalize_fixed_embedding_dimension(cls, value: object) -> object:
        if isinstance(value, dict) and value.get("rag_embedding_dimensions") == "1024":
            value = dict(value)
            value["rag_embedding_dimensions"] = 1024
        return value

    @model_validator(mode="after")
    def require_approved_guest_delivery_in_production(self) -> "Settings":
        production = self.app_env.casefold() in {"production", "prod", "container"}
        if self.app_env.casefold() in {"production", "prod", "staging"} and not self.rag_embedding_enabled:
            raise ValueError(
                "RAG_EMBEDDING_ENABLED must be true in staging/production-like environments"
            )
        if production:
            if self.jwt_secret_key in {"development-only-change-me", "change-this"}:
                raise ValueError("JWT_SECRET_KEY must be replaced in production-like environments")
            if self.admin_password in {"admin123", "change-this-admin-password"}:
                raise ValueError("ADMIN_PASSWORD must be replaced in production-like environments")
            hmac_key = (
                self.rag_query_audit_hmac_key.get_secret_value()
                if self.rag_query_audit_hmac_key is not None
                else ""
            )
            if not hmac_key or hmac_key.casefold().startswith(("change-this", "replace-with")):
                raise ValueError(
                    "RAG_QUERY_AUDIT_HMAC_KEY must be a non-placeholder secret in production-like environments"
                )
        if self.feature_external_guests and production and self.guest_invitation_delivery_adapter != "smtp":
            raise ValueError("FEATURE_EXTERNAL_GUESTS requires SMTP invitation delivery in production")
        if self.guest_invitation_delivery_adapter == "smtp":
            password = self.smtp_password.get_secret_value() if self.smtp_password is not None else ""
            required = {
                "GUEST_INVITATION_PUBLIC_BASE_URL": self.guest_invitation_public_base_url,
                "GUEST_INVITATION_RECIPIENT_ALLOWLIST": self.guest_invitation_recipient_allowlist,
                "SMTP_HOST": self.smtp_host,
                "SMTP_USERNAME": self.smtp_username,
                "SMTP_PASSWORD": password,
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ValueError(f"SMTP invitation delivery requires {', '.join(missing)}")
            assert self.guest_invitation_public_base_url is not None
            if not self.guest_invitation_public_base_url.startswith(("http://", "https://")):
                raise ValueError("GUEST_INVITATION_PUBLIC_BASE_URL must use HTTP or HTTPS")
            if production and not self.guest_invitation_public_base_url.startswith("https://"):
                raise ValueError("Production invitation links must use HTTPS")
        return self

    def guest_invitation_recipient_allowed(self, email: str) -> bool:
        recipients = {
            part.strip().casefold()
            for part in self.guest_invitation_recipient_allowlist.split(",")
            if part.strip()
        }
        return email.strip().casefold() in recipients


@lru_cache
def get_settings() -> Settings:
    return Settings()
