import structlog
from datetime import datetime, timedelta
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.mission import Robot, Mission
from app.config import settings
import json

logger = structlog.get_logger(__name__)

class MissionService:
    def __init__(self, db: AsyncSession, redis_url: str):
        self.db = db
        self.redis = aioredis.from_url(redis_url, decode_responses=True)

    async def assign_robot_to_mission(self, robot_id: str, mission_id: str) -> bool:
        """Assign robot to mission using distributed Redis locks to prevent race conditions."""
        lock_key = f"lock:mission:{mission_id}"
        # Set lock with TTL
        locked = await self.redis.set(lock_key, robot_id, nx=True, ex=settings.MISSION_LOCK_TTL_SECS)
        if not locked:
            logger.warn("mission_already_locked", mission_id=mission_id, robot_id=robot_id)
            return False

        # Update DB structures
        result = await self.db.execute(select(Robot).filter(Robot.id == robot_id))
        robot = result.scalar_one_or_none()
        if not robot:
            await self.release_mission_lock(mission_id)
            return False

        result = await self.db.execute(select(Mission).filter(Mission.id == mission_id))
        mission = result.scalar_one_or_none()
        if not mission or mission.status != 'SCHEDULED':
            await self.release_mission_lock(mission_id)
            return False

        robot.active_mission_id = mission_id
        robot.status = 'AUDITING'
        mission.robot_id = robot_id
        mission.status = 'IN_PROGRESS'
        mission.started_at = datetime.utcnow()
        
        await self.db.commit()
        logger.info("mission_assigned", mission_id=mission_id, robot_id=robot_id)
        return True

    async def release_mission_lock(self, mission_id: str) -> None:
        lock_key = f"lock:mission:{mission_id}"
        await self.redis.delete(lock_key)

    async def handle_robot_heartbeat(self, robot_id: str, battery: float, x: float, y: float, z: float, status: str, yaw: float = 0.0) -> None:
        """Update robot position and state in database and live Redis geo position index."""
        result = await self.db.execute(select(Robot).filter(Robot.id == robot_id))
        robot = result.scalar_one_or_none()
        if not robot:
            return

        robot.battery_pct = battery
        robot.current_coord_x = x
        robot.current_coord_y = y
        robot.current_coord_z = z
        robot.current_yaw = yaw
        robot.status = status
        robot.last_heartbeat = datetime.utcnow()
        await self.db.commit()

        # Update Redis cache for Digital Twin (spatial indexing coordinates)
        robot_loc_key = f"robot:location:{robot.warehouse_id}"
        await self.redis.hset(robot_loc_key, robot_id, json.dumps({
            "robot_id": robot_id,
            "x": x,
            "y": y,
            "z": z,
            "yaw": yaw,
            "battery": battery,
            "status": status,
            "last_seen": datetime.utcnow().isoformat()
        }))

    async def watchdog_check_robots(self) -> None:
        """Watchdog routine identifying offline robots and updating their state."""
        threshold_time = datetime.utcnow() - timedelta(seconds=settings.ROBOT_HEARTBEAT_TIMEOUT_SECS)
        result = await self.db.execute(
            select(Robot).filter(Robot.last_heartbeat < threshold_time, Robot.status != 'OFFLINE')
        )
        offline_robots = result.scalars().all()

        for robot in offline_robots:
            logger.warn("robot_connection_lost", robot_id=robot.id, last_heartbeat=robot.last_heartbeat)
            robot.status = 'OFFLINE'
            
            # If the robot had an active mission, mark the mission as FAILED
            if robot.active_mission_id:
                m_result = await self.db.execute(select(Mission).filter(Mission.id == robot.active_mission_id))
                mission = m_result.scalar_one_or_none()
                if mission and mission.status == 'IN_PROGRESS':
                    mission.status = 'FAILED'
                    mission.failed_at = datetime.utcnow()
                    mission.failure_reason = "Robot heartbeat timeout reached."
                robot.active_mission_id = None
                
        await self.db.commit()
