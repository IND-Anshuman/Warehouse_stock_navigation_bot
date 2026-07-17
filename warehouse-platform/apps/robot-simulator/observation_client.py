"""
observation_client.py — HTTP client for the observation-service.

Handles single and batch observation submission with:
- Automatic retry with exponential back-off (tenacity)
- Request/response structured logging
- Per-call timeout enforcement
- Idempotency via client-generated observation_id UUIDs
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

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class ObservationClient:
    """
    Async HTTP client for the observation-service REST API.

    Responsible for submitting single observations and batches.
    Returns boolean success so callers can decide whether to buffer
    the payload locally.

    Usage
    -----
    ::

        async with ObservationClient(config) as client:
            ok = await client.submit_observation(payload_dict)
    """

    def __init__(self, config: Config) -> None:
        """
        Parameters
        ----------
        config:
            Application configuration (URL, timeouts, retry settings).
        """
        self._config = config
        self._base_url = config.observation_service_url.rstrip("/")
        self._http_client: httpx.AsyncClient | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def __aenter__(self) -> "ObservationClient":
        await self.open()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def open(self) -> None:
        """Initialise the underlying httpx.AsyncClient."""
        self._http_client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(
                connect=3.0,
                read=self._config.http_timeout_seconds,
                write=self._config.http_timeout_seconds,
                pool=5.0,
            ),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Client": "robot-simulator",
            },
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )
        logger.info("observation_client.opened", base_url=self._base_url)

    async def close(self) -> None:
        """Gracefully close the underlying HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        logger.info("observation_client.closed")

    def _ensure_client(self) -> httpx.AsyncClient:
        if not self._http_client:
            raise RuntimeError("ObservationClient not open. Call open() first.")
        return self._http_client

    # ── Public API ─────────────────────────────────────────────────────────────

    async def submit_observation(self, observation: dict[str, Any]) -> bool:
        """
        Submit a single observation to the observation-service.

        Retries up to ``config.http_max_retries`` times with exponential
        back-off before giving up. Does NOT raise on failure — returns
        ``False`` so the caller can fall back to local buffering.

        Parameters
        ----------
        observation:
            Fully-populated observation dict (see ObservationPayload).

        Returns
        -------
        bool
            ``True`` if the service accepted the observation (2xx response).
            ``False`` on any error (network, timeout, 4xx/5xx).
        """
        client = self._ensure_client()

        # Stamp submission time
        observation = {
            **observation,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        }
        request_id = str(uuid.uuid4())

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._config.http_max_retries),
                wait=wait_exponential(
                    multiplier=self._config.http_retry_backoff_seconds,
                    min=0.2,
                    max=8.0,
                ),
                retry=retry_if_exception_type(
                    (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError)
                ),
                reraise=False,
            ):
                with attempt:
                    response = await client.post(
                        "/api/v1/observations",
                        json=observation,
                        headers={"X-Request-ID": request_id},
                    )

                    if response.status_code in (200, 201, 202):
                        logger.debug(
                            "observation_client.submitted",
                            observation_id=observation.get("observation_id"),
                            bin_id=observation.get("bin_id"),
                            status_code=response.status_code,
                            request_id=request_id,
                        )
                        return True

                    if response.status_code == 409:
                        # Idempotency: already received — treat as success
                        logger.debug(
                            "observation_client.duplicate_accepted",
                            observation_id=observation.get("observation_id"),
                            request_id=request_id,
                        )
                        return True

                    if response.status_code >= 500:
                        # Server error — eligible for retry
                        logger.warning(
                            "observation_client.server_error",
                            status_code=response.status_code,
                            request_id=request_id,
                            attempt_number=attempt.retry_state.attempt_number,
                        )
                        response.raise_for_status()  # triggers retry

                    # 4xx client errors — no point retrying
                    logger.error(
                        "observation_client.client_error",
                        status_code=response.status_code,
                        body=response.text[:200],
                        request_id=request_id,
                    )
                    return False

        except (RetryError, httpx.HTTPError, Exception) as exc:
            logger.warning(
                "observation_client.submit_failed",
                observation_id=observation.get("observation_id"),
                bin_id=observation.get("bin_id"),
                error=str(exc),
                request_id=request_id,
            )
            return False

        return False  # unreachable, satisfies type checker

    async def submit_batch(self, observations: list[dict[str, Any]]) -> bool:
        """
        Submit a batch of observations in a single HTTP request.

        Uses the /api/v1/observations/batch endpoint. On failure, returns
        ``False`` so the caller can re-buffer or retry individually.

        Parameters
        ----------
        observations:
            List of observation dicts. Each must have an ``observation_id``.

        Returns
        -------
        bool
            ``True`` if all observations were accepted; ``False`` otherwise.
        """
        if not observations:
            return True  # vacuously true — nothing to do

        client = self._ensure_client()
        request_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()

        # Stamp submission time on each payload
        stamped = [{**obs, "submitted_at": now_iso} for obs in observations]

        payload = {
            "observations": stamped,
            "batch_id": request_id,
            "submitted_at": now_iso,
        }

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._config.http_max_retries),
                wait=wait_exponential(
                    multiplier=self._config.http_retry_backoff_seconds,
                    min=0.5,
                    max=12.0,
                ),
                retry=retry_if_exception_type(
                    (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError)
                ),
                reraise=False,
            ):
                with attempt:
                    response = await client.post(
                        "/api/v1/observations/batch",
                        json=payload,
                        headers={"X-Request-ID": request_id},
                    )

                    if response.status_code in (200, 201, 202, 207):
                        logger.info(
                            "observation_client.batch_submitted",
                            count=len(observations),
                            status_code=response.status_code,
                            request_id=request_id,
                        )
                        return True

                    if response.status_code >= 500:
                        response.raise_for_status()  # triggers retry

                    logger.error(
                        "observation_client.batch_client_error",
                        status_code=response.status_code,
                        count=len(observations),
                        request_id=request_id,
                    )
                    return False

        except (RetryError, httpx.HTTPError, Exception) as exc:
            logger.warning(
                "observation_client.batch_failed",
                count=len(observations),
                error=str(exc),
                request_id=request_id,
            )
            return False

        return False

    async def health_check(self) -> bool:
        """
        Perform a lightweight health-check against the observation-service.

        Returns
        -------
        bool
            ``True`` if the service responds with 200 on /health.
        """
        if not self._http_client:
            return False
        try:
            response = await self._http_client.get("/health", timeout=3.0)
            return response.status_code == 200
        except Exception:
            return False
