import cv2
import numpy as np
import time
import threading
import signal
import sys
import os
from flask import Flask, jsonify, render_template_string, Response, send_file
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

# ------------------- Live Frame Store (for web streaming) -------------------
frame_lock = threading.Lock()
latest_frames = {}  # camera_id -> latest processed frame (numpy array)

# ------------------- Map Image Path -------------------
# 👉 EDIT THIS PATH if your map image location changes
MAP_IMAGE_PATH = r"C:\Users\OMEN\OneDrive\Documents\Arduino\CameraWebServer\map.jpg"

# ------------------- HTML Template -------------------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QR·Track — Real-Time Verification System</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
    :root {
        --bg-base: #0A0E14;
        --surface: #121926;
        --surface-alt: #1A2333;
        --border: #253244;
        --text-primary: #E9EFF7;
        --text-muted: #8A9AAE;
        --accent-blue: #4C93E0;
        --accent-mint: #34C9A3;
        --accent-amber: #E3A73A;
        --accent-red: #E1615E;
        --radius: 10px;
    }

    * { box-sizing: border-box; }

    body {
        margin: 0;
        font-family: 'Inter', 'IBM Plex Sans', Arial, sans-serif;
        background: var(--bg-base);
        color: var(--text-primary);
        padding-top: 74px;
    }

    a, button { font-family: inherit; }

    /* ---------------- Header ---------------- */
    header.topbar {
        position: fixed;
        top: 0; left: 0; right: 0;
        height: 64px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0 22px;
        background: rgba(10, 14, 20, 0.92);
        backdrop-filter: blur(6px);
        border-bottom: 1px solid var(--border);
        z-index: 1000;
    }
    .brand {
        display: flex;
        align-items: center;
        gap: 12px;
    }
    .brand-mark {
        width: 34px; height: 34px;
        border-radius: 8px;
        background: linear-gradient(135deg, var(--accent-blue), var(--accent-mint));
        display: flex; align-items: center; justify-content: center;
        font-family: 'IBM Plex Mono', monospace;
        font-weight: 600;
        font-size: 14px;
        color: #06121C;
        flex-shrink: 0;
    }
    .brand-text h1 {
        margin: 0;
        font-family: 'IBM Plex Sans', sans-serif;
        font-size: 16px;
        font-weight: 600;
        letter-spacing: 0.2px;
    }
    .brand-text .tagline {
        margin: 0;
        font-size: 11px;
        color: var(--text-muted);
        font-family: 'IBM Plex Mono', monospace;
        letter-spacing: 0.5px;
        text-transform: uppercase;
    }

    .header-right {
        display: flex;
        align-items: center;
        gap: 22px;
    }
    .live-status {
        display: flex;
        align-items: center;
        gap: 8px;
        font-family: 'IBM Plex Mono', monospace;
        font-size: 12px;
        color: var(--accent-mint);
        letter-spacing: 0.5px;
    }
    .pulse-dot {
        width: 8px; height: 8px;
        border-radius: 50%;
        background: var(--accent-mint);
        box-shadow: 0 0 0 0 rgba(52, 201, 163, 0.6);
        animation: pulse 2s infinite;
    }
    @keyframes pulse {
        0%   { box-shadow: 0 0 0 0 rgba(52, 201, 163, 0.55); }
        70%  { box-shadow: 0 0 0 8px rgba(52, 201, 163, 0); }
        100% { box-shadow: 0 0 0 0 rgba(52, 201, 163, 0); }
    }
    .clock {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 13px;
        color: var(--text-muted);
        min-width: 92px;
        text-align: right;
    }

    /* ---------------- Segmented toggle controls ---------------- */
    .segmented {
        display: flex;
        gap: 6px;
        background: var(--surface-alt);
        padding: 4px;
        border-radius: 8px;
        border: 1px solid var(--border);
    }
    .segmented button {
        background: transparent;
        border: none;
        color: var(--text-muted);
        padding: 8px 14px;
        border-radius: 6px;
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        display: flex;
        align-items: center;
        gap: 6px;
        transition: background 0.15s ease, color 0.15s ease;
    }
    .segmented button:hover {
        color: var(--text-primary);
        background: rgba(255,255,255,0.04);
    }
    .segmented button.active {
        background: var(--accent-blue);
        color: #06121C;
    }

    /* ---------------- Layout ---------------- */
    main {
        max-width: 1180px;
        margin: 0 auto;
        padding: 24px 22px 60px 22px;
    }

    .panel {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: var(--radius);
        margin-bottom: 20px;
        overflow: hidden;
    }
    .panel-head {
        padding: 16px 20px;
        border-bottom: 1px solid var(--border);
        display: flex;
        align-items: baseline;
        justify-content: space-between;
    }
    .panel-head h2 {
        margin: 0;
        font-size: 14px;
        font-weight: 600;
        letter-spacing: 0.3px;
        text-transform: uppercase;
        font-family: 'IBM Plex Sans', sans-serif;
    }
    .panel-head .subtitle {
        font-size: 12px;
        color: var(--text-muted);
        font-family: 'IBM Plex Mono', monospace;
    }
    .panel-body { padding: 20px; }

    /* ---- Collapsible camera / map panels ---- */
    #cameraContainer, #mapContainer { display: none; }

    #cameraFeed {
        display: block;
        margin: 0 auto;
        max-width: 100%;
        max-height: calc(100vh - 230px);
        width: auto;
        height: auto;
        object-fit: contain;
        border-radius: 8px;
        border: 1px solid var(--border);
        background: #000;
    }

    #mapImage {
        display: block;
        margin: 0 auto 20px auto;
        max-width: 100%;
        border-radius: 8px;
        border: 1px solid var(--border);
    }

    /* ---- Rack control grid ---- */
    .rack-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
        gap: 10px;
    }
    .rack-btn {
        background: var(--surface-alt);
        border: 1px solid var(--border);
        color: var(--text-primary);
        padding: 14px 10px;
        border-radius: 8px;
        cursor: pointer;
        text-align: center;
        transition: border-color 0.15s ease, background 0.15s ease, transform 0.1s ease;
    }
    .rack-btn:hover {
        border-color: var(--accent-blue);
        transform: translateY(-1px);
    }
    .rack-btn .rack-id {
        display: block;
        font-family: 'IBM Plex Mono', monospace;
        font-size: 11px;
        color: var(--text-muted);
        letter-spacing: 0.5px;
        margin-bottom: 4px;
    }
    .rack-btn .rack-label {
        display: block;
        font-size: 14px;
        font-weight: 600;
    }
    .rack-btn.pressed {
        border-color: var(--accent-mint);
        background: rgba(52, 201, 163, 0.12);
    }
    .rack-note {
        margin: 14px 2px 0 2px;
        font-size: 12px;
        color: var(--text-muted);
        font-family: 'IBM Plex Mono', monospace;
    }

    /* ---- Two column: table + log ---- */
    .grid-two {
        display: grid;
        grid-template-columns: 1.4fr 1fr;
        gap: 20px;
        align-items: start;
    }
    @media (max-width: 860px) {
        .grid-two { grid-template-columns: 1fr; }
    }

    table {
        width: 100%;
        border-collapse: collapse;
        font-size: 13px;
    }
    th, td {
        padding: 10px 14px;
        text-align: left;
        border-bottom: 1px solid var(--border);
    }
    th {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 11px;
        letter-spacing: 0.5px;
        text-transform: uppercase;
        color: var(--text-muted);
        font-weight: 500;
    }
    tr:last-child td { border-bottom: none; }
    td { color: var(--text-primary); }
    .empty-state {
        color: var(--text-muted);
        font-size: 13px;
        padding: 6px 2px;
    }

    /* ---- Log feed ---- */
    .log-box {
        max-height: 480px;
        overflow-y: auto;
        display: flex;
        flex-direction: column;
        gap: 6px;
    }
    .log-line {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 12px;
        line-height: 1.5;
        padding: 8px 10px;
        border-radius: 6px;
        border-left: 3px solid var(--border);
        background: var(--surface-alt);
        color: var(--text-primary);
        word-break: break-word;
    }
    .log-line.sev-ok    { border-left-color: var(--accent-mint); }
    .log-line.sev-warn  { border-left-color: var(--accent-amber); }
    .log-line.sev-error { border-left-color: var(--accent-red); }

    /* ---------------- Footer ---------------- */
    .footer {
        max-width: 1180px;
        margin: 0 auto;
        padding: 0 22px 30px 22px;
        display: flex;
        justify-content: space-between;
        font-family: 'IBM Plex Mono', monospace;
        font-size: 11px;
        color: var(--text-muted);
        letter-spacing: 0.3px;
    }

    /* Scrollbar polish */
    ::-webkit-scrollbar { width: 8px; height: 8px; }
    ::-webkit-scrollbar-track { background: var(--surface); }
    ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }

    /* Keyboard focus visibility */
    button:focus-visible, a:focus-visible {
        outline: 2px solid var(--accent-blue);
        outline-offset: 2px;
    }
