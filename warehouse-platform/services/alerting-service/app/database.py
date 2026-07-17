"""
Async SQLAlchemy database setup for the alerting-service.

Provides:
    - Async engine with connection pooling
    - Async session factory
    - FastAPI dependency ``get_db_session``
    - ``create_all_tables`` helper for startup
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = structlog.get_logger(__name__)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all alerting-service models."""
    pass


# ── Engine ────────────────────────────────────────────────────────────────────

def _build_engine() -> AsyncEngine:
    """Create and return the async SQLAlchemy engine."""
    return create_async_engine(
        settings.DATABASE_URL,
        echo=settings.ENVIRONMENT == "development",
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=3600,
    )


engine: AsyncEngine = _build_engine()

# ── Session factory ───────────────────────────────────────────────────────────

AsyncSessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


# ── FastAPI dependency ────────────────────────────────────────────────────────

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields an async SQLAlchemy session.

    Commits on success, rolls back on exception, and always closes the session.

    Yields:
        An ``AsyncSession`` bound to the alerting-service database.
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ── DDL helper ────────────────────────────────────────────────────────────────

async def create_all_tables() -> None:
    """
    Create all tables defined in the ORM models (if they do not already exist).

    Called once during application startup.  In production, prefer Alembic
    migrations; this is a convenience for dev/test environments.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("alerting_db_tables_created_or_verified")


async def dispose_engine() -> None:
    """Dispose the async engine connection pool during application shutdown."""
    await engine.dispose()
    logger.info("alerting_db_engine_disposed")
