# Warehouse Stock Navigation Bot

## Overview

This repository runs a camera-based QR code detection system with a live Flask dashboard. The primary updated script is `Camera_detection_map_webpage_V2.py`, which adds a map view, MJPEG video streaming for the camera feed, rack action buttons (placeholder for SSH execution), and improved logging and save routines.

## Features (in `Camera_detection_map_webpage_V2.py`)

- Flask web dashboard at `http://0.0.0.0:5000` with endpoints for data, logs, video feed, map image, and rack actions.
- MJPEG streaming endpoint: `/video_feed/<camera_id>` (used by the dashboard to show live camera frames).
- Map image route: `/map_image` serving the image at `MAP_IMAGE_PATH` (edit path in the script if needed).
- Rack button route: `/rack/<rack_name>` (currently logs the press; SSH/remote execution can be added later).
- Auto-refreshing dashboard (1s) showing detected QR items and the last ~50 log entries.
- Saves detection snapshots to `Stock/` and logs to `Logs/Resolved` and `Logs/Unresolved` on shutdown or when requested.

## Key files

- `Camera_detection_map_webpage_V2.py` — main updated detector + dashboard.
- `map.jpg` (or any image) — referenced by `MAP_IMAGE_PATH` inside the Python script; ensure it exists and the path is correct.
- `Logs/` — log output folders (Resolved and Unresolved).
- `Stock/` — saved detection snapshots.

## Requirements

- Python 3.8+
- OpenCV (`opencv-python`)
- Flask
- NumPy

Install dependencies:

```bash
pip install opencv-python flask numpy
```

## Configuration

- Edit `MAP_IMAGE_PATH` in `Camera_detection_map_webpage_V2.py` to point to your map image (default is set near the top of the file).
- Make sure your camera device index (0 by default) is correct.

## Run

Start the script:

```bash
python Camera_detection_map_webpage_V2.py
```

Open the dashboard:

```
http://localhost:5000
```

Stop the program with Ctrl+C in the terminal or press `q` in the camera window.

## Endpoints reference

- `/` — Dashboard HTML
- `/data` — JSON list of detected items
- `/logs` — JSON list of log entries
- `/video_feed/<camera_id>` — MJPEG stream for camera preview
- `/map_image` — Map image file (served from `MAP_IMAGE_PATH`)
- `/rack/<rack_name>` — Rack action endpoint (placeholder)

## Notes & Next steps

- The `/rack` endpoint is a stub for now; add SSH execution to trigger remote actions from the dashboard.
- Update the category/location dictionaries inside the script to match your QR encoding scheme.
- If you want, I can commit these README changes and push them to the GitHub remote from this machine — confirm and ensure your git credentials are configured locally.