</style>
</head>
<body>

<header class="topbar">
    <div class="brand">
        <div class="brand-mark">STN</div>
        <div class="brand-text">
            <h1>Stock Tracking Navigator</h1>
            <p class="tagline">Real-time placement verification</p>
        </div>
    </div>
    <div class="header-right">
        <div class="live-status"><span class="pulse-dot"></span>SYSTEM ONLINE</div>
        <div class="clock" id="clock">--:--:--</div>
        <div class="segmented">
            <button id="cameraBtn" onclick="toggleCamera()">📷 Live Cam</button>
            <button id="mapBtn" onclick="toggleMap()">🗺️ Facility Map</button>
        </div>
    </div>
</header>

<main>

    <!-- Live camera feed panel (hidden until toggled) -->
    <div class="panel" id="cameraContainer">
        <div class="panel-head">
            <h2>Live Camera Feed</h2>
            <span class="subtitle">Camera 0 · detection overlay</span>
        </div>
        <div class="panel-body">
            <img id="cameraFeed" src="" alt="Camera feed will appear here when enabled">
        </div>
    </div>

    <!-- Map + rack controls panel (hidden until toggled) -->
    <div class="panel" id="mapContainer">
        <div class="panel-head">
            <h2>Facility Map</h2>
            <span class="subtitle">Select a rack to inspect</span>
        </div>
        <div class="panel-body">
            <img id="mapImage" src="" alt="Map image loaded from MAP_IMAGE_PATH">

            <div class="rack-grid">
                <button class="rack-btn" onclick="pressRack('RackA', this)">
                    <span class="rack-id">R-A</span><span class="rack-label">Rack A</span>
                </button>
                <button class="rack-btn" onclick="pressRack('RackB', this)">
                    <span class="rack-id">R-B</span><span class="rack-label">Rack B</span>
                </button>
                <button class="rack-btn" onclick="pressRack('RackC', this)">
                    <span class="rack-id">R-C</span><span class="rack-label">Rack C</span>
                </button>
                <button class="rack-btn" onclick="pressRack('RackD', this)">
                    <span class="rack-id">R-D</span><span class="rack-label">Rack D</span>
                </button>
                <button class="rack-btn" onclick="pressRack('RackE', this)">
                    <span class="rack-id">R-E</span><span class="rack-label">Rack E</span>
                </button>
            </div>
            <p class="rack-note">Connects to the matching rack controller over SSH and runs its verification script (coming soon).</p>
        </div>
    </div>

    <div class="grid-two">
        <div class="panel">
            <div class="panel-head">
                <h2>Detected Items</h2>
                <span class="subtitle">Confirmed reads</span>
            </div>
            <div class="panel-body" id="dataTableWrapper">
            {% if data %}
            <table>
            <tr><th>#</th><th>Item</th></tr>
            {% for item in data %}
            <tr><td>{{ loop.index }}</td><td>{{ item }}</td></tr>
            {% endfor %}
            </table>
            {% else %}
            <p class="empty-state">No QR codes detected yet.</p>
            {% endif %}
            </div>
        </div>

        <div class="panel">
            <div class="panel-head">
                <h2>System Activity</h2>
                <span class="subtitle">Live event log</span>
            </div>
            <div class="panel-body">
                <div class="log-box" id="logBox">
                {% if logs %}
                {% for entry in logs[-50:] %}
                    {% set sev = 'sev-ok' %}
                    {% if '❌' in entry or 'Unknown' in entry %}{% set sev = 'sev-error' %}
                    {% elif '⚠️' in entry %}{% set sev = 'sev-warn' %}
                    {% endif %}
                    <div class="log-line {{ sev }}">{{ entry }}</div>
                {% endfor %}
                {% else %}
                <p class="empty-state">No logs yet.</p>
                {% endif %}
                </div>
            </div>
        </div>
    </div>

