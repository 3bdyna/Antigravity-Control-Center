"""
Parallel Quota Engine and Account Switcher for Antigravity Control Center.
Handles Windows DPAPI credential management, parallel instant quota polling,
account switching, and reset clock calculations.
"""
import os
import sys
import json
import time
import shutil
import subprocess
import tempfile
import threading
import ctypes
import ctypes.wintypes
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

USERPROFILE = os.environ.get("USERPROFILE", "")
APPDATA = os.environ.get("APPDATA", "")
LOCALAPPDATA = os.environ.get("LOCALAPPDATA", "")

CRED_TARGET = "gemini:antigravity"
SWITCHER_DIR = os.path.join(USERPROFILE, ".gemini", "antigravity-switcher")
ACCOUNTS_DIR = os.path.join(SWITCHER_DIR, "accounts")
ACTIVE_FILE = os.path.join(SWITCHER_DIR, "active_email.txt")
AUTOPILOT_PID = os.path.join(SWITCHER_DIR, "autopilot.pid")
LOG_FILE = os.path.join(SWITCHER_DIR, "autopilot.log")

CLIENT_ID = "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
CLIENT_SECRET = "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"

DPAPI_MAGIC = b"AGDPAPI1"

# In-memory and on-disk quota cache for instant app load (0ms cold-start)
_QUOTA_LOCK = threading.Lock()
_QUOTA_CACHE = {}
_QUOTA_CACHE_TIME = {}
CACHE_TTL = 60.0  # seconds fallback
ACTIVE_CACHE_TTL = 60.0  # Active account cache TTL (1 min)
STANDBY_CACHE_TTL = 300.0  # Standby account cache TTL (5 mins)
_RATE_LIMIT_COOLDOWN = 0.0  # Exponential backoff cooldown timestamp
QUOTA_CACHE_FILE = os.path.join(SWITCHER_DIR, "quotas_cache.json")


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def atomic_write_bytes(path, data):
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=parent, prefix=".tmp_")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        raise


def atomic_write_text(path, text):
    atomic_write_bytes(path, text.encode("utf-8"))


def get_account_dir(email):
    """Safely resolves an account directory strictly inside ACCOUNTS_DIR."""
    if not email or not isinstance(email, str):
        return None
    cleaned = email.strip()
    if not cleaned or cleaned in (".", "..") or any(c in cleaned for c in ("/", "\\", "\x00")):
        return None
    base = os.path.abspath(ACCOUNTS_DIR)
    target = os.path.abspath(os.path.join(base, cleaned))
    try:
        if os.path.commonpath([base, target]) != base or target == base:
            return None
    except ValueError:
        return None
    return target


def dpapi_encrypt(plaintext_bytes):
    """Encrypts bytes using Windows DPAPI (current user scope). Returns original bytes if non-Windows."""
    if os.name != "nt" or not plaintext_bytes:
        return plaintext_bytes
    try:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        buf = ctypes.create_string_buffer(plaintext_bytes, len(plaintext_bytes))
        blob_in = _DATA_BLOB(len(plaintext_bytes), buf)
        blob_out = _DATA_BLOB()
        # CRYPTPROTECT_UI_FORBIDDEN = 0x1
        if crypt32.CryptProtectData(ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out)):
            try:
                encrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
                return DPAPI_MAGIC + encrypted
            finally:
                kernel32.LocalFree(blob_out.pbData)
    except Exception:
        pass
    return plaintext_bytes


def dpapi_decrypt(blob_bytes):
    """Decrypts DPAPI-protected bytes if prefixed with DPAPI_MAGIC; otherwise returns legacy plaintext."""
    if not blob_bytes or not blob_bytes.startswith(DPAPI_MAGIC):
        return blob_bytes
    if os.name != "nt":
        return blob_bytes
    raw = blob_bytes[len(DPAPI_MAGIC):]
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(raw, len(raw))
    blob_in = _DATA_BLOB(len(raw), buf)
    blob_out = _DATA_BLOB()
    if crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out)):
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)
    raise ValueError("DPAPI decryption failed for credential blob")


def write_cred_blob(cred_file, plaintext_bytes):
    """Encrypts credential blob with DPAPI and writes it atomically."""
    protected = dpapi_encrypt(plaintext_bytes)
    atomic_write_bytes(cred_file, protected)


