# SYSTEM ARCHITECTURE & INTERVIEW PREPARATION MANUAL
## SYSTEM: AUTONOMOUS WAREHOUSE INVENTORY AUDIT PLATFORM (`/warehouse-platform`)

## TABLE OF CONTENTS
1. **System Introduction & Business Objective**
   - The Core Business Problem in Warehousing
   - The Autonomous Automated Solution
   - Core System Architecture Overview
2. **Directory Map & File Role Descriptions**
   - Repository Structure
   - System File Mappings & Communication Paths
3. **Shared Packages Layer (`/packages`)**
   - `event-bus`: Reliable Event Streaming with Apache Kafka
   - `security-context`: Role-Based Access Control and Token Validation
   - `shared-utils`: Logging, Exceptions, and Schema Standardization
4. **Microservices Deep-Dive (`/services`)**
   - Auth Service: Identity, TOTP MFA, and Token Rotation
   - Topology Service: Spatial Coordinates and Proximity Mapping
   - Digital Twin Sync: Real-Time WebSockets and State Caching
   - Mission Service: Route Planning and Heartbeat Watchdogs
   - Observation Service: Image Processing and Transactional Outbox
   - Reconciliation Service: Audit Comparison State-Machine
   - Alerting Service: User Preferences and Dispatch Systems
5. **Frontend Application Deep-Dive (`/apps/ops-dashboard`)**
   - React Navigation Topology and Role Guards
   - Zustand Store Architecture
   - WebSocket Sync Hook Lifecycle
   - Responsive SVG Digital Twin Rendering
6. **Robot Fleet Simulator Deep-Dive (`/apps/robot-simulator`)**
   - Simulation Engine Mechanics
   - Offline SQLite Buffering and Syncing Routines
7. **Database Architecture & SQL Relational Design**
   - Spatial Topology and Inventory Schemas
   - Partitioning High-Volume Tables
   - Indexing Strategies for Performance
   - Automated Timestamps and Audit Logging
8. **Infrastructure & Observability Stack**
   - Multi-Container Docker Networks
   - Prometheus Alert Rules and Scrape Targets
9. **Technical Interview Preparation & Defense Manual**
   - Defending the Transactional Outbox Pattern
   - Scaling WebSockets for Real-Time Delivery
   - Optimizing Proximity Search Algorithms
   - Managing High-Volume Writes with Partitioning
10. **System Configuration & Environment Reference**
11. **Comprehensive Endpoint API Catalog**
12. **Detailed Step-by-Step Execution Workflows**
13. **Comprehensive Directory and Service Roles Matrix**
14. **Event and Data Envelope Configurations**
15. **Comprehensive Security Attack Vector Analysis**
16. **Fault Tolerance & Disaster Recovery Protocols**
17. **Detailed Roles Matrix of Database Tables**
18. **Entire System Configuration Environment Values**
19. **System Data Lifecycle & Cleanup Strategies**
20. **Deep Dive on Frontend Routing, Zustand, and WebSocket Interaction**
21. **Robot Simulation Mechanics and Navigation Logic**
22. **Kafka Conduit and Consumer Loop Details**
23. **Comprehensive Endpoint API Catalog - Extended**
24. **JSON Schema and Event Bus Envelopes Catalog**

## 1. SYSTEM INTRODUCTION & BUSINESS OBJECTIVE

### The Core Business Problem in Warehousing
In large-scale distribution centers and logistics hubs, maintaining an accurate record of inventory locations is a critical challenge. The physical layout of a modern warehouse is structured hierarchically to optimize storage and retrieval operations. It starts with the Warehouse itself, which is partitioned into different Zones (such as bulk storage, cold storage, high-security areas, or hazardous materials). Inside these zones are Aisles, which are long corridors lined with Racks. Racks are structural steel structures containing shelving tiers. Shelves are individual horizontal layers, and each shelf is divided into individual storage addresses called Bins.

When inventory is received, workers place items into bins and log the locations in the Warehouse Management System (WMS). However, because of the high volume of daily picks and placements, human errors occur. A worker might place an item in a neighboring bin, put back a canceled pick in the wrong aisle, or enter an incorrect quantity during receiving. These minor mistakes lead to misplaced inventory, which is effectively lost until the shelf is manually audited. The WMS assumes the item is available, but when a picker goes to retrieve it, the bin is empty. This results in delayed shipments, canceled orders, and increased labor costs as staff search the warehouse for the missing stock.

Physical auditing is the traditional solution to this problem, but it is slow, labor-intensive, and expensive. It requires warehouse staff to walk every aisle with handheld barcode scanners, scanning items one by one. Because of the cost and disruption to normal operations, full audits are performed infrequently, often only once or twice a year. This allows errors to persist for months, leading to inventory shrinkage and operational inefficiencies.

### The Autonomous Automated Solution
This platform automates the auditing process using a fleet of autonomous mobile robots (AMRs) equipped with high-resolution cameras, depth sensors (LiDAR), wheel encoders, and spatial navigation systems. The system operates in a continuous, closed loop:

```
+-------------------------------------------------------------+
|                                                             |
|                      1. MISSION CREATION                    |
|          Operator schedules audit via React Dashboard       |
|                                                             |
+------------------------------+------------------------------+
                               |
                               v
+------------------------------+------------------------------+
|                                                             |
|                     2. ROBOT NAVIGATION                     |
|        Robot travels down aisles scanning bin barcodes      |
|                                                             |
+------------------------------+------------------------------+
                               |
                               v
+------------------------------+------------------------------+
|                                                             |
|                    3. DATA INGESTION                        |
|       Observations & coordinates sent to Backend APIs       |
|                                                             |
+------------------------------+------------------------------+
                               |
                               v
+------------------------------+------------------------------+
|                                                             |
|                    4. STATE RECONCILIATION                  |
|     Engine compares actual scan data against WMS records    |
|                                                             |
+------------------------------+------------------------------+
                               |
                               v
+------------------------------+------------------------------+
|                                                             |
|                     5. REAL-TIME UPDATES                    |
|      Discrepancies highlight in red on Digital Twin map      |
|                                                             |
+------------------------------+------------------------------+
```

1. **Mission Creation**: An operator schedules an audit mission using the dashboard, specifying target zones and aisles.
2. **Robot Route Execution**: The assigned robot navigates the corridors, using wheel encoders and LiDAR to track its physical location. As it drives, its camera captures frames of the bins, decodes QR codes, and records the 3D physical coordinates `(x, y, z)` of each scan.
3. **Data Ingestion**: The robot transmits its observations to the backend APIs. If it encounters a WiFi dead zone (common in steel-reinforced warehouses), it saves the scans to a local SQLite database and uploads them in a batch once connection is restored.
4. **State Reconciliation**: The reconciliation service compares the physical scan data against the expected WMS records, identifying discrepancies like misplaced items, missing stock, or quantity errors.
5. **Real-Time Visualizations**: The status of each bin is cached in Redis and streamed via WebSockets to the React dashboard. Discrepancies are highlighted in red, alerting operators to take action immediately.

### Core System Architecture Overview
The platform uses a microservices architecture to ensure scalability and fault tolerance. Ingestion of camera scans is handled by one service, while background reconciliation and real-time visualization are handled by others. This separation ensures that a spike in camera scans does not slow down the operator dashboard or user authentication.

Services communicate asynchronously using **Apache Kafka**, which acts as a durable event log. Synchronous requests (like user authentication or configuration updates) use REST HTTP APIs, while real-time updates use **WebSockets (Socket.IO)** backed by **Redis Pub/Sub** to allow the frontend to scale horizontally.

## 2. DIRECTORY MAP & FILE ROLE DESCRIPTIONS

### Repository Structure and Layout
The monorepo contains the following folders, separating shared utilities, business services, configuration setups, and test suites:
* **`/packages`**: Shared Python libraries built once and installed into each service's container at build time.
* **`/services`**: Independent Python FastAPI microservices running in Docker.
* **`/apps/ops-dashboard`**: React dashboard client.
* **`/apps/robot-simulator`**: Python robot fleet simulator.
* **`/tests`**: Integration and unit testing suites.
* **`/monitoring`**: Configurations for Prometheus metrics and Grafana dashboards.

