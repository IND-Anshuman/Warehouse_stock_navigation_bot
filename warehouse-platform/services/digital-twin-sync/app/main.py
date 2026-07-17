"""
Digital Twin Sync Service — Application Entry Point.

Architecture:
    FastAPI (REST + health/metrics) mounted alongside a Socket.IO ASGI sub-app.
    The combined ASGI app is served by uvicorn.

Lifespan:
    1. Configure structlog JSON logging
    2. Connect to Redis
    3. Build WarehouseTwinState
    4. Configure Socket.IO server with twin state
    5. Start Kafka consumer task
    6. Start Redis Pub/Sub listener task (feeds Socket.IO)
    7. Start periodic stats broadcast task
    Shutdown: graceful shutdown of consumer + Pub/Sub listener
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from redis.asyncio import Redis, from_url as redis_from_url

from app.api.v1.twin_router import router as twin_router
from app.config import settings
from app.kafka.consumer import TwinKafkaConsumer
from app.state.twin_state import WarehouseTwinState
from app.websocket.socket_server import (
    configure_socket_server,
    sio,
    socket_asgi_app,
    start_pubsub_listener,
    stop_pubsub_listener,
)

# ── Structured logging setup ──────────────────────────────────────────────────

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.ExceptionRenderer(),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(__import__("logging"), settings.LOG_LEVEL, 20)
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger(__name__)


# ── Periodic stats broadcast ──────────────────────────────────────────────────

async def _periodic_stats_broadcaster(
    twin_state: WarehouseTwinState,
    redis_client: Redis,
    interval: int,
) -> None:
    """
    Periodically publish warehouse stats to all active-warehouse Pub/Sub channels.

    This drives the ``warehouse_stats_update`` Socket.IO events for connected
    dashboards that need a ticking aggregate view even with no state changes.

    Args:
        twin_state:    Twin state manager.
        redis_client:  Redis client for Pub/Sub publishing.
        interval:      Broadcast interval in seconds.
    """
    logger.info("stats_broadcaster_started", interval=interval)
    while True:
        try:
            await asyncio.sleep(interval)
            warehouses = await twin_state.get_active_warehouses()
            for wh_id in warehouses:
                snapshot = await twin_state.get_warehouse_snapshot(wh_id)
                delta = {
                    "type": "warehouse_stats_update",
                    "warehouse_id": wh_id,
                    "stats": snapshot["stats"],
                    "ts": time.time(),
                }
                channel = f"twin:updates:{wh_id}"
                await redis_client.publish(channel, json.dumps(delta))
        except asyncio.CancelledError:
            logger.info("stats_broadcaster_cancelled")
            return
        except Exception as exc:
            logger.exception("stats_broadcaster_error", error=str(exc))


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    FastAPI lifespan context manager.

    Handles startup initialisation and graceful shutdown of all background
    services (Redis, Kafka consumer, Redis Pub/Sub listener, stats broadcaster).
    """
    logger.info(
        "digital_twin_sync_starting",
        service=settings.SERVICE_NAME,
        port=settings.PORT,
        environment=settings.ENVIRONMENT,
    )

    # ── 1. Redis ──────────────────────────────────────────────────────────────
    redis_client: Redis = redis_from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry_on_timeout=True,
        health_check_interval=30,
    )
    await redis_client.ping()
    logger.info("redis_connected", url=settings.REDIS_URL)

    # ── 2. Twin state ─────────────────────────────────────────────────────────
    twin_state = WarehouseTwinState(
        redis_client=redis_client,
        robot_position_ttl=settings.ROBOT_POSITION_TTL_SECS,
    )

    # Attach to app state for REST endpoints
    app.state.twin_state = twin_state
    app.state.redis_client = redis_client

    # ── 3. Socket.IO ──────────────────────────────────────────────────────────
    configure_socket_server(twin_state, redis_client)
    await start_pubsub_listener()

    # ── 4. Kafka consumer ─────────────────────────────────────────────────────
    kafka_consumer = TwinKafkaConsumer(
        twin_state=twin_state,
        redis_client=redis_client,
    )
    await kafka_consumer.start()
    app.state.kafka_consumer = kafka_consumer

    # ── 5. Periodic stats broadcaster ─────────────────────────────────────────
    stats_task = asyncio.create_task(
        _periodic_stats_broadcaster(
            twin_state=twin_state,
            redis_client=redis_client,
            interval=settings.STATE_SNAPSHOT_INTERVAL_SECS,
        ),
        name="stats-broadcaster",
    )
    app.state.stats_task = stats_task

    logger.info("digital_twin_sync_ready")

    # ── Yield (service runs here) ─────────────────────────────────────────────
    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("digital_twin_sync_shutting_down")

    stats_task.cancel()
    try:
        await stats_task
    except asyncio.CancelledError:
        pass

    await kafka_consumer.stop()
    await stop_pubsub_listener()
    await redis_client.aclose()

    logger.info("digital_twin_sync_shutdown_complete")


