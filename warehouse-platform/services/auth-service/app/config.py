"""
app/config.py — Pydantic Settings for auth-service.
All values can be overridden by environment variables or a .env file.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── Service identity ──────────────────────────────────────────────────────
    SERVICE_NAME: str = Field(default="auth-service")
    PORT: int = Field(default=8006)
    LOG_LEVEL: str = Field(default="INFO")
    ENVIRONMENT: str = Field(default="development")  # development | staging | production

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/auth_db"
    )

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    # ── Kafka ─────────────────────────────────────────────────────────────────
    KAFKA_BOOTSTRAP_SERVERS: str = Field(default="localhost:9092")
    KAFKA_TOPIC_AUTH_EVENTS: str = Field(default="auth.events")

    # ── JWT / Security ────────────────────────────────────────────────────────
    SECRET_KEY: str = Field(
        default="CHANGE-ME-in-production-must-be-at-least-32-chars-long!!!"
    )
    JWT_ALGORITHM: str = Field(default="HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=15)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7)

    # ── Invite / Reset tokens ─────────────────────────────────────────────────
    INVITE_TOKEN_EXPIRE_HOURS: int = Field(default=72)
    RESET_TOKEN_EXPIRE_HOURS: int = Field(default=1)

    # ── Account lockout ───────────────────────────────────────────────────────
    MAX_FAILED_LOGINS: int = Field(default=5)
    LOCKOUT_MINUTES: int = Field(default=30)

    # ── Frontend ──────────────────────────────────────────────────────────────
    FRONTEND_URL: AnyHttpUrl = Field(default="http://localhost:5173")  # type: ignore[assignment]

    # ── SMTP / Email ──────────────────────────────────────────────────────────
    SMTP_HOST: str = Field(default="localhost")
    SMTP_PORT: int = Field(default=1025)
    SMTP_USER: str = Field(default="")
    SMTP_PASSWORD: str = Field(default="")
    SMTP_FROM: str = Field(default="noreply@warehouse-platform.local")
    SMTP_TLS: bool = Field(default=False)
    SMTP_SSL: bool = Field(default=False)

    # ── CORS ──────────────────────────────────────────────────────────────────
    CORS_ORIGINS: list[str] = Field(default=["http://localhost:5173", "http://localhost:3000"])

    # ── Rate limiting ─────────────────────────────────────────────────────────
    RATE_LIMIT_LOGIN_REQUESTS: int = Field(default=20)
    RATE_LIMIT_LOGIN_WINDOW_SECONDS: int = Field(default=60)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()
