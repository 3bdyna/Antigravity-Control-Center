"""
Antigravity Control Center - Core Application Server & Tray GUI.
Streamlined, fast, memory-optimized 3-page Control Center with background token tracking.
"""
import os
import sys

# Suppress console handles if launched via windowed mode
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')

if sys.platform == 'win32':
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        for std_id in (-10, -11, -12):
            h = kernel32.GetStdHandle(std_id)
            if not h or h == -1:
                h_nul = kernel32.CreateFileW('NUL', 0xC0000000, 3, None, 3, 0, None)
                kernel32.SetStdHandle(std_id, h_nul)
    except Exception:
        pass
import gzip
import json
import queue
import time
import shutil
import urllib.parse
import threading
import subprocess
import socketserver
import http.server
from datetime import datetime, timezone
import traceback

def _global_excepthook(exctype, value, tb):
    try:
        switcher_d = os.path.join(os.environ.get("USERPROFILE", ""), ".gemini", "antigravity-switcher")
        with open(os.path.join(switcher_d, "app_crash.log"), "a", encoding="utf-8") as f:
            f.write(f"\n--- UNCAUGHT EXCEPTION AT {datetime.now()} ---\n")
            traceback.print_exception(exctype, value, tb, file=f)
    except Exception:
        pass
sys.excepthook = _global_excepthook

# Local modules
from switcher import (
    _QUOTA_LOCK,
    _QUOTA_CACHE,
    _QUOTA_CACHE_TIME,
    CACHE_TTL,
    save_quota_disk_cache,
    get_saved_accounts,
    get_active_email,
    save_active_credential,
    switch_to_account,
    reload_language_server,
    fetch_all_quotas_parallel,
    fetch_quota_summary,
    get_account_meta_info,
    get_account_dir,
    write_cred_blob,
    atomic_write_text,
    score_account,
    evaluate_account_recommendations,
    clear_session_cache,
    ensure_dirs,
    restart_antigravity,
    LOG_FILE,
    ACCOUNTS_DIR,
    SWITCHER_DIR,
    ACTIVE_FILE,
    CLIENT_ID,
    CLIENT_SECRET
)
from token_tracker import (
    BackgroundTokenWatcher,
    get_token_summary,
    get_all_events,
    get_db_connection,
    init_db,
    get_daily_heatmap,
    get_hourly_productivity,
    get_recent_sessions,
    get_session_turns,
    get_context_stats,
    backup_sqlite_db,
    generate_executive_html_report,
    get_context_mode_stats,
    get_agy_fast_stats,
    is_ai_generating
)
from ui_html import load_static_bytes
from version import APP_VERSION, GITHUB_REPO, is_frozen, updates_dir, cleanup_old_installers
import updater

PORT = 28795
AUTOPILOT_RUNNING = False
AUTOPILOT_STATUS_TEXT = "Disabled (Safe Single-Account Mode)"
TRAY_MENU_UPDATE_CB = None
SHOW_UI_CB = None
QUIT_DAEMON_CB = None
TRAY_ICON = None
TRAY_MENU = None

MAX_LOG_BYTES = 512 * 1024  # Rotate autopilot.log at 512 KB
_LOG_LOCK = threading.Lock()
_SSE_LOCK = threading.Lock()
_SSE_CLIENTS = []
_UI_SSE_CLIENTS = set()
_SHOW_ACK = threading.Event()

_UPDATE_LOCK = threading.Lock()
_UPDATE_CANCEL_EVENT = threading.Event()
_UPDATE_STATE = {
    "status": "idle",
    "current_version": APP_VERSION,
    "latest_version": "",
    "release_notes": "",
    "release_url": f"https://github.com/{GITHUB_REPO}/releases",
    "progress_pct": 0,
    "is_frozen": is_frozen(),
    "error": "",
    "has_installer": False,
}
_UPDATE_INTERNAL = {
    "verified_installer_path": "",
    "release_info": None,
}


def _get_public_update_status():
    """Return a thread-safe copy of public update state (never exposes internal paths)."""
    with _UPDATE_LOCK:
        state = dict(_UPDATE_STATE)
        state["current_version"] = APP_VERSION
        state["is_frozen"] = is_frozen()
        return state


def _start_update_check(silent=False):
    """Trigger a non-blocking GitHub Releases check in a background daemon thread."""
    with _UPDATE_LOCK:
        if _UPDATE_STATE["status"] in ("checking", "downloading"):
            return False
        if not silent:
            _UPDATE_STATE["status"] = "checking"
            _UPDATE_STATE["error"] = ""
            _UPDATE_STATE["progress_pct"] = 0

    if not silent:
        broadcast_event("update")

    def _worker():
        try:
            info = updater.check_for_updates(timeout=8.0)
            with _UPDATE_LOCK:
                _UPDATE_INTERNAL["release_info"] = info
                _UPDATE_INTERNAL["verified_installer_path"] = ""
                _UPDATE_STATE["latest_version"] = info.get("latest_version", "")
                _UPDATE_STATE["release_notes"] = info.get("release_notes", "")
                _UPDATE_STATE["release_url"] = info.get("release_url") or f"https://github.com/{GITHUB_REPO}/releases"
                _UPDATE_STATE["progress_pct"] = 0
                _UPDATE_STATE["error"] = ""
                _UPDATE_STATE["has_installer"] = bool(info.get("asset_url") and info.get("checksums_url"))
                _UPDATE_STATE["status"] = "available" if info.get("update_available") else "up_to_date"
            broadcast_event("update")
        except Exception as e:
            with _UPDATE_LOCK:
                if silent:
                    if _UPDATE_STATE["status"] == "checking":
                        _UPDATE_STATE["status"] = "idle"
                    _UPDATE_STATE["error"] = ""
                else:
                    _UPDATE_STATE["status"] = "error"
                    _UPDATE_STATE["error"] = str(e)
            if not silent:
                log_msg(f"[Updater] Check failed: {e}")
                broadcast_event("update")

    threading.Thread(target=_worker, daemon=True, name="UpdateChecker").start()
    return True


def _start_update_download():
    """Download and verify the latest release installer in a background daemon thread."""
    if not is_frozen():
        return {
            "ok": False,
            "error": "In-app update downloads are only enabled in the installed app (currently running from source in dev mode).",
        }

    with _UPDATE_LOCK:
        if _UPDATE_STATE["status"] == "downloading":
            return {"ok": True, "status": "downloading"}
        rel = _UPDATE_INTERNAL.get("release_info")
        if not rel or not rel.get("update_available"):
            return {
                "ok": False,
                "error": "You are already running the latest version.",
            }
        if not rel.get("asset_url") or not rel.get("checksums_url"):
            return {
                "ok": False,
                "error": "No verified Windows installer asset is available for this release. Check for updates or visit GitHub Releases.",
            }
        rel_copy = dict(rel)
        _UPDATE_CANCEL_EVENT.clear()
        _UPDATE_INTERNAL["verified_installer_path"] = ""
        _UPDATE_STATE["status"] = "downloading"
        _UPDATE_STATE["progress_pct"] = 0
        _UPDATE_STATE["error"] = ""

    broadcast_event("update")

    def _worker():
        last_broadcast_pct = -1

        def _on_progress(pct):
            nonlocal last_broadcast_pct
            with _UPDATE_LOCK:
                _UPDATE_STATE["progress_pct"] = int(pct)
            if pct >= 100 or abs(pct - last_broadcast_pct) >= 2:
                last_broadcast_pct = pct
                broadcast_event("update")

        try:
            verified_path = updater.download_and_verify_update(
                rel_copy,
                progress_cb=_on_progress,
                cancel_event=_UPDATE_CANCEL_EVENT,
            )
            with _UPDATE_LOCK:
                _UPDATE_INTERNAL["verified_installer_path"] = str(verified_path)
                _UPDATE_STATE["status"] = "ready"
                _UPDATE_STATE["progress_pct"] = 100
                _UPDATE_STATE["error"] = ""
            log_msg(f"[Updater] Verified installer ready: {verified_path.name}")
        except updater.UpdateCancelledError:
            with _UPDATE_LOCK:
                _UPDATE_INTERNAL["verified_installer_path"] = ""
                _UPDATE_STATE["status"] = "available"
                _UPDATE_STATE["progress_pct"] = 0
                _UPDATE_STATE["error"] = ""
            log_msg("[Updater] Download cancelled by user")
        except Exception as e:
            with _UPDATE_LOCK:
                _UPDATE_INTERNAL["verified_installer_path"] = ""
                _UPDATE_STATE["status"] = "error"
                _UPDATE_STATE["progress_pct"] = 0
                _UPDATE_STATE["error"] = str(e)
            log_msg(f"[Updater] Download/verification failed: {e}")
        broadcast_event("update")

    threading.Thread(target=_worker, daemon=True, name="UpdateDownloader").start()
    return {"ok": True, "status": "downloading"}


