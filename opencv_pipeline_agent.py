import cv2
import numpy as np
import time
import requests
import uuid
import sys
import os
import aiosqlite
import asyncio
from datetime import datetime

# ------------------- Platform Target Settings -------------------
OBSERVATION_SERVICE_URL = "http://localhost:8003/api/v1/observations"
MISSION_SERVICE_URL = "http://localhost:8002/api/v1"
TOPOLOGY_SERVICE_URL = "http://localhost:8001/api/v1"

# ------------------- Robot Metadata -------------------
ROBOT_ID = "robot-001"
WAREHOUSE_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

class LocalSQLBuffer:
    """Local SQLite buffer to capture and store scans if WiFi disconnects."""
    def __init__(self, db_path="edge_observations.db"):
        self.db_path = db_path

    def initialize(self):
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS buffered_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                observation_id TEXT UNIQUE,
                payload TEXT,
                synced INTEGER DEFAULT 0
            )
        """)
        conn.commit()
        conn.close()

    def buffer_observation(self, obs_id: str, payload: dict):
        import sqlite3
        import json
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO buffered_observations (observation_id, payload) VALUES (?, ?)",
                (obs_id, json.dumps(payload))
            )
            conn.commit()
            conn.close()
            print(f"📁 Network offline. Observation {obs_id} saved to offline local database buffer.")
        except Exception as e:
            print(f"❌ Failed to buffer observation locally: {e}")

    def drain_buffer(self):
        """Send all cached observations to the platform once network is online."""
        import sqlite3
        import json
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, payload FROM buffered_observations WHERE synced = 0")
        rows = cursor.fetchall()
        
        if not rows:
            conn.close()
            return

        print(f"🔄 Network restored. Syncing {len(rows)} buffered observations to platform...")
        for row in rows:
            row_id = row[0]
            payload = json.loads(row[1])
            try:
                r = requests.post(OBSERVATION_SERVICE_URL, json=payload, timeout=3.0)
                if r.status_code in (200, 201):
                    cursor.execute("DELETE FROM buffered_observations WHERE id = ?", (row_id,))
            except Exception:
                # Network failed again, retry later
                break

        conn.commit()
        conn.close()


def resolve_bin_code(payload_data: str) -> str:
    """
    Parse category and location logic from your existing dictionary values.
    Transforms raw zbar QR data (e.g. '1/2/3') to a bin code.
    """
    parts = payload_data.split("/")
    if len(parts) >= 3:
        aisle = parts[0]
        rack = parts[1]
        shelf = parts[2]
        bin_num = parts[3] if len(parts) > 3 else "1"
        return f"A{aisle}-R{rack}-S{shelf}-B{bin_num}"
    return "UNKNOWN-BIN"


def test_platform_connectivity() -> bool:
    try:
        r = requests.get("http://localhost:8003/health", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def start_opencv_ingest_pipeline(camera_device_index=0):
    print("🔌 Starting OpenCV Edge Ingestion Pipeline...")
    qr_decoder = cv2.QRCodeDetector()
    buffer = LocalSQLBuffer()
    buffer.initialize()

    # OpenCV Video Capture Initialization
    cap = cv2.VideoCapture(camera_device_index)
    if not cap.isOpened():
        print(f"❌ Error: Cannot open camera stream on index {camera_device_index}")
        sys.exit(1)

    print("🎥 Video stream active. Decoded scans will feed directly to platform.")

    active_mission_id = None
    last_heartbeat_time = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("⚠️ Frame acquisition error. Retrying...")
                time.sleep(1.0)
                continue

            current_time = time.time()
            is_connected = test_platform_connectivity()

            # 1. Periodically fetch active mission and send Heartbeats
            if current_time - last_heartbeat_time > 2.0:
                last_heartbeat_time = current_time
                if is_connected:
                    # Sync any offline buffered values first
                    buffer.drain_buffer()

                    # Send heartbeat status
                    try:
                        requests.post(f"{MISSION_SERVICE_URL}/robots/{ROBOT_ID}/heartbeat", json={
                            "robot_id": ROBOT_ID,
                            "battery": 95.0,
                            "coord_x": 4.5,
                            "coord_y": 8.0,
                            "coord_z": 0.0,
                            "status": "AUDITING" if active_mission_id else "IDLE"
                        }, timeout=2.0)
                    except Exception:
                        pass

            # 2. Decode Frame
            try:
                data, bbox, _ = qr_decoder.detectAndDecode(frame)
            except Exception:
                data = ""

            if data:
                clean_payload = data.strip()
                bin_code = resolve_bin_code(clean_payload)
                
                # Mock Product SKU mapping based on category parsing
                observed_sku = f"SKU-ELEC-00{clean_payload.split('/')[0]}" if "/" in clean_payload else "SKU-ELEC-001"
                
                observation_id = str(uuid.uuid4())
                obs_payload = {
                    "observation_id": observation_id,
                    "mission_id": active_mission_id,
                    "robot_id": ROBOT_ID,
                    "warehouse_id": WAREHOUSE_ID,
                    "bin_code": bin_code,
                    "decoded_qr": observed_sku,
                    "detection_confidence": 0.95,
                    "frame_blur_score": 150.0,
                    "robot_coord_x": 4.5,
                    "robot_coord_y": 8.0,
                    "robot_coord_z": 0.0,
                    "observed_at": datetime.utcnow().isoformat()
                }

                # 3. Transmit observation payload
                if is_connected:
                    try:
                        r = requests.post(OBSERVATION_SERVICE_URL, json=obs_payload, timeout=2.0)
                        if r.status_code in (200, 201):
                            print(f"🚀 Ingested: QR code payload '{clean_payload}' resolved to {bin_code} (SKU: {observed_sku})")
                        else:
                            buffer.buffer_observation(observation_id, obs_payload)
                    except Exception:
                        buffer.buffer_observation(observation_id, obs_payload)
                else:
                    buffer.buffer_observation(observation_id, obs_payload)

                # Delay window to prevent flooding same SKU duplicate scans
                time.sleep(2.0)

            # Draw visual window
            cv2.putText(frame, "INGESTION ACTIVE", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.imshow("Platform Edge Pipeline Feed", frame)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    except KeyboardInterrupt:
        print("🛑 Edge Pipeline shut down by operator.")
    finally:
        cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    start_opencv_ingest_pipeline()
