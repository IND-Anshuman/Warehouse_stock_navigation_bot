"""
Reconciliation Service — Pydantic v2 Schemas.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ─────────────────────────────────────────────────────────────────────────────
# Alert schemas
# ─────────────────────────────────────────────────────────────────────────────

class AlertFilters(BaseModel):
    """Query parameters for filtering alert listings."""

    model_config = ConfigDict(str_strip_whitespace=True)

    status: str | None = Field(None, description="Filter by alert_status enum value")
    severity: str | None = Field(None, description="Filter by alert_severity enum value")
    warehouse_id: uuid.UUID | None = None
    bin_id: uuid.UUID | None = None
    sku: str | None = None
    start_date: datetime | None = Field(None, description="Inclusive start of created_at range")
    end_date: datetime | None = Field(None, description="Inclusive end of created_at range")
    alert_type: str | None = Field(None, description="Filter by mismatch_type")


class AlertCreate(BaseModel):
    """Internal schema for creating an alert programmatically."""

    warehouse_id: uuid.UUID
    reconciliation_id: uuid.UUID | None = None
    observation_id: uuid.UUID | None = None
    bin_id: uuid.UUID | None = None
    sku: str | None = None
    alert_type: str
    severity: str
    title: str = Field(..., max_length=500)
    description: str | None = None
    expected_value: str | None = None
    observed_value: str | None = None
    auto_resolvable: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class AlertResponse(BaseModel):
    """Summary alert record for list responses."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    warehouse_id: uuid.UUID
    bin_id: uuid.UUID | None
    sku: str | None
    alert_type: str
    severity: str
    status: str
    title: str
    created_at: datetime
    updated_at: datetime
    rescan_requested: bool


class AlertDetail(BaseModel):
    """Full alert record with all fields for detail view."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    warehouse_id: uuid.UUID
    reconciliation_id: uuid.UUID | None
    observation_id: uuid.UUID | None
    bin_id: uuid.UUID | None
    sku: str | None
    alert_type: str
    severity: str
    status: str
    title: str
    description: str | None
    expected_value: str | None
    observed_value: str | None
    acknowledged_by: uuid.UUID | None
    acknowledged_at: datetime | None
    resolved_by: uuid.UUID | None
    resolved_at: datetime | None
    resolution_notes: str | None
    auto_resolvable: bool
    rescan_requested: bool
    created_at: datetime
    updated_at: datetime


class AlertUpdateRequest(BaseModel):
    """PATCH payload for updating an alert."""

    model_config = ConfigDict(str_strip_whitespace=True)

    status: str | None = None
    resolution_notes: str | None = None
    resolved_by: uuid.UUID | None = None
    acknowledged_by: uuid.UUID | None = None


class AlertListResponse(BaseModel):
    """Paginated alert list."""

    items: list[AlertDetail]
    total: int
    skip: int
    limit: int
    has_more: bool


# ─────────────────────────────────────────────────────────────────────────────
# Reconciliation result schemas
# ─────────────────────────────────────────────────────────────────────────────

class ReconciliationResultResponse(BaseModel):
    """Public representation of a reconciliation decision."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    observation_id: uuid.UUID
    warehouse_id: uuid.UUID
    bin_id: uuid.UUID | None
    sku: str | None
    result_type: str
    expected_sku: str | None
    expected_qty: int | None
    observed_sku: str | None
    observed_qty: int
    expected_bin_id: uuid.UUID | None
    reconciled_at: datetime
    confidence: float | None


# ─────────────────────────────────────────────────────────────────────────────
# Inventory schemas
# ─────────────────────────────────────────────────────────────────────────────

class InventoryCreate(BaseModel):
    """Create or upsert a single inventory record."""

    model_config = ConfigDict(str_strip_whitespace=True)

    bin_id: uuid.UUID
    sku: str = Field(..., max_length=100)
    expected_qty: int = Field(..., ge=0)
    lot_number: str | None = None
    expiry_date: date | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class InventoryResponse(BaseModel):
    """Public inventory record."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bin_id: uuid.UUID
    sku: str
    expected_qty: int
    lot_number: str | None
    expiry_date: date | None
    last_wms_sync: datetime | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class InventoryBulkUpsert(BaseModel):
    """Bulk WMS sync payload — list of inventory create records."""

    items: list[InventoryCreate] = Field(
        ..., min_length=1, max_length=5000, description="Up to 5000 inventory records per call"
    )
    sync_source: str = Field(default="WMS", description="Originating system label")
    sync_timestamp: datetime | None = None


class InventoryBulkUpsertResponse(BaseModel):
    """Result of a bulk upsert operation."""

    upserted_count: int
    skipped_count: int
    error_count: int
    errors: list[str] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard / analytics schemas
# ─────────────────────────────────────────────────────────────────────────────

class AlertSeverityCounts(BaseModel):
    """Alert counts broken down by severity."""

    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    info: int = 0


class RecentMismatch(BaseModel):
    """Summary of a recent mismatch for dashboard display."""

    alert_id: uuid.UUID
    bin_id: uuid.UUID | None
    sku: str | None
    mismatch_type: str
    severity: str
    created_at: datetime


class DashboardStats(BaseModel):
    """Warehouse-level dashboard summary."""

    warehouse_id: uuid.UUID
    open_alerts_total: int
    open_alerts_by_severity: AlertSeverityCounts
    recent_mismatches: list[RecentMismatch] = Field(default_factory=list)
    inventory_accuracy_pct: float = Field(
        ge=0.0, le=100.0, description="Percentage of bins correctly stocked"
    )
    total_reconciliations_today: int = 0
    mismatches_today: int = 0
    as_of: datetime