### System File Mappings & Communication Paths
Services communicate through three primary pathways:
1. **HTTP REST (Synchronous)**: Used for immediate request-response actions. For example, the `ops-dashboard` queries the `auth-service` for login verification and JWT issuance. Similarly, the `reconciliation-service` makes HTTP requests to the `topology-service` to resolve coordinates to physical bins.
2. **Apache Kafka (Asynchronous)**: Used for event streaming. When the `observation-service` records a scan, it publishes an `observation.raw` event to Kafka. The `reconciliation-service` consumes this event, processes it, and publishes a `reconciliation.mismatch` or `reconciliation.verified` event back to Kafka.
3. **Redis Pub/Sub & WebSockets (Real-Time)**: The `digital-twin-sync` service consumes reconciliation events from Kafka, caches the state in Redis, and publishes them to a Redis Pub/Sub channel. The WebSocket server instances subscribe to Redis and stream the updates to the React client.

## 3. SHARED PACKAGES LAYER (`/packages`)

Shared packages reside in the `/packages` folder. They are compiled and installed into each microservice's environment, ensuring consistent behavior across services.

### `event-bus` (Kafka Messaging and Resiliency)
This package wraps `aiokafka` to enforce structured event envelopes and handle connection retries.
* **Message Envelope Pattern**: To prevent parsing errors, every message is wrapped in a standard structure. This envelope contains metadata (event ID, source service, and timestamp) and the payload (event details). This ensures that any service consuming the message can parse it consistently.
* **Connection Resilience**: If a network drop disconnects a service from Kafka, the publisher uses the `tenacity` library to retry the publish using exponential backoff (e.g., retrying after 1s, 2s, and 4s) before raising an error.
* **Dead Letter Queues (DLQ)**: If a consumer service fails to process a message due to a database lock or data corruption, it redirects the message to a Dead Letter Queue (such as `observation.raw.dlq`). This prevents the consumer from getting stuck on a bad message and blocking other events in the partition.

### `security-context` (Role-Based Access Control and Token Validation)
This package manages user authentication and permissions.
* **Password Security**: Passwords are encrypted using Bcrypt. Bcrypt generates a unique salt for each password and runs slowly by design, protecting against brute-force and rainbow table attacks.
* **Stateless Token Validation**: When a user logs in, they receive a JSON Web Token (JWT) signed with a secret key. The token contains user details, their role, and authorized warehouse IDs. Services validate the token locally using the shared secret key, eliminating the need to query a central database on every API request.
* **Role-Based Access Control (RBAC)**: Permissions are assigned to roles, and roles are assigned to users. For example, a `PLATFORM_ADMIN` has full access to delete warehouses and manage users, a `WAREHOUSE_MANAGER` can schedule missions and update inventories, and a `ROBOT_AGENT` can only upload heartbeats and observations.

### `shared-utils` (Logging, Exceptions, and Schema Standardization)
This package configures system-wide behaviors.
* **Structured JSON Logging**: In production, logs are formatted as JSON strings, allowing log collectors (like FluentBit or Loki) to index them easily. In development, logs fall back to colorized, human-readable text.
* **HTTP Exception Handling**: Standard exceptions (e.g., `NotFoundError` or `ConflictError`) are mapped to HTTP status codes. Global middleware catches these exceptions and formats them into standard JSON payloads, ensuring a consistent API error structure.

## 4. DISTRIBUTED BACKEND SERVICES (`/services`)

Backend services are written in Python using FastAPI, running asynchronously inside Uvicorn servers.

### Auth Service (Identity, TOTP MFA, and Token Rotation)
Manages user accounts, JWT signatures, session revokations, and multi-factor authentication (MFA).
* **TOTP MFA Workflow**: Multi-Factor Authentication is supported using Time-Based One-Time Passwords (TOTP). The service generates a random base32 key and saves it to the database, encrypted with the system's master key. The key is exposed as a QR code provisioning URL. The user scans this code with an authenticator app (e.g., Google Authenticator). During login, the server validates the 6-digit TOTP code by decrypting the stored secret and checking it against the current time window, allowing for a small clock drift.
* **Refresh Token Rotation (RTR)**: To mitigate session hijacking, the service implements token rotation. When a client requests a new access token using a refresh token:
  * The server invalidates the old refresh token and stores it in a Redis blocklist.
  * It generates a *new* access token and a *new* refresh token.
  * If a client attempts to reuse an old refresh token (indicating a potential replay attack), the server immediately revokes all active sessions for that user, requiring them to log in again.

### Topology Service (Spatial Coordinates and Proximity Mapping)
Manages physical layouts, assets, and 3D coordinate resolution.
* **3D Euclidean Proximity Search**: When a robot scans a shelf barcode, it reports its physical location as `(x, y, z)` coordinates. The topology service maps these coordinates to a physical bin:
  1. The service queries all bins in the warehouse zone (fetched from the Redis cache).
  2. It calculates the Euclidean distance to each bin:
     $$d = \sqrt{(x_{bin} - x_{obs})^2 + (y_{bin} - y_{obs})^2 + (z_{bin} - z_{obs})^2}$$
  3. The bin with the smallest distance is selected.
  4. To prevent false mappings, the coordinates must fall within a 2-meter radius of the bin. If the nearest bin is further away, the request returns a `404 Not Found` error.
* **Cache-Aside Pattern**: Since layouts change infrequently, querying PostgreSQL on every coordinate update is inefficient. The topology service caches layouts in Redis. Layout updates invalidate the cache, ensuring consistency on subsequent reads.

### Digital Twin Sync (Real-Time WebSockets and State Caching)
Bridges Kafka events to real-time client browsers. It mounts a FastAPI REST application alongside a Socket.IO server under a single ASGI web service.
* **Telemetry Ingestion**: A background consumer subscribes to Kafka topics (`robot.telemetry.heartbeat`, `observation.raw`, etc.).
* **Redis Caching**: Ingested updates are cached in Redis. Telemetry entries are saved with a Time-To-Live (TTL) so that offline robots automatically disappear from the dashboard if heartbeats cease.
* **WebSocket Fan-Out**: The consumer publishes updates to a Redis Pub/Sub channel. The WebSocket server instances subscribe to these channels and relay the updates to the Socket.IO rooms matching the warehouse ID, fanning out the data to all connected browser clients.

### Mission Service (Route Planning and Heartbeat Watchdogs)
Schedules and plans audit paths for the robot fleet.
* **Mission Lifecycle State Machine**: Missions transition through states: `SCHEDULED` -> `IN_PROGRESS` -> `COMPLETED`/`FAILED`/`CANCELLED`. The service validates transitions to prevent illegal states (e.g., preventing a `COMPLETED` mission from transitioning back to `IN_PROGRESS`).
* **Heartbeat Watchdog**: A periodic background task monitors robot heartbeats. If a robot fails to report a heartbeat for more than 30 seconds (indicating connection loss or hardware failure), the service flags the robot as `OFFLINE` and marks its active mission as `FAILED`, recording the timeout reason.

### Observation Service (Image Processing and Transactional Outbox)
Ingests raw scans from edge cameras, uploads frames to S3 storage, and uses the transactional outbox pattern to publish events.
* **Image Archiving**: Raw camera frames are uploaded as JPEGs to MinIO (an S3-compatible object store) for visual audit trails.
* **Transactional Outbox Pattern**: To prevent inconsistencies between the database and Kafka:
  1. The service writes the business entity (e.g., the observation) and an `OutboxEvent` record to the database *within the same transaction*.
  2. A background worker polls the outbox table, publishes the events to Kafka, and marks them as processed.
  3. This ensures that even if Kafka is temporarily offline, events are saved in the database and eventually published.

### Reconciliation Service (Audit Comparison State-Machine)
Compares physical scans against WMS expected records to identify discrepancies.
* **Reconciliation Engine**: When a scan event is received, the engine compares the observed SKU and quantity against expectations:
  * **Correct Placement**: Scanned SKU matches expected SKU, and quantities match.
  * **Misplaced**: The scanned SKU is not expected in this bin, but exists elsewhere in the warehouse. The system flags the discrepancy and indicates where the item should be.
  * **Missing**: Expected items are not detected in the bin.
  * **Unknown**: A scanned SKU is not registered in the WMS catalog.
  * **Quantity Discrepancy**: The correct SKU is found, but the scanned count differs from expectations.
