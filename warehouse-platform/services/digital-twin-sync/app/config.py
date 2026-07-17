"""
Configuration for digital-twin-sync service.

Uses pydantic-settings for environment-variable-driven configuration
with full type validation and sensible defaults.
"""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Service identity ──────────────────────────────────────────
    SERVICE_NAME: str = Field(default="digital-twin-sync", description="Service identifier")
    PORT: int = Field(default=8006, ge=1024, le=65535, description="HTTP listen port")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")
    ENVIRONMENT: str = Field(default="development", description="Runtime environment")

    # ── Redis ────────────────────────────────────────────────────
    REDIS_URL: str = Field(
        default="redis://localhost:6379/5",
        description="Redis connection URL",
    )

    # ── Kafka ────────────────────────────────────────────────────
    KAFKA_BOOTSTRAP_SERVERS: str = Field(
        default="localhost:9092",
        description="Comma-separated Kafka bootstrap servers",
    )
    CONSUMER_GROUP_ID: str = Field(
        default="digital-twin-sync-group",
        description="Kafka consumer group identifier",
    )

    # ── External services ────────────────────────────────────────
    TOPOLOGY_SERVICE_URL: str = Field(
        default="http://localhost:8001",
        description="Base URL of the topology service",
    )

    # ── Digital-twin behaviour ───────────────────────────────────
    STATE_SNAPSHOT_INTERVAL_SECS: int = Field(
        default=30,
        ge=5,
        description="How often to broadcast periodic warehouse stats (seconds)",
    )
    ROBOT_POSITION_TTL_SECS: int = Field(
        default=300,
        ge=30,
        description="Redis TTL for robot position entries (seconds)",
    )

    # ── CORS ─────────────────────────────────────────────────────
    CORS_ORIGINS: list[str] = Field(
        default=["*"],
        description="Allowed CORS origins",
    )

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Ensure LOG_LEVEL is a valid Python logging level."""
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}")
        return v.upper()

    @field_validator("KAFKA_BOOTSTRAP_SERVERS")
    @classmethod
    def validate_kafka_servers(cls, v: str) -> str:
        """Strip whitespace from comma-separated server list."""
        return ",".join(s.strip() for s in v.split(","))

    @property
    def kafka_servers_list(self) -> list[str]:
        """Return Kafka bootstrap servers as a list."""
        return self.KAFKA_BOOTSTRAP_SERVERS.split(",")


# Module-level singleton — import this everywhere
settings = Settings()
