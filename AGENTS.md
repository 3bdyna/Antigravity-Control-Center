# Antigravity Control Center — Project Knowledge & Agent Guidelines

## Overview
Windows desktop Control Center (PyQt5 + PyQtWebEngine + local HTTP/SSE server on `127.0.0.1:28795`) for managing Antigravity accounts, parallel quota polling, real-time token/session analytics, and Antigravity UI integration.

## Repository Structure
- `main.py` — Entry point launcher (`from app import main`).
- `app.py` — Core HTTP/SSE server (`PORT = 28795`), Windows tray daemon, PyQt5 WebEngine UI window, `AntigravityAsarWatchdog`, and single-instance mutex management (`Local\AntigravityControlCenterDaemon`, `Local\AntigravityControlCenterUI`).
- `switcher.py` — Parallel quota engine, Windows DPAPI credential storage (`AGDPAPI1`), account switching, and quota disk caching.
- `token_tracker.py` — Background transcript watcher persisting token usage and session metrics to SQLite (`tokens_history.db`, WAL mode).
- `ui_html.py` — Static asset loader resolving `static/` across source and PyInstaller (`_MEIPASS` / `_internal`) layouts.
- `static/` — Frontend UI assets (`index.html`, `app.js`, `styles.css`, `tailwind.css`).
- `scripts/` — Companion runtime scripts deployed to `%LOCALAPPDATA%\Programs\AntigravityControlCenter\`:
  - `auto_patch_antigravity.js` — Patches Antigravity `app.asar` to inject the quota top-bar indicator (invoked by `AntigravityAsarWatchdog` in `app.py`).
  - `antigravity-drag-daemon.js` — CDP (`DevToolsActivePort`) daemon keeping draggable titlebars and the quota indicator active.
  - `antigravity_drag_daemon.pyw`, `run_daemon.vbs`, `start-drag-daemon.vbs` — Silent Windows launchers for the drag daemon.
- `AntigravityControlCenter.spec` — PyInstaller build spec (`app.py`, `app_icon.ico`, `static/`).

## Runtime & Deployment Paths
- **Installed binary (Desktop shortcut target):** `%LOCALAPPDATA%\Programs\AntigravityControlCenter\v1.3.0\AntigravityControlCenter\AntigravityControlCenter.exe`
- **Deployed companion scripts:** `%LOCALAPPDATA%\Programs\AntigravityControlCenter\` (`auto_patch_antigravity.js`, `antigravity-drag-daemon.js`, `.vbs`, `.pyw`)
- **User state & SQLite DB:** `%USERPROFILE%\.gemini\antigravity-switcher\` (`accounts/`, `active_email.txt`, `quotas_cache.json`, `tokens_history.db`, `autopilot.log`, `app_crash.log`)

## Build & Deploy Workflow
1. Run from source for quick testing:
   ```powershell
   python main.py
   ```
2. Build executable with PyInstaller:
   ```powershell
   pyinstaller AntigravityControlCenter.spec --noconfirm
   ```
3. To update the installed desktop app, close the running tray daemon first (`/api/daemon/quit` or Task Manager), then copy `dist\AntigravityControlCenter\` to `%LOCALAPPDATA%\Programs\AntigravityControlCenter\v1.3.0\AntigravityControlCenter\`.
4. If editing files in `scripts/`, copy updated versions to `%LOCALAPPDATA%\Programs\AntigravityControlCenter\` so the live watchdog and daemons pick them up.

## Architectural & Safety Rules
1. **Preserve DPAPI & Atomic Writes:** Always use `atomic_write_bytes` / `atomic_write_text` in `switcher.py` for credential and cache files; never write plaintext credentials outside DPAPI blobs.
2. **Never Break Official Auto-Updater:** In `scripts/auto_patch_antigravity.js`, preserve `cleanUpdaterCache()` as a no-op; never delete `%LOCALAPPDATA%\antigravity-updater`.
3. **Single-Instance & Low-Memory Tray:** Keep Windows Named Mutex checks and working-set trimming intact so duplicate daemons do not spawn.
4. **No Hardcoded Secrets in Git:** Never commit personal tokens, `accounts/` folders, `tokens_history.db`, or `quotas_cache.json`.
5. **Process & Timeout Discipline:** All HTTP/network/subprocess calls must use explicit timeouts and clean up background threads/processes deterministically.
