"""
Configuration for alerting-service.

Uses pydantic-settings for environment-variable-driven configuration
with full type validation and sensible defaults.
"""

from __future__ import annotations

import json
from typing import Optional

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
    SERVICE_NAME: str = Field(default="alerting-service", description="Service identifier")
    PORT: int = Field(default=8005, ge=1024, le=65535, description="HTTP listen port")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")
    ENVIRONMENT: str = Field(default="development", description="Runtime environment")

    # ── Database ─────────────────────────────────────────────────
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://warehouse_admin:warehouse_secret@localhost:5432/warehouse_platform",
        description="Async SQLAlchemy database URL",
    )

    # ── Redis ────────────────────────────────────────────────────
    REDIS_URL: str = Field(
        default="redis://localhost:6379/4",
        description="Redis connection URL",
    )

    # ── Kafka ────────────────────────────────────────────────────
    KAFKA_BOOTSTRAP_SERVERS: str = Field(
        default="localhost:9092",
        description="Comma-separated Kafka bootstrap servers",
    )
    CONSUMER_GROUP_ID: str = Field(
        default="alerting-service-group",
        description="Kafka consumer group identifier",
    )

    # ── SMTP (optional) ──────────────────────────────────────────
    SMTP_HOST: Optional[str] = Field(default=None, description="SMTP server hostname")
    SMTP_PORT: int = Field(default=587, description="SMTP server port")
    SMTP_USERNAME: Optional[str] = Field(default=None, description="SMTP username")
    SMTP_PASSWORD: Optional[str] = Field(default=None, description="SMTP password")
    SMTP_FROM_EMAIL: Optional[str] = Field(
        default=None,
        description="From address for outgoing alert emails",
    )
    SMTP_USE_TLS: bool = Field(default=True, description="Use STARTTLS for SMTP")

    # ── Webhook (optional) ───────────────────────────────────────
    WEBHOOK_URLS: Optional[str] = Field(
        default=None,
        description="JSON array of webhook endpoint URLs",
    )

    # ── Alert deduplication ───────────────────────────────────────
    ALERT_DEDUP_WINDOW_MINUTES: int = Field(
        default=60,
        ge=1,
        description="Prevent duplicate notifications within this window (minutes)",
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

    @property
    def webhook_urls_list(self) -> list[str]:
        """Parse WEBHOOK_URLS JSON string into a Python list."""
        if not self.WEBHOOK_URLS:
            return []
        try:
            parsed = json.loads(self.WEBHOOK_URLS)
            if not isinstance(parsed, list):
                return []
            return [str(url) for url in parsed]
        except (json.JSONDecodeError, TypeError):
            return []

    @property
    def smtp_configured(self) -> bool:
        """Return True if all required SMTP fields are set."""
        return all(
            [self.SMTP_HOST, self.SMTP_USERNAME, self.SMTP_PASSWORD, self.SMTP_FROM_EMAIL]
        )


# Module-level singleton — import this everywhere
settings = Settings()
