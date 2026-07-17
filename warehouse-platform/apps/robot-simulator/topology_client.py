"""
topology_client.py — HTTP client for the topology-service.

Fetches warehouse layout and bin metadata needed by robot agents to
simulate navigation and generate realistic observations.

Uses httpx async client with tenacity retry logic.
"""

from __future__ import annotations

import asyncio
import random
import uuid
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
from models import SimulatedBin

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class TopologyClient:
    """
    Async HTTP client for the warehouse topology-service.

    Fetches warehouse topology (aisle & bin data) and caches bins
    in-memory so robot agents can navigate without repeated network calls.

    All public methods fall back to synthetic data generation if the
    topology-service is unavailable, allowing the simulator to operate
    in stand-alone mode.
    """

    def __init__(self, config: Config) -> None:
        """
        Parameters
        ----------
        config:
            Application configuration containing service URLs and timeouts.
        """
        self._config = config
        self._base_url = config.topology_service_url.rstrip("/")
        self._http_client: httpx.AsyncClient | None = None
        self._bin_cache: dict[str, list[SimulatedBin]] = {}  # keyed by warehouse_id
        self._topology_cache: dict[str, dict[str, Any]] = {}

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def __aenter__(self) -> "TopologyClient":
        """Open the shared HTTP client when used as an async context manager."""
        await self.open()
        return self

    async def __aexit__(self, *_: Any) -> None:
        """Close the HTTP client."""
        await self.close()

    async def open(self) -> None:
        """Create and configure the underlying httpx.AsyncClient."""
        self._http_client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(
                connect=5.0,
                read=self._config.http_timeout_seconds,
                write=5.0,
                pool=5.0,
            ),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Client": "robot-simulator",
                "X-Request-ID": str(uuid.uuid4()),
            },
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )
        logger.info("topology_client.opened", base_url=self._base_url)

    async def close(self) -> None:
        """Gracefully close the HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        logger.info("topology_client.closed")

    def _ensure_client(self) -> httpx.AsyncClient:
        if not self._http_client:
            raise RuntimeError("TopologyClient is not open. Call open() first.")
        return self._http_client

    # ── Public API ─────────────────────────────────────────────────────────────

    async def get_warehouse_topology(self, warehouse_id: str) -> dict[str, Any] | None:
        """
        Fetch the full warehouse topology document.

        Includes zones, aisles, rack configurations, and dimensions.
        Result is cached in memory for the lifetime of this client instance.

        Parameters
        ----------
        warehouse_id:
            Target warehouse identifier.

        Returns
        -------
        dict | None
            Topology document, or None if unavailable.
        """
        if warehouse_id in self._topology_cache:
            logger.debug(
                "topology_client.cache_hit",
                warehouse_id=warehouse_id,
                key="topology",
            )
            return self._topology_cache[warehouse_id]

        client = self._ensure_client()

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._config.http_max_retries),
                wait=wait_exponential(
                    multiplier=self._config.http_retry_backoff_seconds,
                    min=0.5,
                    max=10.0,
                ),
                retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
                reraise=False,
            ):
                with attempt:
                    response = await client.get(
                        f"/api/v1/warehouses/{warehouse_id}",
                        headers={"X-Request-ID": str(uuid.uuid4())},
                    )
                    response.raise_for_status()
                    topology: dict[str, Any] = response.json()
                    self._topology_cache[warehouse_id] = topology
                    logger.info(
                        "topology_client.topology_fetched",
                        warehouse_id=warehouse_id,
                        zones=len(topology.get("zones", [])),
                    )
                    return topology

        except (RetryError, httpx.HTTPError, Exception) as exc:
            logger.warning(
                "topology_client.topology_fetch_failed",
                warehouse_id=warehouse_id,
                error=str(exc),
                fallback="generating synthetic topology",
            )

        # Fall back to a synthetic topology so the simulator can still run
        synthetic = self._generate_synthetic_topology(warehouse_id)
        self._topology_cache[warehouse_id] = synthetic
        return synthetic

    async def get_all_bins(self, warehouse_id: str) -> list[SimulatedBin]:
        """
        Fetch all bins for a warehouse and cache them locally.

        If topology-service is unreachable, generates a realistic set of
        synthetic bins so the simulator can operate stand-alone.

        Parameters
        ----------
        warehouse_id:
            Target warehouse identifier.

        Returns
        -------
        list[SimulatedBin]
            Ordered list of bins (ordered by aisle then bin number).
        """
        if warehouse_id in self._bin_cache:
            logger.debug(
                "topology_client.cache_hit",
                warehouse_id=warehouse_id,
                key="bins",
                count=len(self._bin_cache[warehouse_id]),
            )
            return self._bin_cache[warehouse_id]

        client = self._ensure_client()
        bins: list[SimulatedBin] = []

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._config.http_max_retries),
                wait=wait_exponential(
                    multiplier=self._config.http_retry_backoff_seconds,
                    min=0.5,
                    max=10.0,
                ),
                retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
                reraise=False,
            ):
                with attempt:
                    response = await client.get(
                        f"/api/v1/warehouses/{warehouse_id}/bins",
                        params={"page_size": 1000},
                        headers={"X-Request-ID": str(uuid.uuid4())},
                    )
                    response.raise_for_status()
                    data: dict[str, Any] = response.json()
                    raw_bins: list[dict] = data.get("items", data) if isinstance(data, dict) else data
                    bins = [self._parse_bin(b) for b in raw_bins]
                    logger.info(
                        "topology_client.bins_fetched",
                        warehouse_id=warehouse_id,
                        count=len(bins),
                    )

        except (RetryError, httpx.HTTPError, Exception) as exc:
            logger.warning(
                "topology_client.bins_fetch_failed",
                warehouse_id=warehouse_id,
                error=str(exc),
                fallback="generating synthetic bins",
            )

        if not bins:
            bins = self._generate_synthetic_bins(warehouse_id)

        self._bin_cache[warehouse_id] = bins
        return bins

    async def get_bins_for_aisle(
        self,
        warehouse_id: str,
        aisle_id: str,
    ) -> list[SimulatedBin]:
        """
        Return bins that belong to a specific aisle.

        Uses the cached bin list; triggers fetch if not yet cached.

        Parameters
        ----------
        warehouse_id:
            Warehouse identifier.
        aisle_id:
            Aisle identifier to filter by.

        Returns
        -------
        list[SimulatedBin]
            Bins in the requested aisle.
        """
        all_bins = await self.get_all_bins(warehouse_id)
        return [b for b in all_bins if b.aisle_id == aisle_id]

    def get_cached_bins(self, warehouse_id: str) -> list[SimulatedBin]:
        """Return cached bins synchronously; empty list if not yet fetched."""
        return self._bin_cache.get(warehouse_id, [])

    # ── Parsing helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _parse_bin(raw: dict[str, Any]) -> SimulatedBin:
        """Convert a raw API response dict to a SimulatedBin model."""
        coords = raw.get("coordinates", raw.get("coords", {}))
        location = raw.get("location", {})
        inventory = raw.get("inventory", raw.get("expected_inventory", {}))

        return SimulatedBin(
            bin_id=str(raw.get("bin_id", raw.get("id", uuid.uuid4()))),
            bin_code=str(raw.get("bin_code", raw.get("code", "UNKNOWN"))),
            aisle_id=str(raw.get("aisle_id", location.get("aisle_id", ""))),
            zone_id=str(raw.get("zone_id", location.get("zone_id", ""))),
            coord_x=float(coords.get("x", raw.get("coord_x", 0.0))),
            coord_y=float(coords.get("y", raw.get("coord_y", 0.0))),
            coord_z=float(coords.get("z", raw.get("coord_z", 0.0))),
            sku=str(inventory.get("sku", raw.get("sku", "SKU-UNKNOWN"))),
            expected_quantity=int(inventory.get("quantity", raw.get("expected_quantity", 1))),
            description=str(raw.get("description", "")),
        )

    # ── Synthetic data generators ──────────────────────────────────────────────

    @staticmethod
    def _generate_synthetic_topology(warehouse_id: str) -> dict[str, Any]:
        """Build a minimal synthetic topology document."""
        zones = ["ZONE-A", "ZONE-B", "ZONE-C"]
        aisles_per_zone = 4

        return {
            "warehouse_id": warehouse_id,
            "name": f"Synthetic Warehouse ({warehouse_id})",
            "dimensions": {"length_m": 120.0, "width_m": 60.0, "height_m": 10.0},
            "zones": [
                {
                    "zone_id": zone,
                    "name": zone,
                    "aisles": [
                        {"aisle_id": f"{zone}-AISLE-{i:02d}", "bins_count": 20}
                        for i in range(1, aisles_per_zone + 1)
                    ],
                }
                for zone in zones
            ],
            "_synthetic": True,
        }

    @staticmethod
    def _generate_synthetic_bins(warehouse_id: str) -> list[SimulatedBin]:
        """
        Generate a realistic warehouse bin layout.

        Produces 3 zones × 4 aisles × 20 bins = 240 bins with
        physically plausible coordinates distributed across the floor.
        """
        sku_pool = [
            f"SKU-{cat}-{num:04d}"
            for cat in ["ELEC", "MECH", "CHEM", "MISC", "FOOD"]
            for num in range(1, 200)
        ]
        rng = random.Random(42)  # deterministic for reproducibility

        bins: list[SimulatedBin] = []
        zones = ["ZONE-A", "ZONE-B", "ZONE-C"]
        aisles_per_zone = 4
        bins_per_aisle = 20
        shelf_heights = [0.5, 1.2, 1.9, 2.6]  # metres

        zone_x_offsets = [0.0, 40.0, 80.0]

        for zone_idx, zone_id in enumerate(zones):
            zone_x_base = zone_x_offsets[zone_idx]

            for aisle_idx in range(1, aisles_per_zone + 1):
                aisle_id = f"{zone_id}-AISLE-{aisle_idx:02d}"
                aisle_y = aisle_idx * 10.0  # 10m between aisles

                for bin_num in range(1, bins_per_aisle + 1):
                    bin_code = f"{zone_id[5]}-{aisle_idx:02d}-{bin_num:03d}"
                    bin_id = f"{warehouse_id}-{zone_id}-A{aisle_idx:02d}-B{bin_num:03d}"
                    shelf = shelf_heights[(bin_num - 1) % len(shelf_heights)]

                    coord_x = zone_x_base + (bin_num * 1.5)  # 1.5m per bin slot
                    coord_y = aisle_y
                    coord_z = shelf

                    bins.append(
                        SimulatedBin(
                            bin_id=bin_id,
                            bin_code=bin_code,
                            aisle_id=aisle_id,
                            zone_id=zone_id,
                            coord_x=coord_x,
                            coord_y=coord_y,
                            coord_z=coord_z,
                            sku=rng.choice(sku_pool),
                            expected_quantity=rng.randint(1, 50),
                            description=f"Synthetic bin {bin_code}",
                        )
                    )

        logger.info(
            "topology_client.synthetic_bins_generated",
            warehouse_id=warehouse_id,
            count=len(bins),
        )
        return bins