def read_cred_blob(cred_file):
    """Reads credential blob, decrypting DPAPI or auto-migrating legacy plaintext on read."""
    with open(cred_file, "rb") as f:
        raw = f.read()
    if raw.startswith(DPAPI_MAGIC):
        return dpapi_decrypt(raw)
    # Legacy plaintext JSON: migrate transparently to DPAPI at rest
    if os.name == "nt" and raw.lstrip().startswith(b"{"):
        try:
            write_cred_blob(cred_file, raw)
        except Exception:
            pass
    return raw


def load_quota_disk_cache():
    if os.path.exists(QUOTA_CACHE_FILE):
        try:
            with open(QUOTA_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            quotas = data.get("quotas", {})
            t = data.get("time", time.time())
            with _QUOTA_LOCK:
                _QUOTA_CACHE.clear()
                _QUOTA_CACHE.update(quotas)
                _QUOTA_CACHE_TIME.clear()
                for acc in quotas:
                    _QUOTA_CACHE_TIME[acc] = t
        except Exception:
            pass


def save_quota_disk_cache():
    try:
        ensure_dirs()
        with _QUOTA_LOCK:
            snapshot = dict(_QUOTA_CACHE)
        atomic_write_text(QUOTA_CACHE_FILE, json.dumps({"quotas": snapshot, "time": time.time()}))
    except Exception:
        pass

load_quota_disk_cache()

class CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", ctypes.wintypes.DWORD),
        ("Type", ctypes.wintypes.DWORD),
        ("TargetName", ctypes.wintypes.LPWSTR),
        ("Comment", ctypes.wintypes.LPWSTR),
        ("LastWritten", ctypes.wintypes.FILETIME),
        ("CredentialBlobSize", ctypes.wintypes.DWORD),
        ("CredentialBlob", ctypes.c_void_p),
        ("Persist", ctypes.wintypes.DWORD),
        ("AttributeCount", ctypes.wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", ctypes.wintypes.LPWSTR),
        ("UserName", ctypes.wintypes.LPWSTR),
    ]

PCREDENTIALW = ctypes.POINTER(CREDENTIALW)
advapi32 = ctypes.windll.advapi32

def ensure_dirs():
    os.makedirs(SWITCHER_DIR, exist_ok=True)
    os.makedirs(ACCOUNTS_DIR, exist_ok=True)

def read_windows_credential(target_name=CRED_TARGET):
    pcred = PCREDENTIALW()
    if not advapi32.CredReadW(target_name, 1, 0, ctypes.byref(pcred)):
        return None
    try:
        cred = pcred.contents
        blob = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
        return {
            "target": cred.TargetName,
            "user_name": cred.UserName or "",
            "persist": cred.Persist,
            "blob": blob
        }
    finally:
        advapi32.CredFree(pcred)

def write_windows_credential(target_name, blob, user_name=""):
    blob_bytes = blob if isinstance(blob, bytes) else blob.encode("utf-8")
    cred = CREDENTIALW()
    cred.Flags = 0
    cred.Type = 1  # CRED_TYPE_GENERIC
    cred.TargetName = target_name
    cred.Comment = "Managed by Antigravity Control Center"
    cred.CredentialBlobSize = len(blob_bytes)
    cred.CredentialBlob = ctypes.cast(ctypes.c_char_p(blob_bytes), ctypes.c_void_p)
    cred.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE
    cred.AttributeCount = 0
    cred.Attributes = None
    cred.TargetAlias = None
    cred.UserName = user_name
    return bool(advapi32.CredWriteW(ctypes.byref(cred), 0))

def delete_windows_credential(target_name=CRED_TARGET):
    return bool(advapi32.CredDeleteW(target_name, 1, 0))

def fetch_email_from_blob(blob):
    try:
        data = json.loads(blob.decode("utf-8", errors="ignore"))
        email = data.get("email") or data.get("user") or data.get("account")
        if email:
            return email
        token_info = data.get("token")
        token_str = ""
        if isinstance(token_info, dict):
            token_str = token_info.get("access_token") or token_info.get("id_token") or ""
        elif isinstance(token_info, str):
            token_str = token_info
        id_token = data.get("id_token") or token_str
        if id_token and "." in id_token:
            parts = id_token.split(".")
            if len(parts) >= 2:
                import base64
                pad = len(parts[1]) % 4
                padded = parts[1] + ("=" * (4 - pad) if pad else "")
                payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode("utf-8", errors="ignore"))
                return payload.get("email")
    except Exception:
        pass
    return None

