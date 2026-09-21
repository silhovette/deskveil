# DeskVeil

**Zero-friction visual privacy for Windows.**

DeskVeil automatically covers every display with live frosted glass when you step away, then reveals your desktop when you return. Grab a drink, collect a delivery, or chat with a colleague while your apps keep running underneath.

## Features

- **Automatic presence detection** with local MediaPipe face tracking.
- **All-display coverage**, including the taskbar and newly connected monitors.
- **Live frosted glass** that follows changing windows and playing videos.
- **Smooth 200 ms transitions** with high-precision color blending and fine, stationary dithering.
- **Mouse and touchpad input suppression** with a hidden pointer while covered.
- **Tray controls** available through either left-click or right-click.
- **Instant reveal shortcuts** and a ten-minute snooze.
- **Shared camera capture with [peeker](https://github.com/silhovette/peeker)**.

## Getting started

### Run from source

Use Windows 10 or 11 and Python 3.11 x64. Live desktop capture uses the capture-exclusion API available in Windows 10 version 2004 and later.

```powershell
git clone https://github.com/silhovette/deskveil.git
cd deskveil
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

The repository includes the MediaPipe model in `models/face_landmarker.task`. To download a fresh copy:

```powershell
.\.venv\Scripts\python.exe tools\download_model.py
```

After setup, double-click `run.vbs` to launch directly into the system tray. The icon may appear in the tray overflow menu.

### Build a Windows app

```powershell
.\build.bat
```

The build script installs the packaging dependencies and creates `dist/DeskVeil/DeskVeil.exe`. Distribute the complete `dist/DeskVeil` folder, and launch the executable inside it.

## Controls

Left-click or right-click the tray icon to open the menu.

| Control | Action |
| --- | --- |
| Enable DeskVeil | Turn monitoring on or off. Turning it off immediately reveals the desktop and restores mouse input. |
| Cover Now | Cover every display. Automatic reveal follows a detected departure and a stable return. |
| Snooze for 10 min | Reveal the desktop and pause monitoring for ten minutes. |
| Resume Monitoring | Resume immediately with a fresh presence timer. |
| Camera Preview | Show the live camera image and face boxes for positioning. |
| Exit | Reveal the desktop and close DeskVeil. |

Unchecking the enable toggle pauses monitoring while DeskVeil stays in the tray. Check it again to resume; Exit closes the application. The enable toggle applies to the current session. While disabled, manual cover and camera preview are inactive.

| Shortcut | Action |
| --- | --- |
| **Ctrl + V** while covered | Reveal immediately and continue monitoring with a fresh departure timer. |
| **Ctrl + Alt + Shift + V** | Reveal immediately and snooze for ten minutes. |

On the visible desktop, Ctrl + V retains its normal paste behavior. Both reveal shortcuts act immediately.

Tray colors indicate the current state: **teal** for monitoring, **teal with an amber pause mark** for paused or disabled, and **amber** while waiting for camera or model data.

## Presence detection

DeskVeil uses face size and position to decide whether someone is seated in front of the computer.

- A face qualifies when its bounding box covers at least **3.5% of the camera image** and its center is within **0.45 normalized units** of the image center.
- **Two seconds** of continuous absence activates the veil.
- **0.5 seconds** of continuous presence reveals the desktop.
- Brief detection dropouts are absorbed by the confirmation timers.
- Interrupted camera data resets the confirmation timers. An active veil remains visible until presence returns or a reveal shortcut is used.

The camera defaults to **640 × 360**, with **5 face-inference passes per second**. Presence timing runs independently of the interface through a pure state machine:

```text
PRESENT -> PENDING_AWAY -> COVERED -> PENDING_RETURN -> PRESENT

SNOOZED (temporary pause)
```

Snoozing can be entered from any state. Resuming starts a fresh detection cycle.

## Live glass rendering

Each display gets a full-screen window with a uniform, cool-toned frosted material. Desktop animation and video playback continue underneath, and the foreground application keeps its focus.

Capture, blur, and composition run in a background worker. The rendering pipeline:

1. Captures the desktop with reusable Windows capture resources.
2. Resizes the image and reuses the previous result when the pixels are unchanged.
3. Blurs and blends the material at 16-bit precision per color channel.
4. Composes the complete frame at the display's physical resolution.
5. Applies fixed, high-frequency dithering during final display conversion.
6. Delivers the latest completed frame to the interface through a coalesced notification.

The target refresh rate is **30 FPS**, with throughput depending on display resolution and hardware. Capture stops when the veil is dismissed. The fixed dither pattern gives dark gradients a fine texture while remaining stable across frames.

## Configuration

Edit `config.py` to adjust the defaults:

| Setting | Default | Purpose |
| --- | --- | --- |
| `CAMERA_INDEX` | `0` | Camera device |
| `FRAME_WIDTH` / `FRAME_HEIGHT` | `640` / `360` | Requested camera resolution |
| `INFERENCE_FPS` | `5` | Face-inference frequency |
| `AWAY_CONFIRM_TIME` | `2.0` | Departure confirmation, in seconds |
| `RETURN_CONFIRM_TIME` | `0.5` | Return confirmation, in seconds |
| `MIN_RETURN_FACE_RATIO` | `0.035` | Minimum face area relative to the camera image |
| `MAX_RETURN_CENTER_DISTANCE` | `0.45` | Maximum normalized distance from image center |
| `VEIL_FADE_MS` | `200` | Automatic transition duration |
| `GLASS_FPS` | `30` | Target glass refresh rate |
| `GLASS_MAX_EDGE` | `960` | Working blur resolution |
| `GLASS_BLUR_SIGMA` | `5.0` | Blur strength |
| `GLASS_DIM_ALPHA` | `105` | Material darkening |
| `SNOOZE_MINUTES` | `10` | Snooze duration |

Restart the source app after changing configuration. Rebuild to apply changes to a packaged executable.

## Local processing and camera sharing

Camera frames, face detection, and desktop composition are processed locally in memory. The model is bundled for offline inference. Image buffers are cleared when their monitoring or cover session ends.

DeskVeil and peeker can share one physical camera through Windows named shared memory. One client captures frames, and the other reads the latest frame. Each app runs its own detection logic. When the capturing client pauses or exits, the other takes over automatically.

Use the shared-capture versions of both apps. Pausing both releases the physical camera for a video call. DeskVeil also runs independently.

Operational logs are stored at:

```text
%LOCALAPPDATA%/DeskVeil/logs/deskveil.log
```

Logs contain monitoring state and diagnostic information, with automatic size-based rotation.

## Development and testing

Run the automated tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The test suite covers presence timing, camera interruptions, manual controls, hotkeys, display management, asynchronous frame delivery, and final color composition.

Additional tools exercise the actual Windows desktop and camera:

| Tool | Checks |
| --- | --- |
| `tools/camera_smoke.py` | Camera capture and ten model-inference passes |
| `tools/windows_smoke.py` | Display coverage, native shortcuts, tray controls, and mouse handling |
| `tools/frozen_smoke.py` | Packaged app startup, sustained monitoring, and shutdown |
| `tools/live_glass_smoke.py` | Changing desktop content, focus, and input suppression |
| `tools/video_glass_smoke.py` | Video playback and changing frames beneath the veil |
| `tools/shared_camera_smoke.py` | Concurrent clients, camera handover, and release |
| `tools/coexist_apps_smoke.py` | Packaged DeskVeil and peeker sharing the camera |
| `tools/mouse_exit_smoke.py` | Mouse input restoration after process exit |
| `tools/glass_quality.py` | Synthetic gradient comparison of the previous and current materials |
| `tools/glass_compute_benchmark.py` | Pixel comparison and blur-processing timings |
| `tools/glass_performance.py` | Composition updates, painting, animation intervals, and interface latency |

Run desktop and camera integration tools with the regular DeskVeil instance closed. The coexistence tool uses the peeker build in the sibling `peeker` directory; the shared-camera test starts its own camera clients.

For controlled rendering measurements:

```powershell
.\.venv\Scripts\python.exe tools\glass_performance.py --synthetic
.\.venv\Scripts\python.exe tools\glass_performance.py --synthetic --dynamic
```

## Project layout

```text
deskveil/
  main.py                 Application lifecycle and controls
  config.py               Runtime defaults
  detection/              Camera sharing, face detection, presence state machine
  ui/                     Tray, preview, hotkeys, live glass rendering
  assets/                 Icons
  models/                 MediaPipe model and source information
  tests/                  Automated tests
  tools/                  Integration tests, diagnostics, and build helpers
  build.bat               Windows packaging
  DeskVeil.spec           PyInstaller specification
  run.vbs                 Tray-only source launcher
```

Detection and preview work originated from [peeker](https://github.com/silhovette/peeker). Model source information is available in [models/README.md](models/README.md).
