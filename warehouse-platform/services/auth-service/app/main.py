"""
app/main.py — Main application entrypoint for auth-service.
"""
from __future__ import annotations

import contextlib
import uvicorn
import structlog
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
import redis.asyncio as aioredis

from app.config import settings
from app.database import engine, Base
from app.api.v1.auth_router import router as auth_router
from app.api.v1.admin_router import router as admin_router

# Configure structured logging
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.format_exc_info,
        structlog.processors.TimeStamps(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(settings.LOG_LEVEL),
)

log = structlog.get_logger(__name__)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize Database Tables
    log.info("Initializing database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Initialize Redis Client Connection
    log.info("Connecting to Redis...", url=settings.REDIS_URL)
    redis_client = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True
    )
    app.state.redis = redis_client

    yield

    # Clean up resources
    log.info("Disconnecting from Redis...")
    await redis_client.close()
    log.info("Database engine cleanup...")
    await engine.dispose()


app = FastAPI(
    title=settings.SERVICE_NAME,
    version="1.0.0",
    description="Identity and RBAC authorization microservice",
    lifespan=lifespan
)

# CORS middleware config
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus metrics setup
Instrumentator().instrument(app).expose(app, endpoint="/metrics")


# Health Check endpoint
@app.get("/health", tags=["system"], status_code=status.HTTP_200_OK)
async def health_check():
    """Verify health of auth-service API and dependencies."""
    return {
        "status": "healthy",
        "service": settings.SERVICE_NAME,
        "version": "1.0.0"
    }


# Include Routers
app.include_router(auth_router)
app.include_router(admin_router)


# Global Exception Handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    log.warn("HTTP exception occurred", status_code=exc.status_code, detail=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    log.error("Unhandled server exception", error=str(exc), exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected internal server error occurred."}
    )


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        log_level="info",
        reload=True
    )
