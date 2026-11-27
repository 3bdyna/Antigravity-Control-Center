# Antigravity Control Center — Project Knowledge & Agent Guidelines

## Overview
Windows desktop Control Center (PyQt5 + PyQtWebEngine + local HTTP/SSE server on `127.0.0.1:28795`) for managing Antigravity accounts, parallel quota polling, real-time token/session analytics, and Antigravity UI integration.

## Repository Structure
- `main.py` — Entry point launcher (`from app import main`).
- `version.py` — Single source of truth for `APP_VERSION`, `GITHUB_REPO`, `is_frozen()`, `user_data_dir()`, `updates_dir()`, and `cleanup_old_installers()`.
- `updater.py` — Stdlib-only GitHub Releases self-updater with HTTPS/trusted-host redirect enforcement, SHA-256 verification (`hmac.compare_digest`), atomic staging, and detached silent installer launch.
- `app.py` — Core HTTP/SSE server (`PORT = 28795`), Windows tray daemon, PyQt5 WebEngine UI window, `AntigravityAsarWatchdog`, in-app update API (`/api/update/*`), and single-instance mutex management (`Local\AntigravityControlCenterDaemon`, `Local\AntigravityControlCenterUI`).
- `switcher.py` — Parallel quota engine, Windows DPAPI credential storage (`AGDPAPI1`), account switching, and quota disk caching.
- `token_tracker.py` — Background transcript watcher persisting token usage and session metrics to SQLite (`tokens_history.db`, WAL mode).
- `ui_html.py` — Static asset loader resolving `static/` across source and PyInstaller (`_MEIPASS` / `_internal`) layouts.
- `static/` — Frontend UI assets (`index.html`, `app.js`, `styles.css`, `tailwind.css`).
- `installer/AntigravityControlCenter.iss` — Inno Setup 6 per-user installer script (`PrivilegesRequired=lowest`, fixed `AppId`, canonical install dir, mutex wait loop).
- `scripts/` — Companion runtime & release scripts:
  - `build_release.ps1` — 1-click local release build, in-place local installer (`-InstallLocal`, `-SkipLocalInstall`), & optional GitHub Releases publisher (`-Publish`, `-SkipTests`, `-SkipBuild`).
  - `auto_patch_antigravity.js` — Patches Antigravity `app.asar` to inject the quota top-bar indicator (invoked by `AntigravityAsarWatchdog` in `app.py`).
  - `antigravity-drag-daemon.js` — CDP (`DevToolsActivePort`) daemon keeping draggable titlebars and the quota indicator active.
  - `antigravity_drag_daemon.pyw`, `run_daemon.vbs`, `start-drag-daemon.vbs` — Silent Windows launchers for the drag daemon.
- `tests/test_release.py` — Automated guardrail unit tests for version metadata, updater security, installer mutex/`AppId`/data-safety parity, and privacy checks.
- `AntigravityControlCenter.spec` — PyInstaller build spec (`app.py`, `app_icon.ico`, `static/`).

