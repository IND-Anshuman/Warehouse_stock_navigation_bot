"""
Multi-topic Kafka consumer for the digital-twin-sync service.

Subscribes to the following topics:
    - ``robot.telemetry.heartbeat``         → update robot position in twin state
    - ``observation.raw``                   → update bin state with observed SKU
    - ``inventory.reconciliation.mismatch`` → mark bin MISMATCH
    - ``inventory.reconciliation.verified`` → mark bin VERIFIED

For every processed event the consumer publishes a delta message to the
Redis Pub/Sub channel ``twin:updates:{warehouse_id}`` so that the Socket.IO
layer can fan out the change to all connected web clients.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import structlog
from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaConnectionError
from redis.asyncio import Redis
from tenacity import (
    AsyncRetrying,
    RetryError,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.state.twin_state import WarehouseTwinState

logger = structlog.get_logger(__name__)

# ── Topics ────────────────────────────────────────────────────────────────────
TOPIC_ROBOT_HEARTBEAT = "robot.telemetry.heartbeat"
TOPIC_OBSERVATION_RAW = "observation.raw"
TOPIC_MISMATCH = "inventory.reconciliation.mismatch"
TOPIC_VERIFIED = "inventory.reconciliation.verified"

ALL_TOPICS = [
    TOPIC_ROBOT_HEARTBEAT,
    TOPIC_OBSERVATION_RAW,
    TOPIC_MISMATCH,
    TOPIC_VERIFIED,
]

# Redis Pub/Sub channel template
_PUBSUB_CHANNEL = "twin:updates:{warehouse_id}"


class TwinKafkaConsumer:
    """
    Long-running Kafka consumer that drives digital-twin state updates.

    Each incoming message is decoded, validated, and dispatched to the
    appropriate handler method.  After updating Redis state the consumer
    publishes a compact delta onto the Pub/Sub channel for the affected
    warehouse so the Socket.IO server can relay it to browser clients.
    """

    def __init__(self, twin_state: WarehouseTwinState, redis_client: Redis) -> None:
        """
        Initialise the consumer.

        Args:
            twin_state:    Warehouse twin state manager backed by Redis.
            redis_client:  Connected async Redis client (used for Pub/Sub).
        """
        self._twin = twin_state
        self._redis = redis_client
        self._consumer: AIOKafkaConsumer | None = None
        self._running = False
        self._task: asyncio.Task[None] | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the consumer with automatic retry on connection failure."""
        logger.info("twin_consumer_starting", topics=ALL_TOPICS)
        self._running = True
        self._task = asyncio.create_task(self._run_with_retry(), name="twin-kafka-consumer")

    async def stop(self) -> None:
        """Gracefully stop the consumer."""
        logger.info("twin_consumer_stopping")
        self._running = False
        if self._consumer:
            await self._consumer.stop()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("twin_consumer_stopped")

    # ── Internal run loop ────────────────────────────────────────────────────

    async def _run_with_retry(self) -> None:
        """Run the main consume loop, retrying on Kafka connectivity failures."""
        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception_type(KafkaConnectionError),
                wait=wait_exponential(multiplier=1, min=2, max=30),
                stop=stop_after_attempt(20),
                before_sleep=before_sleep_log(logger, "warning"),  # type: ignore[arg-type]
                reraise=True,
            ):
                with attempt:
                    await self._consume_loop()
        except RetryError:
            logger.error("twin_consumer_exhausted_retries")
        except Exception as exc:
            logger.exception("twin_consumer_fatal_error", error=str(exc))

    async def _consume_loop(self) -> None:
        """Create consumer, subscribe, and process messages indefinitely."""
        self._consumer = AIOKafkaConsumer(
            *ALL_TOPICS,
            bootstrap_servers=settings.kafka_servers_list,
            group_id=settings.CONSUMER_GROUP_ID,
            value_deserializer=lambda b: json.loads(b.decode("utf-8")),
            auto_offset_reset="latest",
            enable_auto_commit=True,
            auto_commit_interval_ms=1000,
            session_timeout_ms=30_000,
            heartbeat_interval_ms=10_000,
            max_poll_records=50,
        )

        await self._consumer.start()
        logger.info("twin_consumer_connected", topics=ALL_TOPICS)

        try:
            async for msg in self._consumer:
                if not self._running:
                    break
                await self._dispatch(msg.topic, msg.value or {})
        finally:
            await self._consumer.stop()
            self._consumer = None

    # ── Dispatch ──────────────────────────────────────────────────────────────

    async def _dispatch(self, topic: str, event: dict[str, Any]) -> None:
        """Route an incoming Kafka message to the correct handler."""
        try:
            if topic == TOPIC_ROBOT_HEARTBEAT:
                await self._handle_robot_heartbeat(event)
            elif topic == TOPIC_OBSERVATION_RAW:
                await self._handle_observation_raw(event)
            elif topic == TOPIC_MISMATCH:
                await self._handle_mismatch(event)
            elif topic == TOPIC_VERIFIED:
                await self._handle_verified(event)
            else:
                logger.warning("twin_consumer_unknown_topic", topic=topic)
        except Exception as exc:
            logger.exception(
                "twin_consumer_dispatch_error",
                topic=topic,
                error=str(exc),
                event_preview=str(event)[:200],
            )

    # ── Handlers ──────────────────────────────────────────────────────────────

    async def _handle_robot_heartbeat(self, event: dict[str, Any]) -> None:
        """
        Process ``robot.telemetry.heartbeat`` event.

        Expected payload fields:
            warehouse_id, robot_id, x, y, z, yaw, battery_pct, status
        """
        warehouse_id = event.get("warehouse_id", "unknown")
        robot_id: str = event.get("robot_id", "")
        if not robot_id:
            logger.warning("robot_heartbeat_missing_robot_id")
            return

        await self._twin.update_robot_position(
            warehouse_id=warehouse_id,
            robot_id=robot_id,
            x=float(event.get("x", 0.0)),
            y=float(event.get("y", 0.0)),
            z=float(event.get("z", 0.0)),
            yaw=float(event.get("yaw", 0.0)),
            battery=float(event.get("battery_pct", 0.0)),
            status=str(event.get("status", "UNKNOWN")),
        )

        delta: dict[str, Any] = {
            "type": "robot_position_update",
            "robot_id": robot_id,
            "warehouse_id": warehouse_id,
            "x": event.get("x"),
            "y": event.get("y"),
            "z": event.get("z"),
            "yaw": event.get("yaw"),
            "battery": event.get("battery_pct"),
            "status": event.get("status"),
            "ts": time.time(),
        }
        await self._publish_delta(warehouse_id, delta)

    async def _handle_observation_raw(self, event: dict[str, Any]) -> None:
        """
        Process ``observation.raw`` event.

        Expected payload fields:
            warehouse_id, bin_id, sku (optional), confidence
        """
        warehouse_id = event.get("warehouse_id", "unknown")
        bin_id: str = str(event.get("bin_id", ""))
        if not bin_id:
            logger.warning("observation_raw_missing_bin_id")
            return

        sku: str | None = event.get("sku") or None
        confidence = float(event.get("confidence", 0.0))

        await self._twin.update_bin_state(
            warehouse_id=warehouse_id,
            bin_id=bin_id,
            sku=sku,
            mismatch_type=None,
            confidence=confidence,
            status="OBSERVED" if sku else "EMPTY",
        )

        delta: dict[str, Any] = {
            "type": "bin_state_update",
            "bin_id": bin_id,
            "warehouse_id": warehouse_id,
            "sku": sku,
            "status": "OBSERVED" if sku else "EMPTY",
            "confidence": confidence,
            "ts": time.time(),
        }
        await self._publish_delta(warehouse_id, delta)

    async def _handle_mismatch(self, event: dict[str, Any]) -> None:
        """
        Process ``inventory.reconciliation.mismatch`` event.

        Expected payload fields:
            warehouse_id, bin_id, expected_sku, observed_sku, mismatch_type, confidence
        """
        warehouse_id = event.get("warehouse_id", "unknown")
        bin_id: str = str(event.get("bin_id", ""))
        if not bin_id:
            logger.warning("mismatch_event_missing_bin_id")
            return

        sku = event.get("observed_sku") or event.get("expected_sku")
        mismatch_type = str(event.get("mismatch_type", "UNKNOWN_MISMATCH"))
        confidence = float(event.get("confidence", 0.0))

        await self._twin.mark_bin_mismatch(
            warehouse_id=warehouse_id,
            bin_id=bin_id,
            sku=sku,
            mismatch_type=mismatch_type,
            confidence=confidence,
        )

        delta: dict[str, Any] = {
            "type": "bin_state_update",
            "bin_id": bin_id,
            "warehouse_id": warehouse_id,
            "sku": sku,
            "status": "MISMATCH",
            "mismatch_type": mismatch_type,
            "confidence": confidence,
            "ts": time.time(),
        }
        await self._publish_delta(warehouse_id, delta)
        logger.info(
            "bin_mismatch_applied",
            warehouse_id=warehouse_id,
            bin_id=bin_id,
            mismatch_type=mismatch_type,
        )

    async def _handle_verified(self, event: dict[str, Any]) -> None:
        """
        Process ``inventory.reconciliation.verified`` event.

        Expected payload fields:
            warehouse_id, bin_id, sku, confidence
        """
        warehouse_id = event.get("warehouse_id", "unknown")
        bin_id: str = str(event.get("bin_id", ""))
        if not bin_id:
            logger.warning("verified_event_missing_bin_id")
            return

        sku = event.get("sku")
        confidence = float(event.get("confidence", 1.0))

        await self._twin.mark_bin_verified(
            warehouse_id=warehouse_id,
            bin_id=bin_id,
            sku=sku,
            confidence=confidence,
        )

        delta: dict[str, Any] = {
            "type": "bin_state_update",
            "bin_id": bin_id,
            "warehouse_id": warehouse_id,
            "sku": sku,
            "status": "VERIFIED",
            "confidence": confidence,
            "ts": time.time(),
        }
        await self._publish_delta(warehouse_id, delta)
        logger.info(
            "bin_verified_applied",
            warehouse_id=warehouse_id,
            bin_id=bin_id,
            sku=sku,
        )

    # ── Pub/Sub publisher ─────────────────────────────────────────────────────

    async def _publish_delta(self, warehouse_id: str, delta: dict[str, Any]) -> None:
        """
        Publish a twin delta to Redis Pub/Sub for the given warehouse.

        The Socket.IO server subscribes to these channels and relays
        the message to all browser clients in the warehouse room.

        Args:
            warehouse_id: Target warehouse identifier.
            delta:        Serialisable dict describing the state change.
        """
        channel = _PUBSUB_CHANNEL.format(warehouse_id=warehouse_id)
        try:
            await self._redis.publish(channel, json.dumps(delta))
        except Exception as exc:
            logger.warning(
                "twin_pubsub_publish_failed",
                channel=channel,
                error=str(exc),
            )