def refresh_access_token(refresh_token):
    if not refresh_token:
        return None
    try:
        payload = {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        }
        req_data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=req_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("access_token")
    except Exception:
        return None

def parse_reset_delta(reset_time_str):
    """
    Returns (human_delta, local_target_str)
    e.g. ('4h 37m', 'Today, 6:18 PM')
    """
    if not reset_time_str:
        return ("", "")
    try:
        ts_clean = reset_time_str.replace("Z", "+00:00")
        dt_utc = datetime.fromisoformat(ts_clean)
        dt_local = dt_utc.astimezone()
        now_local = datetime.now().astimezone()

        diff = dt_local - now_local
        total_seconds = int(diff.total_seconds())

        is_today = dt_local.date() == now_local.date()
        time_part = dt_local.strftime("%I:%M %p").lstrip("0")
        if is_today:
            local_target = f"Today, {time_part}"
        elif (dt_local.date() - now_local.date()).days == 1:
            local_target = f"Tmrw, {time_part}"
        else:
            local_target = f"{dt_local.strftime('%b %d')}, {time_part}"

        if total_seconds <= 0:
            return ("Ready", local_target)

        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60

        if hours >= 24:
            days = hours // 24
            rem_h = hours % 24
            delta_str = f"{days}d {rem_h}h"
        elif hours > 0:
            delta_str = f"{hours}h {minutes}m"
        else:
            delta_str = f"{minutes}m"

        return (delta_str, local_target)
    except Exception:
        return ("", "")

def fetch_quota_summary(email, force_refresh=False):
    """Fetches real-time quota for a given account email with tiered caching & safety backoff."""
    global _RATE_LIMIT_COOLDOWN
    now = time.time()
    active_email = get_active_email()
    ttl = ACTIVE_CACHE_TTL if email == active_email else STANDBY_CACHE_TTL

    # If in rate-limit cooldown, return cached data
    with _QUOTA_LOCK:
        if now < _RATE_LIMIT_COOLDOWN and email in _QUOTA_CACHE:
            return dict(_QUOTA_CACHE[email])
        if not force_refresh and email in _QUOTA_CACHE:
            if now - _QUOTA_CACHE_TIME.get(email, 0) < ttl:
                return dict(_QUOTA_CACHE[email])

    ensure_dirs()
    acc_dir = get_account_dir(email)
    if not acc_dir:
        return {"error": "Invalid account identifier"}
    cred_file = os.path.join(acc_dir, "cred.bin")

    if not os.path.exists(cred_file):
        return {"error": "No credential file found"}

    try:
        blob = read_cred_blob(cred_file)
        cred_data = json.loads(blob.decode("utf-8", errors="ignore"))
    except Exception as e:
        return {"error": f"Failed to load credentials: {e}"}

    tok_obj = cred_data.get("token", {})
    access_token = ""
    refresh_token = ""
    if isinstance(tok_obj, dict):
        access_token = tok_obj.get("access_token", "")
        refresh_token = tok_obj.get("refresh_token", "")
    elif isinstance(tok_obj, str):
        access_token = tok_obj

    # Always ensure valid access token
    if not access_token and refresh_token:
        access_token = refresh_access_token(refresh_token)
        if access_token and isinstance(tok_obj, dict):
            tok_obj["access_token"] = access_token
            try:
                write_cred_blob(cred_file, json.dumps(cred_data).encode("utf-8"))
            except Exception:
                pass

    if not access_token:
        return {"error": "Missing access token"}

    url = "https://daily-cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary"
    req = urllib.request.Request(
        url,
        data=b"{}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "User-Agent": "antigravity/2.12.2"
        }
    )

    def do_call(tok):
        req.add_header("Authorization", f"Bearer {tok}")
        with urllib.request.urlopen(req, timeout=3.5) as r:
            return json.loads(r.read().decode("utf-8"))

    try:
        try:
            res = do_call(access_token)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                import random
                _RATE_LIMIT_COOLDOWN = time.time() + random.uniform(100.0, 140.0)
                with _QUOTA_LOCK:
                    if email in _QUOTA_CACHE:
                        return dict(_QUOTA_CACHE[email])
                return {"error": "HTTP 429: Rate limited by Google (backing off)"}
            if e.code == 401 and refresh_token:
                # Refresh once
                new_tok = refresh_access_token(refresh_token)
                if new_tok:
                    access_token = new_tok
                    if isinstance(tok_obj, dict):
                        tok_obj["access_token"] = new_tok
                        try:
                            write_cred_blob(cred_file, json.dumps(cred_data).encode("utf-8"))
                        except Exception:
                            pass
                    res = do_call(new_tok)
                else:
                    return {"error": "HTTP 401: Unauthorized (refresh failed)"}
            else:
                return {"error": f"HTTP {e.code}"}

        summary = {}
        for g in res.get("groups", []):
            g_name = g.get("displayName", "")
            buckets = {}
            for b in g.get("buckets", []):
                w = b.get("window", "")
                rem = float(b.get("remainingFraction", 1.0)) * 100.0
                rt = b.get("resetTime", "")
                delta, local_target = parse_reset_delta(rt)
                buckets[w] = {
                    "remaining": round(rem, 2),
                    "resetTime": rt,
                    "resetDelta": delta,
                    "resetLocalTime": local_target
                }

            if "Gemini" in g_name:
                summary["gemini"] = buckets
            elif "Claude" in g_name:
                summary["claude"] = buckets

        with _QUOTA_LOCK:
            _QUOTA_CACHE[email] = summary
            _QUOTA_CACHE_TIME[email] = now
        return dict(summary)
    except Exception as e:
        return {"error": str(e)}

