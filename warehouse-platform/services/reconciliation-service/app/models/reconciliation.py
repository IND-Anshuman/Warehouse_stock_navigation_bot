from sqlalchemy import Column, String, Integer, Numeric, Boolean, DateTime, ForeignKey, Table
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func
import uuid

Base = declarative_base()

class Product(Base):
    __tablename__ = 'products'
    sku = Column(String(100), primary_key=True)
    name = Column(String(500), nullable=False)
    description = Column(String)
    category = Column(String(100))
    brand = Column(String(200))
    unit_of_measure = Column(String(50), default='EACH')
    weight_kg = Column(Numeric(10, 4))
    length_cm = Column(Numeric(8, 2))
    width_cm = Column(Numeric(8, 2))
    height_cm = Column(Numeric(8, 2))
    barcode_value = Column(String(255))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

class Inventory(Base):
    __tablename__ = 'inventory'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    bin_id = Column(String, nullable=False)
    sku = Column(String(100), ForeignKey('products.sku'), nullable=False)
    expected_qty = Column(Integer, nullable=False, default=1)
    lot_number = Column(String(100))
    expiry_date = Column(DateTime)
    last_wms_sync = Column(DateTime(timezone=True), default=func.now())
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

class ReconciliationResult(Base):
    __tablename__ = 'reconciliation_results'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    observation_id = Column(String, nullable=False)
    warehouse_id = Column(String, nullable=False)
    bin_id = Column(String)
    sku = Column(String(100))
    result_type = Column(String, nullable=False) # CORRECT_PLACEMENT, MISPLACED, MISSING, DUPLICATE, UNKNOWN, QUANTITY_DISCREPANCY
    expected_sku = Column(String(100))
    expected_qty = Column(Integer)
    observed_sku = Column(String(100))
    observed_qty = Column(Integer, default=1)
    expected_bin_id = Column(String)
    reconciled_at = Column(DateTime(timezone=True), default=func.now())
    confidence = Column(Numeric(5, 4))

class Alert(Base):
    __tablename__ = 'alerts'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    warehouse_id = Column(String, nullable=False)
    reconciliation_id = Column(String, ForeignKey('reconciliation_results.id'))
    observation_id = Column(String)
    bin_id = Column(String)
    sku = Column(String(100))
    alert_type = Column(String, nullable=False) # mismatch_type
    severity = Column(String, default='MEDIUM') # INFO, LOW, MEDIUM, HIGH, CRITICAL
    status = Column(String, default='OPEN') # OPEN, ACKNOWLEDGED, ACTION_REQUIRED, RESOLVED, DISMISSED, FALSE_POSITIVE
    title = Column(String(500), nullable=False)
    description = Column(String)
    expected_value = Column(String)
    observed_value = Column(String)
    acknowledged_by = Column(String)
    acknowledged_at = Column(DateTime(timezone=True))
    resolved_by = Column(String)
    resolved_at = Column(DateTime(timezone=True))
    resolution_notes = Column(String)
    auto_resolvable = Column(Boolean, default=False)
    rescan_requested = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
