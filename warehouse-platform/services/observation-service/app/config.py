"""
Observation Service — Application Configuration.

All settings are sourced from environment variables with sensible defaults.
Pydantic-settings handles validation and type coercion automatically.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Service configuration with environment variable binding."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Service Identity ──────────────────────────────────────────────────────
    SERVICE_NAME: str = Field(default="observation-service", description="Logical service name")
    PORT: int = Field(default=8003, description="HTTP server port")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")
    ENVIRONMENT: str = Field(default="production", description="Runtime environment")
    DEBUG: bool = Field(default=False, description="Enable debug mode")

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://warehouse_admin:warehouse_secret@localhost:5432/warehouse_platform",
        description="Async PostgreSQL connection string",
    )
    DB_POOL_SIZE: int = Field(default=10, description="SQLAlchemy connection pool size")
    DB_MAX_OVERFLOW: int = Field(default=20, description="Max pool overflow connections")
    DB_POOL_TIMEOUT: int = Field(default=30, description="Pool checkout timeout seconds")
    DB_ECHO: bool = Field(default=False, description="Log all SQL statements")

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: str = Field(
        default="redis://:redis_secret@localhost:6379/2",
        description="Redis connection URL",
    )
    REDIS_MAX_CONNECTIONS: int = Field(default=20, description="Redis pool size")

    # ── Kafka ─────────────────────────────────────────────────────────────────
    KAFKA_BOOTSTRAP_SERVERS: str = Field(
        default="localhost:9092",
        description="Comma-separated Kafka broker addresses",
    )
    KAFKA_PRODUCER_ACKS: str = Field(default="all", description="Kafka producer ack mode")
    KAFKA_PRODUCER_RETRIES: int = Field(default=5, description="Kafka producer retry count")
    KAFKA_OBSERVATION_RAW_TOPIC: str = Field(default="observation.raw")
    KAFKA_OBSERVATION_DLQ_TOPIC: str = Field(default="observation.raw.dlq")

    # ── MinIO / Object Storage ────────────────────────────────────────────────
    MINIO_ENDPOINT: str = Field(default="localhost:9000", description="MinIO host:port")
    MINIO_ACCESS_KEY: str = Field(default="minio_admin", description="MinIO access key")
    MINIO_SECRET_KEY: str = Field(default="minio_secret", description="MinIO secret key")
    MINIO_BUCKET: str = Field(default="warehouse-frames", description="Target bucket name")
    MINIO_SECURE: bool = Field(default=False, description="Use TLS for MinIO")
    MINIO_PRESIGN_EXPIRY_SECS: int = Field(default=3600, description="Presigned URL TTL")

    # ── Upstream Services ─────────────────────────────────────────────────────
    TOPOLOGY_SERVICE_URL: str = Field(
        default="http://topology-service:8001",
        description="Base URL of the topology service",
    )
    HTTP_CLIENT_TIMEOUT: float = Field(default=10.0, description="Downstream HTTP timeout")
    HTTP_CLIENT_MAX_CONNECTIONS: int = Field(default=100)

    # ── Domain Thresholds ─────────────────────────────────────────────────────
    CONFIDENCE_THRESHOLD: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="Minimum detection confidence to persist observation",
    )
    BLUR_THRESHOLD: float = Field(
        default=100.0,
        ge=0.0,
        description="Laplacian variance below this → frame is blurry",
    )
    MAX_BATCH_SIZE: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Maximum observations per batch ingest call",
    )
    DEDUP_WINDOW_SECS: int = Field(
        default=86400,
        ge=60,
        description="Observation deduplication TTL in seconds (default 24 h)",
    )

    # ── Outbox Worker ─────────────────────────────────────────────────────────
    OUTBOX_POLL_INTERVAL_SECS: int = Field(default=5, description="Outbox polling interval")
    OUTBOX_BATCH_SIZE: int = Field(default=100, description="Outbox events per poll")
    OUTBOX_MAX_RETRIES: int = Field(default=3, description="Retries before dead-lettering")

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Ensure LOG_LEVEL is a valid Python logging level."""
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}")
        return upper

    @property
    def kafka_bootstrap_servers_list(self) -> list[str]:
        """Return Kafka brokers as a list."""
        return [s.strip() for s in self.KAFKA_BOOTSTRAP_SERVERS.split(",")]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()