# ── FastAPI application ───────────────────────────────────────────────────────

app = FastAPI(
    title="Digital Twin Sync Service",
    description=(
        "Real-time digital twin synchronisation for the Autonomous Warehouse Inventory "
        "Audit Platform. Consumes telemetry and reconciliation events from Kafka and "
        "pushes live updates to connected clients via Socket.IO."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── CORS ───────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Prometheus metrics ─────────────────────────────────────────────────────────
Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    should_respect_env_var=False,
    should_instrument_requests_inprogress=True,
    excluded_handlers=["/health", "/metrics"],
    inprogress_name="digital_twin_sync_requests_inprogress",
    inprogress_labels=True,
).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

# ── REST routes ────────────────────────────────────────────────────────────────
app.include_router(twin_router)


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["system"], include_in_schema=True)
async def health_check() -> dict[str, object]:
    """
    Liveness and readiness health check.

    Returns:
        JSON with service status and Redis/Kafka connectivity.
    """
    health: dict[str, object] = {
        "service": settings.SERVICE_NAME,
        "status": "ok",
        "version": "1.0.0",
        "checks": {},
    }

    # Redis check
    try:
        redis: Redis = app.state.redis_client
        await redis.ping()
        health["checks"]["redis"] = "ok"  # type: ignore[index]
    except Exception as exc:
        health["checks"]["redis"] = f"error: {exc}"  # type: ignore[index]
        health["status"] = "degraded"

    # Kafka consumer alive check
    try:
        consumer = app.state.kafka_consumer
        task: asyncio.Task[None] = consumer._task  # type: ignore[attr-defined]
        health["checks"]["kafka_consumer"] = "ok" if (task and not task.done()) else "stopped"  # type: ignore[index]
    except Exception as exc:
        health["checks"]["kafka_consumer"] = f"error: {exc}"  # type: ignore[index]

    return health


# ── Combined ASGI app (FastAPI + Socket.IO) ────────────────────────────────────

class _CombinedASGI:
    """
    Routes incoming requests to either the FastAPI app or the Socket.IO ASGI app.

    Socket.IO (Engine.IO) requests use the path prefix ``/socket.io/``.
    All other requests go to FastAPI.
    """

    def __init__(self, fastapi_app: FastAPI, sio_asgi_app: socketio.ASGIApp) -> None:  # type: ignore[name-defined]
        self._fastapi = fastapi_app
        self._sio = sio_asgi_app

    async def __call__(self, scope: dict, receive, send) -> None:  # type: ignore[override]
        if scope["type"] in ("http", "websocket") and scope.get("path", "").startswith("/socket.io"):
            await self._sio(scope, receive, send)
        else:
            await self._fastapi(scope, receive, send)


import socketio as _sio_module  # noqa: E402 — needed for type hint above

socket_app = _CombinedASGI(app, socket_asgi_app)


# ── Dev entrypoint ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "app.main:socket_app",
        host="0.0.0.0",
        port=settings.PORT,
        loop="asyncio",
        log_level=settings.LOG_LEVEL.lower(),
        reload=settings.ENVIRONMENT == "development",
    )
