"""
Socket.IO server for the digital-twin-sync service.

Architecture
------------
- Uses python-socketio's ``AsyncServer`` backed by the ``asyncio`` async mode.
- Namespace ``/digital-twin`` is the primary channel for warehouse clients.
- A background task subscribes to Redis Pub/Sub pattern ``twin:updates:*``
  and emits received deltas to the Socket.IO room matching the warehouse.

Client ↔ Server Protocol
------------------------
Client → Server events:
    ``join_warehouse``   (data: {"warehouse_id": "<id>"})
        Join the warehouse room and receive an initial full snapshot.

    ``leave_warehouse``  (data: {"warehouse_id": "<id>"})
        Leave the warehouse room (no further updates).

Server → Client events:
    ``warehouse_snapshot``     (full twin snapshot dict)
    ``robot_position_update``  (delta dict)
    ``bin_state_update``       (delta dict)
    ``warehouse_stats_update`` (periodic stats dict)
    ``error``                  ({"message": "..."})
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import socketio
import structlog
from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from app.state.twin_state import WarehouseTwinState

logger = structlog.get_logger(__name__)

# Socket.IO async server (asyncio mode, no built-in CORS — handled by FastAPI)
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    logger=False,
    engineio_logger=False,
    ping_timeout=60,
    ping_interval=25,
)

# The ASGI-compatible Socket.IO app (mounted under FastAPI)
socket_asgi_app = socketio.ASGIApp(sio)

# Populated during app startup
_twin_state: WarehouseTwinState | None = None
_redis_client: Redis | None = None
_pubsub_task: asyncio.Task[None] | None = None

NAMESPACE = "/digital-twin"


# ── Setup helpers (called from main.py lifespan) ──────────────────────────────

def configure_socket_server(
    twin_state: WarehouseTwinState,
    redis_client: Redis,
) -> None:
    """
    Inject the twin state manager and Redis client into the Socket.IO server.

    Must be called during application startup before any clients connect.

    Args:
        twin_state:    Warehouse twin state backed by Redis.
        redis_client:  Async Redis client used for Pub/Sub subscriptions.
    """
    global _twin_state, _redis_client  # noqa: PLW0603
    _twin_state = twin_state
    _redis_client = redis_client
    logger.info("socket_server_configured")


async def start_pubsub_listener() -> None:
    """
    Start the background Redis Pub/Sub listener task.

    Subscribes to the ``twin:updates:*`` pattern and relays every incoming
    message to the corresponding Socket.IO warehouse room.
    """
    global _pubsub_task  # noqa: PLW0603
    _pubsub_task = asyncio.create_task(
        _pubsub_listener_loop(), name="redis-pubsub-listener"
    )
    logger.info("pubsub_listener_started")


async def stop_pubsub_listener() -> None:
    """Cancel the Pub/Sub listener task gracefully."""
    global _pubsub_task  # noqa: PLW0603
    if _pubsub_task and not _pubsub_task.done():
        _pubsub_task.cancel()
        try:
            await _pubsub_task
        except asyncio.CancelledError:
            pass
    logger.info("pubsub_listener_stopped")


# ── Pub/Sub background listener ───────────────────────────────────────────────

async def _pubsub_listener_loop() -> None:
    """
    Subscribe to ``twin:updates:*`` and forward messages to Socket.IO rooms.

    Runs indefinitely; cancellation is handled gracefully.
    """
    if _redis_client is None:
        logger.error("pubsub_listener_no_redis_client")
        return

    pubsub: PubSub = _redis_client.pubsub()
    await pubsub.psubscribe("twin:updates:*")
    logger.info("pubsub_subscribed", pattern="twin:updates:*")

    try:
        async for raw_message in pubsub.listen():
            msg_type: str = raw_message.get("type", "")
            if msg_type not in ("message", "pmessage"):
                continue

            channel = raw_message.get("channel", b"")
            if isinstance(channel, bytes):
                channel = channel.decode()

            # Extract warehouse_id from channel name "twin:updates:{warehouse_id}"
            parts = channel.split(":", 2)
            if len(parts) < 3:
                continue
            warehouse_id = parts[2]

            data_raw = raw_message.get("data", b"")
            if isinstance(data_raw, bytes):
                data_raw = data_raw.decode()

            try:
                delta: dict[str, Any] = json.loads(data_raw)
            except json.JSONDecodeError:
                logger.warning("pubsub_invalid_json", channel=channel)
                continue

            await _emit_delta_to_room(warehouse_id, delta)

    except asyncio.CancelledError:
        logger.info("pubsub_listener_cancelled")
        raise
    except Exception as exc:
        logger.exception("pubsub_listener_error", error=str(exc))
    finally:
        try:
            await pubsub.punsubscribe("twin:updates:*")
            await pubsub.aclose()
        except Exception:
            pass


async def _emit_delta_to_room(warehouse_id: str, delta: dict[str, Any]) -> None:
    """
    Emit a delta event to all clients in the warehouse room.

    Args:
        warehouse_id: Target warehouse identifier (= Socket.IO room name).
        delta:        Parsed delta dict from Redis Pub/Sub.
    """
    event_type = delta.get("type", "unknown")
    room = f"warehouse:{warehouse_id}"

    if event_type == "robot_position_update":
        await sio.emit(
            "robot_position_update",
            delta,
            room=room,
            namespace=NAMESPACE,
        )
    elif event_type == "bin_state_update":
        await sio.emit(
            "bin_state_update",
            delta,
            room=room,
            namespace=NAMESPACE,
        )
    elif event_type == "warehouse_stats_update":
        await sio.emit(
            "warehouse_stats_update",
            delta,
            room=room,
            namespace=NAMESPACE,
        )
    else:
        # Generic passthrough for future event types
        await sio.emit(
            event_type,
            delta,
            room=room,
            namespace=NAMESPACE,
        )

    logger.debug(
        "socket_event_emitted",
        event=event_type,
        warehouse_id=warehouse_id,
        room=room,
    )


# ── Socket.IO namespace: /digital-twin ────────────────────────────────────────

@sio.event(namespace=NAMESPACE)
async def connect(sid: str, environ: dict[str, Any], auth: Any = None) -> bool:
    """Handle client connection to the /digital-twin namespace."""
    client_ip = environ.get("REMOTE_ADDR", "unknown")
    logger.info("socket_client_connected", sid=sid, ip=client_ip)
    return True  # Accept connection


@sio.event(namespace=NAMESPACE)
async def disconnect(sid: str) -> None:
    """Handle client disconnection from the /digital-twin namespace."""
    logger.info("socket_client_disconnected", sid=sid)


@sio.event(namespace=NAMESPACE)
async def join_warehouse(sid: str, data: Any) -> dict[str, Any]:
    """
    Handle a client request to join a warehouse room.

    After joining, the client immediately receives the full current twin snapshot.

    Args:
        sid:  Socket.IO session ID.
        data: Dict containing ``warehouse_id``.

    Returns:
        Acknowledgement dict with ``status`` and optional ``error``.
    """
    if not isinstance(data, dict) or "warehouse_id" not in data:
        return {"status": "error", "error": "warehouse_id is required"}

    warehouse_id: str = str(data["warehouse_id"])
    room = f"warehouse:{warehouse_id}"

    # Join the Socket.IO room
    await sio.enter_room(sid, room, namespace=NAMESPACE)
    logger.info("socket_joined_warehouse", sid=sid, warehouse_id=warehouse_id)

    # Send initial full snapshot
    if _twin_state is not None:
        try:
            snapshot = await _twin_state.get_warehouse_snapshot(warehouse_id)
            await sio.emit(
                "warehouse_snapshot",
                snapshot,
                to=sid,
                namespace=NAMESPACE,
            )
            logger.info(
                "snapshot_sent",
                sid=sid,
                warehouse_id=warehouse_id,
                robot_count=len(snapshot.get("robots", [])),
                bin_count=len(snapshot.get("bins", {})),
            )
        except Exception as exc:
            logger.exception("snapshot_fetch_failed", sid=sid, error=str(exc))
            await sio.emit(
                "error",
                {"message": "Failed to fetch warehouse snapshot"},
                to=sid,
                namespace=NAMESPACE,
            )

    return {"status": "ok", "warehouse_id": warehouse_id}


@sio.event(namespace=NAMESPACE)
async def leave_warehouse(sid: str, data: Any) -> dict[str, Any]:
    """
    Handle a client request to leave a warehouse room.

    Args:
        sid:  Socket.IO session ID.
        data: Dict containing ``warehouse_id``.

    Returns:
        Acknowledgement dict with ``status``.
    """
    if not isinstance(data, dict) or "warehouse_id" not in data:
        return {"status": "error", "error": "warehouse_id is required"}

    warehouse_id: str = str(data["warehouse_id"])
    room = f"warehouse:{warehouse_id}"

    await sio.leave_room(sid, room, namespace=NAMESPACE)
    logger.info("socket_left_warehouse", sid=sid, warehouse_id=warehouse_id)
    return {"status": "ok", "warehouse_id": warehouse_id}
