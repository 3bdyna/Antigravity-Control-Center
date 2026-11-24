# Antigravity Control Center

A lightweight **Windows desktop dashboard and system tray companion for Google Antigravity IDE**. Manage multiple Google accounts with one-click switching, track live 5-hour and weekly AI model quotas, explore real-time token analytics and coding heatmaps, and inspect active agent sessions — all from a fast, local-first Control Center.

![Platform](https://img.shields.io/badge/Platform-Windows-0078D6?style=flat-square)
![Version](https://img.shields.io/badge/Version-v1.4.0-2ea44f?style=flat-square)
![Python](https://img.shields.io/badge/Python-PyQt5%20%2B%20WebEngine-3776AB?style=flat-square)
![Storage](https://img.shields.io/badge/Storage-SQLite%20WAL%20%2B%20DPAPI-4479A1?style=flat-square)

---

## Why Use It?

Using **Google Antigravity IDE** across multiple accounts or long coding sessions makes it easy to lose track of rate limits, reset timers, and token usage. **Antigravity Control Center** gives you a single cockpit that sits quietly in your Windows system tray and opens instantly whenever you want to:

- **See your remaining Gemini & Claude quotas** across every enrolled account at a glance.
- **Switch accounts in one click** without manually logging in and out or losing track of which profile is active.
- **Geek out on your coding telemetry** — live token burn rate (`tok/s` and `tok/h`), prompt cache hit rate, 52-week coding streaks, and 24-hour day/night productivity charts.
- **Inspect live AI sessions & subagents** — check context window headroom, auto-compaction counts, and turn-by-turn token breakdowns.

---

## Key Features

### 1. Multi-Account Switcher & Quota Monitor
- **Parallel Quota Polling:** Fetches **5-hour cycle** and **weekly quota** percentages with local reset countdowns across all enrolled accounts simultaneously.
- **Smart Account Recommendations:** Highlights whether your active account is healthy, low on quota, on cooldown, or ready for a better standby fallback based on remaining capacity and upcoming weekly reset urgency.
- **One-Click Switching:** Swaps the active `gemini:antigravity` session in Windows Credential Manager and reloads/restarts Antigravity cleanly — accessible from the dashboard or right from the **system tray menu**.
- **Easy Enrollment:** Snapshot your currently signed-in Antigravity profile in one click, or authorize additional Google accounts via the built-in browser OAuth flow.
- **Windows DPAPI Encryption:** Saved credential blobs are encrypted locally with Windows DPAPI (`AGDPAPI1`).

### 2. Token Analytics & Activity Heatmaps
- **Real-Time SQLite Tracking:** A background transcript watcher tails local Antigravity session logs into a local `tokens_history.db` (SQLite WAL mode) and pushes live updates over Server-Sent Events (SSE).
- **Core KPIs:** Track **Total Token Volume**, **Prompt Cache Hit %** (saved quota bandwidth), **Input/Output Volume Ratio**, and **Average Output Speed** (`tok/s`, `tok/min`, `tok/h`). Filter by **Today**, **Last 7D**, **Month**, **Year**, or **All Time**, per account or combined.
- **52-Week Coding Heatmap & Streaks:** GitHub-style activity heatmap showing daily token volume, turns, current streak, active days, and top model per day.
- **Timeline & 24-Hour Cadence:** Inspect daily distribution bars alongside a 24-hour local-time chart comparing day vs. night coding windows.
- **Model Split & Live Event Log:** See token share by model and browse recent SQL-logged turns.
- **Optimizer Telemetry:** Dedicated cards tracking savings and daily activity from `context-mode` (tokens shielded & sandboxed bytes) and `agy-fast` MCP (batched ops & turns saved).
- **Exports & Backups:** Generate a standalone **Executive HTML Report**, download raw events as **CSV** or **JSON**, or create an instant point-in-time **SQLite DB backup**.

### 3. Session & Fleet Inspector
- **Live Conversation & Subagent Fleet:** Switch between active main conversations and optional background subagent workers.
- **Context Window & Compaction Tracking:** Monitor active context volume against the context limit (e.g., `512k`), compaction count, and prompt cache acceleration.
- **Expandable Turn Explorer:** Click any step in a conversation to inspect prompt, output, cache hit, total tokens, and efficiency per turn.
- **Maintenance Tools:** View daemon and DPAPI health, clean stale session lock files, and inspect or clear the live system activity log.

### 4. Lightweight System Tray & Antigravity IDE Top-Bar Indicator
- **Low-Memory Architecture:** The background tray daemon handles the local HTTP/SSE server (`127.0.0.1:28795`), transcript watcher, and tray menu without loading Chromium. The frameless `PyQtWebEngine` window launches on demand (`--ui`) and frees its Chromium RAM when closed to the tray.
- **IDE Top-Bar Integration (`scripts/`):** Includes `auto_patch_antigravity.js` (watched by `AntigravityAsarWatchdog`) to inject a live quota status pill directly into Antigravity's top bar and keep it working after IDE updates (without interfering with the official `antigravity-updater`), plus `antigravity-drag-daemon.js` for draggable titlebars via CDP (`DevToolsActivePort`).

---

## Project Structure

```text
.
├── main.py                        # Entry point launcher
├── app.py                         # HTTP/SSE server (:28795), system tray daemon, PyQtWebEngine UI, ASAR watchdog
├── switcher.py                    # Parallel quota engine, Windows DPAPI credential storage, account switcher
├── token_tracker.py               # Real-time transcript watcher, SQLite WAL analytics, HTML report generator
├── ui_html.py                     # Static asset resolver (source & PyInstaller bundles)
├── AntigravityControlCenter.spec  # PyInstaller Windows build specification
├── static/                        # Frontend dashboard (index.html, app.js, styles.css, tailwind.css)
└── scripts/                       # Optional Antigravity IDE top-bar indicator & window-drag helpers
```

---

## Getting Started (Windows)

### Prerequisites
- **OS:** Windows 10 or Windows 11 (uses Windows DPAPI, Windows Credential Manager, and Win32 named mutexes)
- **Python:** Python 3.10+ with `PyQt5` and `PyQtWebEngine`
- **Optional:** Node.js (only needed if using the `scripts/` JS helpers for IDE `app.asar` patching or the CDP drag daemon)

### Run from Source

1. Clone the repository:
   ```powershell
   git clone https://github.com/3bdyna/Antigravity-Control-Center.git
   cd Antigravity-Control-Center
   ```

2. Install the UI dependencies:
   ```powershell
   pip install PyQt5 PyQtWebEngine
   ```

3. Launch the Control Center:
   ```powershell
   python main.py
   ```
   Useful launch flags:
   - `python main.py --daemon` — Start only the lightweight system tray & API server in the background.
   - `python main.py --ui` — Open the Control Center window (starts the daemon automatically if needed).

### Build Standalone Windows `.exe`

```powershell
pip install pyinstaller
pyinstaller AntigravityControlCenter.spec --noconfirm
```

The compiled application bundle is output to `dist/AntigravityControlCenter/AntigravityControlCenter.exe`.

---

## Privacy & Local Data

All data stays on your machine:
- Local state, encrypted account credentials (`accounts/`), quota cache (`quotas_cache.json`), and token history (`tokens_history.db`) are stored under `%USERPROFILE%\.gemini\antigravity-switcher\`.
- No analytics or credentials are sent to any third-party server — API calls are made solely to Google OAuth / Antigravity endpoints for your own enrolled accounts and locally on `127.0.0.1:28795`.

---

## Keywords

`Google Antigravity` · `Antigravity IDE` · `Antigravity Control Center` · `Multi-Account Switcher` · `AI Quota Monitor` · `Token Tracker` · `LLM Usage Analytics` · `Prompt Cache Analytics` · `Coding Heatmap` · `Session Inspector` · `Windows System Tray` · `PyQt5` · `SQLite` · `DPAPI`
