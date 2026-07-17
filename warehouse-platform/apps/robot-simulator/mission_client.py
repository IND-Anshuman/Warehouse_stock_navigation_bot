"""
mission_client.py — HTTP client for the mission-service.

Handles:
- Robot registration (POST /api/v1/robots)
- Heartbeat transmission (POST /api/v1/robots/{id}/heartbeat)
- Next-task polling (GET /api/v1/robots/{id}/next-task)
- Mission completion (POST /api/v1/missions/{id}/complete)

All methods degrade gracefully: network failures return None/False
rather than raising, allowing robot agents to continue simulating.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config import Config
from models import MissionTask, RobotRegistrationResponse

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class MissionClient:
    """
    Async HTTP client for the mission-service REST API.

    Encapsulates all robot-to-mission-service communication:
    registration, heartbeats, task polling, and mission completion.

    Heartbeat calls intentionally have shorter timeouts and no retry
    (low-latency fire-and-forget semantics). Task polling uses full
    retry logic since a missed task assignment stalls the robot.

    Usage
    -----
    ::

        async with MissionClient(config) as client:
            reg = await client.register_robot("robot-001", "SN-XYZ", "warehouse-001")
    """

    def __init__(self, config: Config) -> None:
        """
        Parameters
        ----------
        config:
            Application configuration (URLs, timeouts, retry parameters).
        """
        self._config = config
        self._base_url = config.mission_service_url.rstrip("/")
        self._http_client: httpx.AsyncClient | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def __aenter__(self) -> "MissionClient":
        await self.open()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def open(self) -> None:
        """Create the underlying httpx.AsyncClient."""
        self._http_client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(
                connect=3.0,
                read=self._config.http_timeout_seconds,
                write=5.0,
                pool=5.0,
            ),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Client": "robot-simulator",
            },
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )
        logger.info("mission_client.opened", base_url=self._base_url)

    async def close(self) -> None:
        """Gracefully close the HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        logger.info("mission_client.closed")

    def _ensure_client(self) -> httpx.AsyncClient:
        if not self._http_client:
            raise RuntimeError("MissionClient not open. Call open() first.")
        return self._http_client

    # ── Public API ─────────────────────────────────────────────────────────────

    async def register_robot(
        self,
        robot_id: str,
        serial_number: str,
        warehouse_id: str,
        model: str = "SimBot-MK4",
        firmware_version: str = "1.0.0-sim",
    ) -> RobotRegistrationResponse | None:
        """
        Register this robot with the mission-service.

        POST /api/v1/robots

        Parameters
        ----------
        robot_id:
            Unique robot identifier.
        serial_number:
            Hardware serial number (used for deduplication in the service).
        warehouse_id:
            The warehouse this robot operates in.
        model:
            Robot model name.
        firmware_version:
            Firmware version string for telemetry.

        Returns
        -------
        RobotRegistrationResponse | None
            Registration response, or None on failure.
        """
        client = self._ensure_client()
        payload = {
            "robot_id": robot_id,
            "serial_number": serial_number,
            "warehouse_id": warehouse_id,
            "model": model,
            "firmware_version": firmware_version,
            "capabilities": ["qr_scan", "weight_sensor", "rfid"],
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }
        request_id = str(uuid.uuid4())

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._config.http_max_retries),
                wait=wait_exponential(
                    multiplier=self._config.http_retry_backoff_seconds,
                    min=1.0,
                    max=15.0,
                ),
                retry=retry_if_exception_type(
                    (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError)
                ),
                reraise=False,
            ):
                with attempt:
                    response = await client.post(
                        "/api/v1/robots",
                        json=payload,
                        headers={"X-Request-ID": request_id},
                    )

                    if response.status_code in (200, 201):
                        data = response.json()
                        reg = RobotRegistrationResponse(
                            robot_id=data.get("robot_id", robot_id),
                            registration_token=data.get("registration_token", ""),
                            status=data.get("status", "registered"),
                        )
                        logger.info(
                            "mission_client.robot_registered",
                            robot_id=robot_id,
                            warehouse_id=warehouse_id,
                            response_status=reg.status,
                        )
                        return reg

                    if response.status_code == 409:
                        # Already registered — acceptable
                        logger.info(
                            "mission_client.robot_already_registered",
                            robot_id=robot_id,
                        )
                        return RobotRegistrationResponse(
                            robot_id=robot_id,
                            status="already_registered",
                        )

                    if response.status_code >= 500:
                        response.raise_for_status()

                    logger.error(
                        "mission_client.registration_client_error",
                        robot_id=robot_id,
                        status_code=response.status_code,
                        body=response.text[:200],
                    )
                    return None

        except (RetryError, httpx.HTTPError, Exception) as exc:
            logger.warning(
                "mission_client.registration_failed",
                robot_id=robot_id,
                error=str(exc),
            )
            return None

        return None

    async def send_heartbeat(
        self,
        robot_id: str,
        battery_pct: float,
        x: float,
        y: float,
        z: float,
        status: str,
        mission_id: str | None = None,
        offline_buffer_size: int = 0,
        warehouse_id: str = "",
    ) -> bool:
        """
        Send a heartbeat to the mission-service.

        POST /api/v1/robots/{robot_id}/heartbeat

        Intentionally uses a short timeout and no retry: heartbeats are
        fire-and-forget. A missed heartbeat is acceptable; the service
        will mark the robot as unreachable after multiple misses.

        Parameters
        ----------
        robot_id:
            Robot identifier.
        battery_pct:
            Current battery percentage.
        x, y, z:
            Current position coordinates.
        status:
            Robot status string.
        mission_id:
            Active mission ID, or None if idle.
        offline_buffer_size:
            Number of observations in local buffer.
        warehouse_id:
            Warehouse identifier.

        Returns
        -------
        bool
            True if heartbeat was acknowledged.
        """
        client = self._ensure_client()
        payload = {
            "robot_id": robot_id,
            "warehouse_id": warehouse_id,
            "battery_pct": round(battery_pct, 2),
            "position": {"x": round(x, 4), "y": round(y, 4), "z": round(z, 4)},
            "status": status,
            "mission_id": mission_id,
            "offline_buffer_size": offline_buffer_size,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        try:
            response = await client.post(
                f"/api/v1/robots/{robot_id}/heartbeat",
                json=payload,
                timeout=2.0,  # short timeout for heartbeats
                headers={"X-Request-ID": str(uuid.uuid4())},
            )
            success = response.status_code in (200, 201, 202, 204)
            if not success:
                logger.debug(
                    "mission_client.heartbeat_rejected",
                    robot_id=robot_id,
                    status_code=response.status_code,
                )
            return success

        except Exception as exc:
            logger.debug(
                "mission_client.heartbeat_failed",
                robot_id=robot_id,
                error=str(exc),
            )
            return False

    async def get_next_task(self, robot_id: str) -> MissionTask | None:
        """
        Poll for the next available mission task.

        GET /api/v1/robots/{robot_id}/next-task

        Parameters
        ----------
        robot_id:
            Robot requesting a task assignment.

        Returns
        -------
        MissionTask | None
            Next assigned task, or None if no task is available or on error.
        """
        client = self._ensure_client()
        request_id = str(uuid.uuid4())

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._config.http_max_retries),
                wait=wait_exponential(
                    multiplier=self._config.http_retry_backoff_seconds,
                    min=0.5,
                    max=10.0,
                ),
                retry=retry_if_exception_type(
                    (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError)
                ),
                reraise=False,
            ):
                with attempt:
                    response = await client.get(
                        f"/api/v1/robots/{robot_id}/next-task",
                        headers={"X-Request-ID": request_id},
                    )

                    if response.status_code == 200:
                        data = response.json()
                        task = MissionTask.model_validate(data)
                        logger.info(
                            "mission_client.task_received",
                            robot_id=robot_id,
                            mission_id=task.mission_id,
                            bin_count=len(task.bin_ids),
                        )
                        return task

                    if response.status_code == 204:
                        # No tasks available — not an error
                        logger.debug(
                            "mission_client.no_task_available",
                            robot_id=robot_id,
                        )
                        return None

                    if response.status_code >= 500:
                        response.raise_for_status()

                    logger.warning(
                        "mission_client.task_poll_error",
                        robot_id=robot_id,
                        status_code=response.status_code,
                    )
                    return None

        except (RetryError, httpx.HTTPError, Exception) as exc:
            logger.warning(
                "mission_client.task_poll_failed",
                robot_id=robot_id,
                error=str(exc),
            )
            return None

        return None

    async def complete_mission(
        self,
        mission_id: str,
        robot_id: str,
        bins_scanned: int,
        observations_submitted: int = 0,
        duration_seconds: float = 0.0,
    ) -> bool:
        """
        Notify the mission-service that a mission has been completed.

        POST /api/v1/missions/{mission_id}/complete

        Parameters
        ----------
        mission_id:
            ID of the mission being completed.
        robot_id:
            Robot that completed the mission.
        bins_scanned:
            Number of bins scanned during the mission.
        observations_submitted:
            Number of observations successfully submitted.
        duration_seconds:
            Total time taken to complete the mission.

        Returns
        -------
        bool
            True if completion was acknowledged.
        """
        client = self._ensure_client()
        payload = {
            "mission_id": mission_id,
            "robot_id": robot_id,
            "bins_scanned": bins_scanned,
            "observations_submitted": observations_submitted,
            "duration_seconds": round(duration_seconds, 2),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        request_id = str(uuid.uuid4())

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._config.http_max_retries),
                wait=wait_exponential(
                    multiplier=self._config.http_retry_backoff_seconds,
                    min=0.5,
                    max=8.0,
                ),
                retry=retry_if_exception_type(
                    (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError)
                ),
                reraise=False,
            ):
                with attempt:
                    response = await client.post(
                        f"/api/v1/missions/{mission_id}/complete",
                        json=payload,
                        headers={"X-Request-ID": request_id},
                    )

                    if response.status_code in (200, 201, 202, 204):
                        logger.info(
                            "mission_client.mission_completed",
                            mission_id=mission_id,
                            robot_id=robot_id,
                            bins_scanned=bins_scanned,
                        )
                        return True

                    if response.status_code >= 500:
                        response.raise_for_status()

                    logger.error(
                        "mission_client.completion_error",
                        mission_id=mission_id,
                        status_code=response.status_code,
                    )
                    return False

        except (RetryError, httpx.HTTPError, Exception) as exc:
            logger.warning(
                "mission_client.completion_failed",
                mission_id=mission_id,
                error=str(exc),
            )
            return False

        return False

    async def health_check(self) -> bool:
        """Lightweight health check against mission-service /health."""
        if not self._http_client:
            return False
        try:
            response = await self._http_client.get("/health", timeout=3.0)
            return response.status_code == 200
        except Exception:
            return False