def get_account_meta_info(accounts):
    """
    Inspects credentials for all accounts to identify actual Google account ownership
    and detect duplicate tokens across account profiles.
    """
    token_map = {}
    info_map = {}

    for acc in accounts:
        acc_dir = get_account_dir(acc)
        if not acc_dir:
            continue
        cred_file = os.path.join(acc_dir, "cred.bin")
        meta_file = os.path.join(acc_dir, "meta.json")
        google_account = acc
        rf_token = None

        if os.path.exists(cred_file):
            try:
                blob = read_cred_blob(cred_file)
                data = json.loads(blob.decode("utf-8", errors="ignore"))
                tok_obj = data.get("token", {})
                if isinstance(tok_obj, dict):
                    rf_token = tok_obj.get("refresh_token")
                extracted = fetch_email_from_blob(blob)
                if extracted:
                    google_account = extracted
            except Exception:
                pass

        if os.path.exists(meta_file):
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta_d = json.load(f)
                    if "google_account" in meta_d:
                        google_account = meta_d["google_account"]
            except Exception:
                pass

        info_map[acc] = {
            "google_account": google_account,
            "refresh_token": rf_token,
            "is_duplicate": False,
            "duplicate_of": None
        }
        if rf_token:
            token_map.setdefault(rf_token, []).append(acc)

    for rf_token, acc_list in token_map.items():
        if len(acc_list) > 1:
            canonical = acc_list[0]
            for a in acc_list:
                if info_map[a]["google_account"] == a:
                    canonical = a
                    break
            for a in acc_list:
                if a != canonical:
                    info_map[a]["is_duplicate"] = True
                    info_map[a]["duplicate_of"] = canonical
                    if info_map[a]["google_account"] == a:
                        info_map[a]["google_account"] = info_map[canonical]["google_account"]

    return info_map

