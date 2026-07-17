-- ============================================================
--  Autonomous Warehouse Inventory Audit Platform
--  PostgreSQL Database Initialization Script
--  Executed on first container startup
-- ============================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "ltree";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ─────────────────────────────────────────────
-- ENUMERATIONS
-- ─────────────────────────────────────────────

CREATE TYPE robot_status AS ENUM ('IDLE', 'AUDITING', 'CHARGING', 'FAULTED', 'OFFLINE', 'MAINTENANCE');
CREATE TYPE mission_status AS ENUM ('SCHEDULED', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'CANCELLED', 'PAUSED');
CREATE TYPE observation_status AS ENUM ('PENDING', 'PROCESSED', 'FAILED', 'DECODE_ERROR');
CREATE TYPE mismatch_type AS ENUM ('CORRECT_PLACEMENT', 'MISPLACED', 'MISSING', 'DUPLICATE', 'UNKNOWN', 'QUANTITY_DISCREPANCY');
CREATE TYPE alert_status AS ENUM ('OPEN', 'ACKNOWLEDGED', 'ACTION_REQUIRED', 'RESOLVED', 'DISMISSED', 'FALSE_POSITIVE');
CREATE TYPE alert_severity AS ENUM ('INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL');
CREATE TYPE user_role AS ENUM ('PLATFORM_ADMIN', 'WAREHOUSE_MANAGER', 'OPERATOR', 'VIEWER', 'ROBOT_AGENT');

-- ─────────────────────────────────────────────
-- TOPOLOGY DOMAIN
-- ─────────────────────────────────────────────

