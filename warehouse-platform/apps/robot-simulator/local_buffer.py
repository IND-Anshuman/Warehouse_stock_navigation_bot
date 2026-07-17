import aiosqlite
import json
import os
import structlog
from typing import List, Dict, Any

logger = structlog.get_logger(__name__)

class LocalObservationBuffer:
    """
    Local SQLite buffer mapping for offline observations when robot WiFi connectivity drops.
    Allows robot to continue scanning in dead zones and upload batches later.
    """
    def __init__(self, db_path: str = "robot_buffer.db"):
        self.db_path = db_path

    async def initialize(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS buffered_observations (
                    id INTEGER PRIMARY KEY AUTOIONCREMENT,
                    observation_id TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    synced INTEGER DEFAULT 0
                )
            """)
            await db.commit()
            logger.info("sqlite_buffer_initialized", path=self.db_path)

    async def save_observation(self, observation_id: str, payload: dict) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO buffered_observations (observation_id, payload) VALUES (?, ?)",
                (observation_id, json.dumps(payload))
            )
            await db.commit()
            logger.debug("observation_buffered_locally", observation_id=observation_id)

    async def get_unsynced_observations(self, limit: int = 10) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT id, payload FROM buffered_observations WHERE synced = 0 ORDER BY id ASC LIMIT ?",
                (limit,)
            ) as cursor:
                rows = await cursor.fetchall()
                results = []
                for row in rows:
                    item = json.loads(row[1])
                    item["local_row_id"] = row[0]
                    results.append(item)
                return results

    async def mark_synced(self, row_ids: List[int]) -> None:
        if not row_ids:
            return
        async with aiosqlite.connect(self.db_path) as db:
            placeholder = ",".join("?" for _ in row_ids)
            await db.execute(
                f"DELETE FROM buffered_observations WHERE id IN ({placeholder})",
                row_ids
            )
            await db.commit()
            logger.info("locally_buffered_observations_purged", count=len(row_ids))

    async def count_unsynced(self) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM buffered_observations WHERE synced = 0") as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0
