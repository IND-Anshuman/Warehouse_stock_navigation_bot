"""
Redis-backed digital twin state manager.

Manages the live state of the warehouse digital twin including:
- Robot positions (with TTL, stored as Redis Hash)
- Bin occupancy states (stored as Redis Hash)
- Warehouse metadata (stored as Redis Hash)
- Robot path history (stored as Redis List, capped)
"""

from __future__ import annotations

import json
import time
from typing import Any

import structlog
from redis.asyncio import Redis

logger = structlog.get_logger(__name__)

# ── Redis key schema ──────────────────────────────────────────────────────────
# twin:{warehouse_id}:robots        → Hash { robot_id: JSON }
# twin:{warehouse_id}:bins          → Hash { bin_id: JSON }
# twin:{warehouse_id}:meta          → Hash { key: value }
# twin:{warehouse_id}:robot_path:{robot_id} → List of JSON position snapshots
# twin:active_warehouses            → Set of warehouse_ids

_ROBOT_HASH_KEY = "twin:{wh}:robots"
_BIN_HASH_KEY = "twin:{wh}:bins"
_META_HASH_KEY = "twin:{wh}:meta"
_ROBOT_PATH_KEY = "twin:{wh}:robot_path:{rid}"
_ACTIVE_WH_KEY = "twin:active_warehouses"

# Maximum positions stored per robot path
_PATH_MAX_LEN = 500


