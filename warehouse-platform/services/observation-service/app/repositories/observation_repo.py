"""
Observation Service — Async Repository Layer.

All database interactions are encapsulated here, keeping the API layer
free of SQLAlchemy specifics (hexagonal architecture adapter pattern).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.observation import Observation, OutboxEvent
from app.schemas.observation import ObservationStats

logger = structlog.get_logger(__name__)


class ObservationRepository:
    """
    All persistence operations for the observation domain.

    Accepts an AsyncSession injected per-request; this class is intentionally
    stateless so it can be constructed cheaply inside a dependency.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Observation CRUD ──────────────────────────────────────────────────────

    async def create_observation(self, data: dict[str, Any]) -> Observation:
        """
        Persist a new observation record.

        Args:
            data: Dict of column values (must not include `id`; auto-generated).

        Returns:
            The newly created Observation with all DB-generated fields populated.
        """
        obs = Observation(**data)
        self._session.add(obs)
        await self._session.flush()
        await self._session.refresh(obs)
        logger.debug("observation.created", observation_id=str(obs.id), bin_code=obs.bin_code)
        return obs

    async def get_observation_by_id(self, obs_id: uuid.UUID) -> Observation | None:
        """
        Fetch a single observation by primary key.

        Returns None if not found (caller decides on 404 vs. other handling).
        """
        result = await self._session.execute(
            select(Observation).where(Observation.id == obs_id)
        )
        return result.scalar_one_or_none()

    async def get_observations_by_mission(
        self,
        mission_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[Observation], int]:
        """
        List observations for a given mission with pagination.

        Returns:
            Tuple of (items, total_count).
        """
        base_filter = Observation.mission_id == mission_id

        count_result = await self._session.execute(
            select(func.count()).select_from(Observation).where(base_filter)
        )
        total = count_result.scalar_one()

        result = await self._session.execute(
            select(Observation)
            .where(base_filter)
            .order_by(Observation.observed_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all(), total  # type: ignore[return-value]

    async def get_observations_by_warehouse(
        self,
        warehouse_id: uuid.UUID,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[Observation], int]:
        """
        List observations for a warehouse with optional time-range filter.

        Returns:
            Tuple of (items, total_count).
        """
        conditions = [Observation.warehouse_id == warehouse_id]
        if start_time:
            conditions.append(Observation.observed_at >= start_time)
        if end_time:
            conditions.append(Observation.observed_at <= end_time)

        where_clause = and_(*conditions)

        count_result = await self._session.execute(
            select(func.count()).select_from(Observation).where(where_clause)
        )
        total = count_result.scalar_one()

        result = await self._session.execute(
            select(Observation)
            .where(where_clause)
            .order_by(Observation.observed_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all(), total  # type: ignore[return-value]

    async def update_observation_status(
        self,
        obs_id: uuid.UUID,
        status: str,
        error: str | None = None,
        image_url: str | None = None,
    ) -> None:
        """
        Update the processing status (and optional error / image_url) of an observation.
        Uses a targeted UPDATE to avoid loading the full row.
        """
        values: dict[str, Any] = {"status": status}
        if error is not None:
            values["processing_error"] = error
        if image_url is not None:
            values["image_url"] = image_url

        await self._session.execute(
            update(Observation).where(Observation.id == obs_id).values(**values)
        )
        logger.debug(
            "observation.status_updated", observation_id=str(obs_id), status=status
        )

    async def get_mission_stats(self, mission_id: uuid.UUID) -> ObservationStats:
        """
        Compute aggregated statistics for a mission's observations.

        Returns an ObservationStats schema instance populated from DB aggregates.
        """
        result = await self._session.execute(
            select(
                func.count().label("total"),
                func.sum(
                    func.cast(Observation.status == "PROCESSED", type_=type(1))
                ).label("processed"),
                func.sum(
                    func.cast(Observation.status.in_(["FAILED", "DECODE_ERROR"]), type_=type(1))
                ).label("failed"),
                func.avg(Observation.detection_confidence).label("avg_confidence"),
                func.avg(Observation.frame_blur_score).label("avg_blur"),
            ).where(Observation.mission_id == mission_id)
        )
        row = result.one()

        total = row.total or 0
        processed = int(row.processed or 0)
        failed = int(row.failed or 0)
        success_rate = (processed / total * 100.0) if total > 0 else 0.0

        return ObservationStats(
            mission_id=mission_id,
            total_count=total,
            processed_count=processed,
            failed_count=failed,
            avg_confidence=float(row.avg_confidence) if row.avg_confidence else None,
            avg_blur_score=float(row.avg_blur) if row.avg_blur else None,
            success_rate=round(success_rate, 2),
        )

    # ── Outbox CRUD ───────────────────────────────────────────────────────────

    async def create_outbox_event(
        self,
        aggregate_type: str,
        aggregate_id: uuid.UUID,
        event_type: str,
        topic: str,
        partition_key: str | None,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> OutboxEvent:
        """
        Write an outbox event within the current transaction.

        This must be called inside the same transaction as the business entity
        creation so both are committed atomically.
        """
        event = OutboxEvent(
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            topic=topic,
            partition_key=partition_key,
            payload=payload,
            headers=headers or {},
        )
        self._session.add(event)
        await self._session.flush()
        logger.debug(
            "outbox.event_created",
            event_id=str(event.id),
            topic=topic,
            event_type=event_type,
        )
        return event

    async def get_pending_outbox_events(self, limit: int = 100) -> list[OutboxEvent]:
        """
        Retrieve PENDING outbox events ordered by scheduled_for ASC.
        Used by the background outbox relay worker.
        """
        result = await self._session.execute(
            select(OutboxEvent)
            .where(OutboxEvent.status == "PENDING")
            .order_by(OutboxEvent.scheduled_for.asc())
            .limit(limit)
        )
        return result.scalars().all()  # type: ignore[return-value]

    async def mark_outbox_processed(self, event_id: uuid.UUID) -> None:
        """Mark an outbox event as PROCESSED after successful Kafka publish."""
        await self._session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id == event_id)
            .values(status="PROCESSED", processed_at=func.now())
        )

    async def mark_outbox_failed(self, event_id: uuid.UUID, error: str) -> None:
        """
        Increment retry_count and record the error.
        After OUTBOX_MAX_RETRIES, mark as DEAD_LETTER.
        """
        result = await self._session.execute(
            select(OutboxEvent).where(OutboxEvent.id == event_id)
        )
        event = result.scalar_one_or_none()
        if event is None:
            return

        event.retry_count += 1
        event.last_error = error
        if event.retry_count >= 3:
            event.status = "DEAD_LETTER"
            logger.warning(
                "outbox.dead_lettered",
                event_id=str(event_id),
                retries=event.retry_count,
                error=error,
            )
        await self._session.flush()
