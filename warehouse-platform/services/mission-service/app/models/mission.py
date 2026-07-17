from sqlalchemy import Column, String, Integer, Numeric, Boolean, DateTime, ForeignKey, Table, Enum
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func
import uuid

Base = declarative_base()

class Robot(Base):
    __tablename__ = 'robots'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    serial_number = Column(String(100), unique=True, nullable=False)
    name = Column(String(255))
    model = Column(String(100))
    warehouse_id = Column(String, nullable=False)
    status = Column(String, default='IDLE') # IDLE, AUDITING, CHARGING, FAULTED, OFFLINE
    battery_pct = Column(Numeric(5, 2), default=100.00)
    firmware_version = Column(String(50))
    last_heartbeat = Column(DateTime(timezone=True))
    current_coord_x = Column(Numeric(10, 4))
    current_coord_y = Column(Numeric(10, 4))
    current_coord_z = Column(Numeric(10, 4), default=0)
    current_yaw = Column(Numeric(8, 4), default=0)
    active_mission_id = Column(String) # UUID format string
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

class Mission(Base):
    __tablename__ = 'missions'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    warehouse_id = Column(String, nullable=False)
    robot_id = Column(String, ForeignKey('robots.id'))
    status = Column(String, default='SCHEDULED') # SCHEDULED, IN_PROGRESS, COMPLETED, FAILED, CANCELLED
    priority = Column(Integer, default=5)
    name = Column(String(255))
    description = Column(String)
    scheduled_at = Column(DateTime(timezone=True), default=func.now())
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    failed_at = Column(DateTime(timezone=True))
    failure_reason = Column(String)
    total_bins_target = Column(Integer, default=0)
    total_bins_scanned = Column(Integer, default=0)
    coverage_pct = Column(Numeric(5, 2), default=0.00)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

class MissionZone(Base):
    __tablename__ = 'mission_zones'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    mission_id = Column(String, ForeignKey('missions.id', ondelete='CASCADE'), nullable=False)
    zone_id = Column(String, nullable=False)
    scan_order = Column(Integer)
    status = Column(String, default='PENDING') # PENDING, IN_PROGRESS, COMPLETED
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