* **Event Dispatching**: Verified placements publish an `InventoryVerified` event, while discrepancies write an alert record and publish an `InventoryMismatchDetected` event to trigger operator notifications.

### Alerting Service (User Preferences and Dispatch Systems)
Dispatches notifications based on user preferences and alert severity.
* **Notification Dispatching**: When a mismatch event is received, the service identifies the operators assigned to that warehouse. It fetches their preferences, renders a custom HTML email template using Jinja2 (populated with details like the bin code and discrepancies), and sends the email asynchronously using `aiosmtplib` to prevent blocking the service.

## 5. FRONTEND APPLICATION (`/apps/ops-dashboard`)

A TypeScript React application built with Vite, Tailwind CSS, Zustand, and Recharts.

### React Navigation Topology and Role Guards
Uses React Router for navigation. Routes are wrapped in a `ProtectedRoute` component that validates user sessions and roles. If an unauthorized user tries to access a page, they are redirected to their default dashboard.

### Zustand Store Architecture
Zustand manages state globally using lightweight, hook-based stores:
* **`authStore`**: Manages user details, access tokens, and permission checks. State is persisted in `localStorage` so sessions survive browser refreshes.
* **`useTwinStore`**: Manages real-time digital twin state, storing robot positions and bin statuses in ES6 Maps (`Map<string, Robot>` and `Map<string, Bin>`). Using Maps allows for fast, key-based updates when WebSocket deltas are received.

### WebSocket Sync Hook Lifecycle
The `useWebSocket` hook manages the live Socket.IO connection:
1. **Mount**: Initiates connection to `/digital-twin` on port 8006, passing the user's JWT.
2. **Room Entry**: Emits a `join_warehouse` event. The server responds with a full `warehouse_snapshot` payload, which populates the Zustand store.
3. **Delta Ingestion**: Listens for `robot_position_update` and `bin_state_update` events, applying modifications directly to the Zustand store.
4. **Unmount**: Disconnects cleanly, cleaning up timers and listeners to prevent memory leaks.

### Responsive SVG Digital Twin Rendering
Renders the warehouse layout using SVGs instead of canvas elements, allowing for responsive, CSS-stylable graphics. Bins are rendered as interactive rectangles, and robots are rendered as moving circles. The colors of the bin elements update dynamically based on the state in the Zustand store (e.g., green for verified, red for mismatch).

## 6. ROBOT FLEET SIMULATOR (`/apps/robot-simulator`)

Simulates fleets of autonomous auditing robots moving through the warehouse.

### Simulation Behavior and Path Interpolation
Robots pull tasks from the mission service, navigate to target bins by interpolating their `(x, y, z)` coordinates, and simulate scans. Scans incorporate simulated physical noise, such as blurry frames, barcode decode failures, and incorrect placements, to test the backend's resilience.

### Offline SQLite Buffering and Syncing Routines
To simulate intermittent WiFi connections, the simulator uses a local SQLite database (`buffer_{robot_id}.db`) to cache scans when offline:
* **Offline Detection**: If a heartbeat ping fails, the robot switches to offline mode.
* **Buffering**: Scans are serialized and saved to the local SQLite table.
* **Syncing**: Once connection is restored, a background task pulls buffered rows, uploads them in batches to the observation service, and deletes them from the local database on success.

## 7. DATABASE DESIGN & SQL RELATIONAL DESIGN

The database runs on PostgreSQL 16. The schema enforces integrity using foreign keys, indexes, table partitions, and triggers.

### Table Partitioning (Scale Design)
The `observations` table is range-partitioned on the `observed_at` column. Monthly tables (e.g., `observations_2026_07`) are generated dynamically. This ensures that:
* Database search scans only traverse the relevant monthly table instead of the entire historical dataset.
* Historical data cleanup is simple: dropping old partitions via `DROP TABLE` is a metadata-only operation, avoiding the table locks and slow transaction logs of large `DELETE` queries.

### Indexing Strategies
* **Spatial Lookup Indexes**: Indexing foreign keys (e.g., `idx_bins_shelf`, `idx_shelves_rack`) speeds up nested topology joins.
* **Partial Indexing**: Creating an index on bin QR codes only where they are not null (`WHERE qr_code IS NOT NULL`) reduces index size and speeds up lookup queries.
* **Polled Indexes**: The outbox table uses a partial index on status and schedule time (`WHERE status = 'PENDING'`) to optimize polling queries for the publisher worker.

### Automated Timestamps and Audit Logging
To maintain an audit trail for compliance, any change to critical tables executes a PostgreSQL trigger function that logs the action, timestamp, old values, and new values to the `audit_logs` table. Additionally, database triggers update the `updated_at` column automatically before updates commit.

## 8. INFRASTRUCTURE & OBSERVABILITY STACK

The system uses Prometheus to scrape metrics from microservices and Grafana to visualize system performance.

### Multi-Container Docker Networks
Microservices run on a private Docker bridge network, isolated from the public internet. Only the `auth-service` and `ops-dashboard` have exposed ports. Communication between microservices (e.g., topology lookups) occurs using internal Docker DNS names.

### Prometheus Alert Rules
The monitoring system evaluates rules to fire alerts:
* **Service Offline**: Triggers if a microservice is unreachable for more than 30 seconds.
* **High Latency**: Triggers if 90% of HTTP requests exceed 500ms over a 1-minute window.
* **Robot Offline**: Triggers if a robot's telemetry heartbeat fails to update for more than 2 minutes.

## 9. TECHNICAL INTERVIEW PREPARATION & DEFENSE MANUAL

This guide helps you explain and defend the architectural choices made in this project during technical interviews.

### 1. Defending the Transactional Outbox Pattern
* **The Design Choice**: We write events to an `outbox_events` table within the same database transaction as the business operation, and a background task publishes them to Kafka.
* **The Tradeoff**: This adds a database write and a small delay in event propagation.
* **Defense**: *"Direct publishing can fail due to network drops, leaving the database updated but downstream services uninformed. The outbox pattern ensures **at-least-once delivery** and eventual consistency across our microservices."*

### 2. Scaling WebSockets for Real-Time Delivery
* **The Design Choice**: The WebSocket sync service consumes events from Kafka, caches state in Redis, and publishes updates to Redis Pub/Sub, which are relayed to Socket.IO clients.
* **The Tradeoff**: This introduces Redis network overhead and duplicates message propagation.
* **Defense**: *"Scaling WebSockets horizontally is difficult because clients are tied to specific server nodes. By using Redis Pub/Sub, we decouple the WebSocket servers from the Kafka consumers. Any WebSocket instance can receive updates via Redis and relay them to its connected clients, allowing the system to scale horizontally."*

### 3. Optimizing Proximity Search Algorithms
* **The Design Choice**: We calculate the 3D Euclidean distance to resolve robot coordinates to bins.
* **The Tradeoff**: This calculation is CPU-bound and can slow down database queries as the number of bins grows.
* **Defense**: *"We scope the search to the robot's active zone. To scale further, we can cache bin coordinates in a Redis spatial index (`GEOADD`) and use Redis (`GEORADIUS`) to perform the proximity calculations in $O(\log N)$ time, offloading the calculations from the database."*

### 4. Managing High-Volume Writes with Partitioning
* **The Design Choice**: We partition the `observations` table monthly on the `observed_at` column.
* **The Tradeoff**: This adds complexity to queries that span multiple months.
* **Defense**: *"Robots generate millions of scans daily. Partitioning prevents index degradation and ensures write performance remains stable. It also allows us to drop old data instantly using `DROP TABLE` on old partition tables, avoiding the performance impact of large `DELETE` operations."*

## 10. SYSTEM CONFIGURATION & ENVIRONMENT REFERENCE

To run this platform in staging or production, a set of keys must be configured across the environment, specifying how components locate services, verify permissions, and authenticate database connections.