CREATE TABLE warehouses (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    code            VARCHAR(50) UNIQUE NOT NULL,
    name            VARCHAR(255) NOT NULL,
    address         TEXT,
    city            VARCHAR(100),
    country         VARCHAR(100),
    timezone        VARCHAR(100) DEFAULT 'UTC',
    total_area_sqm  NUMERIC(10, 2),
    is_active       BOOLEAN DEFAULT TRUE,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE zones (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    warehouse_id    UUID NOT NULL REFERENCES warehouses(id) ON DELETE CASCADE,
    code            VARCHAR(50) NOT NULL,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    zone_type       VARCHAR(50),  -- STORAGE, RECEIVING, SHIPPING, HAZMAT
    floor_level     INT DEFAULT 0,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(warehouse_id, code)
);

CREATE TABLE aisles (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    zone_id         UUID NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
    code            VARCHAR(50) NOT NULL,
    aisle_number    INT NOT NULL,
    direction       VARCHAR(10) DEFAULT 'NORTH_SOUTH',  -- NORTH_SOUTH, EAST_WEST
    start_coord_x   NUMERIC(10, 4),
    start_coord_y   NUMERIC(10, 4),
    end_coord_x     NUMERIC(10, 4),
    end_coord_y     NUMERIC(10, 4),
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(zone_id, code)
);

CREATE TABLE racks (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    aisle_id        UUID NOT NULL REFERENCES aisles(id) ON DELETE CASCADE,
    code            VARCHAR(100) NOT NULL,
    rack_number     INT NOT NULL,
    side            VARCHAR(10) DEFAULT 'LEFT',  -- LEFT, RIGHT, CENTER
    num_shelves     INT NOT NULL DEFAULT 5,
    coord_x         NUMERIC(10, 4),
    coord_y         NUMERIC(10, 4),
    coord_z         NUMERIC(10, 4) DEFAULT 0,
    height_cm       NUMERIC(8, 2),
    width_cm        NUMERIC(8, 2),
    depth_cm        NUMERIC(8, 2),
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(aisle_id, code)
);

CREATE TABLE shelves (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rack_id         UUID NOT NULL REFERENCES racks(id) ON DELETE CASCADE,
    code            VARCHAR(100) NOT NULL,
    level_number    INT NOT NULL,
    height_from_floor_cm NUMERIC(8, 2),
    load_capacity_kg NUMERIC(10, 2),
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(rack_id, level_number)
);

CREATE TABLE bins (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    shelf_id        UUID NOT NULL REFERENCES shelves(id) ON DELETE CASCADE,
    code            VARCHAR(150) NOT NULL UNIQUE,
    bin_number      INT NOT NULL,
    coord_x         NUMERIC(10, 4),
    coord_y         NUMERIC(10, 4),
    coord_z         NUMERIC(10, 4),
    width_cm        NUMERIC(8, 2),
    depth_cm        NUMERIC(8, 2),
    height_cm       NUMERIC(8, 2),
    qr_code         VARCHAR(255),
    is_active       BOOLEAN DEFAULT TRUE,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Navigation waypoints for robot path planning
CREATE TABLE navigation_nodes (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    warehouse_id    UUID NOT NULL REFERENCES warehouses(id) ON DELETE CASCADE,
    node_type       VARCHAR(50) NOT NULL,  -- WAYPOINT, CHARGING_STATION, BIN_APPROACH
    coord_x         NUMERIC(10, 4) NOT NULL,
    coord_y         NUMERIC(10, 4) NOT NULL,
    coord_z         NUMERIC(10, 4) DEFAULT 0,
    linked_bin_id   UUID REFERENCES bins(id),
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────
-- INVENTORY DOMAIN
-- ─────────────────────────────────────────────

CREATE TABLE products (
    sku             VARCHAR(100) PRIMARY KEY,
    name            VARCHAR(500) NOT NULL,
    description     TEXT,
    category        VARCHAR(100),
    brand           VARCHAR(200),
    unit_of_measure VARCHAR(50) DEFAULT 'EACH',
    weight_kg       NUMERIC(10, 4),
    length_cm       NUMERIC(8, 2),
    width_cm        NUMERIC(8, 2),
    height_cm       NUMERIC(8, 2),
    barcode_value   VARCHAR(255),
    is_active       BOOLEAN DEFAULT TRUE,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Expected inventory state (sourced from WMS)
CREATE TABLE inventory (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    bin_id          UUID NOT NULL REFERENCES bins(id),
    sku             VARCHAR(100) NOT NULL REFERENCES products(sku),
    expected_qty    INT NOT NULL DEFAULT 1,
    lot_number      VARCHAR(100),
    expiry_date     DATE,
    last_wms_sync   TIMESTAMPTZ DEFAULT NOW(),
    is_active       BOOLEAN DEFAULT TRUE,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(bin_id, sku)
);

-- ─────────────────────────────────────────────
-- ROBOT & MISSION DOMAIN
-- ─────────────────────────────────────────────

CREATE TABLE robots (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    serial_number   VARCHAR(100) UNIQUE NOT NULL,
    name            VARCHAR(255),
    model           VARCHAR(100),
    warehouse_id    UUID REFERENCES warehouses(id),
    status          robot_status DEFAULT 'IDLE',
    battery_pct     NUMERIC(5, 2) DEFAULT 100.0,
    firmware_version VARCHAR(50),
    last_heartbeat  TIMESTAMPTZ,
    current_coord_x NUMERIC(10, 4),
    current_coord_y NUMERIC(10, 4),
    current_coord_z NUMERIC(10, 4) DEFAULT 0,
    current_yaw     NUMERIC(8, 4) DEFAULT 0,
    active_mission_id UUID,  -- forward reference resolved below
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE missions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    warehouse_id    UUID NOT NULL REFERENCES warehouses(id),
    robot_id        UUID REFERENCES robots(id),
    status          mission_status DEFAULT 'SCHEDULED',
    priority        INT DEFAULT 5,  -- 1 (highest) to 10 (lowest)
    name            VARCHAR(255),
    description     TEXT,
    scheduled_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    failed_at       TIMESTAMPTZ,
    failure_reason  TEXT,
    total_bins_target INT DEFAULT 0,
    total_bins_scanned INT DEFAULT 0,
    coverage_pct    NUMERIC(5, 2) DEFAULT 0,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Resolve forward reference
ALTER TABLE robots ADD CONSTRAINT fk_robot_active_mission FOREIGN KEY (active_mission_id) REFERENCES missions(id);

CREATE TABLE mission_zones (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    mission_id      UUID NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    zone_id         UUID NOT NULL REFERENCES zones(id),
    aisle_ids       UUID[],
    scan_order      INT,
    status          VARCHAR(50) DEFAULT 'PENDING',
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    UNIQUE(mission_id, zone_id)
);

-- ─────────────────────────────────────────────
-- OBSERVATION DOMAIN
-- ─────────────────────────────────────────────

CREATE TABLE observations (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    mission_id      UUID REFERENCES missions(id),
    robot_id        UUID NOT NULL REFERENCES robots(id),
    warehouse_id    UUID NOT NULL REFERENCES warehouses(id),
    bin_id          UUID REFERENCES bins(id),
    bin_code        VARCHAR(150),  -- denormalized for speed
    decoded_qr      VARCHAR(500),
    raw_qr_payload  TEXT,
    detection_confidence NUMERIC(5, 4),
    frame_blur_score NUMERIC(10, 4),
    image_url       TEXT,
    observed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    robot_coord_x   NUMERIC(10, 4),
    robot_coord_y   NUMERIC(10, 4),
    robot_coord_z   NUMERIC(10, 4),
    status          observation_status DEFAULT 'PENDING',
    processing_error TEXT,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
) PARTITION BY RANGE (observed_at);

-- Create initial partitions (monthly)
CREATE TABLE observations_2026_07 PARTITION OF observations
    FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
CREATE TABLE observations_2026_08 PARTITION OF observations
    FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
CREATE TABLE observations_2026_09 PARTITION OF observations
    FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');

-- ─────────────────────────────────────────────
-- RECONCILIATION & ALERTS DOMAIN
-- ─────────────────────────────────────────────

CREATE TABLE reconciliation_results (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    observation_id  UUID NOT NULL REFERENCES observations(id),
    warehouse_id    UUID NOT NULL REFERENCES warehouses(id),
    bin_id          UUID REFERENCES bins(id),
    sku             VARCHAR(100),
    result_type     mismatch_type NOT NULL,
    expected_sku    VARCHAR(100),
    expected_qty    INT,
    observed_sku    VARCHAR(100),
    observed_qty    INT DEFAULT 1,
    expected_bin_id UUID REFERENCES bins(id),  -- if MISPLACED: where it should be
    reconciled_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    confidence      NUMERIC(5, 4),
    metadata        JSONB DEFAULT '{}'
);

CREATE TABLE alerts (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    warehouse_id    UUID NOT NULL REFERENCES warehouses(id),
    reconciliation_id UUID REFERENCES reconciliation_results(id),
    observation_id  UUID REFERENCES observations(id),
    bin_id          UUID REFERENCES bins(id),
    sku             VARCHAR(100),
    alert_type      mismatch_type NOT NULL,
    severity        alert_severity NOT NULL DEFAULT 'MEDIUM',
    status          alert_status NOT NULL DEFAULT 'OPEN',
    title           VARCHAR(500) NOT NULL,
    description     TEXT,
    expected_value  TEXT,
    observed_value  TEXT,
    acknowledged_by UUID,
    acknowledged_at TIMESTAMPTZ,
    resolved_by     UUID,
    resolved_at     TIMESTAMPTZ,
    resolution_notes TEXT,
    auto_resolvable BOOLEAN DEFAULT FALSE,
    rescan_requested BOOLEAN DEFAULT FALSE,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────
-- IDENTITY & AUDIT DOMAIN
-- ─────────────────────────────────────────────

CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email           VARCHAR(255) UNIQUE NOT NULL,
    username        VARCHAR(100) UNIQUE NOT NULL,
    full_name       VARCHAR(255),
    role            user_role NOT NULL DEFAULT 'VIEWER',
    is_active       BOOLEAN DEFAULT TRUE,
    last_login_at   TIMESTAMPTZ,
    password_hash   VARCHAR(255),
    warehouse_ids   UUID[] DEFAULT '{}',  -- warehouses this user can access
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE audit_logs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID REFERENCES users(id),
    warehouse_id    UUID REFERENCES warehouses(id),
    action          VARCHAR(100) NOT NULL,
    resource_type   VARCHAR(100),
    resource_id     UUID,
    old_value       JSONB,
    new_value       JSONB,
    ip_address      INET,
    user_agent      TEXT,
    request_id      UUID,
    performed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Transactional outbox for reliable event publishing
CREATE TABLE outbox_events (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    aggregate_type  VARCHAR(100) NOT NULL,
    aggregate_id    UUID NOT NULL,
    event_type      VARCHAR(200) NOT NULL,
    topic           VARCHAR(200) NOT NULL,
    partition_key   VARCHAR(200),
    payload         JSONB NOT NULL,
    headers         JSONB DEFAULT '{}',
    status          VARCHAR(50) DEFAULT 'PENDING',
    retry_count     INT DEFAULT 0,
    last_error      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at    TIMESTAMPTZ,
    scheduled_for   TIMESTAMPTZ DEFAULT NOW()
);

-- ─────────────────────────────────────────────
-- INDICES
-- ─────────────────────────────────────────────

-- Topology indices
CREATE INDEX idx_zones_warehouse ON zones(warehouse_id);
CREATE INDEX idx_aisles_zone ON aisles(zone_id);
CREATE INDEX idx_racks_aisle ON racks(aisle_id);
CREATE INDEX idx_shelves_rack ON shelves(rack_id);
CREATE INDEX idx_bins_shelf ON bins(shelf_id);
CREATE INDEX idx_bins_code ON bins(code);
CREATE INDEX idx_bins_qr ON bins(qr_code) WHERE qr_code IS NOT NULL;

-- Robot & Mission indices
CREATE INDEX idx_robots_warehouse ON robots(warehouse_id);
CREATE INDEX idx_robots_status ON robots(status);
CREATE INDEX idx_missions_warehouse ON missions(warehouse_id);
CREATE INDEX idx_missions_robot ON missions(robot_id);
CREATE INDEX idx_missions_status ON missions(status);

-- Observation indices (on parent table, propagated to partitions)
CREATE INDEX idx_observations_mission ON observations(mission_id);
CREATE INDEX idx_observations_robot ON observations(robot_id);
CREATE INDEX idx_observations_warehouse ON observations(warehouse_id);
CREATE INDEX idx_observations_bin ON observations(bin_id);
CREATE INDEX idx_observations_qr ON observations(decoded_qr);
CREATE INDEX idx_observations_time ON observations(observed_at DESC);

-- Reconciliation & Alert indices
CREATE INDEX idx_recon_observation ON reconciliation_results(observation_id);
CREATE INDEX idx_recon_warehouse ON reconciliation_results(warehouse_id);
CREATE INDEX idx_recon_type ON reconciliation_results(result_type);
CREATE INDEX idx_alerts_warehouse ON alerts(warehouse_id);
CREATE INDEX idx_alerts_status ON alerts(status);
CREATE INDEX idx_alerts_severity ON alerts(severity);
CREATE INDEX idx_alerts_created ON alerts(created_at DESC);
CREATE INDEX idx_alerts_bin ON alerts(bin_id);

-- Outbox index for polling worker
CREATE INDEX idx_outbox_status_scheduled ON outbox_events(status, scheduled_for)
    WHERE status = 'PENDING';

-- Inventory index
CREATE INDEX idx_inventory_bin ON inventory(bin_id);
CREATE INDEX idx_inventory_sku ON inventory(sku);

-- ─────────────────────────────────────────────
-- SEED DATA
-- ─────────────────────────────────────────────

-- Default admin user (password: admin123 - bcrypt hash)
INSERT INTO users (email, username, full_name, role, password_hash) VALUES
    ('admin@warehouse-platform.local', 'admin', 'Platform Administrator', 'PLATFORM_ADMIN',
     '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW'),
    ('manager@warehouse-platform.local', 'manager', 'Warehouse Manager', 'WAREHOUSE_MANAGER',
     '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW'),
    ('operator@warehouse-platform.local', 'operator', 'Floor Operator', 'OPERATOR',
     '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW');

-- Default Demo Warehouse
INSERT INTO warehouses (id, code, name, address, city, country, total_area_sqm, timezone)
VALUES (
    'a1b2c3d4-e5f6-7890-abcd-ef1234567890',
    'WH-001',
    'Primary Distribution Center',
    '123 Industrial Blvd',
    'Bangalore',
    'India',
    25000.00,
    'Asia/Kolkata'
);

-- Demo Products
INSERT INTO products (sku, name, category, unit_of_measure, weight_kg) VALUES
    ('SKU-ELEC-001', 'Intel Core i9 Processor', 'Electronics', 'EACH', 0.3),
    ('SKU-ELEC-002', 'Samsung 4K Monitor 27"', 'Electronics', 'EACH', 5.2),
    ('SKU-FURN-001', 'Ergonomic Office Chair', 'Furniture', 'EACH', 15.0),
    ('SKU-FURN-002', 'Standing Desk 180cm', 'Furniture', 'EACH', 45.0),
    ('SKU-BOOK-001', 'Clean Code - Robert Martin', 'Books', 'EACH', 0.6),
    ('SKU-BOOK-002', 'System Design Interview Vol.2', 'Books', 'EACH', 0.8),
    ('SKU-TOOL-001', 'DeWalt Drill Machine 18V', 'Tools', 'EACH', 2.1),
    ('SKU-TOOL-002', 'Stanley Tape Measure 10m', 'Tools', 'EACH', 0.3),
    ('SKU-CONS-001', 'Laptop Cooling Pad USB', 'Consumer Electronics', 'EACH', 0.5),
    ('SKU-CONS-002', 'Mechanical Keyboard RGB', 'Consumer Electronics', 'EACH', 0.9);

-- Update timestamps trigger function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply trigger to all relevant tables
CREATE TRIGGER update_warehouses_updated_at BEFORE UPDATE ON warehouses
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_bins_updated_at BEFORE UPDATE ON bins
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_inventory_updated_at BEFORE UPDATE ON inventory
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_robots_updated_at BEFORE UPDATE ON robots
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_missions_updated_at BEFORE UPDATE ON missions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_alerts_updated_at BEFORE UPDATE ON alerts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_products_updated_at BEFORE UPDATE ON products
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