def broadcast_event(event_name="status"):
    """Notifies all connected SSE clients with the given event name."""
    with _SSE_LOCK:
        clients = list(_SSE_CLIENTS)
    for q in clients:
        try:
            q.put_nowait(event_name)
        except queue.Full:
            pass


def _reveal_in_explorer(target_path):
    """Opens Windows Explorer with target_path selected (best-effort, non-blocking)."""
    if not target_path or not os.path.exists(target_path):
        return
    try:
        norm = os.path.normpath(target_path)
        if os.name == "nt":
            subprocess.Popen(f'explorer /select,"{norm}"')
    except Exception:
        pass


def broadcast_status_event():
    broadcast_event("status")


def _rotate_log_if_needed():
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > MAX_LOG_BYTES:
            backup = LOG_FILE + ".1"
            if os.path.exists(backup):
                os.remove(backup)
            os.replace(LOG_FILE, backup)
    except Exception:
        pass


def read_recent_logs(max_lines=30, max_bytes=16384):
    """Fast tail-reader: reads only the last max_bytes of autopilot.log instead of the entire file."""
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            start = max(0, size - max_bytes)
            f.seek(start)
            chunk = f.read().decode("utf-8", errors="ignore")
        lines = [l.strip() for l in chunk.splitlines() if l.strip()]
        if start > 0 and lines:
            lines = lines[1:]  # Drop potentially partial first line
        recent = lines[-max_lines:]
        recent.reverse()
        return recent
    except Exception:
        return []


def log_msg(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        with _LOG_LOCK:
            _rotate_log_if_needed()
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass

class AntigravityAsarWatchdog(threading.Thread):
    """
    Dedicated thread that continuously watches Antigravity's app.asar.
    Whenever an official Antigravity auto-update replaces app.asar:
    - If Antigravity is OPEN: instantly injects the top-bar quota pill live via CDP
      with ZERO file touching, zero restarts, and zero agent crashes.
    - If Antigravity is CLOSED: safely repacks app.asar on disk so future launches have it.
    """
    def __init__(self, check_interval_sec=3.0):
        super().__init__(daemon=True, name="AntigravityAsarWatchdog")
        self.check_interval_sec = check_interval_sec
        self.asar_path = os.path.expandvars(r"%LOCALAPPDATA%\Programs\antigravity\resources\app.asar")
        self.patch_script = os.path.expandvars(r"%LOCALAPPDATA%\Programs\AntigravityControlCenter\auto_patch_antigravity.js")
        self.running = True
        self.last_asar_mtime = None
        self.last_live_patch_attempt = 0.0
        self._missing_script_logged = False
        self._missing_node_logged = False

    def _resolve_patch_script(self):
        """Return the first existing auto_patch_antigravity.js path or None."""
        candidates = [self.patch_script]
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(os.path.join(meipass, "scripts", "auto_patch_antigravity.js"))
        candidates.append(os.path.join(os.path.dirname(sys.executable), "_internal", "scripts", "auto_patch_antigravity.js"))
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "auto_patch_antigravity.js"))
        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                return candidate
        return None

    def _resolve_node_exe(self):
        """Return the first usable Node.js executable path or None."""
        which_node = shutil.which("node")
        if which_node:
            return which_node
        candidates = [
            os.path.expandvars(r"%ProgramFiles%\nodejs\node.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\nodejs\node.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\nodejs\node.exe"),
        ]
        for candidate in candidates:
            if candidate and os.path.isfile(candidate):
                return candidate
        return None

    def _notify_restart_needed(self):
        try:
            if TRAY_ICON is not None:
                from PyQt5.QtCore import QMetaObject, Qt, Q_ARG
                QMetaObject.invokeMethod(
                    TRAY_ICON,
                    "showMessage",
                    Qt.QueuedConnection,
                    Q_ARG(str, "Antigravity Updated"),
                    Q_ARG(str, "Top-bar usage indicator was re-patched. Restart Antigravity once to show it."),
                )
        except Exception:
            pass

    def run(self):
        time.sleep(3.0)
        while self.running:
            try:
                self.check_and_patch()
            except Exception as e:
                log_msg(f"[AsarWatchdog] Loop error: {e}")
            time.sleep(self.check_interval_sec)

    def check_and_patch(self):
        if not os.path.exists(self.asar_path):
            return
        script_path = self._resolve_patch_script()
        if script_path is None:
            if not self._missing_script_logged:
                log_msg("[AsarWatchdog] Patch script not found in install dir or bundled fallback; skipping patch.")
                self._missing_script_logged = True
            return
        self._missing_script_logged = False
        node_exe = self._resolve_node_exe()
        if node_exe is None:
            if not self._missing_node_logged:
                log_msg("[AsarWatchdog] Node.js executable not found on PATH or standard install locations; skipping patch.")
                self._missing_node_logged = True
            return
        self._missing_node_logged = False
        try:
            mtime = os.path.getmtime(self.asar_path)
            if self.last_asar_mtime is not None and mtime == self.last_asar_mtime:
                return
            now = time.time()
            if self.last_live_patch_attempt > 0 and (now - self.last_live_patch_attempt) < 15.0:
                return
            self.last_live_patch_attempt = now

            is_initial = self.last_asar_mtime is None
            if not is_initial:
                log_msg("[AsarWatchdog] Antigravity update detected (app.asar mtime changed)! Applying quota extension...")

            cmd = [node_exe, script_path]
            creationflags = 0x08000000 if os.name == 'nt' else 0
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60, creationflags=creationflags)
            if res.returncode == 0:
                out = res.stdout.strip()
                prefix = "[AsarWatchdog] Initial asar check:" if is_initial else "[AsarWatchdog] Quota extension applied cleanly:"
                log_msg(f"{prefix} {out}")
                self.last_asar_mtime = os.path.getmtime(self.asar_path) if os.path.exists(self.asar_path) else mtime
                if "Successfully patched Antigravity app.asar!" in out and "Successfully ensured draggable titlebar" not in out:
                    self._notify_restart_needed()
            else:
                err = (res.stderr or res.stdout or "").strip()
                log_msg(f"[AsarWatchdog] Patch script error ({res.returncode}): {err}")
        except Exception as e:
            log_msg(f"[AsarWatchdog] Verification error: {e}")

    def stop(self):
        self.running = False