### Common Configuration Variables
* **`DATABASE_URL`**: Used by services to connect to PostgreSQL.
  * *Purpose*: Defines database credentials (username, password, host, port, database name).
  * *Production Value*: E.g., `postgresql+asyncpg://app_user:secure_pwd@postgres-cluster.local:5432/warehouse_db`.
* **`REDIS_URL`**: Points to the Redis cache cluster.
  * *Purpose*: Holds transient telemetry caches, token blocklists, and coordinates Redis Pub/Sub channels.
  * *Production Value*: E.g., `redis://:redis_pass@redis-sentinel.local:6379/0`.
* **`KAFKA_BOOTSTRAP_SERVERS`**: Identifies broker node addresses.
  * *Purpose*: Sets the entry point where Python `event-bus` scripts fetch cluster metadata and establish partitions.
  * *Production Value*: E.g., `kafka-node-1.local:9092,kafka-node-2.local:9092`.
* **`JWT_SECRET_KEY`**: Signed payload validation token.
  * *Purpose*: Ensures JWT claims issued by the auth service cannot be spoofed or modified.
  * *Production Value*: High-entropy hexadecimal string (e.g., 256-bit key).
* **`MFA_SECRET_KEY`**: Decrypts TOTP secrets in the database.
  * *Purpose*: Prevents access to TOTP tokens if the raw database records are compromised.
* **`MINIO_ENDPOINT` / `S3_BUCKET_NAME`**: Image payload parameters.
  * *Purpose*: Sets the network paths and folder buckets where robot camera frames are archived.
* **`SMTP_HOST` / `SMTP_PORT`**: SMTP connection variables.
  * *Purpose*: Sets SMTP credentials and parameters for dispatching email notifications.

## 11. DETAILED EXPLANATION OF MICROSERVICE CODES & LOGIC FLOWS

In this section, we analyze the operational workflows of the microservices, walking through the logic of how data travels through the codebase step-by-step.

### 1. The Observation Ingestion Logic
The `observation-service` receives raw scan requests from robots. The request path is handled as follows:
* **FastAPI Router Reception**: The POST endpoint receives a JSON payload representing a scan observation, along with a base64 encoded string of the camera frame.
* **Security Decryption**: The service's security middleware reads the HTTP authorization headers, validates the signature of the robot's JWT, and extracts the claims (e.g., confirming the serial number matches the active robot database registry).
* **MinIO Object Upload**: The service decodes the base64 string into raw binary bytes. It builds a unique file name using the pattern `warehouse-id/robot-id/observation-id.jpg` and uploads the image to the configured MinIO S3 bucket.
* **Transactional DB Outbox Commit**: The service opens an asynchronous database transaction. It writes the metadata of the observation (coordinates, SKU decoded, blur score, and image URL) to the partitioned `observations` table. Concurrently, it writes an event envelope into the `outbox_events` table. Once both writes are ready, it commits the transaction. This guarantees that no event is lost even if the Kafka brokers fail.
* **Async Outbox Polling**: A background task polls the `outbox_events` table for records marked as `PENDING`. It serializes them and publishes them to the Kafka broker under the topic `observation.raw`. Once Kafka acknowledges receipt, the task updates the outbox record status to `PROCESSED`.

### 2. The Verification Comparison Logic
The `reconciliation-service` acts as the audit brain of the warehouse:
* **Kafka Consumer Loop**: The service runs a persistent consumer loop. When an event is published to `observation.raw`, the consumer extracts the payload.
* **Database Session Allocation**: The consumer starts an async database session and queries the `inventory` table for the target `bin_id`.
* **Discrepancy Evaluation**:
  * If the bin is supposed to be empty but the robot scans an item: The service searches the database for that SKU. If the SKU is found in another bin, the result is flagged as `MISPLACED`, recording the item's expected bin. If the SKU is unregistered, the result is flagged as `UNKNOWN`.
  * If the bin is supposed to contain items but the robot detects nothing: The engine records a result of `MISSING`.
  * If the SKU matches but the counts differ: The engine records a `QUANTITY_DISCREPANCY`.
  * If the SKU and counts match expectations: The engine records a `CORRECT_PLACEMENT`.
* **Event Dispatching**: If a discrepancy is found, the engine writes an alert record to the database and publishes an `InventoryMismatchDetected` event to Kafka. If the placement is correct, it publishes an `InventoryVerified` event.

### 3. Real-Time Telemetry and State Streaming
The `digital-twin-sync` service processes incoming Kafka events and streams them to the dashboard:
* **Kafka Telemetry Consumer**: A background loop consumes events from `robot.telemetry.heartbeat`, `inventory.reconciliation.mismatch`, and `inventory.reconciliation.verified`.
* **State Updates**: When a heartbeat is received, the consumer parses the coordinates and updates the robot's state in Redis. The Redis hash is updated with a TTL (e.g., 30 seconds) so that if a robot goes offline, its state expires and it disappears from the map.
* **Redis Pub/Sub Sync**: The service publishes a state update to a Redis Pub/Sub channel. The WebSocket server instances subscribe to these channels and relay the updates to the Socket.IO rooms matching the warehouse ID, fanning out the data to all connected browser clients.

## 12. STEP-BY-STEP PLATFORM EXECUTION WALKTHROUGH

This walkthrough traces how data flows through the system during a typical audit run:

1. **System Initialization**:
   An operator starts the platform by running `make up`. Docker Compose starts the infrastructure containers (PostgreSQL, Kafka, Redis, MinIO) and the microservices.
2. **Topology Seeding**:
   The database is seeded with a default warehouse (WH-001) containing layout data and 3D bin coordinates. The WMS catalog is seeded with active SKUs, and expected inventories are assigned to bins.
3. **Mission Scheduling**:
   A manager logs into the dashboard, navigates to the Mission Control panel, and schedules an audit mission for Zone A. The dashboard makes a POST request to the mission service, which writes the mission record to PostgreSQL.
4. **Robot Deployment**:
   An idle robot checks the mission service (`GET /api/v1/robots/robot-001/next-task`). It retrieves the assigned mission, loads the coordinate waypoints, and updates its status to `AUDITING`.
5. **Scanning Shelf Bins**:
   The robot drives down Aisle 1. Its camera scans a shelf bin and decodes a QR code. The robot's edge agent generates an observation payload containing the decoded SKU, physical coordinates, and camera frame.
6. **Sending the Observation**:
   The edge agent attempts to POST the scan to the observation service. If the robot loses WiFi connection, it saves the payload to its local SQLite database. Once the connection is restored, it uploads the buffered scans in a batch to the backend.
7. **Ingesting and Archiving**:
   The observation service uploads the camera frame to MinIO and writes the observation and outbox records to PostgreSQL within a single transaction. The outbox worker publishes the event to Kafka under the topic `observation.raw`.
8. **Reconciling the Scan**:
   The reconciliation service consumes the raw observation event. It queries the topology service to resolve the coordinates to a bin and compares the scanned SKU against the WMS expectations.
9. **Highlighting Discrepancies**:
   Finding a mismatch (e.g., an item is in Bin 1 instead of Bin 10), the reconciliation service writes an alert record and publishes a mismatch event to Kafka.
10. **Twin Updates**:
    The twin sync service consumes the mismatch event, updates the bin status in Redis, and publishes the update to Redis Pub/Sub. The Socket.IO server receives the update and emits it to the React dashboard.
11. **Operator Alert**:
    The dashboard updates its Zustand store, and the SVG map highlights the mismatched bin in red. Simultaneously, the alerting service detects the critical mismatch and dispatches an email notification to the assigned operator.
12. **Mission Completion**:
    Once the robot scans all target bins, it reports the mission as completed. The mission service updates the database record, and the robot returns to its charging station.

## 13. COMPREHENSIVE DIRECTORY AND SERVICE ROLES MATRIX

To ensure you can confidently explain the relationship between every single folder, database table, and service in an interview, this section details the system-wide dependencies and interfaces.

### Service Endpoint Definitions and Interfaces
Here is a plain-English layout of the primary endpoints that power the system:

#### 1. Auth Service Interfaces (Port 8000)
* **`POST /api/v1/auth/register`**: Creates a new user record in PostgreSQL with role permissions.
* **`POST /api/v1/auth/login`**: Verifies password hashes and generates a temporary session, prompting for MFA if enabled.
* **`POST /api/v1/auth/mfa/setup`**: Generates a TOTP key and outputs a QR barcode link.
* **`POST /api/v1/auth/mfa/verify`**: Validates the 6-digit passcode against the TOTP time windows and issues the active JWT.
* **`POST /api/v1/auth/refresh`**: Decodes a refresh token, checks the Redis blocklist to prevent replay attacks, and issues a new token pair.
* **`POST /api/v1/auth/logout`**: Revokes the active session and blocklists the refresh token.

#### 2. Topology Service Interfaces (Port 8001)
* **`GET /api/v1/warehouses`**: Returns a list of active warehouses.
* **`POST /api/v1/warehouses`**: Registers a new warehouse in PostgreSQL.
* **`GET /api/v1/warehouses/{id}/topology`**: Returns the nested spatial layout tree (Zones, Aisles, Racks, Shelves, Bins).
* **`POST /api/v1/bins/resolve`**: Performs Euclidean coordinate resolution calculations to map spatial parameters to a physical bin.

#### 3. Mission Service Interfaces (Port 8002)
* **`POST /api/v1/missions`**: Schedules a new audit route for a target robot and zone.
* **`GET /api/v1/robots/{id}/next-task`**: Returns the next assigned audit mission for a robot.
* **`POST /api/v1/robots/{id}/heartbeat`**: Updates the robot's coordinates, battery percentage, and status in PostgreSQL, refreshing the watchdog timer.
* **`POST /api/v1/missions/{id}/status`**: Updates mission states (e.g., `IN_PROGRESS` or `COMPLETED`).

#### 4. Observation Service Interfaces (Port 8003)
* **`POST /api/v1/observations`**: Ingests raw scan observations, archives frames in MinIO, and commits transaction records to PostgreSQL.
* **`POST /api/v1/observations/batch`**: Bulk uploads buffered observations captured during network dropouts.

#### 5. Reconciliation Service Interfaces (Port 8004)
* **`GET /api/v1/reconciliation/results`**: Retrieves historical audit logs and mismatch records.
* **`GET /api/v1/alerts`**: Retrieves active inventory alerts.

#### 6. Alerting Service Interfaces (Port 8005)
* **`GET /api/v1/preferences/{user_id}`**: Retrieves operator notification preferences.
* **`PUT /api/v1/preferences/{user_id}`**: Updates notification preferences.
* **`POST /api/v1/preferences/dispatch`**: Dispatches alert updates.

## 14. EVENT AND DATA ENVELOPE CONFIGURATIONS

To allow the platform to scale, Kafka uses partitioned topics, distributing messages across multiple brokers.

### Topics Schema Layout
* **`robot.telemetry.heartbeat`**: Broadcasts robot status and location updates (coordinates, battery, status).
* **`mission.lifecycle`**: Emits mission state transitions.
* **`observation.raw`**: Pipes raw scan observations from the edge.
* **`inventory.reconciliation.mismatch`**: Emits discrepancy details (missing items, misplaced stock).
* **`inventory.reconciliation.verified`**: Emits verified item records.
* **`alert.lifecycle`**: Broadcasts operator dispatch notifications.

### Message Serialization Flow
To optimize network performance, event payloads are structured as compact JSON objects:
1. **Metadata Wrapper**: Wraps the payload with an event ID, originating service, event type, and UTC timestamp.
2. **Payload Fields**: Contains the structured details of the event.
3. **Partition Keys**: Assigns a partition key (such as the warehouse ID) to ensure that all events for a given warehouse are processed in chronological order on the same Kafka partition.

## 15. COMPREHENSIVE SECURITY ATTACK VECTOR ANALYSIS

To build an industrial-grade system, security must be assessed across multiple layers of authentication, authorization, and network isolation. This section documents potential security vulnerabilities and the built-in defenses that prevent system compromise.

### 1. Token Theft and Replay Attacks (Session Hijacking)
* **Threat**: If an attacker steals a user's JWT or refresh token from a compromised browser client, they can access API endpoints and query sensitive inventory records.
* **Mitigation**: 
  - **Short-lived Access Tokens**: JWTs expire after 60 minutes, limiting the window of opportunity for stolen tokens.
  - **Refresh Token Rotation (RTR)**: When the client uses a refresh token to request a new access token, the auth service revokes the old refresh token and stores it in a Redis blocklist. If the same refresh token is presented again (indicating a replay attack), the system revokes all active sessions for that user, rendering the attacker's tokens useless.
  - **Secure Storage**: Access and refresh tokens are stored in `HttpOnly` and `Secure` cookies with a `SameSite=Strict` flag. This prevents JavaScript from accessing the tokens, protecting them against Cross-Site Scripting (XSS) attacks.

### 2. Password Database Compromise
* **Threat**: An attacker gains access to the PostgreSQL database records and attempts to extract user credentials.
* **Mitigation**: 
  - **Bcrypt Hashing**: Passwords are never stored in plaintext. They are hashed using Bcrypt with a work factor of 12. Bcrypt incorporates a unique salt for each password, protecting them against rainbow table lookups and brute-force cracking.
  - **MFA Secret Encryption**: Multi-Factor Authentication TOTP keys are encrypted with an environment-level key (`MFA_SECRET_KEY`) before being saved in PostgreSQL. Even if the database records are leaked, the attacker cannot generate valid TOTP codes without the master key.

### 3. Edge Sensor Device Spoofing
* **Threat**: An attacker connects a rogue hardware node to the warehouse network and attempts to inject false observations or telemetry.
* **Mitigation**: 
  - **Device Certificates**: Robots must authenticate using asymmetric client TLS certificates before accessing the edge endpoints.
  - **Role-Based Access Control**: Robot agents are assigned a restricted role (`ROBOT_AGENT`) that only permits write operations to `observations:write` and `robots:write`. They cannot query user tables, read database audit logs, or schedule audit missions.

### 4. Denial of Service (DoS) via Event Flooding
* **Threat**: A rogue device or a malfunctioning camera floods the ingestion service with duplicate scan events, overloading the database and message broker.
* **Mitigation**: 
  - **Idempotency Verification**: The `observation-service` uses Redis to store unique `observation_id` keys (`SET EX NX`) with a 5-minute expiration. If an event with a duplicate ID is received within this window, the service discards it immediately.
  - **Rate Limiting**: Nginx or an API Gateway rates limits requests on the `/api/v1/observations` routes, preventing any single device index from saturating the backend.

## 16. FAULT TOLERANCE & DISASTER RECOVERY PROTOCOLS

This section outlines how the platform handles unexpected infrastructure failures to ensure eventual consistency.

### 1. Database Connection Losses
* **Behavior**: If the PostgreSQL cluster goes offline, microservices will fail to write transactions.
* **Fault Handling**: The transactional database connection pool is configured with automatic reconnect wrappers. If a connection drops, SQLAlchemy discards the stale sockets and attempts to establish new sessions.
* **Data Recovery**: The OpenCV edge agent on the robots caches observations locally in SQLite. The agent pings the heartbeat endpoint and drains the local buffer once connection is restored, ensuring no scan data is lost.

### 2. Kafka Cluster Broker Outages
* **Behavior**: Services cannot publish event envelopes to Kafka.
* **Fault Handling**: Publishers use the `tenacity` library to retry operations. If the brokers remain offline, the outbox publisher pauses. Once the Kafka cluster comes back online, the publisher resumes polling the database outbox table, ensuring all events are processed in chronological order.

### 3. Redis Cache Eviction
* **Behavior**: Redis runs out of memory and evicts cached topology data or telemetry hashes.
* **Fault Handling**: Cache queries use the Cache-Aside pattern. If a Redis query returns a cache miss, the service queries the database and updates the cache. This ensures the system remains operational, albeit with a temporary increase in latency.

## 17. DETAILED ROLES MATRIX OF DATABASE TABLES

To facilitate deep database reviews, this section outlines the design constraints, indices, and roles of the PostgreSQL database tables.

