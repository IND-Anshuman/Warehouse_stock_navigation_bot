"""
Observation Service — SQLAlchemy ORM Models.

Mirrors the init.sql schema exactly:
  - observations (partitioned by observed_at)
  - outbox_events (transactional outbox)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Observation(Base):
    """
    Physical scan record produced by a robot camera frame.

    The underlying PostgreSQL table is range-partitioned by `observed_at`
    (monthly partitions), which SQLAlchemy uses transparently.
    """

    __tablename__ = "observations"

    # ── Primary key ───────────────────────────────────────────────────────────
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.uuid_generate_v4(),
    )

    # ── Foreign keys ──────────────────────────────────────────────────────────
    mission_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("missions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    robot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("robots.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    bin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bins.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ── QR / Detection data ───────────────────────────────────────────────────
    bin_code: Mapped[str | None] = mapped_column(
        String(150), nullable=True, comment="Denormalised bin code for fast lookup"
    )
    decoded_qr: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    raw_qr_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    detection_confidence: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    frame_blur_score: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Spatial data ──────────────────────────────────────────────────────────
    robot_coord_x: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    robot_coord_y: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    robot_coord_z: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)

    # ── Timestamps ────────────────────────────────────────────────────────────
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
        comment="Partition key — DO NOT update after insert",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ── Status ────────────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        Enum(
            "PENDING", "PROCESSED", "FAILED", "DECODE_ERROR",
            name="observation_status",
            create_type=False,
        ),
        nullable=False,
        default="PENDING",
        server_default="PENDING",
    )
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Extra payload ─────────────────────────────────────────────────────────
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    def __repr__(self) -> str:
        return f"<Observation id={self.id} bin_code={self.bin_code} status={self.status}>"


class OutboxEvent(Base):
    """
    Transactional outbox table — rows are written in the same DB transaction
    as the business entity and then relayed to Kafka by the outbox worker.
    """

    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.uuid_generate_v4(),
    )
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(200), nullable=False)
    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    partition_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    headers: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="PENDING", server_default="PENDING"
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<OutboxEvent id={self.id} topic={self.topic} status={self.status}>"
