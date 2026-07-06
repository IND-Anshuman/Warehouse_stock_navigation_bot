# Warehouse Stock Navigation Bot

## Overview

This repository contains a warehouse stock navigation project built around camera-based QR code detection and a live web dashboard. The main Python script `Camer_detection_&_webpage.py` captures video from a camera, detects QR codes, parses product and location data, and streams detection results through a Flask web interface.

## What the code does

- Uses OpenCV to access a camera stream and detect QR codes in each frame.
- Parses QR data into a category ID, product serial number, and location ID.
- Maps detected IDs to human-readable product names and shelf locations.
- Flags mismatches when products are placed in the wrong location.
- Displays detected items and logs on a live webpage served by Flask.
- Auto-refreshes the dashboard every second to show the latest detections.

## Main script

- `Camer_detection_&_webpage.py`
  - Starts a Flask server at `http://0.0.0.0:5000`.
  - Runs a QR code detector in a camera loop.
  - Draws bounding boxes around detected QR codes.
  - Stores detected data and logs for display on the dashboard.

## Log folders

- `Logs/Resolved/` — contains resolved detection logs.
- `Logs/Unresolved/` — contains unresolved or error logs.
- `Stock/` — contains inventory or stock log records.

## Requirements

- Python 3.x
- OpenCV (`opencv-python`)
- Flask
- NumPy

## Run the project

1. Install dependencies:
   ```bash
   pip install opencv-python flask numpy
   ```
2. Run the script:
   ```bash
   python "Camer_detection_&_webpage.py"
   ```
3. Open your browser and go to:
   ```
   http://localhost:5000
   ```

## Notes

- The script uses example category and location mappings. Update the dictionaries in `Camer_detection_&_webpage.py` if your QR codes use a different format.
- Press `q` to stop the camera detection loop.
