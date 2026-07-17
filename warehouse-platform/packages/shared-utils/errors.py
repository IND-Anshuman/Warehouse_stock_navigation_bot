"""
Platform-wide exception hierarchy.
All domain errors inherit from WarehousePlatformError for consistent handling.
"""
from typing import Any


class WarehousePlatformError(Exception):
    """Base class for all platform-specific errors."""

    def __init__(
        self,
        message: str,
        error_code: str = "PLATFORM_ERROR",
        detail: dict[str, Any] | None = None,
        http_status: int = 500,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.detail = detail or {}
        self.http_status = http_status

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": self.message,
            "detail": self.detail,
        }


class NotFoundError(WarehousePlatformError):
    """Resource not found (404)."""

    def __init__(self, resource: str, identifier: Any) -> None:
        super().__init__(
            message=f"{resource} with identifier '{identifier}' not found.",
            error_code="RESOURCE_NOT_FOUND",
            detail={"resource": resource, "identifier": str(identifier)},
            http_status=404,
        )


class ValidationError(WarehousePlatformError):
    """Input validation failed (422)."""

    def __init__(self, message: str, fields: dict[str, str] | None = None) -> None:
        super().__init__(
            message=message,
            error_code="VALIDATION_ERROR",
            detail={"fields": fields or {}},
            http_status=422,
        )


class ConflictError(WarehousePlatformError):
    """Resource conflict — duplicate, lock contention, etc. (409)."""

    def __init__(self, message: str, conflicting_id: Any | None = None) -> None:
        super().__init__(
            message=message,
            error_code="CONFLICT",
            detail={"conflicting_id": str(conflicting_id) if conflicting_id else None},
            http_status=409,
        )


class UnauthorizedError(WarehousePlatformError):
    """Authentication or authorization failed (401/403)."""

    def __init__(self, message: str = "Unauthorized.", is_forbidden: bool = False) -> None:
        super().__init__(
            message=message,
            error_code="FORBIDDEN" if is_forbidden else "UNAUTHORIZED",
            http_status=403 if is_forbidden else 401,
        )


class ServiceUnavailableError(WarehousePlatformError):
    """Downstream service unavailable (503)."""

    def __init__(self, service_name: str, reason: str | None = None) -> None:
        super().__init__(
            message=f"Service '{service_name}' is currently unavailable.",
            error_code="SERVICE_UNAVAILABLE",
            detail={"service": service_name, "reason": reason},
            http_status=503,
        )


class RobotNotFoundError(NotFoundError):
    """Robot-specific not found."""

    def __init__(self, robot_id: str) -> None:
        super().__init__("Robot", robot_id)


class MissionNotFoundError(NotFoundError):
    """Mission-specific not found."""

    def __init__(self, mission_id: str) -> None:
        super().__init__("Mission", mission_id)


class BinNotFoundError(NotFoundError):
    """Bin-specific not found."""

    def __init__(self, bin_id: str) -> None:
        super().__init__("Bin", bin_id)


class WarehouseNotFoundError(NotFoundError):
    """Warehouse-specific not found."""

    def __init__(self, warehouse_id: str) -> None:
        super().__init__("Warehouse", warehouse_id)


class MissionAlreadyActiveError(ConflictError):
    """Attempt to start a mission that's already running."""

    def __init__(self, robot_id: str, active_mission_id: str) -> None:
        super().__init__(
            message=f"Robot '{robot_id}' is already assigned to mission '{active_mission_id}'.",
            conflicting_id=active_mission_id,
        )


class InvalidMissionTransitionError(WarehousePlatformError):
    """Illegal state machine transition on a mission."""

    def __init__(self, mission_id: str, current_status: str, target_status: str) -> None:
        super().__init__(
            message=(
                f"Cannot transition mission '{mission_id}' from "
                f"'{current_status}' to '{target_status}'."
            ),
            error_code="INVALID_STATE_TRANSITION",
            detail={
                "mission_id": str(mission_id),
                "current_status": current_status,
                "target_status": target_status,
            },
            http_status=409,
        )
