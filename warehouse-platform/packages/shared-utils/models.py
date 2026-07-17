"""
Common Pydantic v2 base response models used across all services.
"""
from typing import Any, Generic, TypeVar
from pydantic import BaseModel, Field
from datetime import datetime

T = TypeVar("T")


class BaseResponse(BaseModel):
    """Base class with common response fields."""

    model_config = {"from_attributes": True}


class PaginationMeta(BaseModel):
    """Pagination metadata."""

    total: int
    skip: int
    limit: int
    has_more: bool

    @classmethod
    def create(cls, total: int, skip: int, limit: int) -> "PaginationMeta":
        return cls(total=total, skip=skip, limit=limit, has_more=(skip + limit) < total)


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated list response."""

    items: list[T]
    pagination: PaginationMeta

    @classmethod
    def create(
        cls,
        items: list[T],
        total: int,
        skip: int,
        limit: int,
    ) -> "PaginatedResponse[T]":
        return cls(
            items=items,
            pagination=PaginationMeta.create(total=total, skip=skip, limit=limit),
        )


class ErrorDetail(BaseModel):
    """Single error detail entry."""

    field: str | None = None
    message: str
    code: str | None = None


class ErrorResponse(BaseModel):
    """
    RFC 7807-compliant Problem Details response.
    Used as the standard error format across all API endpoints.
    """

    type: str = "https://api.warehouse-platform.local/errors/generic"
    title: str
    status: int
    detail: str
    instance: str | None = None
    errors: list[ErrorDetail] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    request_id: str | None = None

    model_config = {
        "json_encoders": {datetime: lambda v: v.isoformat()}
    }


class HealthCheckResponse(BaseModel):
    """Standard health check response."""

    status: str = "ok"
    service: str
    version: str = "1.0.0"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    checks: dict[str, str] = Field(default_factory=dict)

    model_config = {
        "json_encoders": {datetime: lambda v: v.isoformat()}
    }