class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if not parsed.path.startswith("/callback"):
            self.send_response(404)
            self.end_headers()
            return

        qs = urllib.parse.parse_qs(parsed.query)
        code = qs.get("code", [""])[0]
        returned_state = qs.get("state", [""])[0]
        expected_state = getattr(self.server, "expected_state", "")

        if not code or (expected_state and returned_state != expected_state):
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body style='background:#0e0e11;color:#f87171;font-family:sans-serif;padding:40px;text-align:center;'><h2>Authentication Failed</h2><p>Invalid authorization code or state. Please try again.</p></body></html>")
            return

        try:
            redirect_uri = getattr(self.server, "redirect_uri", "")
            post_fields = {
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri
            }
            req_data = urllib.parse.urlencode(post_fields).encode("utf-8")
            req = urllib.request.Request(
                "https://oauth2.googleapis.com/token",
                data=req_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            with urllib.request.urlopen(req, timeout=12) as r:
                tokens = json.loads(r.read().decode("utf-8"))

            access_token = tokens.get("access_token", "")
            if not access_token:
                raise ValueError("No access token in response from Google")

            u_req = urllib.request.Request(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            with urllib.request.urlopen(u_req, timeout=10) as u_res:
                user_info = json.loads(u_res.read().decode("utf-8"))

            email = user_info.get("email", "").strip()
            if not email:
                raise ValueError("No email returned from Google userinfo")

            acc_dir = get_account_dir(email)
            if not acc_dir:
                raise ValueError("Invalid email returned from Google userinfo")
            os.makedirs(acc_dir, exist_ok=True)

            cred_obj = {
                "auth_method": "consumer",
                "id_token": tokens.get("id_token", ""),
                "token": {
                    "access_token": access_token,
                    "token_type": tokens.get("token_type", "Bearer"),
                    "refresh_token": tokens.get("refresh_token", ""),
                    "expires_in": tokens.get("expires_in", 3600),
                    "expiry": datetime.fromtimestamp(time.time() + tokens.get("expires_in", 3600), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                }
            }

            write_cred_blob(os.path.join(acc_dir, "cred.bin"), json.dumps(cred_obj).encode("utf-8"))
            atomic_write_text(
                os.path.join(acc_dir, "meta.json"),
                json.dumps({
                    "email": email,
                    "user_name": email,
                    "google_account": email,
                    "updated": datetime.now().isoformat()
                }, indent=2)
            )

            LocalApiHandler.cached_status = None
            broadcast_status_event()
            log_msg(f"Successfully enrolled Google account via loopback OAuth: {email}")

            html_success = f"""<!DOCTYPE html>
<html>
<head><title>Account Linked</title></head>
<body style="background:#0e0e11;color:#fff;font-family:system-ui,-apple-system,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;">
  <div style="background:#15161e;padding:40px;border-radius:16px;border:1px solid #334155;text-align:center;max-width:440px;box-shadow:0 20px 40px rgba(0,0,0,0.5);">
    <div style="width:48px;height:48px;background:rgba(16,185,129,0.15);border:1px solid rgba(16,185,129,0.3);border-radius:50%;display:flex;align-items:center;justify-content:center;margin:0 auto 16px auto;">
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
    </div>
    <h2 style="color:#ffffff;margin:0 0 8px 0;font-size:20px;font-weight:600;">Account Connected!</h2>
    <p style="color:#94a3b8;font-size:13px;line-height:1.5;margin:0 0 20px 0;">Successfully linked <strong style="color:#38bdf8;">{email}</strong> to Antigravity Control Center with dedicated quota.</p>
    <div style="padding:10px;background:#1e293b;border-radius:8px;font-size:12px;color:#94a3b8;font-family:monospace;">
      You can close this tab and return to the Control Center.
    </div>
  </div>
</body>
</html>"""

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html_success.encode("utf-8"))

        except Exception as e:
            log_msg(f"OAuth token exchange error: {e}")
            self.send_response(500)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"<html><body style='background:#0e0e11;color:#f87171;font-family:sans-serif;padding:40px;text-align:center;'><h2>Authentication Failed</h2><p>{e}</p></body></html>".encode("utf-8"))

        finally:
            threading.Thread(target=lambda: (time.sleep(1.0), self.server.shutdown()), daemon=True).start()

_IS_REFRESHING_BG = False

class LocalApiHandler(http.server.BaseHTTPRequestHandler):
    cached_status = None
    last_status_fetch = 0.0
    _tailwind_bytes = None
    _static_cache = {}
    _static_gzip_cache = {}

    def log_message(self, format, *args):
        pass  # Suppress default noisy console logs

    def check_origin_safe(self):
        origin = self.headers.get("Origin", "")
        if not origin:
            return True
        allowed = (
            "http://127.0.0.1",
            "https://127.0.0.1",
            "http://localhost",
            "https://localhost",
            "vscode-file://",
            "vscode-webview://",
            "devtools://",
            "null"
        )
        return any(origin.startswith(a) for a in allowed)

    def _add_safe_cors_headers(self):
        origin = self.headers.get("Origin", "")
        if origin and self.check_origin_safe():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Vary", "Origin")

    def do_OPTIONS(self):
        if not self.check_origin_safe():
            self.send_response(403)
            self.end_headers()
            return
        self.send_response(204)
        self._add_safe_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With, Access-Control-Request-Private-Network")
        self.end_headers()

    def send_json(self, data, status_code=200):
        raw_body = json.dumps(data, separators=(",", ":")).encode("utf-8")
        accept_enc = self.headers.get("Accept-Encoding", "")
        use_gzip = "gzip" in accept_enc and len(raw_body) > 2048
        body = gzip.compress(raw_body, compresslevel=4) if use_gzip else raw_body
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if use_gzip:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self._add_safe_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def send_static(self, key, raw_bytes, content_type, cache_control="public, max-age=86400"):
        accept_enc = self.headers.get("Accept-Encoding", "")
        use_gzip = "gzip" in accept_enc and len(raw_bytes) > 1024
        if use_gzip:
            gz = LocalApiHandler._static_gzip_cache.get(key)
            if gz is None:
                gz = gzip.compress(raw_bytes, compresslevel=6)
                LocalApiHandler._static_gzip_cache[key] = gz
            body = gz
        else:
            body = raw_bytes
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if use_gzip:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        if cache_control:
            self.send_header("Cache-Control", cache_control)
        self.end_headers()
        self.wfile.write(body)

    def _get_static_asset(self, filename):
        cached = LocalApiHandler._static_cache.get(filename)
        if cached is not None:
            return cached
        data = load_static_bytes(filename)
        if data is not None:
            LocalApiHandler._static_cache[filename] = data
        return data

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path.startswith("/api/") and not self.check_origin_safe():
            self.send_json({"ok": False, "error": "Cross-origin request forbidden"}, status_code=403)
            return

        if path in ("/", "/index.html"):
            body = self._get_static_asset("index.html")
            if body is not None:
                self.send_static("index.html", body, "text/html; charset=utf-8", cache_control="no-store, no-cache, must-revalidate")
                return

        if path == "/static/tailwind.css":
            body = self._get_static_asset("tailwind.css")
            if body is not None:
                self.send_static("tailwind.css", body, "text/css; charset=utf-8", cache_control="public, max-age=31536000, immutable")
                return

        if path == "/static/styles.css":
            body = self._get_static_asset("styles.css")
            if body is not None:
                self.send_static("styles.css", body, "text/css; charset=utf-8", cache_control="no-store, no-cache, must-revalidate")
                return

        if path == "/static/app.js":
            body = self._get_static_asset("app.js")
            if body is not None:
                self.send_static("app.js", body, "application/javascript; charset=utf-8", cache_control="no-store, no-cache, must-revalidate")
                return

        if path == "/static/app_icon.png":
            body = self._get_static_asset("app_icon.png")
            if body is not None:
                self.send_static("app_icon.png", body, "image/png", cache_control="public, max-age=86400")
                return

        if path == "/tailwind.min.js":
            if LocalApiHandler._tailwind_bytes is None:
                candidate_dirs = [
                    getattr(sys, "_MEIPASS", ""),
                    os.path.dirname(os.path.abspath(__file__)),
                    os.path.dirname(os.path.abspath(sys.executable)),
                    os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "_internal")
                ]
                for d in candidate_dirs:
                    if d:
                        cand = os.path.join(d, "tailwind.min.js")
                        if os.path.exists(cand):
                            try:
                                with open(cand, "rb") as f:
                                    LocalApiHandler._tailwind_bytes = f.read()
                                break
                            except Exception:
                                pass
            if LocalApiHandler._tailwind_bytes:
                self.send_static(
                    "tailwind.min.js",
                    LocalApiHandler._tailwind_bytes,
                    "application/javascript; charset=utf-8",
                    cache_control="public, max-age=31536000, immutable"
                )
                return

        if path == "/api/events":
            is_ui_ctrl = qs.get("role", [""])[0] == "ui"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self._add_safe_cors_headers()
            self.end_headers()
            client_q = queue.Queue(maxsize=16)
            with _SSE_LOCK:
                _SSE_CLIENTS.append(client_q)
                if is_ui_ctrl:
                    _UI_SSE_CLIENTS.add(client_q)
            try:
                self.wfile.write(b": connected\n\n")
                self.wfile.flush()
                while True:
                    try:
                        ev = client_q.get(timeout=25.0)
                        self.wfile.write(f"event: {ev}\ndata: 1\n\n".encode("utf-8"))
                        self.wfile.flush()
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
            except Exception:
                pass
            finally:
                with _SSE_LOCK:
                    if client_q in _SSE_CLIENTS:
                        _SSE_CLIENTS.remove(client_q)
                    _UI_SSE_CLIENTS.discard(client_q)
            return

        if path == "/api/ping":
            self.send_json({"status": "ok"})
            return

        if path == "/api/open-ui":
            if open_or_restore_ui():
                self.send_json({"status": "ui_restored"})
            else:
                self.send_json({"status": "ui_unresponsive"}, status_code=503)
            return

        if path == "/api/status":
            force = qs.get("refresh", ["0"])[0] == "1"
            status_data = self.build_status_payload(force_refresh=force)
            self.send_json(status_data)
            return

        if path == "/api/refresh-quotas":
            force = qs.get("force", ["1"])[0] == "1"
            accounts = get_saved_accounts()
            quotas = fetch_all_quotas_parallel(accounts, force_refresh=force)
            active = get_active_email()
            rec_data = evaluate_account_recommendations(active, accounts, quotas)
            self.send_json({
                "quotas": quotas,
                "best": rec_data.get("best", active),
                "recommendations": rec_data.get("details", {})
            })
            return

        if path == "/api/tokens/summary":
            tr = qs.get("range", ["month"])[0]
            acc = qs.get("account", ["all"])[0]
            summary = get_token_summary(time_range=tr, account=acc)
            self.send_json(summary)
            return

        if path == "/api/tokens/heatmap":
            acc = qs.get("account", ["all"])[0]
            heatmap = get_daily_heatmap(account=acc)
            self.send_json(heatmap)
            return

        if path == "/api/tokens/hourly":
            tr = qs.get("range", ["month"])[0]
            acc = qs.get("account", ["all"])[0]
            hourly = get_hourly_productivity(account=acc, range_key=tr)
            self.send_json(hourly)
            return

        if path == "/api/context-mode/stats":
            stats = get_context_mode_stats()
            self.send_json(stats)
            return

        if path == "/api/agy-fast/stats":
            stats = get_agy_fast_stats()
            self.send_json(stats)
            return

        if path == "/api/sessions/context-stats":
            acc = qs.get("account", ["all"])[0]
            limit_val = qs.get("limit", ["50"])[0]
            limit = int(limit_val) if limit_val.isdigit() else 50
            stats = get_context_stats(account=acc, limit=limit)
            self.send_json(stats)
            return

        if path == "/api/sessions/recent":
            acc = qs.get("account", ["all"])[0]
            limit_val = qs.get("limit", ["25"])[0]
            limit = int(limit_val) if limit_val.isdigit() else 25
            inc_sub = qs.get("include_subagents", ["0"])[0] == "1"
            sessions = get_recent_sessions(limit=limit, account=acc, include_subagents=inc_sub)
            self.send_json(sessions)
            return

        if path == "/api/sessions/turns":
            sid = qs.get("session_id", [""])[0]
            limit_val = qs.get("limit", ["50"])[0]
            limit = int(limit_val) if limit_val.isdigit() else 50
            turns = get_session_turns(session_id=sid, limit=limit)
            self.send_json(turns)
            return

        if path == "/api/update/status":
            self.send_json(_get_public_update_status())
            return

        if path == "/api/backup/db":
            res = backup_sqlite_db()
            self.send_json(res)
            return

        if path == "/api/export/report":
            tr = qs.get("range", ["month"])[0]
            acc = qs.get("account", ["all"])[0]
            html_content = generate_executive_html_report(time_range=tr, account=acc)
            body = html_content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Disposition", f"inline; filename=executive_report_{tr}_{datetime.now().strftime('%Y%m%d')}.html")
            self.send_header("Content-Length", str(len(body)))
            self._add_safe_cors_headers()
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/tokens/export":
            fmt_type = qs.get("format", ["json"])[0]
            tr = qs.get("range", ["month"])[0]
            acc = qs.get("account", ["all"])[0]
            events = get_all_events(time_range=tr, account=acc)

            if fmt_type == "csv":
                import io, csv
                output = io.StringIO()
                output.write('\ufeff')  # UTF-8 BOM for Excel
                writer = csv.writer(output)
                writer.writerow(["ID", "Session ID", "Created At", "Day", "Account", "Model", "Input Tokens", "Output Tokens", "Cache Read Tokens", "Total Tokens"])
                for e in events:
                    writer.writerow([e["id"], e["session_id"], e["created_at"], e["day"], e["account"], e["model"], e["input_tokens"], e["output_tokens"], e["cache_read_tokens"], e["total_tokens"]])
                body = output.getvalue().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f"attachment; filename=tokens_{tr}_{acc}_{datetime.now().strftime('%Y%m%d')}.csv")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            else:
                body = json.dumps(events, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Disposition", f"attachment; filename=tokens_{tr}_{acc}_{datetime.now().strftime('%Y%m%d')}.json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if not self.check_origin_safe():
            self.send_json({"ok": False, "error": "Cross-origin request forbidden"}, status_code=403)
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        post_data = {}
        if length > 0:
            try:
                post_data = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                pass

        if path == "/api/open-ui":
            if open_or_restore_ui():
                self.send_json({"status": "ui_launched"})
            else:
                self.send_json({"status": "ui_unresponsive"}, status_code=503)
            return

        if path == "/api/switch":
            email = post_data.get("email", "")
            if not email:
                self.send_json({"ok": False, "error": "Missing email"})
                return
            restart_ide = post_data.get("restart", True)
            force_switch = bool(post_data.get("force", False))
            if restart_ide and not force_switch and is_ai_generating():
                self.send_json({
                    "ok": False,
                    "ai_generating": True,
                    "error": "Antigravity AI is currently generating a response. Confirm to force switch."
                })
                return
            log_msg(f"Manual switch request to: {email} (restart Antigravity IDE: {restart_ide})")
            res = switch_to_account(email, restart_ide=restart_ide)
            if res.get("ok"):
                log_msg(f"Switched successfully to: {email} (IDE restarted: {res.get('restarted')})")
                LocalApiHandler.cached_status = None
                broadcast_status_event()
                global TRAY_MENU_UPDATE_CB
                if TRAY_MENU_UPDATE_CB:
                    try:
                        TRAY_MENU_UPDATE_CB()
                    except Exception:
                        pass
            self.send_json(res)
            return

        if path == "/api/toggle-autopilot":
            global AUTOPILOT_RUNNING
            AUTOPILOT_RUNNING = False
            self.send_json({"ok": False, "autopilot": False, "message": "AutoPilot account switching has been permanently disabled for Google account safety."})
            return

        if path == "/api/delete":
            email = post_data.get("email", "").strip()
            if not email:
                self.send_json({"ok": False, "error": "Missing account email"}, status_code=400)
                return
            if email == get_active_email():
                self.send_json({"ok": False, "error": "Cannot remove the currently active account. Switch accounts first."}, status_code=400)
                return
            target_dir = get_account_dir(email)
            if not target_dir:
                self.send_json({"ok": False, "error": "Invalid account identifier"}, status_code=400)
                return
            if os.path.exists(target_dir):
                shutil.rmtree(target_dir, ignore_errors=True)
                log_msg(f"Removed account: {email}")
            LocalApiHandler.cached_status = None
            with _QUOTA_LOCK:
                _QUOTA_CACHE.pop(email, None)
                _QUOTA_CACHE_TIME.pop(email, None)
            save_quota_disk_cache()
            broadcast_status_event()
            self.send_json({"ok": True})
            return

        if path == "/api/clean-cache":
            cleaned = clear_session_cache()
            log_msg(f"Cleaned {cleaned} session lock/cache files.")
            LocalApiHandler.cached_status = None
            broadcast_status_event()
            self.send_json({"ok": True, "cleaned": cleaned})
            return

        if path == "/api/clear-logs":
            try:
                with _LOG_LOCK:
                    with open(LOG_FILE, "w", encoding="utf-8") as f:
                        f.write("")
            except Exception:
                pass
            LocalApiHandler.cached_status = None
            broadcast_status_event()
            self.send_json({"ok": True})
            return

        if path == "/api/enroll":
            log_msg("Initiating Google OAuth loopback enrollment...")
            try:
                import random
                import secrets
                import webbrowser

                port = random.randint(19876, 19999)
                server = socketserver.TCPServer(("127.0.0.1", port), OAuthCallbackHandler)
                server.allow_reuse_address = True

                state = secrets.token_hex(16)
                redirect_uri = f"http://127.0.0.1:{port}/callback"
                server.expected_state = state
                server.redirect_uri = redirect_uri

                scopes = [
                    "https://www.googleapis.com/auth/cloud-platform",
                    "https://www.googleapis.com/auth/userinfo.email",
                    "https://www.googleapis.com/auth/userinfo.profile",
                    "https://www.googleapis.com/auth/cclog",
                    "https://www.googleapis.com/auth/experimentsandconfigs"
                ]

                auth_params = {
                    "client_id": CLIENT_ID,
                    "redirect_uri": redirect_uri,
                    "response_type": "code",
                    "scope": " ".join(scopes),
                    "access_type": "offline",
                    "prompt": "consent",
                    "state": state
                }
                oauth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(auth_params)

                t = threading.Thread(target=server.serve_forever, daemon=True)
                t.start()
                threading.Timer(120.0, lambda: server.shutdown()).start()

                webbrowser.open(oauth_url)
                self.send_json({"ok": True, "message": "Browser opened for Google OAuth loopback login"})
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)})
            return

        if path == "/api/import-active":
            try:
                saved = save_active_credential()
                if saved:
                    LocalApiHandler.cached_status = None
                    log_msg(f"Imported current Antigravity credential: {saved}")
                    self.send_json({"ok": True, "imported": saved})
                else:
                    self.send_json({"ok": False, "error": "No active credential found in Windows Credential Manager"})
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)})
            return

        if path == "/api/backup/db":
            res = backup_sqlite_db()
            if res.get("ok") and res.get("path"):
                _reveal_in_explorer(res["path"])
            self.send_json(res)
            return

        if path == "/api/update/check":
            _start_update_check(silent=False)
            self.send_json({"ok": True, "update": _get_public_update_status()})
            return

        if path == "/api/update/download":
            res = _start_update_download()
            self.send_json(res, status_code=200 if res.get("ok") else 400)
            return

        if path == "/api/update/cancel":
            _UPDATE_CANCEL_EVENT.set()
            self.send_json({"ok": True})
            return

        if path == "/api/update/install":
            if not is_frozen():
                self.send_json(
                    {"ok": False, "error": "In-app installation is disabled when running from source (dev mode)."},
                    status_code=400,
                )
                return
            with _UPDATE_LOCK:
                verified_path_str = _UPDATE_INTERNAL.get("verified_installer_path") or ""
            try:
                from pathlib import Path
                verified_path = Path(verified_path_str).resolve() if verified_path_str else None
                upd_dir = updates_dir().resolve()
                if not verified_path or verified_path.parent != upd_dir or not verified_path.is_file():
                    self.send_json(
                        {"ok": False, "error": "No verified update installer is ready to install."},
                        status_code=400,
                    )
                    return
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, status_code=400)
                return

            self.send_json({"ok": True})

            def _install_and_exit():
                time.sleep(0.15)
                close_ui_window_if_open()
                release_daemon_mutex()
                try:
                    updater.launch_installer(verified_path)
                except Exception as e:
                    log_msg(f"[Updater] Failed to launch installer: {e}")
                    return
                if QUIT_DAEMON_CB:
                    try:
                        QUIT_DAEMON_CB()
                        time.sleep(0.6)
                    except Exception:
                        pass
                else:
                    time.sleep(0.2)
                os._exit(0)

            threading.Thread(target=_install_and_exit, daemon=True, name="UpdateInstallerLauncher").start()
            return

        if path == "/api/daemon/quit":
            self.send_json({"ok": True})
            def _graceful_quit():
                close_ui_window_if_open()
                release_daemon_mutex()
                if QUIT_DAEMON_CB:
                    try:
                        QUIT_DAEMON_CB()
                        time.sleep(1.2)
                    except Exception:
                        pass
                else:
                    time.sleep(0.2)
                os._exit(0)
            threading.Thread(target=_graceful_quit, daemon=True).start()
            return

        # Window controls fallbacks (normally intercepted client-side by QWebEngine)
        if path in ("/api/window/drag", "/api/window/minimize", "/api/window/maximize", "/api/window/close", "/api/window/quit"):
            self.send_json({"ok": True})
            return

        self.send_response(404)
        self.end_headers()

    def build_status_payload(self, force_refresh=False):
        now = time.time()
        if not force_refresh and LocalApiHandler.cached_status and (now - LocalApiHandler.last_status_fetch < 3.0):
            return LocalApiHandler.cached_status

        active = get_active_email()
        accounts = get_saved_accounts()

        # Instant zero-latency load: serve memory/disk quota cache immediately if available
        with _QUOTA_LOCK:
            all_cached = bool(accounts) and all(acc in _QUOTA_CACHE for acc in accounts)
            if not force_refresh and all_cached:
                quotas = {acc: dict(_QUOTA_CACHE[acc]) for acc in accounts}
                needs_bg_refresh = any(now - _QUOTA_CACHE_TIME.get(acc, 0) > CACHE_TTL for acc in accounts)
            else:
                quotas = None
                needs_bg_refresh = False

        if quotas is not None:
            # Asynchronously refresh in background thread if expired without blocking HTTP UI response
            if needs_bg_refresh:
                global _IS_REFRESHING_BG
                if not _IS_REFRESHING_BG:
                    _IS_REFRESHING_BG = True
                    def _bg_fetch():
                        global _IS_REFRESHING_BG
                        try:
                            fetch_all_quotas_parallel(accounts, force_refresh=True)
                            LocalApiHandler.cached_status = None
                            broadcast_status_event()
                        finally:
                            _IS_REFRESHING_BG = False
                    threading.Thread(target=_bg_fetch, daemon=True).start()
        else:
            quotas = fetch_all_quotas_parallel(accounts, force_refresh=force_refresh)

        meta_info = get_account_meta_info(accounts)
        for acc in accounts:
            if acc in quotas and isinstance(quotas[acc], dict):
                m = meta_info.get(acc, {})
                quotas[acc]["google_account"] = m.get("google_account", acc)
                quotas[acc]["is_duplicate"] = m.get("is_duplicate", False)
                quotas[acc]["duplicate_of"] = m.get("duplicate_of", None)

        rec_data = evaluate_account_recommendations(active, accounts, quotas)
        best_acc = rec_data.get("best", active)
        recs_details = rec_data.get("details", {})

        logs = read_recent_logs(max_lines=30)

        burn_rate_val = 0.0
        burn_rate_sec = 0.0
        try:
            tok_sum = get_token_summary(time_range="today", account=active)
            burn_rate_val = tok_sum.get("burn_rate", {}).get("tokens_per_min", 0.0)
            burn_rate_sec = tok_sum.get("burn_rate", {}).get("tokens_per_sec", 0.0)
        except Exception:
            pass

        payload = {
            "active": active,
            "accounts": accounts,
            "quotas": quotas,
            "best": best_acc,
            "recommendations": recs_details,
            "autopilot": AUTOPILOT_RUNNING,
            "autopilot_status": AUTOPILOT_STATUS_TEXT if AUTOPILOT_RUNNING else "OFF",
            "logs": logs,
            "burn_rate": burn_rate_val,
            "tokens_per_sec": burn_rate_sec
        }
        LocalApiHandler.cached_status = payload
        LocalApiHandler.last_status_fetch = now
        return payload

class ReusableThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

def run_server(server=None):
    try:
        if server is None:
            server = ReusableThreadingServer(("127.0.0.1", PORT), LocalApiHandler)
        log_msg(f"Antigravity Control Center server started on http://127.0.0.1:{PORT}")
        server.serve_forever()
    except Exception as e:
        log_msg(f"Server listen error on port {PORT}: {e}")

DAEMON_MUTEX_NAME = "Local\\AntigravityControlCenterDaemon"
UI_MUTEX_NAME = "Local\\AntigravityControlCenterUI"
_DAEMON_MUTEX_HANDLE = None
_UI_MUTEX_HANDLE = None
_UI_LAUNCH_LOCK = threading.Lock()
_UI_PROC = None
_UI_LAST_LAUNCH = 0.0


def _get_kernel32():
    """Return a kernel32 handle with 64-bit safe HANDLE argtypes/restypes."""
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_bool
    return kernel32


def acquire_daemon_mutex():
    """Atomically acquires the daemon mutex. Returns False if another daemon already holds it."""
    global _DAEMON_MUTEX_HANDLE
    if _DAEMON_MUTEX_HANDLE:
        return True
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = _get_kernel32()
            handle = kernel32.CreateMutexW(None, False, DAEMON_MUTEX_NAME)
            err = ctypes.get_last_error()
            if not handle or err == 183:  # ERROR_ALREADY_EXISTS
                if handle:
                    kernel32.CloseHandle(ctypes.c_void_p(handle))
                return False
            _DAEMON_MUTEX_HANDLE = handle
        except Exception:
            pass
    return True


