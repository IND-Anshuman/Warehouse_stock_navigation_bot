import json
from typing import Optional, Dict, Any
import redis.asyncio as aioredis
from app.config import settings

class TopologyCache:
    def __init__(self, redis_url: str):
        self.redis = aioredis.from_url(redis_url, decode_responses=True)

    async def get_cached_topology(self, warehouse_id: str) -> Optional[Dict[str, Any]]:
        data = await self.redis.get(f"topology:{warehouse_id}")
        if data:
            return json.loads(data)
        return None

    async def cache_topology(self, warehouse_id: str, topology_dict: Dict[str, Any]) -> None:
        await self.redis.set(
            f"topology:{warehouse_id}",
            json.dumps(topology_dict),
            ex=settings.REDIS_TOPOLOGY_TTL_SECONDS
        )

    async def invalidate_topology(self, warehouse_id: str) -> None:
        await self.redis.delete(f"topology:{warehouse_id}")

    async def cache_bin(self, bin_id: str, bin_dict: Dict[str, Any]) -> None:
        await self.redis.set(
            f"bin:{bin_id}",
            json.dumps(bin_dict),
            ex=3600  # Cache individual bin details for 1 hr
        )

    async def get_cached_bin(self, bin_id: str) -> Optional[Dict[str, Any]]:
        data = await self.redis.get(f"bin:{bin_id}")
        if data:
            return json.loads(data)
        return None