</main>

<div class="footer">
    <span>Auto-refresh: 1s</span>
    <span>Press 'q' in the camera window or Ctrl+C in terminal to stop</span>
</div>

<script>
let cameraVisible = false;
let mapVisible = false;

function updateClock() {
    const now = new Date();
    document.getElementById('clock').textContent = now.toLocaleTimeString();
}
updateClock();
setInterval(updateClock, 1000);

function toggleCamera() {
    cameraVisible = !cameraVisible;
    const container = document.getElementById('cameraContainer');
    const img = document.getElementById('cameraFeed');
    const btn = document.getElementById('cameraBtn');
    if (cameraVisible) {
        container.style.display = 'block';
        img.src = '/video_feed/0?_=' + Date.now();
        btn.classList.add('active');
    } else {
        container.style.display = 'none';
        img.src = '';
        btn.classList.remove('active');
    }
}

function toggleMap() {
    mapVisible = !mapVisible;
    const container = document.getElementById('mapContainer');
    const img = document.getElementById('mapImage');
    const btn = document.getElementById('mapBtn');
    if (mapVisible) {
        container.style.display = 'block';
        img.src = '/map_image?_=' + Date.now();
        btn.classList.add('active');
    } else {
        container.style.display = 'none';
        img.src = '';
        btn.classList.remove('active');
    }
}