def release_daemon_mutex():
    """Safely closes the daemon mutex handle if owned by this process."""
    global _DAEMON_MUTEX_HANDLE
    handle = _DAEMON_MUTEX_HANDLE
    _DAEMON_MUTEX_HANDLE = None
    if handle and os.name == "nt":
        try:
            import ctypes
            kernel32 = _get_kernel32()
            kernel32.CloseHandle(ctypes.c_void_p(handle))
        except Exception:
            pass


def acquire_ui_mutex():
    """Returns True if this process owns the UI mutex, False if another --ui is already running."""
    global _UI_MUTEX_HANDLE
    if _UI_MUTEX_HANDLE:
        return True
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = _get_kernel32()
            handle = kernel32.CreateMutexW(None, False, UI_MUTEX_NAME)
            err = ctypes.get_last_error()
            if not handle or err == 183:  # ERROR_ALREADY_EXISTS
                if handle:
                    kernel32.CloseHandle(ctypes.c_void_p(handle))
                return False
            _UI_MUTEX_HANDLE = handle
        except Exception:
            pass
    return True


def release_ui_mutex():
    """Safely closes the UI mutex handle if owned by this process."""
    global _UI_MUTEX_HANDLE
    handle = _UI_MUTEX_HANDLE
    _UI_MUTEX_HANDLE = None
    if handle and os.name == "nt":
        try:
            import ctypes
            kernel32 = _get_kernel32()
            kernel32.CloseHandle(ctypes.c_void_p(handle))
        except Exception:
            pass


