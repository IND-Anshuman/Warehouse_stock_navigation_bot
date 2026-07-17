"""
Reconciliation Service — Application Configuration.
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
    SERVICE_NAME: str = Field(default="reconciliation-service")
    PORT: int = Field(default=8004)
    LOG_LEVEL: str = Field(default="INFO")
    ENVIRONMENT: str = Field(default="production")
    DEBUG: bool = Field(default=False)

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://warehouse_admin:warehouse_secret@localhost:5432/warehouse_platform"
    )
    DB_POOL_SIZE: int = Field(default=10)
    DB_MAX_OVERFLOW: int = Field(default=20)
    DB_POOL_TIMEOUT: int = Field(default=30)
    DB_ECHO: bool = Field(default=False)

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: str = Field(default="redis://:redis_secret@localhost:6379/3")
    REDIS_MAX_CONNECTIONS: int = Field(default=20)

    # ── Kafka ─────────────────────────────────────────────────────────────────
    KAFKA_BOOTSTRAP_SERVERS: str = Field(default="localhost:9092")
    CONSUMER_GROUP_ID: str = Field(
        default="reconciliation-service-group",
        description="Kafka consumer group identifier",
    )
    KAFKA_OBSERVATION_RAW_TOPIC: str = Field(default="observation.raw")
    KAFKA_OBSERVATION_DLQ_TOPIC: str = Field(default="observation.raw.dlq")
    KAFKA_MISMATCH_TOPIC: str = Field(default="inventory.reconciliation.mismatch")
    KAFKA_VERIFIED_TOPIC: str = Field(default="inventory.reconciliation.verified")
    KAFKA_ALERT_TOPIC: str = Field(default="alert.lifecycle")
    KAFKA_CONSUMER_MAX_POLL_RECORDS: int = Field(default=50)
    KAFKA_CONSUMER_AUTO_OFFSET_RESET: str = Field(default="earliest")

    # ── Upstream Services ─────────────────────────────────────────────────────
    TOPOLOGY_SERVICE_URL: str = Field(default="http://topology-service:8001")
    HTTP_CLIENT_TIMEOUT: float = Field(default=10.0)

    # ── Domain Thresholds ─────────────────────────────────────────────────────
    CONFIDENCE_ACCEPT_THRESHOLD: float = Field(
        default=0.70,
        ge=0.0,
        le=1.0,
        description="Minimum confidence to trigger reconciliation",
    )
    DEDUP_WINDOW_SECS: int = Field(default=86400)

    # ── Consumer Behaviour ────────────────────────────────────────────────────
    CONSUMER_MAX_RETRIES: int = Field(default=3)
    CONSUMER_RETRY_BACKOFF_MS: int = Field(default=1000)

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}")
        return upper

    @property
    def kafka_bootstrap_servers_list(self) -> list[str]:
        return [s.strip() for s in self.KAFKA_BOOTSTRAP_SERVERS.split(",")]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()
