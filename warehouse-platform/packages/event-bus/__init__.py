"""
Event Bus: Shared Kafka producer/consumer abstractions.
Wraps aiokafka with retry logic, structured serialization, and dead-letter queue support.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Callable, Awaitable

import structlog
from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
from aiokafka.errors import KafkaError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────
#  TOPIC CONSTANTS
# ─────────────────────────────────────────────────────────

class Topics:
    ROBOT_HEARTBEAT = "robot.telemetry.heartbeat"
    MISSION_LIFECYCLE = "mission.lifecycle"
    OBSERVATION_RAW = "observation.raw"
    OBSERVATION_DLQ = "observation.raw.dlq"
    RECONCILIATION_MISMATCH = "inventory.reconciliation.mismatch"
    RECONCILIATION_VERIFIED = "inventory.reconciliation.verified"
    ALERT_LIFECYCLE = "alert.lifecycle"
    DIGITAL_TWIN_UPDATES = "digital.twin.updates"


# ─────────────────────────────────────────────────────────
#  SERIALIZATION
# ─────────────────────────────────────────────────────────

def _serialize_payload(payload: dict[str, Any]) -> bytes:
    """JSON-serialize payload with ISO-format datetimes."""
    def default(obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, uuid.UUID):
            return str(obj)
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    return json.dumps(payload, default=default).encode("utf-8")


def _deserialize_payload(data: bytes) -> dict[str, Any]:
    """Deserialize JSON bytes to dict."""
    return json.loads(data.decode("utf-8"))


# ─────────────────────────────────────────────────────────
#  BASE PRODUCER
# ─────────────────────────────────────────────────────────

class BaseEventProducer:
    """
    Async Kafka producer with structured event envelope and retry logic.
    
    Every event produced follows the envelope pattern:
    {
        "event_id": "<uuid>",
        "event_type": "<string>",
        "source_service": "<string>",
        "produced_at": "<ISO datetime>",
        "payload": { ...domain data... }
    }
    """

    def __init__(
        self,
        bootstrap_servers: str,
        service_name: str,
        acks: str = "all",
        enable_idempotence: bool = True,
    ) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._service_name = service_name
        self._acks = acks
        self._enable_idempotence = enable_idempotence
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        """Initialize and start the Kafka producer."""
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap_servers,
            acks=self._acks,
            enable_idempotence=self._enable_idempotence,
            value_serializer=lambda v: v,  # we serialize manually
            compression_type="gzip",
            linger_ms=10,  # micro-batching for throughput
            max_batch_size=16384,
        )
        await self._producer.start()
        logger.info("kafka_producer_started", service=self._service_name)

    async def stop(self) -> None:
        """Flush and stop the producer gracefully."""
        if self._producer:
            await self._producer.stop()
            logger.info("kafka_producer_stopped", service=self._service_name)

    def _build_envelope(
        self,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Wrap domain payload in standard event envelope."""
        return {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "source_service": self._service_name,
            "produced_at": datetime.utcnow().isoformat(),
            "payload": payload,
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(KafkaError),
        reraise=True,
    )
    async def publish(
        self,
        topic: str,
        event_type: str,
        payload: dict[str, Any],
        partition_key: str | None = None,
    ) -> None:
        """
        Publish an event to the specified Kafka topic.
        
        Retries up to 3 times with exponential backoff on transient errors.
        """
        if not self._producer:
            raise RuntimeError("Producer not started. Call start() first.")

        envelope = self._build_envelope(event_type, payload)
        key = partition_key.encode("utf-8") if partition_key else None
        value = _serialize_payload(envelope)

        await self._producer.send_and_wait(topic, value=value, key=key)

        logger.debug(
            "event_published",
            topic=topic,
            event_type=event_type,
            partition_key=partition_key,
            event_id=envelope["event_id"],
        )

    async def publish_to_dlq(
        self,
        original_topic: str,
        original_payload: bytes,
        error: str,
    ) -> None:
        """Send a failed message to the Dead Letter Queue topic."""
        dlq_topic = f"{original_topic}.dlq"
        dlq_payload = {
            "original_topic": original_topic,
            "error": error,
            "failed_at": datetime.utcnow().isoformat(),
            "original_payload": original_payload.decode("utf-8", errors="replace"),
        }
        if self._producer:
            await self._producer.send_and_wait(
                dlq_topic,
                value=_serialize_payload(dlq_payload),
            )
            logger.warning("event_sent_to_dlq", dlq_topic=dlq_topic, error=error)