def _trim_working_set():
    """Trims idle pages from the daemon working set on Windows (~20-30 MB in tray)."""
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.psapi.EmptyWorkingSet(ctypes.windll.kernel32.GetCurrentProcess())
        except Exception:
            pass


def is_daemon_alive():
    """Instant (~0.01ms) daemon check using Windows Named Mutex, with fast socket fallback."""
    if os.name == "nt":
        try:
            import ctypes
            SYNCHRONIZE = 0x00100000
            h = ctypes.windll.kernel32.OpenMutexW(SYNCHRONIZE, False, DAEMON_MUTEX_NAME)
            if h:
                ctypes.windll.kernel32.CloseHandle(h)
                return True
            return False
        except Exception:
            pass
    try:
        import socket
        with socket.create_connection(("127.0.0.1", PORT), timeout=0.15):
            return True
    except Exception:
        return False


def is_server_ready():
    """Fast TCP readiness check (non-blocking 80ms timeout)."""
    try:
        import socket
        with socket.create_connection(("127.0.0.1", PORT), timeout=0.08):
            return True
    except Exception:
        return False


def force_bring_to_front(hwnd):
    """Brings a Qt window above the foreground app (e.g. Antigravity IDE) without AttachThreadInput deadlocks."""
    if not hwnd:
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        else:
            user32.ShowWindow(hwnd, 5)  # SW_SHOW
        SWP_SHOW = 0x0001 | 0x0002 | 0x0040  # SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW
        SWP_KEEP = 0x0001 | 0x0002 | 0x0010  # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
        # Elevate above current foreground window, switch focus, then release topmost shortly after
        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, SWP_SHOW)  # HWND_TOPMOST
        try:
            user32.SwitchToThisWindow(hwnd, True)
        except Exception:
            pass
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)

        def _drop_topmost():
            time.sleep(0.12)
            try:
                user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, SWP_KEEP)  # HWND_NOTOPMOST
            except Exception:
                pass

        threading.Thread(target=_drop_topmost, daemon=True).start()
    except Exception:
        pass


def _find_ui_hwnd():
    if os.name != "nt":
        return 0
    try:
        import ctypes
        return int(ctypes.windll.user32.FindWindowW(None, "Antigravity Control Center") or 0)
    except Exception:
        return 0


def _spawn_cmd(extra_args):
    if getattr(sys, "frozen", False):
        return [sys.executable] + list(extra_args)
    return [sys.executable, os.path.abspath(sys.argv[0])] + list(extra_args)


def open_or_restore_ui():
    """Focuses existing --ui window (<20ms) or spawns an on-demand --ui subprocess immediately."""
    global _UI_PROC, _UI_LAST_LAUNCH

    hwnd = _find_ui_hwnd()
    if hwnd:
        force_bring_to_front(hwnd)
        return True

    with _UI_LAUNCH_LOCK:
        hwnd = _find_ui_hwnd()
        if hwnd:
            force_bring_to_front(hwnd)
            return True

        now = time.time()
        if _UI_PROC is not None and _UI_PROC.poll() is None:
            if (now - _UI_LAST_LAUNCH) < 2.5:
                return True
            try:
                _UI_PROC.terminate()
            except Exception:
                pass
            _UI_PROC = None

        try:
            cmd = _spawn_cmd(["--ui"])
            proc = subprocess.Popen(cmd, close_fds=True)
            if os.name == "nt":
                try:
                    import ctypes
                    ctypes.windll.user32.AllowSetForegroundWindow(proc.pid)
                except Exception:
                    pass
            _UI_PROC = proc
            _UI_LAST_LAUNCH = now

            def _watch_ui_exit(p):
                try:
                    p.wait()
                except Exception:
                    pass
                time.sleep(0.3)
                _trim_working_set()

            threading.Thread(target=_watch_ui_exit, args=(proc,), daemon=True).start()
            return True
        except Exception as e:
            log_msg(f"[Daemon] Failed to spawn --ui subprocess: {e}")
            return False


def close_ui_window_if_open():
    """Terminates the on-demand --ui subprocess if running."""
    global _UI_PROC
    with _UI_LAUNCH_LOCK:
        if _UI_PROC is not None and _UI_PROC.poll() is None:
            try:
                _UI_PROC.terminate()
            except Exception:
                pass
        _UI_PROC = None
    hwnd = _find_ui_hwnd()
    if hwnd and os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
        except Exception:
            pass


def _kill_other_instances():
    """Self-healing cleanup: terminates any wedged/unresponsive older Control Center instance."""
    if os.name != "nt":
        return
    my_pid = os.getpid()
    try:
        flags = 0x08000000  # CREATE_NO_WINDOW
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq AntigravityControlCenter.exe", "/FO", "CSV", "/NH"],
            creationflags=flags,
            text=True,
            timeout=3,
        )
        for line in out.splitlines():
            parts = [p.strip('"') for p in line.split(",")]
            if len(parts) >= 2 and parts[1].isdigit():
                pid = int(parts[1])
                if pid != my_pid:
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, creationflags=flags, timeout=3)
    except Exception:
        pass


def _resolve_icon_path():
    for base in (
        getattr(sys, "_MEIPASS", ""),
        os.path.dirname(os.path.abspath(__file__)),
        os.path.dirname(os.path.abspath(sys.executable)),
    ):
        if base:
            cand = os.path.join(base, "app_icon.ico")
            if os.path.exists(cand):
                return cand
    return ""


def run_daemon():
    """
    Lightweight Chromium-free background daemon:
    HTTP API (:28795) + BackgroundTokenWatcher + AntigravityAsarWatchdog + PyQt5 System Tray.
    Never imports QtWebEngineWidgets, keeping tray RAM around ~20-30 MB.
    """
    try:
        _run_daemon_inner()
    except Exception:
        with open(os.path.join(SWITCHER_DIR, "app_crash.log"), "a", encoding="utf-8") as f:
            f.write(f"\n--- DAEMON CRASH AT {datetime.now()} ---\n{traceback.format_exc()}\n")


