---
name: publish-release
description: >-
  Use this skill when building, packaging, updating the local installed app
  (`-InstallLocal` / `-StaticOnly`), publishing a GitHub release (`"publish update"`),
  or editing Antigravity Control Center's installer (`installer/AntigravityControlCenter.iss`),
  PyInstaller spec, release script (`scripts/build_release.ps1`), or self-updater (`updater.py`).
---

# Antigravity Control Center Release, Installer & Updater Runbook

## Commands
- **Run guardrail unit tests:** `$env:PYTHONPATH=".;tests"; python -m unittest test_release -v`
- **Fast local sync for UI/static/script-only edits (`static/*` or companion `scripts/*`, ~5s):**
  `.\scripts\build_release.ps1 -SkipTests -InstallLocal -StaticOnly`
- **Local install for Python/code edits (fast mirror sync without Inno Setup):**
  `.\scripts\build_release.ps1 -SkipTests -InstallLocal`
- **Full local installer & `SHA256SUMS.txt` build (outputs to `dist\release\`):**
  `.\scripts\build_release.ps1`
- **Publish GitHub Release (ONLY when user says `"publish update"`):**
  `.\scripts\build_release.ps1 -Publish`

## 2-Word Publish Workflow (`"publish update"`)
1. Check if tag `v<APP_VERSION>` already exists on GitHub; if so, auto-bump the patch version in `version.py`.
2. Run full guardrail unit tests (`$env:PYTHONPATH=".;tests"; python -m unittest test_release -v`).
3. Stage (excluding secrets/user state), commit, and push to `origin/main`.
4. Run `.\scripts\build_release.ps1 -Publish`.

## Smart Local App Updates
- Skip rebuilds for docs-only edits (`README.md`, `AGENTS.md`, `LICENSE`).
- While iterating on quick UI/small tweaks, batch local rebuilds unless the user asks to test the installed app now.
- When finishing a feature or ready to apply locally (after verification & commit/push), use `-StaticOnly` for `static/*`/companion scripts or `-SkipTests -InstallLocal` for Python changes.

## Release, Installer & Updater Guardrails (DO NOT BREAK)
1. **Explicit Release Gate:** NEVER bump `version.APP_VERSION`, create git tags, or run `-Publish` unless explicitly requested by the user.
2. **Fixed Inno Setup `AppId`:** Never change `AppId={{6E3A9B14-7C2D-4F8A-9B51-2D8E4C7A1F03}}` in `installer/AntigravityControlCenter.iss`, and never delete or modify `%USERPROFILE%\.gemini\antigravity-switcher` during install/uninstall.
3. **Mutex & Security Parity:** Keep `DAEMON_MUTEX_NAME` (`Local\AntigravityControlCenterDaemon`) and `UI_MUTEX_NAME` (`Local\AntigravityControlCenterUI`) in `app.py` identical to `installer/AntigravityControlCenter.iss`.
4. **Updater Security:** Keep `updater.py` stdlib-only, keep TLS verification enabled, enforce HTTPS + `TRUSTED_DOWNLOAD_HOSTS` on every redirect hop, verify SHA-256 via `hmac.compare_digest` before renaming `.part` -> `.exe`, and never accept installer paths from client HTTP requests.
5. **Installed Paths:** Binary installs to `%LOCALAPPDATA%\Programs\AntigravityControlCenter\AntigravityControlCenter.exe` alongside bundled companion scripts (`auto_patch_antigravity.js`, `antigravity-drag-daemon.js`, `.vbs`, `.pyw`).
