from sqlalchemy import Column, String, Integer, Numeric, Boolean, DateTime, ForeignKey, Table
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func
import uuid

Base = declarative_base()

class Warehouse(Base):
    __tablename__ = 'warehouses'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    code = Column(String(50), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    address = Column(String)
    city = Column(String(100))
    country = Column(String(100))
    timezone = Column(String(100), default='UTC')
    total_area_sqm = Column(Numeric(10, 2))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

    zones = relationship("Zone", back_populates="warehouse", cascade="all, delete-orphan")

class Zone(Base):
    __tablename__ = 'zones'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    warehouse_id = Column(String, ForeignKey('warehouses.id', ondelete='CASCADE'), nullable=False)
    code = Column(String(50), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(String)
    zone_type = Column(String(50))
    floor_level = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

    warehouse = relationship("Warehouse", back_populates="zones")
    aisles = relationship("Aisle", back_populates="zone", cascade="all, delete-orphan")

class Aisle(Base):
    __tablename__ = 'aisles'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    zone_id = Column(String, ForeignKey('zones.id', ondelete='CASCADE'), nullable=False)
    code = Column(String(50), nullable=False)
    aisle_number = Column(Integer, nullable=False)
    direction = Column(String(10), default='NORTH_SOUTH')
    start_coord_x = Column(Numeric(10, 4))
    start_coord_y = Column(Numeric(10, 4))
    end_coord_x = Column(Numeric(10, 4))
    end_coord_y = Column(Numeric(10, 4))
    created_at = Column(DateTime(timezone=True), default=func.now())

    zone = relationship("Zone", back_populates="aisles")
    racks = relationship("Rack", back_populates="aisle", cascade="all, delete-orphan")

class Rack(Base):
    __tablename__ = 'racks'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    aisle_id = Column(String, ForeignKey('aisles.id', ondelete='CASCADE'), nullable=False)
    code = Column(String(100), nullable=False)
    rack_number = Column(Integer, nullable=False)
    side = Column(String(10), default='LEFT')
    num_shelves = Column(Integer, nullable=False, default=5)
    coord_x = Column(Numeric(10, 4))
    coord_y = Column(Numeric(10, 4))
    coord_z = Column(Numeric(10, 4), default=0)
    height_cm = Column(Numeric(8, 2))
    width_cm = Column(Numeric(8, 2))
    depth_cm = Column(Numeric(8, 2))
    created_at = Column(DateTime(timezone=True), default=func.now())

    aisle = relationship("Aisle", back_populates="racks")
    shelves = relationship("Shelf", back_populates="rack", cascade="all, delete-orphan")

class Shelf(Base):
    __tablename__ = 'shelves'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    rack_id = Column(String, ForeignKey('racks.id', ondelete='CASCADE'), nullable=False)
    code = Column(String(100), nullable=False)
    level_number = Column(Integer, nullable=False)
    height_from_floor_cm = Column(Numeric(8, 2))
    load_capacity_kg = Column(Numeric(10, 2))
    created_at = Column(DateTime(timezone=True), default=func.now())

    rack = relationship("Rack", back_populates="shelves")
    bins = relationship("Bin", back_populates="shelf", cascade="all, delete-orphan")

class Bin(Base):
    __tablename__ = 'bins'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    shelf_id = Column(String, ForeignKey('shelves.id', ondelete='CASCADE'), nullable=False)
    code = Column(String(150), nullable=False, unique=True)
    bin_number = Column(Integer, nullable=False)
    coord_x = Column(Numeric(10, 4))
    coord_y = Column(Numeric(10, 4))
    coord_z = Column(Numeric(10, 4))
    width_cm = Column(Numeric(8, 2))
    depth_cm = Column(Numeric(8, 2))
    height_cm = Column(Numeric(8, 2))
    qr_code = Column(String(255))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

    shelf = relationship("Shelf", back_populates="bins")