function pressRack(rackName, btnEl) {
    fetch('/rack/' + rackName)
        .then(res => res.json())
        .then(data => {
            console.log(data);
            btnEl.classList.add('pressed');
            setTimeout(() => btnEl.classList.remove('pressed'), 500);
        })
        .catch(err => console.error('Rack button error:', err));
}

// ---- AJAX refresh of data table + logs (keeps camera/map toggle state intact) ----
function escapeHtml(str) {
    const div = document.createElement('div');
    div.innerText = str;
    return div.innerHTML;
}

function refreshData() {
    fetch('/data').then(r => r.json()).then(items => {
        const wrapper = document.getElementById('dataTableWrapper');
        if (!items || items.length === 0) {
            wrapper.innerHTML = '<p class="empty-state">No QR codes detected yet.</p>';
            return;
        }
        let html = '<table><tr><th>#</th><th>Item</th></tr>';
        items.forEach((item, idx) => {
            html += '<tr><td>' + (idx + 1) + '</td><td>' + escapeHtml(item) + '</td></tr>';
        });
        html += '</table>';
        wrapper.innerHTML = html;
    }).catch(err => console.error('Data refresh error:', err));

    fetch('/logs').then(r => r.json()).then(allLogs => {
        const logBox = document.getElementById('logBox');
        if (!allLogs || allLogs.length === 0) {
            logBox.innerHTML = '<p class="empty-state">No logs yet.</p>';
            return;
        }
        const recent = allLogs.slice(-50);
        let html = '';
        recent.forEach(entry => {
            let sev = 'sev-ok';
            if (entry.includes('❌') || entry.includes('Unknown')) {
                sev = 'sev-error';
            } else if (entry.includes('⚠️')) {
                sev = 'sev-warn';
            }
            html += '<div class="log-line ' + sev + '">' + escapeHtml(entry) + '</div>';
        });
        logBox.innerHTML = html;
        logBox.scrollTop = logBox.scrollHeight;
    }).catch(err => console.error('Logs refresh error:', err));
}

setInterval(refreshData, 1000);
</script>

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

# ------------------- Live Video Streaming Route -------------------
def generate_mjpeg(camera_id):
    """Generator that yields the latest processed frame for a given camera as MJPEG."""
    while not stop_event.is_set():
        with frame_lock:
            frame = latest_frames.get(camera_id)

        if frame is None:
            time.sleep(0.1)
            continue

        ret, buffer = cv2.imencode('.jpg', frame)
        if not ret:
            continue

        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        time.sleep(0.05)  # ~20 fps cap for the web stream

@app.route('/video_feed/<int:camera_id>')
def video_feed(camera_id):
    return Response(generate_mjpeg(camera_id),
                     mimetype='multipart/x-mixed-replace; boundary=frame')

# ------------------- Map Image Route -------------------
@app.route('/map_image')
def map_image():
    if not os.path.isfile(MAP_IMAGE_PATH):
        msg = f"❌ Map image not found at: {MAP_IMAGE_PATH}"
        print(msg)
        return msg, 404
    return send_file(MAP_IMAGE_PATH, mimetype='image/jpeg')

# ------------------- Rack Button Route -------------------
@app.route('/rack/<rack_name>')
def rack_button(rack_name):
    # NOTE: This is where SSH-into-Raspberry-Pi + "python3 <rack_name>.py" logic
    # will be added later. For now it just logs/prints that the button was pressed.
    msg = f"🔘 Button pressed: {rack_name} (SSH execution will be added later)"
    print(msg)
    logs.append(msg)
    return jsonify({"status": "ok", "rack": rack_name, "message": msg})

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

            try:
                data, bbox, _ = qrDecoder.detectAndDecode(frame)
            except cv2.error as e:
                # OpenCV occasionally throws on a degenerate/zero-area QR contour
                # (a bad or partial detection in a single frame). Skip this frame
                # instead of crashing the whole detector thread.
                msg = f"⚠️ [Cam {camera_id}] Skipped a bad frame (QR decode error): {e}"
                if msg not in logged_messages:
                    logs.append(msg)
                    print(msg)
                    logged_messages.add(msg)
                data, bbox = "", None

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
            try:
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
            except Exception as e:
                # Any unexpected drawing error shouldn't kill detection —
                # just log it and keep going with the next frame.
                msg = f"⚠️ [Cam {camera_id}] Skipped drawing on a bad frame: {e}"
                if msg not in logged_messages:
                    logs.append(msg)
                    print(msg)
                    logged_messages.add(msg)

            # Store the latest processed frame for the web live-feed (thread-safe)
            with frame_lock:
                latest_frames[camera_id] = frame.copy()

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