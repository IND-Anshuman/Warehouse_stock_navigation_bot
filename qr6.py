import cv2
import numpy as np
import time
import threading
import signal
import sys
import os
from flask import Flask, jsonify, render_template_string
from datetime import datetime

# ------------------- Flask Web Server -------------------
app = Flask(__name__)
detected_data = set()
logs = []
stop_event = threading.Event()

# Trackers
active_issues = {}
resolved_issues = set()
logged_messages = set()

# ------------------- HTML Template -------------------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>📦 QR Code Dashboard</title>
<style>
    body { font-family: Arial, sans-serif; background: #101820; color: #f2f2f2; text-align: center; }
    h1 { color: #00ffcc; }
    h2 { color: #00ccff; margin-top: 30px; }
    table { margin: 20px auto; border-collapse: collapse; width: 80%; background: #1c1c1c; }
    th, td { padding: 10px 20px; border: 1px solid #333; }
    th { background: #00ffcc; color: #000; }
    tr:nth-child(even) { background: #2a2a2a; }
    .footer { margin-top: 20px; color: #888; font-size: 14px; }
    .log-box { width: 80%; margin: 20px auto; background: #151515; border: 1px solid #333; border-radius: 8px; padding: 10px; text-align: left; }
    .log-entry { margin: 5px 0; border-bottom: 1px solid #333; padding-bottom: 4px; }
    .error { color: #ff4d4d; font-weight: bold; }
    .warning { color: #ffcc00; font-weight: bold; }
    .success { color: #00ff99; }
</style>
<script>
setInterval(() => { window.location.reload(); }, 1000);
</script>
</head>
<body>
<h1>📷 QR Code Detection Dashboard</h1>

{% if data %}
<table>
<tr><th>#</th><th>Detected QR Data</th></tr>
{% for item in data %}
<tr><td>{{ loop.index }}</td><td>{{ item }}</td></tr>
{% endfor %}
</table>
{% else %}
<p>No QR codes detected yet...</p>
{% endif %}

<h2>🧾 System Logs</h2>
<div class="log-box">
{% if logs %}
{% for entry in logs[-50:] %}
    {% set style = 'success' %}
    {% if '❌' in entry or 'Unknown' in entry %}{% set style = 'error' %}
    {% elif '⚠️' in entry %}{% set style = 'warning' %}
    {% endif %}
    <div class="log-entry {{ style }}">🔹 {{ entry }}</div>
{% endfor %}
{% else %}
<p>No logs yet...</p>
{% endif %}
</div>

<div class="footer">Auto-refreshes every 1s | Press 'q' or Ctrl+C to stop</div>
</body>
</html>
"""

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE, data=sorted(list(detected_data)), logs=logs)

@app.route('/data')
def get_data():
    return jsonify(sorted(list(detected_data)))

@app.route('/logs')
def get_logs():
    return jsonify(logs)

def start_server():
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)

# ------------------- QR Code Detection -------------------
def qr_code_detector_video(camera_id):
    qrDecoder = cv2.QRCodeDetector()
    category_dict = {
        "1": "Product_A",
        "2": "Product_B",
        "3": "Product_C",
        "4": "Product_D",
        "5": "Product_E",
    }
    location_dict = {
        "1": "Shelf1-Row1",
        "2": "Shelf1-Row2",
        "3": "Shelf2-Row1",
        "4": "Shelf2-Row2",
        "5": "Shelf1-Row3",
    }
    expected_location = {
        "Product_A": "Shelf1-Row1",
        "Product_B": "Shelf1-Row2",
        "Product_C": "Shelf2-Row1",
        "Product_D": "Shelf2-Row2",
        "Product_E": "Shelf1-Row3"
    }

    while not stop_event.is_set():
        cap = cv2.VideoCapture(camera_id)
        if not cap.isOpened():
            msg = f"❌ Error: Could not open camera {camera_id}. Retrying in 3s..."
            if msg not in logged_messages:
                logs.append(msg)
                print(msg)
                logged_messages.add(msg)
            time.sleep(3)
            continue

        print(f"🚀 QR Detector started for camera {camera_id}. Press 'q' to quit.")
        cv2.namedWindow(f"QR Detector Cam {camera_id}", cv2.WINDOW_NORMAL)
        cv2.resizeWindow(f"QR Detector Cam {camera_id}", 800, 600)

        while not stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                msg = f"⚠️ Frame read error on camera {camera_id}. Reconnecting..."
                if msg not in logged_messages:
                    logs.append(msg)
                    print(msg)
                    logged_messages.add(msg)
                break

            frame = cv2.resize(frame, (800, 600))
            final_output = ""  # ✅ prevents UnboundLocalError
            data, bbox, _ = qrDecoder.detectAndDecode(frame)

            if data:
                data = data.strip()
                parts = data.split("/")
                if len(parts) >= 3:
                    category_id, product_id, location_id = parts[:3]
                    category = category_dict.get(category_id)
                    location = location_dict.get(location_id)

                    # Handle Unknowns
                    if not category:
                        key = f"unknown_cat_{category_id}_cam{camera_id}"
                        msg = f"[Cam {camera_id}] ❌ Unknown category ID {category_id}"
                        if key not in active_issues:
                            logs.append(msg)
                            print(msg)
                            active_issues[key] = time.time()
                        continue
                    if not location:
                        key = f"unknown_loc_{location_id}_cam{camera_id}"
                        msg = f"[Cam {camera_id}] ❌ Unknown location ID {location_id}"
                        if key not in active_issues:
                            logs.append(msg)
                            print(msg)
                            active_issues[key] = time.time()
                        continue

                    final_output = f"Category: {category}, Product_Serial_Number: {product_id}, Location: {location}"
                    detected_data.add(final_output)

                    # Mismatch Check
                    expected_loc = expected_location.get(category)
                    issue_key = f"{category}_wrongloc_{location}_cam{camera_id}"
                    if expected_loc and location != expected_loc:
                        msg = f"[Cam {camera_id}] ⚠️ '{category}' placed at '{location}' instead of '{expected_loc}'."
                        if issue_key not in active_issues:
                            logs.append(msg)
                            print(msg)
                            active_issues[issue_key] = time.time()
                    else:
                        for key in list(active_issues.keys()):
                            if category in key and f"cam{camera_id}" in key:
                                res_msg = f"✅ [Cam {camera_id}] '{category}' correctly placed at '{location}'."
                                if key not in resolved_issues:
                                    logs.append(res_msg)
                                    print(res_msg)
                                    resolved_issues.add(key)
                                active_issues.pop(key, None)

                    # Normal decode log
                    decode_msg = f"✅ [Cam {camera_id}] Detected: {final_output}"
                    if decode_msg not in logged_messages:
                        logs.append(decode_msg)
                        print(decode_msg)
                        logged_messages.add(decode_msg)

            # --- Drawing QR box ---
            if bbox is not None:
                points = np.int32(bbox).reshape(-1, 2)
                x, y, w, h = cv2.boundingRect(points)
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

                if final_output:
                    label = final_output
                    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                    cv2.rectangle(frame, (x, y - th - 8), (x + tw + 4, y), (0, 0, 0), -1)
                    cv2.putText(frame, data, (x + 2, y - 5),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            else:
                cv2.putText(frame, "Detecting...", (30, 50),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 0), 2)

            cv2.imshow(f"QR Detector Cam {camera_id}", frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                stop_event.set()
                break

        cap.release()
        cv2.destroyWindow(f"QR Detector Cam {camera_id}")
        print(f"🛑 Camera {camera_id} closed.")
        time.sleep(2)

# ------------------- File Saving -------------------
def save_data_to_file():
    folder = "Stock"
    os.makedirs(folder, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    file = os.path.join(folder, f"qr_log_{timestamp}.txt")

    with open(file, "w", encoding="utf-8") as f:
        f.write("📦 Detected QR Data Log\n==========================\n")
        f.write(f"🕒 Saved on: {datetime.now()}\n\n")
        if not detected_data:
            f.write("No QR data detected.\n")
        else:
            for i, item in enumerate(sorted(list(detected_data)), 1):
                f.write(f"{i}. {item}\n")
    print(f"✅ Data saved → {file}")

def save_logs_to_file():
    base = "Logs"
    os.makedirs(base, exist_ok=True)
    os.makedirs(os.path.join(base, "Unresolved"), exist_ok=True)
    os.makedirs(os.path.join(base, "Resolved"), exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    unresolved = os.path.join(base, "Unresolved", f"unresolved_{timestamp}.txt")
    resolved = os.path.join(base, "Resolved", f"resolved_{timestamp}.txt")

    with open(unresolved, "w", encoding="utf-8") as f:
        f.write("🧾 Unresolved Issues\n=====================\n")
        if not active_issues:
            f.write("🎉 No unresolved issues.\n")
        else:
            for k in active_issues: f.write(f"{k}\n")

    with open(resolved, "w", encoding="utf-8") as f:
        f.write("✅ Resolved Issues\n=====================\n")
        if not resolved_issues:
            f.write("No resolved issues yet.\n")
        else:
            for k in resolved_issues: f.write(f"{k}\n")

    print(f"🧾 Logs saved → {unresolved} and {resolved}")

# ------------------- Graceful Exit -------------------
def signal_handler(sig, frame):
    print("\n🛑 Ctrl+C detected — shutting down...")
    save_data_to_file()
    save_logs_to_file()
    stop_event.set()
    cv2.destroyAllWindows()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

# ------------------- MAIN -------------------
if __name__ == "__main__":
    threading.Thread(target=start_server, daemon=True).start()

    cam1 = threading.Thread(target=qr_code_detector_video, args=(0,), daemon=True)
    #cam2 = threading.Thread(target=qr_code_detector_video, args=("http://10.23.114.109:81/stream",), daemon=True)

    cam1.start()
    #cam2.start()

    try:
        while not stop_event.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        signal_handler(None, None)
    finally:
        save_data_to_file()
        save_logs_to_file()
        print("✅ All threads stopped and data saved.")
