import asyncio
import random
import uuid
import structlog
import httpx
from datetime import datetime
from models import RobotState, SimulatedBin
from local_buffer import LocalObservationBuffer
from config import config

logger = structlog.get_logger(__name__)

class RobotAgent:
    """
    Independent autonomous robot simulation agent task.
    Orchestrates:
    - Heartbeat generation at 1Hz
    - Pull-model mission dispatch tasks
    - Aisle navigation simulations
    - Vision system frame/QR detection scans
    - SQLite buffering for intermittent WiFi signals
    """
    def __init__(self, robot_id: str, warehouse_id: str):
        self.state = RobotState(
            robot_id=robot_id,
            warehouse_id=warehouse_id,
            battery_pct=100.0,
            status="IDLE"
        )
        self.buffer = LocalObservationBuffer(db_path=f"buffer_{robot_id}.db")
        self.http_client = httpx.AsyncClient(timeout=5.0)
        self.bins: list[SimulatedBin] = []
        self.connected = True

    async def initialize(self) -> None:
        await self.buffer.initialize()
        await self._register_robot()
        await self._fetch_topology()

    async def _register_robot(self) -> None:
        url = f"{config.MISSION_SERVICE_URL}/api/v1/robots"
        try:
            response = await self.http_client.post(url, json={
                "serial_number": f"SN-{self.state.robot_id.upper()}",
                "name": f"Robot {self.state.robot_id}",
                "model": "WH-AUDITOR-V1",
                "warehouse_id": self.state.warehouse_id
            })
            if response.status_code in (200, 201):
                logger.info("robot_registered_successfully", robot_id=self.state.robot_id)
        except Exception as e:
            logger.error("robot_registration_failed", robot_id=self.state.robot_id, error=str(e))

    async def _fetch_topology(self) -> None:
        """Load bin topology data from platform for coordinate tracking."""
        url = f"{config.TOPOLOGY_SERVICE_URL}/api/v1/warehouses/{self.state.warehouse_id}/topology"
        try:
            response = await self.http_client.get(url)
            if response.status_code == 200:
                data = response.json()
                # Parse zones -> aisles -> racks -> shelves -> bins
                for zone in data.get("zones", []):
                    for aisle in zone.get("aisles", []):
                        for rack in aisle.get("racks", []):
                            for shelf in rack.get("shelves", []):
                                for b in shelf.get("bins", []):
                                    self.bins.append(SimulatedBin(
                                        bin_id=b["id"],
                                        bin_code=b["code"],
                                        coord_x=float(b["coord_x"]),
                                        coord_y=float(b["coord_y"]),
                                        coord_z=float(b["coord_z"]),
                                        sku=b.get("qr_code"),
                                        qr_code=b.get("qr_code")
                                    ))
                logger.info("topology_loaded_locally", robot_id=self.state.robot_id, bins_count=len(self.bins))
        except Exception as e:
            logger.error("topology_fetch_failed", robot_id=self.state.robot_id, error=str(e))

    async def run(self) -> None:
        # Start heartbeat loop in background
        asyncio.create_task(self._heartbeat_loop())
        
        while True:
            if self.state.status == "IDLE":
                await self._request_and_execute_mission()
            await asyncio.sleep(5)

    async def _heartbeat_loop(self) -> None:
        while True:
            # Simulate random network dropout check
            self.connected = random.random() > config.CONNECTIVITY_FAILURE_PROBABILITY
            
            # Drain battery
            if self.state.status != "CHARGING":
                self.state.battery_pct = max(0.0, self.state.battery_pct - config.BATTERY_DRAIN_RATE)
            
            if self.state.battery_pct < 10.0 and self.state.status != "CHARGING":
                logger.warn("robot_battery_low_docking", robot_id=self.state.robot_id)
                self.state.status = "CHARGING"
                self.state.battery_pct = 100.0  # instant charge simulation
            
            if self.connected:
                # Sync offline buffer records
                asyncio.create_task(self._sync_offline_buffer())
                
                # Send heartbeat
                url = f"{config.MISSION_SERVICE_URL}/api/v1/robots/{self.state.robot_id}/heartbeat"
                try:
                    await self.http_client.post(url, json={
                        "robot_id": self.state.robot_id,
                        "battery": self.state.battery_pct,
                        "coord_x": self.state.current_x,
                        "coord_y": self.state.current_y,
                        "coord_z": self.state.current_z,
                        "status": self.state.status
                    })
                except Exception:
                    pass
            await asyncio.sleep(config.HEARTBEAT_INTERVAL_MS / 1000.0)

    async def _sync_offline_buffer(self) -> None:
        unsynced = await self.buffer.get_unsynced_observations(limit=10)
        if not unsynced:
            return
        
        url = f"{config.OBSERVATION_SERVICE_URL}/api/v1/observations/batch"
        try:
            # Strip local row keys before sending
            clean_batch = []
            for item in unsynced:
                clean_item = item.copy()
                clean_item.pop("local_row_id", None)
                clean_batch.append(clean_item)

            response = await self.http_client.post(url, json={"observations": clean_batch})
            if response.status_code in (200, 201):
                row_ids = [item["local_row_id"] for item in unsynced]
                await self.buffer.mark_synced(row_ids)
        except Exception:
            pass

    async def _request_and_execute_mission(self) -> None:
        url = f"{config.MISSION_SERVICE_URL}/api/v1/robots/{self.state.robot_id}/next-task"
        try:
            response = await self.http_client.get(url)
            if response.status_code == 200:
                task = response.json()
                if task and "mission_id" in task:
                    self.state.mission_id = task["mission_id"]
                    self.state.status = "AUDITING"
                    logger.info("mission_started", robot_id=self.state.robot_id, mission_id=self.state.mission_id)
                    await self._execute_mission_run()
        except Exception as e:
            logger.error("mission_request_failed", robot_id=self.state.robot_id, error=str(e))

    async def _execute_mission_run(self) -> None:
        # Simulate visiting a subset of bins (e.g. 5-10 bins)
        target_bins = random.sample(self.bins, min(len(self.bins), random.randint(5, 10)))
        bins_scanned = 0
        
        for idx, bin_obj in enumerate(target_bins):
            # Navigate coordinates interpolation
            await self._navigate_to(bin_obj.coord_x, bin_obj.coord_y, bin_obj.coord_z)
            await asyncio.sleep(config.SCAN_INTERVAL_MS / 1000.0)

            # Generate Scan Observation
            obs_payload = await self._generate_scan(bin_obj)
            
            # Send observation
            if self.connected:
                url = f"{config.OBSERVATION_SERVICE_URL}/api/v1/observations"
                try:
                    await self.http_client.post(url, json=obs_payload)
                except Exception:
                    await self.buffer.save_observation(obs_payload["observation_id"], obs_payload)
            else:
                await self.buffer.save_observation(obs_payload["observation_id"], obs_payload)
                
            bins_scanned += 1

        # Mark mission complete
        url = f"{config.MISSION_SERVICE_URL}/api/v1/missions/{self.state.mission_id}/complete"
        try:
            await self.http_client.post(url, json={
                "total_bins_scanned": bins_scanned,
                "coverage_pct": float(bins_scanned / len(target_bins)) * 100.0
            })
        except Exception:
            pass

        self.state.status = "IDLE"
        self.state.mission_id = None
        logger.info("mission_run_completed", robot_id=self.state.robot_id)

    async def _navigate_to(self, x: float, y: float, z: float) -> None:
        # Smooth position interpolation simulation
        steps = 5
        dx = (x - self.state.current_x) / steps
        dy = (y - self.state.current_y) / steps
        dz = (z - self.state.current_z) / steps
        
        for _ in range(steps):
            self.state.current_x += dx
            self.state.current_y += dy
            self.state.current_z += dz
            await asyncio.sleep(0.2)

    async def _generate_scan(self, bin_obj: SimulatedBin) -> dict:
        obs_id = str(uuid.uuid4())
        decoded_qr = bin_obj.qr_code

        # Add physical noise edge cases
        is_blurred = random.random() < 0.05
        decode_failed = random.random() < config.DECODE_FAILURE_PROBABILITY
        mismatch_sku = random.random() < 0.05

        if decode_failed or is_blurred:
            decoded_qr = None

        if mismatch_sku and decoded_qr:
            # Scan returns incorrect SKU code
            decoded_qr = "SKU-WRONG-999"

        return {
            "observation_id": obs_id,
            "mission_id": self.state.mission_id,
            "robot_id": self.state.robot_id,
            "warehouse_id": self.state.warehouse_id,
            "bin_id": bin_obj.bin_id,
            "bin_code": bin_obj.bin_code,
            "decoded_qr": decoded_qr,
            "detection_confidence": 0.50 if is_blurred else round(random.uniform(0.85, 0.99), 4),
            "frame_blur_score": 50.0 if is_blurred else 200.0,
            "robot_coord_x": self.state.current_x,
            "robot_coord_y": self.state.current_y,
            "robot_coord_z": self.state.current_z,
            "observed_at": datetime.utcnow().isoformat()
        }
