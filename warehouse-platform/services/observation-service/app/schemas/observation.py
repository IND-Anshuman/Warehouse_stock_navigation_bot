"""
Observation Service — Pydantic v2 Schemas.

All schemas use model_config = ConfigDict(from_attributes=True) so they
can be instantiated directly from SQLAlchemy ORM objects.
"""

from __future__ import annotations

import base64
import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


# ── Enums (string literals matching DB enums) ─────────────────────────────────

ObservationStatus = Annotated[str, Field(pattern="^(PENDING|PROCESSED|FAILED|DECODE_ERROR)$")]


# ─────────────────────────────────────────────────────────────────────────────
# Inbound schemas (robot → service)
# ─────────────────────────────────────────────────────────────────────────────

class ObservationIngest(BaseModel):
    """
    Single observation payload sent by an autonomous robot.

    Either `bin_code` OR (`robot_coord_x`, `robot_coord_y`) must be supplied
    so the service can resolve the target bin.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    robot_id: uuid.UUID = Field(..., description="UUID of the robot that produced this frame")
    mission_id: uuid.UUID | None = Field(None, description="Active mission UUID, if any")
    warehouse_id: uuid.UUID = Field(..., description="Warehouse in which the robot operates")

    # Bin identification — at least one of bin_code / coords must be present
    bin_code: str | None = Field(None, max_length=150, description="Bin barcode / QR code label")
    bin_id: uuid.UUID | None = Field(None, description="Direct bin UUID if already resolved")

    # Decoded observation data
    decoded_qr: str | None = Field(None, max_length=500, description="QR/barcode data decoded by the robot")
    raw_qr_payload: str | None = Field(None, description="Raw bytes payload before decoding")

    # Quality signals
    detection_confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Robot's own confidence in the QR decode"
    )
    frame_blur_score: float | None = Field(
        None, ge=0.0, description="Laplacian variance of the frame (higher = sharper)"
    )

    # Robot spatial position at time of capture
    robot_coord_x: float | None = Field(None, description="Robot X coordinate in warehouse frame")
    robot_coord_y: float | None = Field(None, description="Robot Y coordinate in warehouse frame")
    robot_coord_z: float | None = Field(None, description="Robot Z (height) coordinate")

    # Timestamp (robot clock — may differ from server time)
    observed_at: datetime = Field(..., description="UTC timestamp when the frame was captured")

    # Optional embedded image (base64-encoded JPEG/PNG)
    image_b64: str | None = Field(
        None,
        description="Base64-encoded frame image. If provided, the service uploads it to MinIO.",
    )

    @field_validator("image_b64")
    @classmethod
    def validate_base64(cls, v: str | None) -> str | None:
        """Ensure the image_b64 string is valid base64."""
        if v is None:
            return v
        try:
            base64.b64decode(v, validate=True)
        except Exception:
            raise ValueError("image_b64 must be a valid base64-encoded string")
        return v

    @model_validator(mode="after")
    def require_bin_identifier(self) -> "ObservationIngest":
        """At least one of bin_code, bin_id, or robot coords must be present."""
        has_bin = self.bin_code is not None or self.bin_id is not None
        has_coords = self.robot_coord_x is not None and self.robot_coord_y is not None
        if not has_bin and not has_coords:
            raise ValueError(
                "At least one of 'bin_code', 'bin_id', or "
                "('robot_coord_x', 'robot_coord_y') must be provided."
            )
        return self


class ObservationBatch(BaseModel):
    """Batch of observations from a single robot mission."""

    model_config = ConfigDict(str_strip_whitespace=True)

    robot_id: uuid.UUID
    mission_id: uuid.UUID | None = None
    warehouse_id: uuid.UUID
    observations: list[ObservationIngest] = Field(
        ..., min_length=1, max_length=50, description="List of individual observations (max 50)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Outbound schemas (service → API clients)
# ─────────────────────────────────────────────────────────────────────────────

class ObservationResponse(BaseModel):
    """Full observation record returned to API callers."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    mission_id: uuid.UUID | None
    robot_id: uuid.UUID
    warehouse_id: uuid.UUID
    bin_id: uuid.UUID | None
    bin_code: str | None
    decoded_qr: str | None
    raw_qr_payload: str | None
    detection_confidence: float | None
    frame_blur_score: float | None
    image_url: str | None
    robot_coord_x: float | None
    robot_coord_y: float | None
    robot_coord_z: float | None
    observed_at: datetime
    status: str
    processing_error: str | None
    created_at: datetime


class ObservationListResponse(BaseModel):
    """Paginated list of observations."""

    items: list[ObservationResponse]
    total: int
    skip: int
    limit: int


class ObservationStats(BaseModel):
    """Statistical summary of observations for a mission."""

    mission_id: uuid.UUID
    total_count: int = 0
    processed_count: int = 0
    failed_count: int = 0
    avg_confidence: float | None = None
    avg_blur_score: float | None = None
    success_rate: float = 0.0  # processed / total * 100


class FrameUploadResponse(BaseModel):
    """Result of a frame upload via multipart form."""

    observation_id: uuid.UUID
    image_url: str
    blur_score: float | None = None
    decoded_qr: str | None = None
    detection_confidence: float | None = None
    is_blurry: bool = False
    status: str


# ─────────────────────────────────────────────────────────────────────────────
# Internal / outbox schemas
# ─────────────────────────────────────────────────────────────────────────────

class ObservationEventPayload(BaseModel):
    """Kafka event payload published to observation.raw topic."""

    event_type: str
    observation_id: str
    mission_id: str | None
    robot_id: str
    warehouse_id: str
    bin_id: str | None
    bin_code: str | None
    decoded_qr: str | None
    detection_confidence: float | None
    frame_blur_score: float | None
    image_url: str | None
    robot_coord_x: float | None
    robot_coord_y: float | None
    robot_coord_z: float | None
    observed_at: str
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict)