def _run_daemon_inner():
    if not acquire_daemon_mutex():
        return
    ensure_dirs()

    # Bind HTTP server synchronously BEFORE creating QSystemTrayIcon so any duplicate
    # or port-conflict exits cleanly without ever flashing a second tray icon.
    bound_server = None
    try:
        bound_server = ReusableThreadingServer(("127.0.0.1", PORT), LocalApiHandler)
    except Exception as e:
        log_msg(f"Server listen error on port {PORT}: {e}")
        if is_server_ready():
            return

    if bound_server is not None:
        server_thread = threading.Thread(target=run_server, args=(bound_server,), daemon=True)
        server_thread.start()

    # Start background workers
    def init_background_workers():
        try:
            save_active_credential()
            init_db()
        except Exception:
            pass

        token_watcher = BackgroundTokenWatcher(interval_sec=3.0, on_new_events=broadcast_status_event)
        token_watcher.start()

        asar_watchdog = AntigravityAsarWatchdog(check_interval_sec=3.0)
        asar_watchdog.start()

        global AUTOPILOT_RUNNING
        AUTOPILOT_RUNNING = False

        try:
            accs = get_saved_accounts()
            fetch_all_quotas_parallel(accs, force_refresh=True)
            LocalApiHandler.cached_status = None
            broadcast_status_event()
        except Exception:
            pass

        try:
            cleanup_old_installers()
        except Exception:
            pass

        if is_frozen():
            try:
                _start_update_check(silent=True)
            except Exception:
                pass

        time.sleep(1.5)
        _trim_working_set()

    threading.Thread(target=init_background_workers, daemon=True).start()

    # Lightweight PyQt5 System Tray ONLY (NO QtWebEngine imported or loaded)
    from PyQt5.QtWidgets import QApplication, QSystemTrayIcon, QMenu
    from PyQt5.QtCore import QObject, QTimer, pyqtSignal
    from PyQt5.QtGui import QIcon

    global TRAY_ICON, TRAY_MENU, TRAY_MENU_UPDATE_CB, SHOW_UI_CB, QUIT_DAEMON_CB
    app = QApplication([sys.argv[0]])
    app.setQuitOnLastWindowClosed(False)

    icon_path = _resolve_icon_path()
    app_icon = QIcon(icon_path) if icon_path else app.style().standardIcon(app.style().SP_ComputerIcon)

    SHOW_UI_CB = open_or_restore_ui

    TRAY_ICON = QSystemTrayIcon(app)
    TRAY_ICON.setIcon(app_icon)
    TRAY_ICON.setToolTip("Antigravity Control Center")

    TRAY_MENU = QMenu()

    def _hide_tray_icon():
        try:
            if TRAY_ICON:
                TRAY_ICON.hide()
                TRAY_ICON.setVisible(False)
            app.processEvents()
        except Exception:
            pass

    _quitting = False

    def on_quit_all():
        nonlocal _quitting
        if _quitting:
            return
        _quitting = True
        _hide_tray_icon()
        close_ui_window_if_open()
        release_daemon_mutex()
        app.quit()
        threading.Thread(target=lambda: (time.sleep(0.35), os._exit(0)), daemon=True).start()

    def _do_update_menu():
        try:
            TRAY_MENU.clear()
            active_em = get_active_email()
            act_lbl = TRAY_MENU.addAction(f"Active: {active_em}")
            act_lbl.setEnabled(False)
            TRAY_MENU.addSeparator()

            def _bg_switch(acc_email):
                res = switch_to_account(acc_email, restart_ide=True)
                if res.get("ok"):
                    LocalApiHandler.cached_status = None
                    broadcast_status_event()
                    update_tray_menu()

            def _bg_refresh_quotas():
                fetch_all_quotas_parallel(get_saved_accounts(), force_refresh=True)
                LocalApiHandler.cached_status = None
                broadcast_status_event()

            for acc in get_saved_accounts():
                prefix = "✓ " if acc == active_em else "   "
                action = TRAY_MENU.addAction(f"{prefix}{acc}")
                action.triggered.connect(lambda checked, a=acc: threading.Thread(target=_bg_switch, args=(a,), daemon=True).start())

            TRAY_MENU.addSeparator()
            show_act = TRAY_MENU.addAction("Open Control Center")
            show_act.triggered.connect(lambda: open_or_restore_ui())

            refresh_act = TRAY_MENU.addAction("Refresh Quotas Now")
            refresh_act.triggered.connect(lambda: threading.Thread(target=_bg_refresh_quotas, daemon=True).start())

            TRAY_MENU.addSeparator()
            quit_act = TRAY_MENU.addAction("Quit Control Center")
            quit_act.triggered.connect(on_quit_all)
        except Exception:
            pass

    class _TrayBridge(QObject):
        sig_update_menu = pyqtSignal()
        sig_quit = pyqtSignal()

    tray_bridge = _TrayBridge()
    tray_bridge.sig_update_menu.connect(_do_update_menu)
    tray_bridge.sig_quit.connect(on_quit_all)

    def update_tray_menu():
        try:
            tray_bridge.sig_update_menu.emit()
        except Exception:
            pass

    TRAY_MENU_UPDATE_CB = update_tray_menu
    QUIT_DAEMON_CB = lambda: tray_bridge.sig_quit.emit()
    app.aboutToQuit.connect(_hide_tray_icon)
    TRAY_MENU.aboutToShow.connect(_do_update_menu)
    _do_update_menu()
    TRAY_ICON.setContextMenu(TRAY_MENU)
    TRAY_ICON.show()

    def on_tray_activated(reason):
        if reason in (QSystemTrayIcon.DoubleClick, QSystemTrayIcon.Trigger):
            open_or_restore_ui()

    TRAY_ICON.activated.connect(on_tray_activated)

    QTimer.singleShot(1000, _trim_working_set)

    log_msg("[Daemon] Entering lightweight tray app.exec_() (Chromium-free)...")
    exit_code = app.exec_()
    _hide_tray_icon()
    log_msg(f"[Daemon] app.exec_() returned with exit code: {exit_code}")
    sys.exit(exit_code)


def run_ui():
    """
    On-demand frameless WebEngine window (--ui).
    Uses low-memory Chromium flags and exits completely on close so 100% of Chromium RAM is freed.
    """
    try:
        _run_ui_inner()
    except Exception:
        with open(os.path.join(SWITCHER_DIR, "app_crash.log"), "a", encoding="utf-8") as f:
            f.write(f"\n--- UI CRASH AT {datetime.now()} ---\n{traceback.format_exc()}\n")


