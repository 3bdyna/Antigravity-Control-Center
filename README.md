# Antigravity Control Center

A local-first **Windows desktop & system tray control center for Google Antigravity IDE**. Built for multi-account quota management, real-time token telemetry, and live session/subagent inspection with minimal memory overhead.

![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6?style=flat-square)
![Version](https://img.shields.io/badge/Version-v1.4.0-2ea44f?style=flat-square)
![Stack](https://img.shields.io/badge/Stack-Python%20%7C%20PyQt5%20%7C%20WebEngine-3776AB?style=flat-square)
![Storage](https://img.shields.io/badge/Storage-SQLite%20WAL%20%2B%20DPAPI-4479A1?style=flat-square)

---

## Overview

**Antigravity Control Center** pairs a lightweight Chromium-free Windows tray daemon (`127.0.0.1:28795` HTTP/SSE server) with an on-demand frameless `PyQtWebEngine` dashboard. It lets you manage multiple Google Antigravity accounts securely via Windows DPAPI, monitor 5-hour and weekly model quotas in parallel, tail conversation transcripts into SQLite for real-time token analytics, and inspect active sessions and subagent workers.

---

## Core Capabilities

### 1. Multi-Account Switcher & Quota Engine
- **Parallel Quota Polling:** Queries **5-hour cycle** and **weekly quota** remaining percentages (Gemini & Claude) with local reset countdowns across all enrolled accounts concurrently, backed by in-memory and on-disk caching (`quotas_cache.json`).
- **Recommendation Engine:** Evaluates active account health vs. standby capacity and weekly reset urgency to flag `Active`, `Active (Low)`, `Recommended`, `Cooldown`, and `Standby` states.
- **1-Click Account Switching:** Atomically updates Windows Credential Manager (`gemini:antigravity`), clears stale session cache, and reloads/restarts Antigravity — available from both the dashboard and the system tray context menu.
- **Account Enrollment:** Snapshot the currently active Antigravity profile directly from Windows Credential Manager, or enroll additional accounts via local Google OAuth callback flow.
- **Windows DPAPI Security:** Account credentials are encrypted at rest with Windows DPAPI (`AGDPAPI1`) using atomic file writes — no plaintext tokens are persisted.

### 2. Token Analytics & Telemetry
- **Background Transcript Watcher:** Continuously tails local Antigravity session transcripts into `%USERPROFILE%\.gemini\antigravity-switcher\tokens_history.db` (**SQLite WAL mode**) and broadcasts updates to the UI via **Server-Sent Events (SSE)**.
- **KPIs & Timeframes:** Filter by **Today**, **Last 7D**, **Month**, **Year**, or **All Time** (per-account or combined) to track **Total Volume**, **Prompt Cache Hit %** & saved quota bandwidth, **I/O Volume Ratio**, and **Output Speed** (`tok/s`, `tok/min`, `tok/h`).
- **52-Week Activity Heatmap & Cadence:** Track coding streaks, active days, daily token volume, top model per day, and a 24-hour day/night token distribution breakdown.
- **Optimizer Telemetry:** Dedicated tracking cards for **`context-mode`** (tokens shielded & bytes sandboxed across v1/v2 logs) and **`agy-fast` MCP** (batched operations, turns saved, and batch multiplier).
- **Exports & Snapshots:** Generate a standalone **Executive HTML Report**, export raw SQL events to **CSV** or **JSON**, or trigger an instant point-in-time **SQLite DB backup**.

### 3. Session & Fleet Inspector
- **Conversation & Subagent Fleet:** Inspect active main sessions and toggle visibility for background subagent workers.
- **Context Load & Compaction Tracking:** Monitor active context volume against context limits (e.g., `512k`), headroom, auto-compaction count, and prompt cache acceleration.
- **Turn-by-Turn Explorer:** Expand individual conversation steps to view prompt tokens, output tokens, cache hits, totals, and turn efficiency.
- **Diagnostics & Maintenance:** Inspect daemon/DPAPI status, purge stale session lock files, and monitor or clear the live system activity log.

### 4. Low-Memory Daemon & IDE Top-Bar Integration
- **Split Daemon / UI Lifecycle:** The `--daemon` process runs the HTTP/SSE server, watchers, and PyQt5 tray icon without importing `QtWebEngineWidgets` (~20–30 MB tray footprint). Opening the window spawns `--ui` on demand; closing to tray terminates the WebEngine process to reclaim 100% of Chromium RAM. Single-instance enforcement uses Win32 named mutexes.
- **Antigravity IDE Top-Bar Watchdog (`scripts/`):** `AntigravityAsarWatchdog` monitors Antigravity's `app.asar` and invokes `scripts/auto_patch_antigravity.js` to inject a live quota indicator pill into the IDE top bar (injecting live via CDP if Antigravity is open, or safely repacking `app.asar` when closed — while preserving `%LOCALAPPDATA%\antigravity-updater`). Includes `scripts/antigravity-drag-daemon.js` for persistent draggable titlebars via `DevToolsActivePort`.

---

## Architecture

```text
.
├── main.py                        # Entry launcher (delegates to app.main)
├── app.py                         # HTTP/SSE server (:28795), PyQt5 tray daemon, on-demand WebEngine UI, AsarWatchdog
├── switcher.py                    # Parallel quota fetcher, Windows DPAPI (AGDPAPI1) & Credential Manager switcher
├── token_tracker.py               # Transcript watcher, SQLite WAL analytics, heatmap/cadence queries, HTML report
├── ui_html.py                     # Static asset loader (source & PyInstaller _MEIPASS / _internal layouts)
├── AntigravityControlCenter.spec  # PyInstaller spec bundling app.py, app_icon.ico, and static/
├── static/                        # Frontend UI (index.html, app.js, styles.css, tailwind.css)
└── scripts/                       # Optional Node.js / VBS helpers for app.asar top-bar pill & CDP drag daemon
```

---

## Installation & Build

### Option A: Standalone Windows `.exe` (Packaged Build)
When packaged via PyInstaller (`AntigravityControlCenter.spec`), **Python, `PyQt5`, `PyQtWebEngine`, and all `static/` UI assets are bundled inside `dist/AntigravityControlCenter/`**. End users running the `.exe` do **not** need Python or any `pip` packages installed.

> **Optional dependency:** **Node.js** is only required if you use the `scripts/` helpers (`auto_patch_antigravity.js` / `antigravity-drag-daemon.js`) for the Antigravity IDE top-bar indicator. The Control Center dashboard, tray daemon, account switcher, quota monitor, and token/session analytics all run natively without Node.js.

### Option B: Run from Source (Windows 10/11)

**Prerequisites:**
- **Windows 10 / 11** (uses Win32 DPAPI, Credential Manager, and named mutexes)
- **Python 3.10+**
- **Node.js** *(optional — only for `scripts/` IDE `app.asar` patching / CDP drag helper)*

```powershell
git clone https://github.com/3bdyna/Antigravity-Control-Center.git
cd Antigravity-Control-Center

pip install PyQt5 PyQtWebEngine
python main.py
```

**CLI Flags:**
- `python main.py --daemon` (or `--tray`, `--minimized`, `--hidden`) — Start only the background tray daemon and local API server (`127.0.0.1:28795`).
- `python main.py --ui` — Launch the frameless WebEngine dashboard (auto-starts `--daemon` if not running).

### Build Standalone `.exe` with PyInstaller

```powershell
pip install pyinstaller
pyinstaller AntigravityControlCenter.spec --noconfirm
```

Output binary: `dist\AntigravityControlCenter\AntigravityControlCenter.exe`.

---

## Local State & Privacy

- All state, DPAPI-encrypted account blobs (`accounts/`), quota cache (`quotas_cache.json`), SQLite history (`tokens_history.db`), and logs (`autopilot.log`, `app_crash.log`) reside locally in `%USERPROFILE%\.gemini\antigravity-switcher\`.
- No third-party telemetry is collected; external requests go solely to Google OAuth / Antigravity quota endpoints for your enrolled accounts, and UI traffic runs strictly on `127.0.0.1:28795`.

**Privacy & Transparency Note:** All account credentials are encrypted per-user locally via Windows DPAPI in `%USERPROFILE%\.gemini\antigravity-switcher\` (never uploaded), and the optional in-IDE top-bar quota indicator uses Node.js (`auto_patch_antigravity.js`) to patch Antigravity's `app.asar` locally.

---

## Optional Companion Tools

These external tools are **not bundled** with Antigravity Control Center. The app works cleanly without them—their dedicated optimizer analytics cards appear automatically only when local telemetry is detected:

- [`INK-Q/agy-fast`](https://github.com/INK-Q/agy-fast) (MIT) — Batched codebase search, outlines, multi-file edits, and concurrent checks.
- [`mksglu/context-mode`](https://github.com/mksglu/context-mode) (Elastic License 2.0) — Sandboxed command execution and context-window compaction telemetry.

---

## Credits & License

Built upon the original [`demusraph/antigravity-control-center`](https://github.com/demusraph/antigravity-control-center) (MIT License) by `@demusraph`. This repository is a heavily redesigned and extended version featuring token analytics, the `app.asar` top-bar watchdog, and a native installer/self-updater, released under the MIT License ([`LICENSE`](LICENSE)).

---

## Keywords

`Google Antigravity` · `Antigravity IDE` · `Antigravity Control Center` · `Multi-Account Switcher` · `AI Quota Monitor` · `Token Tracker` · `LLM Telemetry` · `Prompt Cache Analytics` · `SQLite WAL` · `Windows DPAPI` · `Session Inspector` · `PyQt5` · `PyQtWebEngine` · `agy-fast` · `context-mode` · `MCP`
