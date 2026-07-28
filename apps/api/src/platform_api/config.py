"""Typed application configuration loaded only from trusted local sources."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, EmailStr, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
PositiveSeconds = Annotated[float, Field(gt=0)]
ModelName = Annotated[
    str,
    Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*(?::[A-Za-z0-9._-]+)?$", max_length=200),
]


class StrictSettings(BaseSettings):
    """Base settings policy shared by every independently loaded section."""

    model_config = SettingsConfigDict(
        env_file=(".env", "apps/api/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        frozen=True,
        populate_by_name=True,
        validate_default=True,
    )


class ApplicationSettings(StrictSettings):
    """HTTP application identity and runtime behavior."""

    model_config = SettingsConfigDict(env_prefix="APP_")

    name: str = "AI Website Generator API"
    environment: Environment = Field(default="development", validation_alias="APP_ENV")
    version: str = "0.0.0"
    debug: bool = False
    log_level: LogLevel = Field(default="INFO", validation_alias="LOG_LEVEL")
    api_host: str = Field(default="127.0.0.1", validation_alias="API_HOST")
    api_port: int = Field(default=8000, ge=1, le=65535, validation_alias="API_PORT")
    fake_dependencies: bool = False
    cors_allowed_origins: tuple[AnyHttpUrl, ...] = ()

    @field_validator("cors_allowed_origins")
    @classmethod
    def reject_cors_wildcard(cls, origins: tuple[AnyHttpUrl, ...]) -> tuple[AnyHttpUrl, ...]:
        """Require concrete origins so credentials can never combine with a wildcard."""
        if any(str(origin) == "*" for origin in origins):
            raise ValueError("CORS origins must be explicit")
        return origins


class DatabaseSettings(StrictSettings):
    """PostgreSQL connectivity and SQLAlchemy pool limits."""

    model_config = SettingsConfigDict(env_prefix="DATABASE_")

    url: SecretStr | None = None
    pool_size: int = Field(default=10, ge=1, le=100)
    max_overflow: int = Field(default=10, ge=0, le=100)
    pool_timeout_seconds: PositiveSeconds = 10.0
    command_timeout_seconds: PositiveSeconds = 30.0
    echo: bool = False

    @field_validator("url", mode="before")
    @classmethod
    def normalize_blank_url(cls, value: object) -> object:
        """Treat an intentionally blank example value as unconfigured."""
        return None if value == "" else value

    @field_validator("url")
    @classmethod
    def validate_asyncpg_url(cls, value: SecretStr | None) -> SecretStr | None:
        """Require the SQLAlchemy asyncpg driver and a concrete database host."""
        if value is None:
            return None
        parsed = urlsplit(value.get_secret_value())
        if parsed.scheme != "postgresql+asyncpg" or parsed.hostname is None:
            raise ValueError("DATABASE_URL must use postgresql+asyncpg:// with a host")
        return value


class RedisSettings(StrictSettings):
    """Redis connection and namespace settings."""

    model_config = SettingsConfigDict(env_prefix="REDIS_")

    url: SecretStr | None = None
    key_prefix: str = "aiwg"
    connect_timeout_seconds: PositiveSeconds = 3.0
    job_event_stream_max_length: int = Field(default=10_000, ge=100, le=1_000_000)
    job_event_heartbeat_seconds: float = Field(default=15.0, ge=1.0, le=60.0)
    job_event_authorization_recheck_seconds: float = Field(default=15.0, ge=1.0, le=60.0)
    job_event_max_streams_per_user: int = Field(default=3, ge=1, le=20)
    job_event_stream_lease_seconds: int = Field(default=90, ge=30, le=600)

    @field_validator("url", mode="before")
    @classmethod
    def normalize_blank_url(cls, value: object) -> object:
        """Treat an intentionally blank example value as unconfigured."""
        return None if value == "" else value

    @field_validator("url")
    @classmethod
    def validate_redis_url(cls, value: SecretStr | None) -> SecretStr | None:
        """Require a supported Redis transport and concrete host."""
        if value is None:
            return None
        parsed = urlsplit(value.get_secret_value())
        if parsed.scheme not in {"redis", "rediss"} or parsed.hostname is None:
            raise ValueError("REDIS_URL must use redis:// or rediss:// with a host")
        return value


class TemporalSettings(StrictSettings):
    """Temporal endpoint and control-plane workflow defaults."""

    model_config = SettingsConfigDict(env_prefix="TEMPORAL_")

    address: str = "127.0.0.1:7233"
    namespace: str = "default"
    task_queue: str = "control"
    connect_timeout_seconds: PositiveSeconds = 5.0

    @field_validator("address")
    @classmethod
    def validate_address(cls, value: str) -> str:
        """Require an explicit host and port for the trusted Temporal endpoint."""
        parsed = urlsplit(f"tcp://{value}")
        if parsed.hostname is None or parsed.port is None:
            raise ValueError("TEMPORAL_ADDRESS must contain a host and port")
        return value


class MinioSettings(StrictSettings):
    """MinIO development or AWS S3-compatible artifact storage settings."""

    model_config = SettingsConfigDict(env_prefix="MINIO_")

    provider: Literal["minio", "aws"] = "minio"
    endpoint: AnyHttpUrl | None = AnyHttpUrl("http://127.0.0.1:9000")
    region: str = "us-east-1"
    access_key: SecretStr | None = None
    secret_key: SecretStr | None = None
    session_token: SecretStr | None = None
    secure: bool = False
    connect_timeout_seconds: PositiveSeconds = 5.0
    read_timeout_seconds: PositiveSeconds = 60.0
    multipart_part_size: int = Field(
        default=8 * 1_024 * 1_024,
        ge=5 * 1_024 * 1_024,
        le=128 * 1_024 * 1_024,
    )

    @field_validator("endpoint", mode="before")
    @classmethod
    def normalize_blank_endpoint(cls, value: object) -> object:
        return None if value == "" else value

    @model_validator(mode="after")
    def validate_provider(self) -> Self:
        if (self.access_key is None) != (self.secret_key is None):
            raise ValueError("MINIO_ACCESS_KEY and MINIO_SECRET_KEY must be supplied together")
        if self.provider == "minio":
            if self.endpoint is None:
                raise ValueError("MinIO provider requires MINIO_ENDPOINT")
            if self.access_key is None or self.secret_key is None:
                return self
            if self.secure and self.endpoint.scheme != "https":
                raise ValueError("MINIO_SECURE requires an HTTPS endpoint")
        elif self.endpoint is not None:
            raise ValueError("AWS provider must use the SDK endpoint without MINIO_ENDPOINT")
        return self


class QdrantSettings(StrictSettings):
    """Private vector service and versioned design-pattern collection settings."""

    model_config = SettingsConfigDict(env_prefix="QDRANT_")

    url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:6333")
    api_key: SecretStr | None = None
    connect_timeout_seconds: PositiveSeconds = 5.0
    request_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    max_concurrency: int = Field(default=8, ge=1, le=64)
    max_batch_size: int = Field(default=256, ge=1, le=1_000)
    collection_alias: str = Field(
        default="design-patterns", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
    )
    vector_name: str = Field(default="design-pattern", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    serialization_schema_version: int = Field(default=1, ge=1, le=65_535)

    @model_validator(mode="after")
    def validate_endpoint(self) -> Self:
        parsed = urlsplit(str(self.url))
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("QDRANT_URL must not contain credentials, query, or fragment")
        if parsed.path not in {"", "/"}:
            raise ValueError("QDRANT_URL must identify the service root")
        return self


class OllamaSettings(StrictSettings):
    """Private inference endpoint and model identities."""

    model_config = SettingsConfigDict(env_prefix="OLLAMA_")

    url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:11434")
    vision_model: ModelName = "qwen3-vl:8b"
    generation_model: ModelName = "qwen3-coder:30b"
    embedding_model: ModelName = "qwen3-embedding:0.6b"
    connect_timeout_seconds: PositiveSeconds = 5.0
    request_timeout_seconds: float = Field(default=300.0, gt=0, le=1_800)
    concurrency_wait_seconds: float = Field(default=10.0, gt=0, le=120)
    max_concurrency: int = Field(default=2, ge=1, le=32)
    max_attempts: int = Field(default=3, ge=1, le=5)
    retry_backoff_seconds: float = Field(default=0.25, ge=0, le=10)
    circuit_failure_threshold: int = Field(default=3, ge=1, le=20)
    circuit_recovery_seconds: float = Field(default=30.0, gt=0, le=600)
    metadata_cache_seconds: float = Field(default=30.0, ge=0, le=600)
    max_prompt_bytes: int = Field(default=262_144, ge=1_024, le=2_097_152)
    max_image_bytes: int = Field(default=10_485_760, ge=1_024, le=52_428_800)
    max_total_image_bytes: int = Field(default=20_971_520, ge=1_024, le=104_857_600)
    max_response_bytes: int = Field(default=4_194_304, ge=1_024, le=16_777_216)
    keep_alive: str = Field(default="5m", pattern=r"^-?\d+(?:ms|s|m|h)?$")

    @model_validator(mode="after")
    def validate_endpoint_and_limits(self) -> Self:
        parsed = urlsplit(str(self.url))
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("OLLAMA_URL must not contain credentials, query, or fragment")
        if parsed.path not in {"", "/"}:
            raise ValueError("OLLAMA_URL must identify the service root")
        if self.max_total_image_bytes < self.max_image_bytes:
            raise ValueError("OLLAMA_MAX_TOTAL_IMAGE_BYTES must cover one maximum-sized image")
        return self


class SecuritySettings(StrictSettings):
    """Transport and middleware security policy."""

    model_config = SettingsConfigDict(env_prefix="SECURITY_")

    trusted_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "testserver")
    force_https: bool = True
    enable_docs: bool = False
    request_id_header: str = Field(default="X-Request-ID", pattern=r"^[A-Za-z][A-Za-z0-9-]{0,63}$")
    max_request_body_bytes: int = Field(default=1_048_576, ge=1_024, le=10_485_760)
    access_token_secret: SecretStr | None = None
    access_token_issuer: str = "ai-website-generator"  # noqa: S105 - public issuer ID.
    access_token_audience: str = "ai-website-generator-web"  # noqa: S105 - public audience ID.
    access_token_ttl_seconds: int = Field(default=300, ge=60, le=3_600)
    refresh_token_ttl_seconds: int = Field(default=2_592_000, ge=3_600, le=7_776_000)
    refresh_cookie_name: str = Field(
        default="aiwg_refresh", pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$"
    )
    refresh_cookie_domain: str | None = None
    refresh_cookie_secure: bool = True
    refresh_cookie_samesite: Literal["lax", "strict"] = "lax"
    login_rate_limit_attempts: int = Field(default=5, ge=1, le=100)
    login_rate_limit_window_seconds: int = Field(default=300, ge=10, le=3_600)
    email_verification_ttl_seconds: int = Field(default=86_400, ge=300, le=604_800)
    password_reset_ttl_seconds: int = Field(default=1_800, ge=300, le=86_400)
    administrator_emails: tuple[EmailStr, ...] = ()

    @field_validator("administrator_emails")
    @classmethod
    def normalize_administrator_emails(cls, values: tuple[EmailStr, ...]) -> tuple[EmailStr, ...]:
        normalized = tuple(value.strip().casefold() for value in values)
        if len(normalized) != len(set(normalized)):
            raise ValueError("SECURITY_ADMINISTRATOR_EMAILS must not contain duplicates")
        return normalized

    @field_validator("access_token_secret")
    @classmethod
    def validate_access_token_secret(cls, value: SecretStr | None) -> SecretStr | None:
        """Require enough entropy for the symmetric access-token signing key."""
        if value is not None and len(value.get_secret_value().encode()) < 32:
            raise ValueError("SECURITY_ACCESS_TOKEN_SECRET must contain at least 32 bytes")
        return value

    @field_validator("trusted_hosts")
    @classmethod
    def reject_wildcard_hosts(cls, hosts: tuple[str, ...]) -> tuple[str, ...]:
        """Prevent accidental deployment with an unrestricted Host header policy."""
        if not hosts or "*" in hosts:
            raise ValueError("SECURITY_TRUSTED_HOSTS must contain explicit hosts")
        return hosts


class EmailSettings(StrictSettings):
    """Transactional authentication email delivery settings."""

    model_config = SettingsConfigDict(env_prefix="EMAIL_")

    smtp_host: str = "127.0.0.1"
    smtp_port: int = Field(default=1025, ge=1, le=65_535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_start_tls: bool = False
    smtp_use_tls: bool = False
    smtp_timeout_seconds: PositiveSeconds = 10.0
    from_address: str = "no-reply@local.test"
    public_web_url: AnyHttpUrl = AnyHttpUrl("http://localhost:4200")

    @model_validator(mode="after")
    def validate_tls_modes(self) -> Self:
        """Reject mutually exclusive implicit and STARTTLS modes."""
        if self.smtp_use_tls and self.smtp_start_tls:
            raise ValueError("EMAIL_SMTP_USE_TLS and EMAIL_SMTP_START_TLS are mutually exclusive")
        return self


class ScanningSettings(StrictSettings):
    """Control-plane validation limits for future scan commands."""

    model_config = SettingsConfigDict(env_prefix="SCANNING_")

    max_pages_per_scan: int = Field(default=100, ge=1, le=10_000)
    max_depth: int = Field(default=5, ge=0, le=20)
    requests_per_second: float = Field(default=1.0, gt=0, le=20)
    crawler_user_agent: str = Field(
        default="AIWebsiteGeneratorBot/1.0", min_length=1, max_length=256
    )
    robots_max_bytes: int = Field(default=524_288, ge=1_024, le=2_097_152)
    workflow_timeout_seconds: int = Field(default=7_200, ge=60, le=86_400)


class GenerationSettings(StrictSettings):
    """Control-plane validation limits for future generation commands."""

    model_config = SettingsConfigDict(env_prefix="GENERATION_")

    max_pages_per_site: int = Field(default=50, ge=1, le=500)
    max_repair_attempts: int = Field(default=3, ge=0, le=10)
    workflow_timeout_seconds: int = Field(default=3_600, ge=60, le=86_400)


class Settings(StrictSettings):
    """Complete immutable settings graph assembled from independent sections."""

    application: ApplicationSettings = Field(default_factory=ApplicationSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    temporal: TemporalSettings = Field(default_factory=TemporalSettings)
    minio: MinioSettings = Field(default_factory=MinioSettings)
    qdrant: QdrantSettings = Field(default_factory=QdrantSettings)
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    email: EmailSettings = Field(default_factory=EmailSettings)
    scanning: ScanningSettings = Field(default_factory=ScanningSettings)
    generation: GenerationSettings = Field(default_factory=GenerationSettings)

    @model_validator(mode="after")
    def enforce_deployed_cookie_security(self) -> Self:
        """Never permit plaintext refresh cookies in deployed environments."""
        if self.application.environment in {"staging", "production"}:
            if not self.security.refresh_cookie_secure:
                raise ValueError("secure refresh cookies are required outside development and test")
            if self.security.access_token_secret is None:
                raise ValueError(
                    "access token signing secret is required outside development and test"
                )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache the process settings graph."""
    return Settings()


def clear_settings_cache() -> None:
    """Clear cached settings for tests that deliberately change the environment."""
    get_settings.cache_clear()
