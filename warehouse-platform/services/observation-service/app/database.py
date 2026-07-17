"""
Observation Service — Async SQLAlchemy Database Engine & Session Factory.

Uses SQLAlchemy 2.0 async patterns with proper connection pooling.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

import structlog
from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import Settings, get_settings

logger = structlog.get_logger(__name__)


class Base(DeclarativeBase):
    """Declarative base for all ORM models in this service."""
    pass


# Module-level singletons — initialised by lifespan
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_engine(settings: Settings) -> AsyncEngine:
    """Create and return the async SQLAlchemy engine."""
    return create_async_engine(
        settings.DATABASE_URL,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_pre_ping=True,
        pool_recycle=1800,
        echo=settings.DB_ECHO,
    )


async def init_db(settings: Settings) -> None:
    """Initialise engine and session factory; call once at startup."""
    global _engine, _session_factory

    _engine = create_engine(settings)
    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )
    logger.info("database.initialised", pool_size=settings.DB_POOL_SIZE)


async def close_db() -> None:
    """Dispose the engine connection pool gracefully."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        logger.info("database.connection_pool_closed")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields a scoped async database session.

    The session is committed on success and rolled back on any exception,
    then closed regardless of outcome.
    """
    if _session_factory is None:
        raise RuntimeError("Database not initialised. Call init_db() at startup.")

    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# Type alias for dependency injection
DbSession = Annotated[AsyncSession, Depends(get_session)]