def fetch_all_quotas_parallel(accounts, force_refresh=False):
    """
    Instantly refreshes quotas for ALL accounts concurrently in parallel.
    Completes in <1.0 second.
    """
    results = {}
    if not accounts:
        return results

    meta_info = get_account_meta_info(accounts)

    with ThreadPoolExecutor(max_workers=min(6, len(accounts))) as executor:
        future_map = {executor.submit(fetch_quota_summary, acc, force_refresh): acc for acc in accounts}
        for future in as_completed(future_map):
            acc = future_map[future]
            try:
                res = future.result()
                if isinstance(res, dict):
                    m = meta_info.get(acc, {})
                    res["google_account"] = m.get("google_account", acc)
                    res["is_duplicate"] = m.get("is_duplicate", False)
                    res["duplicate_of"] = m.get("duplicate_of", None)
                results[acc] = res
            except Exception as e:
                results[acc] = {"error": str(e)}

    # Inject meta for cached results as well
    for acc, res in results.items():
        if isinstance(res, dict) and "google_account" not in res:
            m = meta_info.get(acc, {})
            res["google_account"] = m.get("google_account", acc)
            res["is_duplicate"] = m.get("is_duplicate", False)
            res["duplicate_of"] = m.get("duplicate_of", None)

    save_quota_disk_cache()
    return results

def get_saved_accounts():
    ensure_dirs()
    accs = []
    if os.path.exists(ACCOUNTS_DIR):
        for name in os.listdir(ACCOUNTS_DIR):
            p = os.path.join(ACCOUNTS_DIR, name)
            if os.path.isdir(p) and os.path.exists(os.path.join(p, "cred.bin")):
                accs.append(name)
    active = get_active_email()
    if active and active not in accs:
        accs.append(active)
    return sorted(list(set(accs)))

def get_active_email():
    if os.path.exists(ACTIVE_FILE):
        try:
            with open(ACTIVE_FILE, "r", encoding="utf-8") as f:
                em = f.read().strip()
                if em:
                    return em
        except Exception:
            pass
    win = read_windows_credential()
    if win and win.get("blob"):
        em = fetch_email_from_blob(win["blob"])
        if em:
            with open(ACTIVE_FILE, "w", encoding="utf-8") as f:
                f.write(em)
            return em
    return "default"

def save_active_credential():
    ensure_dirs()
    cred = read_windows_credential()
    if not cred:
        return None
    email = fetch_email_from_blob(cred["blob"])
    if not email:
        email = get_active_email()
    if not email:
        email = "default"

    acc_dir = get_account_dir(email)
    if not acc_dir:
        return None
    os.makedirs(acc_dir, exist_ok=True)
    write_cred_blob(os.path.join(acc_dir, "cred.bin"), cred["blob"])
    atomic_write_text(
        os.path.join(acc_dir, "meta.json"),
        json.dumps({"email": email, "user_name": cred["user_name"], "updated": datetime.now().isoformat()}, indent=2)
    )
    atomic_write_text(ACTIVE_FILE, email)
    return email

def clear_session_cache():
    cleaned = 0
    patterns = [
        os.path.join(APPDATA, "Antigravity", "DevToolsActivePort"),
        os.path.join(APPDATA, "Antigravity", "SingletonLock"),
        os.path.join(APPDATA, "Antigravity", "SingletonSocket"),
        os.path.join(APPDATA, "Antigravity", "SingletonCookie"),
    ]
    for p in patterns:
        if os.path.exists(p):
            try:
                os.remove(p)
                cleaned += 1
            except Exception:
                pass
    return cleaned

def restart_antigravity():
    """
    Terminates running Antigravity IDE instances, cleans session locks,
    and launches a fresh Antigravity IDE process with the active account.
    """
    candidates = [
        os.path.join(LOCALAPPDATA, "Programs", "antigravity", "Antigravity.exe"),
        os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "antigravity", "Antigravity.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "antigravity", "Antigravity.exe"),
    ]
    exe_path = None
    for cand in candidates:
        if cand and os.path.exists(cand):
            exe_path = cand
            break
    if not exe_path:
        exe_path = shutil.which("antigravity") or shutil.which("Antigravity.exe")

    # 1. Terminate running Antigravity IDE instances
    try:
        flags = 0x08000000 if os.name == 'nt' else 0  # CREATE_NO_WINDOW
        subprocess.run(["taskkill", "/F", "/IM", "Antigravity.exe", "/T"],
                       capture_output=True,
                       creationflags=flags)
    except Exception:
        pass

    # 2. Wait for OS socket & file cleanup
    time.sleep(0.6)

    # 3. Clean Electron session lock files
    clear_session_cache()

    # 4. Spawn fresh instance detached
    if exe_path and os.path.exists(exe_path):
        flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == 'nt' else 0
        subprocess.Popen([exe_path], creationflags=flags, close_fds=True)
        return True
    return False

