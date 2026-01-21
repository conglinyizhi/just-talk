# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Just Talk is a speech recognition desktop app with global hotkey support. It uses PyQt6 with WebEngine for the UI (HTML/CSS/JS frontend served in a WebView) and pynput for global keyboard/mouse event capture.

## Commands

### Run the app
```bash
uv run python asr_pyqt6_app.py
```

### Build (Linux)
```bash
uv sync --frozen --extra build
make build-linux
```

### Build (Windows via Docker+Wine)
```bash
make build-windows
```

### Create release tarball
```bash
./scripts/release-linux.sh
```

## Architecture

### Main Components

- **`asr_pyqt6_app.py`** (~3000 lines): Monolithic main application file containing:
  - SAUC binary protocol implementation for speech-to-text streaming
  - Tiny WebSocket client (stdlib-only, no external WS library)
  - PyQt6 application with WebEngine for UI
  - Audio recording via QtMultimedia
  - Bridge between Qt/Python and the web frontend via QWebChannel

- **`recording_indicator.py`**: Floating recording indicator widget (waveform animation, X11 window properties for non-focus-stealing overlay)

- **`hotkey/`**: Global hotkey system
  - `config.py`: Configuration dataclasses for hotkey settings
  - `listener.py`: pynput-based keyboard/mouse listener
  - `manager.py`: Hotkey manager coordinating listeners
  - `settings_ui.py`: PyQt6 settings dialog

- **`web/`**: Frontend assets loaded into WebEngine
  - `index.html`: Main UI (settings, provider config, etc.)
  - `app.js`: Frontend JavaScript
  - `styles.css`: Styling

### Key Technical Details

- Forces X11/XCB platform on Linux (`QT_QPA_PLATFORM=xcb`) to work around Wayland limitations
- Recording indicator uses X11 window properties (`_NET_WM_WINDOW_TYPE_NOTIFICATION`, `WM_HINTS`) for screen-key-like behavior (no focus stealing, always on top)
- Configuration stored via QSettings at `~/.config/JustTalk/AsrApp.conf`
- PyInstaller spec (`just_talk.spec`) bundles the `web/` directory and PyQt6 WebEngine components

### Hotkey Modes

1. **Push-to-talk** (Ctrl+Super or middle mouse): Hold to record, release to stop
2. **Toggle mode** (Alt): Press to start, press again to stop