def _run_ui_inner():
    if not acquire_ui_mutex():
        hwnd = _find_ui_hwnd()
        if hwnd:
            force_bring_to_front(hwnd)
        sys.exit(0)

    flags = [
        "--disable-gpu",
        "--disable-gpu-compositing",
        "--renderer-process-limit=1",
        "--disable-logging",
        "--disable-speech-api",
        "--disable-sync",
        "--disable-extensions",
        "--disable-component-update",
        "--disable-background-networking",
        "--disable-default-apps",
        "--no-first-run",
        "--no-sandbox",
        "--disable-features=AudioServiceOutOfProcess,TranslateUI",
        "--js-flags=--max-old-space-size=96",
    ]
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(flags)

    from PyQt5.QtWidgets import QApplication, QMainWindow, QFileDialog
    from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineProfile, QWebEnginePage, QWebEngineSettings
    from PyQt5.QtWebEngineCore import QWebEngineUrlRequestInterceptor
    from PyQt5.QtCore import QUrl, Qt, QTimer, pyqtSignal
    from PyQt5.QtGui import QIcon, QColor, QCursor, QDesktopServices
    import ctypes
    from ctypes import wintypes

    class ExternalPopupPage(QWebEnginePage):
        """Captures window.open('_blank') URLs and forwards them to the default system browser."""

        def acceptNavigationRequest(self, url, nav_type, is_main_frame):
            if url.isValid() and url.scheme() in ("http", "https"):
                QDesktopServices.openUrl(url)
            QTimer.singleShot(0, self.deleteLater)
            return False

    class ControlCenterWebPage(QWebEnginePage):
        """Main WebEnginePage supporting external popup delegation for reports."""

        def __init__(self, profile, parent=None):
            super().__init__(profile, parent)
            self._popups = []

        def createWindow(self, _win_type):
            popup = ExternalPopupPage(self.profile(), self)
            self._popups.append(popup)
            popup.destroyed.connect(
                lambda _obj=None, p=popup: self._popups.remove(p) if p in self._popups else None
            )
            return popup

    class WindowControlInterceptor(QWebEngineUrlRequestInterceptor):
        def __init__(self, win):
            super().__init__()
            self.win = win

        def interceptRequest(self, info):
            path = info.requestUrl().path()
            if path == "/api/window/drag":
                info.block(True)
                self.win.sig_drag.emit()
            elif path == "/api/window/minimize":
                info.block(True)
                self.win.sig_minimize.emit()
            elif path == "/api/window/maximize":
                info.block(True)
                self.win.sig_toggle_max.emit()
            elif path == "/api/window/close":
                info.block(True)
                self.win.sig_close.emit()
            elif path == "/api/window/quit":
                info.block(True)
                self.win.sig_quit.emit()

    class MainWindow(QMainWindow):
        sig_drag = pyqtSignal()
        sig_minimize = pyqtSignal()
        sig_toggle_max = pyqtSignal()
        sig_close = pyqtSignal()
        sig_quit = pyqtSignal()

        def __init__(self, app_icon):
            super().__init__()
            self._revealed = False
            self._active_downloads = []
            self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
            self.setAttribute(Qt.WA_TranslucentBackground, False)
            self.setWindowTitle("Antigravity Control Center")
            self.resize(1180, 760)
            self.setMinimumSize(850, 600)
            self.setWindowIcon(app_icon)

            try:
                hwnd = int(self.winId())
                ctypes.windll.user32.SetWindowTextW(hwnd, "Antigravity Control Center")
                WS_MAXIMIZEBOX = 0x00010000
                WS_MINIMIZEBOX = 0x00020000
                WS_THICKFRAME  = 0x00040000
                style = ctypes.windll.user32.GetWindowLongW(hwnd, -16)
                ctypes.windll.user32.SetWindowLongW(hwnd, -16, (style | WS_MAXIMIZEBOX | WS_MINIMIZEBOX) & ~WS_THICKFRAME)
            except Exception:
                pass

            self.sig_drag.connect(self.on_native_drag)
            self.sig_minimize.connect(self.showMinimized)
            self.sig_toggle_max.connect(self.toggle_maximized)
            self.sig_close.connect(self.on_close_to_tray)
            self.sig_quit.connect(self.on_quit_all)

            cache_dir = os.path.join(SWITCHER_DIR, "web_cache")
            os.makedirs(cache_dir, exist_ok=True)
            profile = QWebEngineProfile.defaultProfile()
            profile.setCachePath(cache_dir)
            profile.setPersistentStoragePath(cache_dir)
            profile.setHttpCacheType(QWebEngineProfile.DiskHttpCache)
            profile.setHttpCacheMaximumSize(8 * 1024 * 1024)
            profile.downloadRequested.connect(self.on_download_requested)

            self.browser = QWebEngineView()
            self.web_page = ControlCenterWebPage(profile, self.browser)
            self.browser.setPage(self.web_page)
            self.web_page.setBackgroundColor(QColor("#111110"))
            self.browser.settings().setAttribute(QWebEngineSettings.JavascriptCanAccessClipboard, True)

            self.interceptor = WindowControlInterceptor(self)
            profile.setUrlRequestInterceptor(self.interceptor)
            self.setCentralWidget(self.browser)
            self.browser.loadFinished.connect(lambda _ok: self.reveal_window())
            self.browser.load(QUrl(f"http://127.0.0.1:{PORT}"))

            try:
                dwm = ctypes.windll.dwmapi
                hwnd = wintypes.HWND(int(self.winId()))
                corner = ctypes.c_int(2)
                dwm.DwmSetWindowAttribute(hwnd, wintypes.DWORD(33), ctypes.byref(corner), ctypes.sizeof(corner))
                border_color = ctypes.c_int(-2)
                dwm.DwmSetWindowAttribute(hwnd, wintypes.DWORD(34), ctypes.byref(border_color), ctypes.sizeof(border_color))
            except Exception:
                pass

            # Safety fallback so window always reveals even if loadFinished is delayed
            QTimer.singleShot(250, self.reveal_window)

        def reveal_window(self):
            if self._revealed:
                return
            self._revealed = True
            try:
                screen = QApplication.primaryScreen()
                if screen:
                    avail = screen.availableGeometry()
                    geo = self.frameGeometry()
                    if not avail.intersects(geo):
                        self.move(
                            avail.x() + max(0, (avail.width() - self.width()) // 2),
                            avail.y() + max(0, (avail.height() - self.height()) // 2),
                        )
            except Exception:
                pass
            self.show()
            self.raise_()
            self.activateWindow()
            try:
                hwnd = int(self.winId())
                force_bring_to_front(hwnd)
                QTimer.singleShot(80, lambda: force_bring_to_front(hwnd))
            except Exception:
                pass

        def on_native_drag(self):
            try:
                if self.isMaximized():
                    cursor = QCursor.pos()
                    normal_w = 1180
                    self.showNormal()
                    new_x = max(0, cursor.x() - normal_w // 2)
                    new_y = max(0, cursor.y() - 25)
                    self.move(new_x, new_y)
                    QApplication.processEvents()

                hwnd = int(self.winId())
                ctypes.windll.user32.ReleaseCapture()
                ctypes.windll.user32.SendMessageW(hwnd, 0x0112, 0xF012, 0)

                cursor_pos = QCursor.pos()
                for screen in QApplication.screens():
                    geom = screen.geometry()
                    if geom.left() <= cursor_pos.x() <= geom.right() and (geom.top() - 15 <= cursor_pos.y() <= geom.top() + 20):
                        self.showMaximized()
                        break
            except Exception:
                pass

        def toggle_maximized(self):
            if self.isMaximized():
                self.showNormal()
            else:
                self.showMaximized()

        def on_download_requested(self, download):
            """Prompts for destination and reveals the exported file in Explorer once saved."""
            suggested = download.suggestedFileName() or download.downloadFileName() or "export.dat"
            user_profile = os.environ.get("USERPROFILE") or os.path.expanduser("~")
            downloads_dir = os.path.join(user_profile, "Downloads")
            default_dir = downloads_dir if os.path.isdir(downloads_dir) else user_profile
            default_path = os.path.join(default_dir, suggested)

            ext = os.path.splitext(suggested)[1].lower()
            if ext == ".csv":
                file_filter = "CSV Files (*.csv);;All Files (*)"
            elif ext == ".json":
                file_filter = "JSON Files (*.json);;All Files (*)"
            else:
                file_filter = "All Files (*)"

            dest_path, _ = QFileDialog.getSaveFileName(self, "Save Export", default_path, file_filter)
            if not dest_path:
                download.cancel()
                return

            download.setDownloadDirectory(os.path.dirname(dest_path))
            download.setDownloadFileName(os.path.basename(dest_path))
            self._active_downloads.append(download)

            def _on_finished():
                if download in self._active_downloads:
                    self._active_downloads.remove(download)
                if os.path.exists(dest_path):
                    _reveal_in_explorer(dest_path)

            download.finished.connect(_on_finished)
            download.accept()

        def on_close_to_tray(self):
            self.close()

        def on_quit_all(self):
            try:
                import urllib.request
                req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/daemon/quit", method="POST")
                urllib.request.urlopen(req, timeout=0.5)
            except Exception:
                pass
            self.close()

        def closeEvent(self, event):
            try:
                self.browser.setUrl(QUrl("about:blank"))
                self.browser.deleteLater()
            except Exception:
                pass
            release_ui_mutex()
            event.accept()
            QApplication.instance().quit()
            threading.Thread(target=lambda: (time.sleep(0.15), os._exit(0)), daemon=True).start()

    app = QApplication(sys.argv)
    icon_path = _resolve_icon_path()
    app_icon = QIcon(icon_path) if icon_path else app.style().standardIcon(app.style().SP_ComputerIcon)
    app.setWindowIcon(app_icon)

    win = MainWindow(app_icon)
    exit_code = app.exec_()
    sys.exit(exit_code)


def _ensure_daemon_started():
    """Spawns --daemon detached if not already alive and waits up to 3s for HTTP readiness."""
    if is_daemon_alive():
        if is_server_ready():
            return True
        # Existing daemon is still booting; wait for its HTTP server instead of spawning a duplicate
        for _ in range(120):
            time.sleep(0.025)
            if is_server_ready():
                return True
        return False
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
    subprocess.Popen(_spawn_cmd(["--daemon"]), creationflags=flags, close_fds=True)
    for _ in range(120):
        time.sleep(0.025)
        if is_server_ready():
            return True
    return False


def main():
    args = sys.argv[1:]

    if "--ui" in args:
        _ensure_daemon_started()
        run_ui()
        return

    if any(arg in args for arg in ("--daemon", "--minimized", "--tray", "--hidden")):
        if not acquire_daemon_mutex():
            sys.exit(0)
        run_daemon()
        return

    # Default invocation (desktop shortcut, IPC fallback, or antigravity-cc://open)
    if is_daemon_alive():
        # Wait briefly if the daemon just started and is still binding the HTTP port
        if not is_server_ready():
            for _ in range(100):
                time.sleep(0.025)
                if is_server_ready():
                    break
        try:
            import urllib.request
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/open-ui", timeout=1.5) as r:
                if r.status == 200:
                    sys.exit(0)
        except Exception:
            pass
        # Old daemon wedged/unresponsive -> request clean quit first, then force-kill if needed
        try:
            import urllib.request
            req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/daemon/quit", method="POST")
            urllib.request.urlopen(req, timeout=0.6)
            time.sleep(0.5)
        except Exception:
            pass
        if is_daemon_alive():
            _kill_other_instances()
            time.sleep(0.3)

    _ensure_daemon_started()
    run_ui()

if __name__ == "__main__":
    main()
