"""
Shared utilities package for the Warehouse Platform.
Provides: structured logging, telemetry, error handling, event bus, and common models.
"""
from .logging import get_logger, setup_logging
from .errors import (
    WarehousePlatformError,
    NotFoundError,
    ValidationError,
    ConflictError,
    UnauthorizedError,
    ServiceUnavailableError,
)
from .models import (
    BaseResponse,
    PaginatedResponse,
    ErrorResponse,
)

__all__ = [
    "get_logger",
    "setup_logging",
    "WarehousePlatformError",
    "NotFoundError",
    "ValidationError",
    "ConflictError",
    "UnauthorizedError",
    "ServiceUnavailableError",
    "BaseResponse",
    "PaginatedResponse",
    "ErrorResponse",
]
