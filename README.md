# Antigravity Control Center

**A fast, local-first Windows dashboard for managing Google Antigravity IDE accounts, tracking live 5-hour & weekly quotas, and inspecting real-time token & subagent usage.**

![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6?style=flat-square)
![Version](https://img.shields.io/badge/Version-v1.4.1-2ea44f?style=flat-square)
![Stack](https://img.shields.io/badge/Stack-Python%20%7C%20PyQt5%20%7C%20WebEngine-3776AB?style=flat-square)
![Storage](https://img.shields.io/badge/Storage-SQLite%20WAL%20%2B%20DPAPI-4479A1?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-blue?style=flat-square)

> [!NOTE]
> **Note:** I'm not a professional programmer—this project was vibe-coded with AI because I wanted a cleaner, faster dashboard for my own Antigravity accounts, quotas, and token usage. Expect the occasional feature that is totally *not* a bug.

![Antigravity Control Center — Accounts & Quotas Overview](docs/screenshots/accounts-overview.png)
*Multi-account overview with live 5-hour & weekly quota bars, DPAPI-encrypted storage, smart standby recommendations, and real-time token velocity.*

---

## Why Use It?

Antigravity Control Center pairs a tiny Windows system tray daemon (`~20–30 MB` RAM, local `127.0.0.1:28795` HTTP/SSE server) with an on-demand `PyQtWebEngine` dashboard that frees **100% of Chromium memory** the moment you close it back to the tray.

- **1-Click Multi-Account Switching:** Enroll multiple Google Antigravity accounts via browser OAuth or snapshot your currently active profile straight from Windows Credential Manager. Credentials are encrypted locally at rest with **Windows DPAPI (`AGDPAPI1`)** using atomic writes—no plaintext tokens ever touch disk.
- **Parallel Quota Polling:** Concurrently checks **5-hour cycle** and **weekly quotas** for both **Gemini** and **Claude & GPT** with reset countdowns and automatic recommendations (`Active`, `Active (Low)`, `Recommended`, `Cooldown`, `Standby`), plus optional **Auto-Pilot** switching.
- **Real-Time Token & Session Analytics:** A background transcript watcher saves usage into SQLite (`tokens_history.db`, WAL mode) and streams live updates over SSE—tracking total volume, prompt cache hit rate, I/O ratio, output speed (`tok/s`), 52-week heatmaps, model breakdowns, and subagent fleets. Export anytime to **Executive HTML**, **CSV**, **JSON**, or a point-in-time SQLite backup.
- **Optional IDE Top-Bar Integration:** Built-in `AntigravityAsarWatchdog` can inject a live quota pill right into the Antigravity IDE titlebar (`scripts/auto_patch_antigravity.js` & `scripts/antigravity-drag-daemon.js`) whenever Antigravity IDE and Node.js are installed, while leaving Antigravity's own updater cache (`%LOCALAPPDATA%\antigravity-updater`) untouched.
- **SHA-256 Verified In-App Updates:** Checks GitHub Releases over HTTPS (with trusted-host redirect enforcement), waits for your confirmation before downloading, verifies the installer's SHA-256 checksum via `hmac.compare_digest`, and runs a clean 1-click upgrade.
- **100% Local & Zero Telemetry:** No external analytics or tracking servers. Everything stays inside `%USERPROFILE%\.gemini\antigravity-switcher\`.

---

## Inside the Dashboard

### Token Analytics & Heatmaps
See your lifetime or per-account usage at a glance—across **Today**, **Last 7D**, **Month**, **Year**, or **All Time**—with a 52-week coding activity heatmap, token timeline, 24-hour cadence split (day vs. night), model distribution bars, and a live SQL event log.

![Antigravity Control Center — All-Time Token Analytics](docs/screenshots/token-analytics.png)

### Session & Subagent Fleet Inspector
Inspect individual conversations and background subagent workers turn by turn—monitor context-window headroom before auto-compaction, expand any step to inspect prompt/output/cache breakdowns, check daemon & DPAPI health, or review the system activity log.

![Antigravity Control Center — Session & Subagent Fleet Inspector](docs/screenshots/session-fleet-inspector.png)

---

## Download & Install (Windows 10/11)

### Option A: Windows Installer *(Recommended)*
1. Download the latest **`AntigravityControlCenter-Setup-*.exe`** from [**GitHub Releases**](https://github.com/3bdyna/Antigravity-Control-Center/releases/latest).
2. Run the installer (per-user install into `%LOCALAPPDATA%\Programs\AntigravityControlCenter\`, no admin rights needed).
   - **Windows SmartScreen Note:** Because this is an unsigned indie installer, Windows Defender SmartScreen may show a *"Windows protected your PC"* prompt. Click **More info** → **Run anyway** to continue.

> [!TIP]
> **No Python or Node.js required:** The installer includes everything needed for the account switcher, quota tracker, tray daemon, and analytics dashboard. **Node.js** is only needed if you want the optional Antigravity IDE top-bar quota pill (`scripts/`).

### Option B: Run from Source

**Prerequisites:** Windows 10/11, Python 3.10+, and *(optional)* Node.js for the IDE top-bar patcher.

```powershell
git clone https://github.com/3bdyna/Antigravity-Control-Center.git
cd Antigravity-Control-Center

pip install PyQt5 PyQtWebEngine
python main.py
```

**Helpful CLI Flags:**
- `python main.py --daemon` *(or `--tray`, `--minimized`, `--hidden`)* — Start only the background tray daemon and local API server (`127.0.0.1:28795`).
- `python main.py --ui` — Open the frameless WebEngine dashboard (auto-starts `--daemon` if needed).

### Build Standalone `.exe` Locally

```powershell
pip install pyinstaller
pyinstaller AntigravityControlCenter.spec --noconfirm
```

Output binary: `dist\AntigravityControlCenter\AntigravityControlCenter.exe`.

---

## Recommended Companion Tools *(Optional)*

If you want to cut down token burn and speed up Antigravity coding sessions, Control Center pairs really well with these two open-source MCP tools:

- **[`context-mode`](https://github.com/mksglu/context-mode)** *(Elastic License 2.0)* — Sandboxes heavy command outputs and compacts context-window usage so long sessions stay lean and burn fewer tokens.
- **[`agy-fast`](https://github.com/INK-Q/agy-fast)** *(MIT License)* — Batches codebase search, file outlines, multi-file edits, and concurrent checks to cut round-trips and speed up Antigravity workflows.

> **Not Bundled & Zero Clutter:** Neither tool is bundled—install them separately from their own repositories if you'd like to try them. Control Center **automatically detects** them when installed and shows live token-savings and batching cards on your dashboard. If you don't use them, those cards stay **completely hidden** so your layout stays clean.

---

## Privacy & `app.asar` Patcher Disclosure

- **Local-First Storage:** All DPAPI-encrypted account blobs (`accounts/`), quota cache (`quotas_cache.json`), SQLite token history (`tokens_history.db`), and logs (`autopilot.log`, `app_crash.log`) stay strictly on your machine in `%USERPROFILE%\.gemini\antigravity-switcher\`.
- **Network Scope:** External requests go solely to Google OAuth / Antigravity quota endpoints for your enrolled accounts (plus optional GitHub Releases update checks). Dashboard UI traffic runs strictly on `127.0.0.1:28795`.
- **Optional IDE Patcher:** If enabled, the top-bar quota indicator uses Node.js (`scripts/auto_patch_antigravity.js`) to inject a live quota pill via CDP or repack Antigravity's local `app.asar` when the IDE is closed. You can use Control Center purely as a standalone switcher and analytics dashboard without using the patcher.

---

## Inspiration & Credits

This project was originally inspired by and built upon **[`demusraph/antigravity-control-center`](https://github.com/demusraph/antigravity-control-center)** (MIT License) by `@demusraph`. Huge thanks to `@demusraph` for the original concept—this repository has since been heavily redesigned and expanded with parallel quota polling, real-time SQLite token analytics, session/subagent inspection, an optional `app.asar` top-bar watchdog, and a native installer with SHA-256 verified auto-updates.

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
├── scripts/                       # Optional Node.js / VBS helpers for app.asar top-bar pill & CDP drag daemon
└── docs/screenshots/              # Redacted README screenshots
```