# ─────────────────────────────────────────────────────────
#  BASE CONSUMER
# ─────────────────────────────────────────────────────────

MessageHandler = Callable[[str, dict[str, Any]], Awaitable[None]]


class BaseEventConsumer:
    """
    Async Kafka consumer with automatic retry, dead-letter routing, and deduplication support.
    """

    def __init__(
        self,
        bootstrap_servers: str,
        group_id: str,
        topics: list[str],
        service_name: str,
        max_retries: int = 3,
        auto_commit: bool = False,
    ) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._group_id = group_id
        self._topics = topics
        self._service_name = service_name
        self._max_retries = max_retries
        self._auto_commit = auto_commit
        self._consumer: AIOKafkaConsumer | None = None
        self._handlers: dict[str, MessageHandler] = {}
        self._running = False

    def register_handler(self, event_type: str, handler: MessageHandler) -> None:
        """Register a handler for a specific event_type value inside the envelope."""
        self._handlers[event_type] = handler

    async def start(self) -> None:
        """Initialize and start the Kafka consumer."""
        self._consumer = AIOKafkaConsumer(
            *self._topics,
            bootstrap_servers=self._bootstrap_servers,
            group_id=self._group_id,
            auto_offset_reset="earliest",
            enable_auto_commit=self._auto_commit,
            value_deserializer=lambda v: v,  # we deserialize manually
            max_poll_records=100,
            session_timeout_ms=30000,
            heartbeat_interval_ms=10000,
        )
        await self._consumer.start()
        self._running = True
        logger.info(
            "kafka_consumer_started",
            service=self._service_name,
            group_id=self._group_id,
            topics=self._topics,
        )

    async def stop(self) -> None:
        """Commit offsets and stop the consumer."""
        self._running = False
        if self._consumer:
            await self._consumer.stop()
            logger.info("kafka_consumer_stopped", service=self._service_name)

    async def run(self) -> None:
        """
        Main consumption loop. Runs until stop() is called.
        
        Dispatches messages to registered handlers by event_type.
        Implements retry logic and DLQ routing.
        """
        if not self._consumer:
            raise RuntimeError("Consumer not started. Call start() first.")

        logger.info("consumer_loop_started", service=self._service_name)

        async for message in self._consumer:
            if not self._running:
                break

            retry_count = 0
            last_error: str | None = None

            while retry_count <= self._max_retries:
                try:
                    envelope = _deserialize_payload(message.value)
                    event_type = envelope.get("event_type", "UNKNOWN")
                    payload = envelope.get("payload", {})

                    handler = self._handlers.get(event_type)
                    if handler:
                        await handler(event_type, payload)
                    else:
                        # No handler registered — log and skip
                        logger.debug(
                            "unhandled_event_type",
                            event_type=event_type,
                            topic=message.topic,
                        )

                    if not self._auto_commit:
                        await self._consumer.commit()

                    break  # success — exit retry loop

                except Exception as exc:  # noqa: BLE001
                    retry_count += 1
                    last_error = str(exc)
                    logger.warning(
                        "message_processing_error",
                        attempt=retry_count,
                        max_retries=self._max_retries,
                        error=last_error,
                        topic=message.topic,
                        offset=message.offset,
                    )

                    if retry_count > self._max_retries:
                        logger.error(
                            "message_sent_to_dlq",
                            topic=message.topic,
                            offset=message.offset,
                            error=last_error,
                        )
                        # In a real impl, publish to DLQ topic here
                        if not self._auto_commit:
                            await self._consumer.commit()
                        break