### 1. The `warehouses` Table
* **Role**: The root of the layout tree. Holds physical warehouse records.
* **Columns**:
  - `id` (UUID): Primary key.
  - `code` (VARCHAR): Unique code (e.g. WH-001) for human indexing.
  - `name` (VARCHAR): Friendly name.
  - `total_area_sqm` (NUMERIC): Dimension metrics.
  - `timezone` (VARCHAR): Controls scheduled time execution ranges.
  - `created_at` / `updated_at`: Standard timestamp trackers.

### 2. The `zones` Table
* **Role**: Defines zone storage types (e.g., COLD, HAZMAT, BULK).
* **Columns**:
  - `id` (UUID): Primary key.
  - `warehouse_id` (UUID): Foreign key linked to `warehouses(id)`.
  - `code` (VARCHAR): Unique zone suffix code.
  - `zone_type` (VARCHAR): Category descriptor.
  - **Constraint**: Unique index on `(warehouse_id, code)` to prevent duplicates.

### 3. The `aisles` Table
* **Role**: Houses aisle pathways.
* **Columns**:
  - `id` (UUID): Primary key.
  - `zone_id` (UUID): Foreign key linked to `zones(id)`.
  - `code` (VARCHAR): Aisle designator.
  - `start_coord_x` / `start_coord_y` / `end_coord_x` / `end_coord_y`: Start and end points of the aisle segment.

### 4. The `racks` Table
* **Role**: Defines steel rack placements.
* **Columns**:
  - `id` (UUID): Primary key.
  - `aisle_id` (UUID): Foreign key linked to `aisles(id)`.
  - `code` (VARCHAR): Unique rack code.
  - `coord_x` / `coord_y` / `coord_z`: Proximity centroids.

### 5. The `shelves` Table
* **Role**: Defines vertical tiers on racks.
* **Columns**:
  - `id` (UUID): Primary key.
  - `rack_id` (UUID): Foreign key linked to `racks(id)`.
  - `level_number` (INT): Shelf tier level index (1 to N).
  - **Constraint**: Unique index on `(rack_id, level_number)`.

### 6. The `bins` Table
* **Role**: The final physical addresses for products.
* **Columns**:
  - `id` (UUID): Primary key.
  - `shelf_id` (UUID): Foreign key linked to `shelves(id)`.
  - `code` (VARCHAR): Unique physical bin address.
  - `coord_x` / `coord_y` / `coord_z`: 3D centroids.
  - `qr_code` (VARCHAR): Barcode value.

### 7. The `products` Table
* **Role**: Master inventory catalog.
* **Columns**:
  - `sku` (VARCHAR): Unique primary key.
  - `name` / `description` / `category` / `brand`: Details.
  - `weight_kg` / `length_cm` / `width_cm` / `height_cm`: Dimensions.

### 8. The `inventory` Table
* **Role**: WMS expected inventory records.
* **Columns**:
  - `id` (UUID): Primary key.
  - `bin_id` (UUID): Foreign key linked to `bins(id)`.
  - `sku` (VARCHAR): Foreign key linked to `products(sku)`.
  - `expected_qty` (INT): Expected quantity of the product.
  - **Constraint**: Unique index on `(bin_id, sku)` to prevent duplicate listings.

### 9. The `robots` Table
* **Role**: Tracks active robot status.
* **Columns**:
  - `id` (UUID): Primary key.
  - `serial_number` (VARCHAR): Unique physical serial number.
  - `status` (ROBOT_STATUS): E.g., `IDLE`, `AUDITING`, `OFFLINE`.
  - `battery_pct` (NUMERIC): Current battery.
  - `current_coord_x` / `current_coord_y` / `current_coord_z`: Current coordinates.

### 10. The `missions` Table
* **Role**: Tracks audit routes.
* **Columns**:
  - `id` (UUID): Primary key.
  - `warehouse_id` (UUID): Foreign key linked to `warehouses(id)`.
  - `robot_id` (UUID): Foreign key linked to `robots(id)`.
  - `status` (MISSION_STATUS): E.g., `SCHEDULED`, `IN_PROGRESS`, `COMPLETED`.

### 11. The `observations` Table
* **Role**: Monthly-partitioned physical scans table.
* **Columns**:
  - `id` (UUID): Primary key part.
  - `observed_at` (TIMESTAMPTZ): Partition range key.
  - `bin_id` (UUID): Reference to the resolved bin.
  - `decoded_qr` (VARCHAR): Scanned SKU value.
  - `frame_blur_score` (NUMERIC): Sharpness score.
  - `robot_coord_x` / `robot_coord_y` / `robot_coord_z`: Physical scan location coordinates.

### 12. The `reconciliation_results` Table
* **Role**: Discrepancy comparison logs.
* **Columns**:
  - `id` (UUID): Primary key.
  - `observation_id` (UUID): Linked raw observation.
  - `result_type` (MISMATCH_TYPE): E.g., `MISPLACED`, `MISSING`, `CORRECT_PLACEMENT`.
  - `expected_sku` / `observed_sku` / `expected_qty` / `observed_qty`: Discrepancy values.

### 13. The `alerts` Table
* **Role**: Active inventory alerts.
* **Columns**:
  - `id` (UUID): Primary key.
  - `reconciliation_id` (UUID): Reference to the discrepancy.
  - `status` (ALERT_STATUS): E.g., `OPEN`, `ACKNOWLEDGED`, `RESOLVED`.
  - `severity` (ALERT_SEVERITY): E.g., `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`.
  - `title` / `description`: Operator details.

### 14. The `outbox_events` Table
* **Role**: Transactional outbox log.
* **Columns**:
  - `id` (UUID): Primary key.
  - `topic` (VARCHAR): Destination Kafka topic.
  - `payload` (JSONB): Message data.
  - `status` (VARCHAR): E.g., `PENDING`, `PROCESSED`, `FAILED`.

## 18. ENTIRE SYSTEM CONFIGURATION ENVIRONMENT VALUES

This section documents all environment variables required to run the platform.

### Microservices Common Settings

* **`DATABASE_URL`**: E.g., `postgresql+asyncpg://app_user:secure_pwd@postgres-cluster.local:5432/warehouse_db`. Used by SQLAlchemy to connect to the PostgreSQL cluster.
* **`REDIS_URL`**: E.g., `redis://:redis_pass@redis-sentinel.local:6379/0`. Used for session storage and WebSocket pub/sub channels.
* **`KAFKA_BOOTSTRAP_SERVERS`**: E.g., `kafka-node-1.local:9092,kafka-node-2.local:9092`. Used by the `event-bus` library to locate the Kafka cluster.
* **`JWT_SECRET_KEY`**: High-entropy secret key used to sign JWTs.
* **`MFA_SECRET_KEY`**: Secret key used to encrypt TOTP keys in the database.
* **`MINIO_ENDPOINT`**: Endpoint of the MinIO object store.
* **`SMTP_HOST` / `SMTP_PORT`**: Credentials for sending email alerts.

## 19. SYSTEM DATA LIFECYCLE & CLEANUP STRATEGIES

With robots generating millions of scans daily, a robust data lifecycle strategy is required to maintain system performance.

### 1. Partition Pruning and Table Dropping
The `observations` table is partitioned monthly. To archive or delete historical observations (e.g., observations older than 90 days), the system drops old partition tables (e.g., `DROP TABLE observations_2026_04`). This is a metadata-only operation, avoiding the table locks and slow transaction logs of large `DELETE` queries.

### 2. Redis Telemetry TTLs
Telemetry data (like robot coordinates and battery percentages) is cached in Redis with a short TTL (e.g., 30 seconds). If a robot goes offline, its state expires naturally, keeping the Redis cache clean and preventing the dashboard from displaying stale data.

### 3. MinIO Lifecycle Policies
Raw camera frames are uploaded to MinIO buckets. An S3 lifecycle policy automatically transitions images older than 30 days to cold storage, and deletes them after 90 days, keeping storage costs low.

## 20. DEEP DIVE ON FRONTEND ROUTING, ZUSTAND, AND WEBSOCKET INTERACTION

To ensure that someone building this system from scratch can construct the exact React operator control panel, we detail the client-side state transitions, store variables, and event handlers.