def reload_language_server():
    """
    Gracefully restarts the language_server process without closing Antigravity IDE.
    The IDE's host bridge automatically respawns language_server with the updated credentials.
    """
    try:
        flags = 0x08000000 if os.name == 'nt' else 0  # CREATE_NO_WINDOW
        subprocess.run(["taskkill", "/F", "/IM", "language_server.exe"], capture_output=True, creationflags=flags)
        return True
    except Exception:
        return False

def switch_to_account(target_email, restart_ide=False, reload_ls=True):
    ensure_dirs()
    acc_dir = get_account_dir(target_email)
    if not acc_dir:
        return {"ok": False, "error": "Invalid target account identifier"}
    save_active_credential()

    cred_file = os.path.join(acc_dir, "cred.bin")
    if not os.path.exists(cred_file):
        return {"ok": False, "error": f"Credential for {target_email} not found"}

    try:
        blob = read_cred_blob(cred_file)
    except Exception as e:
        return {"ok": False, "error": f"Could not read credential blob: {e}"}

    success = write_windows_credential(CRED_TARGET, blob, user_name=target_email)
    if not success:
        return {"ok": False, "error": "Win32 CredWriteW failed"}

    atomic_write_text(ACTIVE_FILE, target_email)

    clear_session_cache()
    # Invalidate cache for target
    with _QUOTA_LOCK:
        _QUOTA_CACHE.pop(target_email, None)

    restarted = False
    ls_reloaded = False
    if restart_ide:
        restarted = restart_antigravity()
    elif reload_ls:
        ls_reloaded = reload_language_server()

    return {"ok": True, "active": target_email, "restarted": restarted, "ls_reloaded": ls_reloaded}

def get_seconds_until_reset(reset_time_str):
    if not reset_time_str:
        return 999999999
    try:
        ts_clean = reset_time_str.replace("Z", "+00:00")
        dt_utc = datetime.fromisoformat(ts_clean)
        dt_local = dt_utc.astimezone()
        now_local = datetime.now().astimezone()
        diff = (dt_local - now_local).total_seconds()
        return max(0, int(diff))
    except Exception:
        return 999999999