class WarehouseTwinState:
    """
    Manages the live digital twin state in Redis.

    Stores:
    - Robot positions: Hash ``twin:{warehouse_id}:robots`` keyed by robot_id (JSON values)
    - Bin states:      Hash ``twin:{warehouse_id}:bins``   keyed by bin_id   (JSON values)
    - Warehouse meta:  Hash ``twin:{warehouse_id}:meta``   arbitrary metadata
    - Robot paths:     List ``twin:{warehouse_id}:robot_path:{robot_id}`` (capped)
    """

    def __init__(self, redis_client: Redis, robot_position_ttl: int = 300) -> None:
        """
        Initialise the twin state manager.

        Args:
            redis_client: Connected async Redis client.
            robot_position_ttl: Seconds after which a robot entry expires if no
                                 heartbeat is received (default 300 s / 5 min).
        """
        self._redis = redis_client
        self._robot_ttl = robot_position_ttl

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _robot_key(self, warehouse_id: str) -> str:
        return _ROBOT_HASH_KEY.format(wh=warehouse_id)

    def _bin_key(self, warehouse_id: str) -> str:
        return _BIN_HASH_KEY.format(wh=warehouse_id)

    def _meta_key(self, warehouse_id: str) -> str:
        return _META_HASH_KEY.format(wh=warehouse_id)

    def _path_key(self, warehouse_id: str, robot_id: str) -> str:
        return _ROBOT_PATH_KEY.format(wh=warehouse_id, rid=robot_id)

    # ── Robot positions ───────────────────────────────────────────────────────

    async def update_robot_position(
        self,
        warehouse_id: str,
        robot_id: str,
        x: float,
        y: float,
        z: float,
        yaw: float,
        battery: float,
        status: str,
    ) -> None:
        """
        Store or refresh a robot's position in the digital twin.

        The robot hash entry is given a TTL so stale robots disappear from the
        twin automatically if heartbeats cease.

        Args:
            warehouse_id: Identifier of the warehouse.
            robot_id:     Identifier of the robot.
            x, y, z:      Cartesian position in metres.
            yaw:          Heading in radians.
            battery:      Battery percentage (0–100).
            status:       Robot operational status string.
        """
        now_ts = time.time()
        payload: dict[str, Any] = {
            "robot_id": robot_id,
            "warehouse_id": warehouse_id,
            "x": x,
            "y": y,
            "z": z,
            "yaw": yaw,
            "battery": battery,
            "status": status,
            "last_seen": now_ts,
        }

        robot_hash_key = self._robot_key(warehouse_id)
        path_key = self._path_key(warehouse_id, robot_id)

        async with self._redis.pipeline(transaction=False) as pipe:
            # Update robot hash
            pipe.hset(robot_hash_key, robot_id, json.dumps(payload))
            # Refresh hash TTL on each heartbeat (the whole hash key)
            pipe.expire(robot_hash_key, self._robot_ttl)
            # Append to path history (trimmed to MAX_LEN)
            path_snap = json.dumps({"x": x, "y": y, "z": z, "yaw": yaw, "ts": now_ts})
            pipe.rpush(path_key, path_snap)
            pipe.ltrim(path_key, -_PATH_MAX_LEN, -1)
            pipe.expire(path_key, self._robot_ttl * 2)
            # Mark warehouse as active
            pipe.sadd(_ACTIVE_WH_KEY, warehouse_id)
            await pipe.execute()

        logger.debug(
            "robot_position_updated",
            warehouse_id=warehouse_id,
            robot_id=robot_id,
            x=x,
            y=y,
            battery=battery,
            status=status,
        )

    # ── Bin states ────────────────────────────────────────────────────────────

    async def update_bin_state(
        self,
        warehouse_id: str,
        bin_id: str,
        sku: str | None,
        mismatch_type: str | None,
        confidence: float,
        status: str = "OBSERVED",
    ) -> None:
        """
        Update the occupancy / audit state for a warehouse bin.

        Args:
            warehouse_id:   Identifier of the warehouse.
            bin_id:         Identifier of the bin/slot.
            sku:            SKU currently observed (None if empty).
            mismatch_type:  Mismatch classification (None if verified).
            confidence:     AI-model confidence score for the observation.
            status:         State label: OBSERVED | MISMATCH | VERIFIED | EMPTY.
        """
        payload: dict[str, Any] = {
            "bin_id": bin_id,
            "warehouse_id": warehouse_id,
            "sku": sku,
            "mismatch_type": mismatch_type,
            "confidence": confidence,
            "status": status,
            "last_updated": time.time(),
        }

        bin_hash_key = self._bin_key(warehouse_id)
        await self._redis.hset(bin_hash_key, bin_id, json.dumps(payload))

        logger.debug(
            "bin_state_updated",
            warehouse_id=warehouse_id,
            bin_id=bin_id,
            sku=sku,
            status=status,
            confidence=confidence,
        )

    async def mark_bin_mismatch(
        self,
        warehouse_id: str,
        bin_id: str,
        sku: str | None,
        mismatch_type: str,
        confidence: float,
    ) -> None:
        """Convenience wrapper: mark a bin as MISMATCH state."""
        await self.update_bin_state(
            warehouse_id=warehouse_id,
            bin_id=bin_id,
            sku=sku,
            mismatch_type=mismatch_type,
            confidence=confidence,
            status="MISMATCH",
        )

    async def mark_bin_verified(
        self,
        warehouse_id: str,
        bin_id: str,
        sku: str | None,
        confidence: float,
    ) -> None:
        """Convenience wrapper: mark a bin as VERIFIED state."""
        await self.update_bin_state(
            warehouse_id=warehouse_id,
            bin_id=bin_id,
            sku=sku,
            mismatch_type=None,
            confidence=confidence,
            status="VERIFIED",
        )

    # ── Reads ─────────────────────────────────────────────────────────────────

    async def get_robot_positions(self, warehouse_id: str) -> list[dict[str, Any]]:
        """
        Return all active robot positions for a warehouse.

        Returns:
            List of robot position dicts; empty list if none.
        """
        raw: dict[bytes, bytes] = await self._redis.hgetall(self._robot_key(warehouse_id))
        result: list[dict[str, Any]] = []
        for _rid, data in raw.items():
            try:
                result.append(json.loads(data))
            except json.JSONDecodeError:
                logger.warning("invalid_robot_json", key=_rid)
        return result

    async def get_bin_states(self, warehouse_id: str) -> dict[str, Any]:
        """
        Return all bin states for a warehouse.

        Returns:
            Dict mapping bin_id → bin state dict.
        """
        raw: dict[bytes, bytes] = await self._redis.hgetall(self._bin_key(warehouse_id))
        result: dict[str, Any] = {}
        for bin_id_bytes, data in raw.items():
            bin_id = bin_id_bytes.decode() if isinstance(bin_id_bytes, bytes) else bin_id_bytes
            try:
                result[bin_id] = json.loads(data)
            except json.JSONDecodeError:
                logger.warning("invalid_bin_json", bin_id=bin_id)
        return result

    async def get_warehouse_snapshot(self, warehouse_id: str) -> dict[str, Any]:
        """
        Return a complete warehouse twin snapshot.

        Returns a dict with keys:
        - ``warehouse_id`` (str)
        - ``robots``  (list[dict]) — all active robot positions
        - ``bins``    (dict)       — all bin states keyed by bin_id
        - ``stats``   (dict)       — summary counts
        - ``snapshot_ts`` (float)  — UNIX timestamp of this snapshot
        """
        robots = await self.get_robot_positions(warehouse_id)
        bins = await self.get_bin_states(warehouse_id)

        # Compute summary stats
        total_bins = len(bins)
        mismatch_count = sum(1 for b in bins.values() if b.get("status") == "MISMATCH")
        verified_count = sum(1 for b in bins.values() if b.get("status") == "VERIFIED")
        active_robots = len(robots)

        stats: dict[str, Any] = {
            "total_bins_tracked": total_bins,
            "mismatch_count": mismatch_count,
            "verified_count": verified_count,
            "observed_count": total_bins - mismatch_count - verified_count,
            "active_robots": active_robots,
            "robots_online": sum(1 for r in robots if r.get("status") == "ONLINE"),
            "average_battery": (
                round(sum(r.get("battery", 0) for r in robots) / active_robots, 1)
                if active_robots
                else 0.0
            ),
        }

        return {
            "warehouse_id": warehouse_id,
            "robots": robots,
            "bins": bins,
            "stats": stats,
            "snapshot_ts": time.time(),
        }

    async def get_robot_path_history(
        self, warehouse_id: str, robot_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """
        Return the most recent robot path positions.

        Args:
            warehouse_id: Identifier of the warehouse.
            robot_id:     Identifier of the robot.
            limit:        Maximum number of positions to return.

        Returns:
            List of position snapshot dicts (oldest first).
        """
        path_key = self._path_key(warehouse_id, robot_id)
        raw_entries = await self._redis.lrange(path_key, -limit, -1)
        result: list[dict[str, Any]] = []
        for entry in raw_entries:
            try:
                result.append(json.loads(entry))
            except json.JSONDecodeError:
                logger.warning("invalid_path_json", robot_id=robot_id)
        return result

    async def get_active_warehouses(self) -> list[str]:
        """
        Return IDs of warehouses with active robot sessions.

        Returns:
            List of warehouse ID strings.
        """
        members: set[bytes] = await self._redis.smembers(_ACTIVE_WH_KEY)
        return [m.decode() if isinstance(m, bytes) else m for m in members]