### 1. Zustand Client Stores
The dashboard manages state globally using three lightweight, hook-based stores:
* **`authStore`**: Manages user sessions, tokens, and role validation.
  - *State Variables*: `user` (details like ID, role, authorized warehouses), `token` (current JWT), `isAuthenticated` (boolean status), `mfaRequired` (boolean flag).
  - *Actions*: `login(credentials)` (calls auth API, handles MFA redirects, sets token), `verifyMfa(code)` (submits TOTP code, receives final JWT), `logout()` (clears token, resets state, redirects to login).
* **`useTwinStore`**: Manages the real-time digital twin representation.
  - *State Variables*: `robotPositions` (ES6 Map storing robot IDs to coordinates, speed, battery), `binStates` (ES6 Map storing bin IDs to physical SKU values, counts, mismatch flags), `warehouseId` (current warehouse context).
  - *Actions*: `setSnapshot(snapshot)` (populates maps on room entry), `updateRobotPosition(telemetry)` (updates target robot coordinates in the map), `updateBinState(bin)` (modifies bin status when verification events occur).
* **`useAppStore`**: Handles UI state.
  - *State Variables*: `sidebarOpen` (boolean navigation toggle), `activeNotifications` (array of unread mismatch toasts), `wsConnected` (boolean WebSocket status).
  - *Actions*: `setWsConnected(status)` (updates WebSocket indicator), `addNotification(toast)` (adds alert message, increments badge count).

### 2. WebSocket Sync Hook Lifecycle (`useWebSocket.ts`)
The custom hook manages the live Socket.IO connection to the `digital-twin-sync` gateway on port `8006`:
1. **Connection**: Establishes a persistent Socket.IO connection. If the connection fails, it schedules an exponential backoff reconnect timer (capped at 30 seconds).
2. **Room Registration**: Once connected, it emits `join_warehouse` with the active warehouse ID. The server routes the socket connection to the corresponding room and sends a full `warehouse_snapshot` payload to initialize the client maps.
3. **Event Listening**: Listens for `robot_position_update` (updating robot coordinates in the twin store) and `bin_state_update` (updating cell status to verified or mismatch).
4. **Cleanup**: When the component unmounts, the hook closes the connection and removes event listeners to prevent memory leaks.

### 3. SVG Layout Maps Rendering
The digital twin renders the warehouse layout using SVGs, which are responsive and CSS-stylable:
* **Grid Projection**: 3D bin coordinates `(x, y, z)` are scaled to 2D canvas coordinates `(X, Y)`. Racks are rendered as rectangle elements grouped by zones.
* **Interactive Cells**: Bin rectangles are styled using classes that update dynamically based on the state in the Zustand store (e.g., green for verified, red for mismatch). Clicking a cell opens a detail panel showing WMS expected values and scan frames.
* **Robot Markers**: Robots are rendered as circles with pulsing keyframe animations. The coordinates update in real time as the robot travels along waypoints.

## 21. ROBOT SIMULATION MECHANICS AND NAVIGATION LOGIC

The simulator mimics a fleet of autonomous auditing robots moving through the warehouse.

### 1. Navigation Interpolation
The simulator models physical robot movement by interpolating coordinates along target waypoints:
* **Mission Retrieval**: The robot polls the mission service for tasks (`GET /api/v1/robots/{id}/next-task`). If a task is assigned, it retrieves the routing waypoints (e.g., Bin 1 to Bin 20).
* **Path Planning**: The coordinates of the target bins are extracted from the topology cache.
* **Movement Simulation**: The robot moves along the path by incrementing its coordinates at a configured speed (e.g., 1.2 m/s). It calculates the step distance:
  $$\Delta x = v \cdot \Delta t \cdot \cos(\theta), \quad \Delta y = v \cdot \Delta t \cdot \sin(\theta)$$
  where $v$ is velocity and $\theta$ is heading angle.
* **Telemetry heartbeats**: During movement, the robot sends heartbeats at 1Hz (`POST /api/v1/robots/{id}/heartbeat`), reporting its coordinates, heading angle, battery level, and status (`AUDITING`).

### 2. Barcode Scanning and Scan Noise Simulation
When the robot reaches a target bin, it captures a simulated scan:
* **Image Capture**: The robot generates a simulated image payload.
* **Blur Calculation**: To simulate motion blur, the simulator calculates a random blur score. If the score falls below a threshold (simulating a fast-moving robot), the image is marked as blurry, preventing barcode decoding.
* **Barcode Decode Simulation**: The simulator generates a decoded SKU value. It randomly injects errors, such as barcode decode failures (simulating damaged labels) or incorrect SKUs (simulating misplaced inventory).
* **Observation Ingestion**: The observation payload is POSTed to the observation service on port 8003.

### 3. Offline Buffering for WiFi Dropouts
In large steel-reinforced warehouses, robots frequently experience WiFi dropouts. The simulator uses a local SQLite database (`buffer_{robot_id}.db`) to cache scans when offline:
* **Offline Detection**: If a heartbeat or scan POST fails with a connection timeout, the robot switches to offline mode.
* **Local Buffering**: Observations are serialized and saved to the SQLite table.
* **Reconnection Sync**: The robot continue pining the heartbeat endpoint. Once a ping succeeds, the robot drains the SQLite database, uploading buffered scans in batches of 10 to `/api/v1/observations/batch`. On a successful response, the local rows are deleted, ensuring no data loss.

## 22. KAFKA CONDUIT AND CONSUMER LOOP DETAILS

The event bus standardizes event serialization and routes messages across the cluster.

### 1. Consumer Group Processing
Microservices run as part of Kafka consumer groups to distribute the processing load:
* **Partitions**: Kafka topics (like `observation.raw`) are split into partitions.
* **Consumer Group ID**: Instances of the `reconciliation-service` share a consumer group ID. Each instance is assigned a subset of partitions, allowing them to process observations in parallel.
* **Rebalancing**: If a reconciliation instance crashes, Kafka detects the heartbeat failure and reassigns its partitions to the remaining instances, preventing data loss.

### 2. Offset Commit Policies
To prevent duplicate processing or data loss, the event bus handles commits manually:
* **Manual Offsets**: Auto-commit is disabled (`enable.auto.commit = False`).
* **At-Least-Once Processing**: The consumer loops poll a batch of events, process them, and commit offsets only after database transactions are complete.
* **Idempotency**: Since manual commits can lead to duplicate events if a service restarts during processing, downstream services use Redis idempotency keys (`SET EX NX`) to discard duplicate messages.

## 23. COMPREHENSIVE ENDPOINT API CATALOG

This section documents the JSON schemas, authorization requirements, and execution processes for every microservice REST route.

### 1. `POST /api/v1/auth/register`
* **Purpose**: Registers a new dashboard user or robot credential.
* **Headers**: None.
* **Request Body**:
  ```json
  {
    "username": "operator_john",
    "password": "Password123!",
    "role": "OPERATOR",
    "warehouse_ids": ["c29b6348-12c8-472e-8b1e-2cb039d91f25"]
  }
  ```
* **Execution Flow**:
  1. Hashes password using Bcrypt.
  2. Commits record to `users` table.
  3. Returns `201 Created` status with user metadata.

### 2. `POST /api/v1/auth/login`
* **Purpose**: Performs primary authentication.
* **Request Body**:
  ```json
  {
    "username": "operator_john",
    "password": "Password123!"
  }
  ```
* **Response (MFA Enabled)**:
  ```json
  {
    "status": "MFA_REQUIRED",
    "mfa_token": "a4d8ef29b8c34..."
  }
  ```

### 3. `POST /api/v1/auth/mfa/verify`
* **Purpose**: Verifies TOTP code and returns final access token.
* **Request Body**:
  ```json
  {
    "mfa_token": "a4d8ef29b8c34...",
    "code": "123456"
  }
  ```
* **Response**:
  ```json
  {
    "access_token": "eyJhbGciOiJIUzI1Ni...",
    "refresh_token": "d8f3b29c-a2b8...",
    "expires_in": 3600
  }
  ```

### 4. `POST /api/v1/bins/resolve`
* **Purpose**: Resolves spatial coordinates to a physical bin.
* **Headers**: `Authorization: Bearer <JWT>`
* **Request Body**:
  ```json
  {
    "warehouse_id": "c29b6348-12c8-472e-8b1e-2cb039d91f25",
    "coord_x": 12.34,
    "coord_y": 5.67,
    "coord_z": 1.20
  }
  ```