def evaluate_account_recommendations(active_email, accounts, quotas):
    """
    Intelligent multi-factor recommendation engine:
    1. Session Continuity: If active account has healthy quota (5h >= 20% and weekly >= 15%),
       keep active account as optimal (no disruptive switching recommended).
    2. Rate Limit Detection: If active account 5h is low (<20%), find the optimal fallback standby.
    3. Urgency Optimization ("Use-it-before-you-lose-it"): Prioritize standby accounts whose
       weekly quota resets soonest, provided they have available 5h capacity (>= 20%).
    4. Cooldown & Duplicate Exclusion: Standbys with 0% 5h quota are marked Cooldown; duplicates are penalized.
    """
    if not accounts:
        return {"best": active_email, "details": {}}

    account_metrics = {}
    for acc in accounts:
        q = quotas.get(acc, {})
        if not q or "error" in q:
            account_metrics[acc] = {
                "g5": 0.0, "gw": 0.0, "g5_sec": 999999, "gw_sec": 999999,
                "gw_delta": "", "is_dup": False, "valid": False
            }
            continue

        gemini = q.get("gemini", {})
        g5_obj = gemini.get("5h", {})
        gw_obj = gemini.get("weekly", {})
        g5 = float(g5_obj.get("remaining", 0.0))
        gw = float(gw_obj.get("remaining", 0.0))
        g5_sec = get_seconds_until_reset(g5_obj.get("resetTime", ""))
        gw_sec = get_seconds_until_reset(gw_obj.get("resetTime", ""))
        gw_delta = gw_obj.get("resetDelta", "")
        is_dup = bool(q.get("is_duplicate", False))

        account_metrics[acc] = {
            "g5": g5,
            "gw": gw,
            "g5_sec": g5_sec,
            "gw_sec": gw_sec,
            "gw_delta": gw_delta,
            "is_dup": is_dup,
            "valid": True
        }

    # 1. Check if active account is healthy
    active_m = account_metrics.get(active_email, {"g5": 0.0, "gw": 0.0})
    active_is_healthy = active_m.get("g5", 0.0) >= 20.0 and active_m.get("gw", 0.0) >= 15.0

    best_acc = active_email
    best_fallback = None
    best_fallback_score = -999.0

    # Evaluate standbys
    for acc in accounts:
        if acc == active_email:
            continue
        m = account_metrics.get(acc, {})
        if not m.get("valid") or m.get("is_dup"):
            continue
        if m.get("g5", 0.0) < 20.0:
            continue  # Not enough 5h cycle capacity

        # Standby score: capacity + reset urgency bonus
        score = (m["g5"] * 0.4) + (m["gw"] * 0.3)
        if m["gw_sec"] < 2 * 86400:     # Resets within 2 days
            score += 35.0
        elif m["gw_sec"] < 4 * 86400:   # Resets within 4 days
            score += 20.0
        elif m["gw_sec"] < 6 * 86400:   # Resets within 6 days
            score += 10.0

        if score > best_fallback_score:
            best_fallback_score = score
            best_fallback = acc

    if not active_is_healthy and best_fallback:
        best_acc = best_fallback

    # Build per-account recommendation details
    details = {}
    for acc in accounts:
        is_active = (acc == active_email)
        m = account_metrics.get(acc, {})

        if is_active:
            if active_is_healthy:
                status = "active"
                badge_label = "Active"
                badge_color = "emerald"
                reason = "Active • Quota Healthy"
            else:
                status = "active_low"
                badge_label = "Active (Low)"
                badge_color = "amber"
                reason = "Quota Low • Switch Recommended"
        elif acc == best_fallback and not active_is_healthy:
            status = "recommended"
            badge_label = "Recommended"
            badge_color = "blue"
            urgency_str = f"Resets in {m['gw_delta']}" if m.get("gw_delta") else "Optimal Quota"
            reason = f"Best Fallback • {urgency_str}"
        elif m.get("g5", 100) <= 0.0:
            status = "cooldown"
            badge_label = "Cooldown"
            badge_color = "amber"
            reason = "5h Cycle Depleted"
        else:
            status = "standby"
            badge_label = "Standby"
            badge_color = "gray"
            urgency_str = f"Resets in {m['gw_delta']}" if m.get("gw_delta") else "Ready"
            reason = f"Standby • {urgency_str}"

        details[acc] = {
            "status": status,
            "badge_label": badge_label,
            "badge_color": badge_color,
            "reason": reason,
            "is_best": (acc == best_acc)
        }

    return {"best": best_acc, "details": details}

def score_account(quota_data):
    if not quota_data or "error" in quota_data:
        return -1.0
    gemini = quota_data.get("gemini", {})
    claude = quota_data.get("claude", {})
    g5 = float(gemini.get("5h", {}).get("remaining", 0.0))
    gw = float(gemini.get("weekly", {}).get("remaining", 0.0))
    c5 = float(claude.get("5h", {}).get("remaining", 0.0))
    cw = float(claude.get("weekly", {}).get("remaining", 0.0))
    if g5 < 10.0:
        return 0.0
    gw_sec = get_seconds_until_reset(gemini.get("weekly", {}).get("resetTime", ""))
    urgency = 0.0
    if gw_sec < 2 * 86400:
        urgency = 25.0
    elif gw_sec < 4 * 86400:
        urgency = 15.0
    return (g5 * 0.4) + (gw * 0.3) + (c5 * 0.2) + (cw * 0.1) + urgency

if __name__ == "__main__":
    print("Testing Parallel Quota Fetcher...")
    accs = get_saved_accounts()
    print("Accounts:", accs)
    t0 = time.time()
    res = fetch_all_quotas_parallel(accs, force_refresh=True)
    t1 = time.time()
    print(f"Parallel fetch took {t1 - t0:.2f} seconds!")
    for a, q in res.items():
        if "error" in q:
            print(f"  {a}: Error = {q['error']}")
        else:
            g5 = q.get("gemini", {}).get("5h", {})
            gw = q.get("gemini", {}).get("weekly", {})
            print(f"  {a}: Gemini 5h={g5.get('remaining')}% (resets in {g5.get('resetDelta')}, target: {g5.get('resetLocalTime')}), Weekly={gw.get('remaining')}% (resets in {gw.get('resetDelta')}, target: {gw.get('resetLocalTime')})")
