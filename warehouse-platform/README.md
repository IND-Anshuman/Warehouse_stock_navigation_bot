# 📦 Autonomous Warehouse Inventory Audit Platform

This is a production-grade, distributed software platform designed to ingest data from fleet-scale mobile autonomous robots, reconcile physical observations against Expected Inventory records (WMS), manage real-time Digital Twins, and alert operators to discrepancies.

## 🚀 Quick Start (Local Development)

Execute these steps to launch the entire platform:

1. **Start Infrastructure Stack**:
   ```bash
   make up
   ```
   This boots up PostgreSQL, Redis, Kafka + ZooKeeper, MinIO (S3 clone), Prometheus, Grafana, and all microservices.

2. **Verify Containers Status**:
   ```bash
   make status
   ```

3. **Seed Demo Topology**:
   ```bash
   make seed
   ```
   Seeds a demo warehouse (`WH-001`) with zones, aisles, racks, and bins in the database.

4. **Launch Robot Simulator Fleet**:
   The `robot-simulator` service runs within the Docker Compose stack. You can view its live dashboard output in the logs:
   ```bash
   make logs service=robot-simulator
   ```

5. **Open Operations Dashboard**:
   Open your browser and navigate to `http://localhost:8090` (Kafka UI), `http://localhost:9001` (MinIO console), or run the dashboard app locally:
   ```bash
   cd apps/ops-dashboard
   npm install && npm run dev
   ```

## 🛠️ Microservice Directory Layout

- `services/topology-service`: Database of physical warehouse coordinates, layout zones, and bins.
- `services/mission-service`: Schedules, plans, and assigns audit tasks to robots.
- `services/observation-service`: Validates visual scans, decodes QRs, and saves raw frame image blobs.
- `services/reconciliation-service`: The core engine verifying observed scans vs. WMS expected records.
- `services/digital-twin-sync`: Distributes real-time websocket layout updates.
- `services/alerting-service`: Dispatches SMS/Email notifications on layout mismatches.

---
*Architected and engineered under Staff/Principal standards.*