* **Response**:
  ```json
  {
    "bin_id": "e2f8c293-1b9c-482f-8a2e-4b2b93cf258e",
    "code": "BIN-A-12-3",
    "distance": 0.12
  }
  ```

### 5. `POST /api/v1/observations`
* **Purpose**: Ingests physical scans.
* **Request Body**:
  ```json
  {
    "observation_id": "f8c2839d-b8c2-482e-9d2c-cb0f23d9a12b",
    "robot_id": "3b2a8d1c-29b8-4c3e-8e1f-4b2f3d8a1c2e",
    "coord_x": 12.34,
    "coord_y": 5.67,
    "coord_z": 1.20,
    "barcode_data": "SKU-998877",
    "image_base64": "iVBORw0KGgoAAAANS..."
  }
  ```
* **Response**:
  ```json
  {
    "status": "ACCEPTED",
    "observation_id": "f8c2839d-b8c2-482e-9d2c-cb0f23d9a12b"
  }
  ```

## 23. COMPREHENSIVE ENDPOINT API CATALOG - EXTENDED

This section contains definitions for the remaining microservice endpoints.

### 6. `POST /api/v1/observations/batch`
* **Purpose**: Ingests multiple buffered observations from an offline robot.
* **Headers**: `Authorization: Bearer <JWT>`
* **Request Body**:
  ```json
  [
    {
      "observation_id": "f8c2839d-b8c2-482e-9d2c-cb0f23d9a12b",
      "robot_id": "3b2a8d1c-29b8-4c3e-8e1f-4b2f3d8a1c2e",
      "coord_x": 12.34,
      "coord_y": 5.67,
      "coord_z": 1.20,
      "barcode_data": "SKU-998877",
      "image_base64": "iVBORw0KGgoAAAANS..."
    }
  ]
  ```
* **Response**:
  ```json
  {
    "status": "PROCESSED",
    "count": 1
  }
  ```

### 7. `GET /api/v1/warehouses`
* **Purpose**: Retrieves all registered warehouses.
* **Headers**: `Authorization: Bearer <JWT>`
* **Response**:
  ```json
  [
    {
      "id": "c29b6348-12c8-472e-8b1e-2cb039d91f25",
      "code": "WH-001",
      "name": "Central distribution center",
      "total_area_sqm": 50000.0,
      "timezone": "America/New_York"
    }
  ]
  ```

### 8. `GET /api/v1/warehouses/{id}/topology`
* **Purpose**: Retrieves the hierarchical spatial topology tree of a warehouse.
* **Headers**: `Authorization: Bearer <JWT>`
* **Response**:
  ```json
  {
    "warehouse_id": "c29b6348-12c8-472e-8b1e-2cb039d91f25",
    "zones": [
      {
        "zone_id": "z1...",
        "code": "ZONE-A",
        "zone_type": "BULK",
        "aisles": [
          {
            "aisle_id": "a1...",
            "code": "AISLE-12",
            "racks": []
          }
        ]
      }
    ]
  }
  ```

### 9. `POST /api/v1/missions`
* **Purpose**: Schedules a new audit mission.
* **Headers**: `Authorization: Bearer <JWT>`
* **Request Body**:
  ```json
  {
    "warehouse_id": "c29b6348-12c8-472e-8b1e-2cb039d91f25",
    "robot_id": "3b2a8d1c-29b8-4c3e-8e1f-4b2f3d8a1c2e",
    "target_zone_id": "z1..."
  }
  ```
* **Response**:
  ```json
  {
    "mission_id": "m123b32a-d8c9...",
    "status": "SCHEDULED"
  }
  ```

### 10. `GET /api/v1/robots/{id}/next-task`
* **Purpose**: Allows robots to pull their next assigned mission.
* **Headers**: `Authorization: Bearer <JWT>`
* **Response**:
  ```json
  {
    "mission_id": "m123b32a-d8c9...",
    "warehouse_id": "c29b6348-12c8-472e-8b1e-2cb039d91f25",
    "waypoints": [
      {
        "x": 12.34,
        "y": 5.67,
        "z": 1.20
      }
    ]
  }
  ```

### 11. `POST /api/v1/robots/{id}/heartbeat`
* **Purpose**: Receives coordinate and status updates from active robots.
* **Headers**: `Authorization: Bearer <JWT>`
* **Request Body**:
  ```json
  {
    "coord_x": 14.50,
    "coord_y": 6.20,
    "coord_z": 0.00,
    "battery_pct": 85.5,
    "status": "AUDITING"
  }
  ```
* **Response**:
  ```json
  {
    "status": "OK"
  }
  ```

### 12. `GET /api/v1/reconciliation/results`
* **Purpose**: Retrieves audit reconciliation logs.
* **Headers**: `Authorization: Bearer <JWT>`
* **Query Parameters**:
  - `warehouse_id`: String (Required)
  - `result_type`: String (Optional, e.g. `MISPLACED`)
* **Response**:
  ```json
  [
    {
      "id": "r1...",
      "bin_code": "BIN-A-12-3",
      "result_type": "MISPLACED",
      "expected_sku": "SKU-111",
      "observed_sku": "SKU-222",
      "expected_qty": 5,
      "observed_qty": 5,
      "reconciled_at": "2026-07-17T14:00:00Z"
    }
  ]
  ```

## 24. JSON SCHEMA AND EVENT BUS ENVELOPES CATALOG

This section contains schemas for Kafka message payloads and digital twin state updates.

### 1. Unified Event Bus Envelope Schema
Every event sent to Kafka is structured using this schema:
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "EventEnvelope",
  "type": "OBJECT",
  "properties": {
    "event_id": { "type": "STRING", "format": "uuid" },
    "event_type": { "type": "STRING" },
    "source_service": { "type": "STRING" },
    "timestamp": { "type": "STRING", "format": "date-time" },
    "payload": { "type": "OBJECT" }
  },
  "required": ["event_id", "event_type", "source_service", "timestamp", "payload"]
}
```

### 2. Telemetry Heartbeat Event Payload (`robot.telemetry.heartbeat`)
```json
{
  "title": "TelemetryHeartbeatPayload",
  "type": "OBJECT",
  "properties": {
    "robot_id": { "type": "STRING", "format": "uuid" },
    "warehouse_id": { "type": "STRING", "format": "uuid" },
    "coordinates": {
      "type": "OBJECT",
      "properties": {
        "x": { "type": "NUMBER" },
        "y": { "type": "NUMBER" },
        "z": { "type": "NUMBER" }
      },
      "required": ["x", "y", "z"]
    },
    "battery_pct": { "type": "NUMBER", "minimum": 0, "maximum": 100 },
    "status": { "type": "STRING", "enum": ["IDLE", "AUDITING", "OFFLINE"] }
  },
  "required": ["robot_id", "warehouse_id", "coordinates", "battery_pct", "status"]
}
```

### 3. Inventory Mismatch Detected Payload (`inventory.reconciliation.mismatch`)
```json
{
  "title": "InventoryMismatchPayload",
  "type": "OBJECT",
  "properties": {
    "reconciliation_id": { "type": "STRING", "format": "uuid" },
    "warehouse_id": { "type": "STRING", "format": "uuid" },
    "bin_id": { "type": "STRING", "format": "uuid" },
    "bin_code": { "type": "STRING" },
    "discrepancy_type": { "type": "STRING", "enum": ["MISPLACED", "MISSING", "UNKNOWN", "QUANTITY_DISCREPANCY"] },
    "details": {
      "type": "OBJECT",
      "properties": {
        "expected_sku": { "type": ["STRING", "null"] },
        "observed_sku": { "type": ["STRING", "null"] },
        "expected_qty": { "type": "INTEGER" },
        "observed_qty": { "type": "INTEGER" }
      },
      "required": ["expected_sku", "observed_sku", "expected_qty", "observed_qty"]
    }
  },
  "required": ["reconciliation_id", "warehouse_id", "bin_id", "bin_code", "discrepancy_type", "details"]
}
```
