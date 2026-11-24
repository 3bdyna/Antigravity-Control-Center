# Antigravity Control Center

**Multi-account switcher, live quota tracker, and real-time token & session analytics dashboard for Google Antigravity IDE on Windows.**

![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6?style=flat-square)
![Version](https://img.shields.io/badge/Version-v1.4.0-2ea44f?style=flat-square)
![Stack](https://img.shields.io/badge/Stack-Python%20%7C%20PyQt5%20%7C%20WebEngine-3776AB?style=flat-square)
![Storage](https://img.shields.io/badge/Storage-SQLite%20WAL%20%2B%20DPAPI-4479A1?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-blue?style=flat-square)

> [!NOTE]
> **Note:** I'm not a professional programmer. This project was vibe-coded with AI because I wanted a cleaner, faster dashboard for my own Antigravity accounts, quotas, and token usage. Expect the features that totally are NOT bugs.

---

## What It Does & Key Features

**Antigravity Control Center** pairs a lightweight Windows system tray daemon (`~20–30 MB` RAM, local `127.0.0.1:28795` HTTP/SSE server) with an on-demand `PyQtWebEngine` dashboard that frees 100% of Chromium memory when closed to the tray.

- **Multi-Account Switcher (DPAPI-Encrypted):** Enroll multiple Google Antigravity accounts, snapshot active profiles from Windows Credential Manager, and switch accounts in 1 click from the dashboard or tray menu. All credentials are encrypted locally at rest with Windows DPAPI (`AGDPAPI1`) using atomic file writes—no plaintext tokens are ever stored.
- **Parallel Quota Polling:** Concurrently checks **5-hour cycle** and **weekly model quotas** (Gemini & Claude) with reset countdowns and smart recommendations (`Active`, `Active (Low)`, `Recommended`, `Cooldown`, `Standby`) across all enrolled accounts.
- **Real-Time Token & Session Analytics:** Background transcript watcher persists usage into SQLite (`tokens_history.db`, WAL mode) and streams live updates via SSE. Track **Total Volume**, **Prompt Cache Hit %**, **I/O Ratio**, **Output Speed** (`tok/s`), **52-week activity heatmaps**, turn-by-turn token breakdowns, and active subagent fleets—plus export to **Executive HTML**, **CSV**, **JSON**, or SQLite backup.
- **Antigravity IDE Top-Bar Integration:** Built-in `AntigravityAsarWatchdog` automatically injects a live quota pill into the Antigravity IDE titlebar (`scripts/auto_patch_antigravity.js` & `scripts/antigravity-drag-daemon.js`) whenever Antigravity IDE and Node.js are present, while leaving Antigravity's own updater cache (`%LOCALAPPDATA%\antigravity-updater`) untouched.
- **Built-In SHA-256 Verified Auto-Updater:** Automatically checks GitHub Releases over HTTPS (with trusted-host redirect enforcement) and waits for you to click **"Download & Install"**, then verifies the installer's SHA-256 checksum via `hmac.compare_digest` before running a 1-click no-wizard in-place upgrade.
- **100% Local & Zero Telemetry:** No external analytics or tracking servers. All state lives in `%USERPROFILE%\.gemini\antigravity-switcher\`.

---

## Download & Install (Windows 10/11)

### Option A: Windows Installer (Recommended)
1. Download the latest **`AntigravityControlCenter-Setup-*.exe`** from [**GitHub Releases**](https://github.com/3bdyna/Antigravity-Control-Center/releases/latest).
2. Run the installer (per-user install into `%LOCALAPPDATA%\Programs\AntigravityControlCenter\`, no admin rights required).
   - **Windows SmartScreen Note:** Because this is an unsigned indie installer, Windows Defender SmartScreen may show a *"Windows protected your PC"* prompt. Click **More info** → **Run anyway** to proceed.

> **Optional Dependency:** **Node.js** is only needed if you enable the optional Antigravity IDE top-bar quota indicator (`scripts/`). The account switcher, quota tracker, tray daemon, and token analytics dashboard all work out of the box without Python or Node.js.

### Option B: Run from Source

**Prerequisites:** Windows 10/11, Python 3.10+, and *(optional)* Node.js for the IDE top-bar patcher.

```powershell
git clone https://github.com/3bdyna/Antigravity-Control-Center.git
cd Antigravity-Control-Center

pip install PyQt5 PyQtWebEngine
python main.py
```

**CLI Flags:**
- `python main.py --daemon` *(or `--tray`, `--minimized`, `--hidden`)* — Run only the background tray daemon and local API server (`127.0.0.1:28795`).
- `python main.py --ui` — Open the frameless WebEngine dashboard (auto-starts `--daemon` if needed).

### Build Standalone `.exe` Locally

```powershell
pip install pyinstaller
pyinstaller AntigravityControlCenter.spec --noconfirm
```

Output binary: `dist\AntigravityControlCenter\AntigravityControlCenter.exe`.

---

## Recommended Companion Tools (Optional)

If you want to cut down token burn and speed up Antigravity coding sessions, I strongly recommend pairing Control Center with these two open-source MCP tools:

- **[`context-mode`](https://github.com/mksglu/context-mode)** *(Elastic License 2.0)* — Sandboxes heavy command outputs and compacts context-window usage so long sessions stay lean and burn fewer tokens.
- **[`agy-fast`](https://github.com/INK-Q/agy-fast)** *(MIT License)* — Batches codebase search, file outlines, multi-file edits, and concurrent checks to cut round-trips and speed up Antigravity workflows.

> **Not Bundled & Zero Clutter:** Neither tool is bundled with Antigravity Control Center—install them separately from their own repositories if you want them. Control Center **automatically detects** them when installed and surfaces live token-savings and batching activity cards on your dashboard. If you don't use them, those cards stay **completely hidden** so your layout stays clean.

---

## Privacy & `app.asar` Patcher Disclosure

- **Local-First Storage:** All DPAPI-encrypted account blobs (`accounts/`), quota cache (`quotas_cache.json`), SQLite token history (`tokens_history.db`), and logs (`autopilot.log`, `app_crash.log`) stay strictly on your machine in `%USERPROFILE%\.gemini\antigravity-switcher\`.
- **Network Scope:** External traffic goes solely to Google OAuth / Antigravity quota endpoints for your enrolled accounts (plus optional GitHub Releases update checks). Dashboard UI traffic runs strictly on `127.0.0.1:28795`.
- **Optional IDE Patcher:** If enabled, the top-bar quota indicator uses Node.js (`scripts/auto_patch_antigravity.js`) to inject a live quota pill via CDP or repack Antigravity's local `app.asar` when the IDE is closed. You can use Control Center purely as a standalone switcher and analytics dashboard without using the patcher.

---

## Inspiration & Credits

This project was originally inspired by and built upon **[`demusraph/antigravity-control-center`](https://github.com/demusraph/antigravity-control-center)** (MIT License) by `@demusraph`. Huge thanks to `@demusraph` for starting the original concept—this repository has since been heavily redesigned and expanded with parallel quota polling, real-time SQLite token analytics, session/subagent inspection, an optional `app.asar` top-bar watchdog, and a native installer with SHA-256 verified auto-updates.

Released under the **MIT License** — see [`LICENSE`](LICENSE).

---

## Architecture

```text
.
├── main.py                        # Entry launcher (delegates to app.main)
├── app.py                         # HTTP/SSE server (:28795), PyQt5 tray daemon, on-demand WebEngine UI, AsarWatchdog
├── switcher.py                    # Parallel quota fetcher, Windows DPAPI (AGDPAPI1) & Credential Manager switcher
├── token_tracker.py               # Transcript watcher, SQLite WAL analytics, heatmap/cadence queries, HTML report
├── updater.py                     # HTTPS + SHA-256 verified GitHub Releases self-updater
├── version.py                     # App version & user-data/update directory helpers
├── ui_html.py                     # Static asset loader (source & PyInstaller _MEIPASS / _internal layouts)
├── AntigravityControlCenter.spec  # PyInstaller spec bundling app.py, app_icon.ico, and static/
├── installer/                     # Inno Setup 6 per-user installer script
├── static/                        # Frontend UI (index.html, app.js, styles.css, tailwind.css)
└── scripts/                       # Optional Node.js / VBS helpers for app.asar top-bar pill & CDP drag daemon
```