## Runtime & Deployment Paths
- **Installed binary (canonical per-user install dir):** `%LOCALAPPDATA%\Programs\AntigravityControlCenter\AntigravityControlCenter.exe`
- **Deployed companion scripts:** `%LOCALAPPDATA%\Programs\AntigravityControlCenter\` (`auto_patch_antigravity.js`, `antigravity-drag-daemon.js`, `.vbs`, `.pyw`) — bundled automatically by the Inno Setup installer.
- **User state, SQLite DB & updates cache:** `%USERPROFILE%\.gemini\antigravity-switcher\` (`accounts/`, `active_email.txt`, `quotas_cache.json`, `tokens_history.db`, `autopilot.log`, `app_crash.log`, `updates/`)

## Build, Test & Release Workflow
1. Run from source for quick testing:
   ```powershell
   python main.py
   ```
2. Run automated guardrail unit tests:
   ```powershell
   $env:PYTHONPATH=".;tests"; python -m unittest test_release -v
   ```
3. Build local installer & `SHA256SUMS.txt` (outputs to `dist\release\`):
   ```powershell
   .\scripts\build_release.ps1
   ```
4. Publish a GitHub Release (ONLY when explicitly requested):
   ```powershell
   .\scripts\build_release.ps1 -Publish
   ```

## Architectural & Safety Rules
1. **Preserve DPAPI & Atomic Writes:** Always use `atomic_write_bytes` / `atomic_write_text` in `switcher.py` for credential and cache files; never write plaintext credentials outside DPAPI blobs.
2. **Never Break Official Auto-Updater:** In `scripts/auto_patch_antigravity.js`, preserve `cleanUpdaterCache()` as a no-op; never delete `%LOCALAPPDATA%\antigravity-updater`.
3. **Single-Instance & Low-Memory Tray:** Keep Windows Named Mutex checks (`Local\AntigravityControlCenterDaemon`, `Local\AntigravityControlCenterUI`), safe handle release, and working-set trimming intact so duplicate daemons do not spawn and silent upgrades can replace binaries cleanly.
4. **No Hardcoded Secrets or Personal Paths in Git:** Never commit personal tokens, `accounts/` folders, `tokens_history.db`, `quotas_cache.json`, or hardcoded `C:\Users\<username>` paths.
5. **Process & Timeout Discipline:** All HTTP/network/subprocess calls must use explicit timeouts and clean up background threads/processes deterministically.
6. **Release & Updater Guardrails:**
   - **Explicit Release Gate:** NEVER bump `version.APP_VERSION`, create git tags, or run `.\scripts\build_release.ps1 -Publish` unless explicitly requested by the user.
   - **Fixed Inno Setup `AppId`:** Never change `AppId={{6E3A9B14-7C2D-4F8A-9B51-2D8E4C7A1F03}}` in `installer/AntigravityControlCenter.iss`, and never delete or modify `%USERPROFILE%\.gemini\antigravity-switcher` during install/uninstall.
   - **Mutex & Security Parity:** Keep `DAEMON_MUTEX_NAME` / `UI_MUTEX_NAME` in `app.py` identical to `installer/AntigravityControlCenter.iss`, keep TLS verification enabled, enforce HTTPS + `TRUSTED_DOWNLOAD_HOSTS` on every redirect hop, verify SHA-256 via `hmac.compare_digest` before renaming `.part` -> `.exe`, and never accept installer paths from client HTTP requests.
   - **Smart Local App Updates:** Skip rebuilds for docs-only edits (`README.md`, `AGENTS.md`, `LICENSE`). While iterating on quick UI/small tweaks, you may batch local rebuilds unless the user asks to test the installed app now. When finishing a feature or ready to apply locally (after verification & commit/push):
     - For UI/static/script-only edits (`static/*` or companion `scripts/*`), run `.\scripts\build_release.ps1 -SkipTests -InstallLocal -StaticOnly` (~5s fast sync).
     - For Python/code edits, run `.\scripts\build_release.ps1 -SkipTests -InstallLocal` (fast mirror sync without Inno Setup).
   - **Smart Verification & 2-Word Publish Workflow (`publish update`):**
     - **Quick / iterative edits:** Run targeted syntax checks (`python -m py_compile` / `node --check`) on touched files, then commit and push to `origin/main`. Never bump `version.py`, create tags, or run `-Publish`.
     - **Critical changes (updater, DPAPI/auth, packaging, installer) or `"publish update"`:** Always run full guardrail tests (`$env:PYTHONPATH=".;tests"; python -m unittest test_release -v`). On `"publish update"`, if tag `v<APP_VERSION>` already exists on GitHub, auto-bump the patch version in `version.py`, run full tests, commit & push to `origin/main`, and run `.\scripts\build_release.ps1 -Publish`.
7. **Auto-Commit & Push After Updates:** After completing and verifying any code or config update, stage the changed files (excluding secrets/state listed in rule 4), commit with a clear message, and push to `origin/main` automatically.
