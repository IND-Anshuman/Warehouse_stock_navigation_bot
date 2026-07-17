from pydantic import BaseModel
from typing import Optional, List
import uuid

class RobotState(BaseModel):
    robot_id: str
    warehouse_id: str
    current_x: float = 0.0
    current_y: float = 0.0
    current_z: float = 0.0
    yaw: float = 0.0
    battery_pct: float = 100.0
    status: str = "IDLE"  # IDLE, AUDITING, CHARGING, FAULTED
    mission_id: Optional[str] = None
    offline_buffer_size: int = 0

class SimulatedBin(BaseModel):
    bin_id: str
    bin_code: str
    coord_x: float
    coord_y: float
    coord_z: float
    sku: Optional[str] = None
    qr_code: Optional[str] = None
    has_correct_item: bool = True
    has_mismatch: bool = False
