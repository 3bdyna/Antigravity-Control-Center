"""Stdlib-only secure self-updater for Antigravity Control Center (GitHub Releases)."""

import hashlib
import hmac
import json
import os
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from version import APP_VERSION, GITHUB_REPO, updates_dir

TRUSTED_DOWNLOAD_HOSTS = frozenset({
    "github.com",
    "api.github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "github-releases.githubusercontent.com",
    "codeload.github.com",
})

_SEMVER_RE = re.compile(r"^[vV]?(\d+)\.(\d+)\.(\d+)$")
_INSTALLER_NAME_RE = re.compile(r"^AntigravityControlCenter-Setup-\d+\.\d+\.\d+\.exe$")
_SHA256_LINE_RE = re.compile(r"^\s*([0-9a-fA-F]{64})\s+\*?(.+?)\s*$")
_MAX_CHECKSUMS_BYTES = 1024 * 1024  # 1 MiB cap for SHA256SUMS.txt
_DOWNLOAD_CHUNK_SIZE = 64 * 1024  # 64 KiB streaming chunks


class UpdateError(RuntimeError):
    """Raised when an update check, download, or verification fails."""


class UpdateCancelledError(UpdateError):
    """Raised when an in-progress update download is cancelled."""


def parse_version(ver: str) -> tuple[int, int, int]:
    """Parse a semantic version string ('1.4.0' or 'v1.4.0') into a numeric tuple."""
    if not isinstance(ver, str):
        raise ValueError(f"Version must be a string, got {type(ver).__name__}")
    match = _SEMVER_RE.match(ver.strip())
    if not match:
        raise ValueError(f"Invalid semantic version: {ver!r}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def is_newer_version(latest: str, current: str) -> bool:
    """Return True if latest is strictly newer than current using numeric semver."""
    return parse_version(latest) > parse_version(current)


def validate_trusted_https_url(url: str) -> str:
    """Ensure a URL uses HTTPS and targets a host in TRUSTED_DOWNLOAD_HOSTS."""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("Download URL must be a non-empty string")
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme.lower() != "https":
        raise ValueError(f"Untrusted URL scheme (HTTPS required): {parsed.scheme!r}")
    if parsed.username or parsed.password:
        raise ValueError("URL credentials are not permitted")
    host = (parsed.hostname or "").lower()
    if host not in TRUSTED_DOWNLOAD_HOSTS:
        raise ValueError(f"Untrusted download host: {host!r}")
    return url.strip()


class TrustedHTTPSRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Redirect handler that enforces HTTPS-only and TRUSTED_DOWNLOAD_HOSTS on every hop."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        resolved = urllib.parse.urljoin(req.full_url, newurl)
        validate_trusted_https_url(resolved)
        redirected = super().redirect_request(req, fp, code, msg, headers, resolved)
        if redirected is not None:
            # Strip sensitive headers across hosts
            orig_host = (urllib.parse.urlparse(req.full_url).hostname or "").lower()
            next_host = (urllib.parse.urlparse(resolved).hostname or "").lower()
            if orig_host != next_host:
                redirected.headers.pop("Authorization", None)
                redirected.unredirected_hdrs.pop("Authorization", None)
        return redirected


def _find_bundled_cafile() -> Optional[str]:
    """Locate a bundled cacert.pem in PyInstaller frozen layouts, if present."""
    candidates: list[str] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, "cacert.pem"))
    exe_dir = os.path.dirname(sys.executable)
    if exe_dir:
        candidates.append(os.path.join(exe_dir, "_internal", "cacert.pem"))
        candidates.append(os.path.join(exe_dir, "cacert.pem"))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def build_secure_opener() -> urllib.request.OpenerDirector:
    """Create a urllib opener with strict TLS verification and trusted-host redirects."""
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.load_default_certs(ssl.Purpose.SERVER_AUTH)
    cafile = _find_bundled_cafile()
    if cafile:
        ssl_ctx.load_verify_locations(cafile=cafile)
    return urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl_ctx),
        TrustedHTTPSRedirectHandler(),
    )


def _open_trusted(url: str, headers: dict | None = None, timeout: float = 15.0):
    safe_url = validate_trusted_https_url(url)
    req_headers = {"User-Agent": f"AntigravityControlCenter/{APP_VERSION}"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(safe_url, headers=req_headers, method="GET")
    opener = build_secure_opener()
    return opener.open(req, timeout=timeout)


def parse_sha256sums(content: str, target_filename: str) -> str:
    """Extract the expected 64-hex-char SHA-256 digest for target_filename from SHA256SUMS.txt."""
    if not target_filename:
        raise ValueError("Target filename is required")
    cleaned = content.lstrip("\ufeff")
    for line in cleaned.splitlines():
        match = _SHA256_LINE_RE.match(line)
        if not match:
            continue
        digest, fname = match.group(1).lower(), match.group(2).strip()
        if os.path.basename(fname) == target_filename:
            return digest
    raise ValueError(f"No SHA-256 entry found for {target_filename!r} in SHA256SUMS.txt")


def verify_file_sha256(file_path: Path, expected_sha256: str) -> bool:
    """Stream-hash file_path with SHA-256 and compare via hmac.compare_digest."""
    expected = (expected_sha256 or "").strip().lower()
    if len(expected) != 64 or not all(c in "0123456789abcdef" for c in expected):
        return False
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(_DOWNLOAD_CHUNK_SIZE)
            if not chunk:
                break
            hasher.update(chunk)
    actual = hasher.hexdigest().lower()
    return hmac.compare_digest(actual, expected)


def check_for_updates(timeout: float = 8.0) -> dict:
    """Query GitHub Releases latest endpoint and return structured update metadata."""
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    releases_page = f"https://github.com/{GITHUB_REPO}/releases"
    try:
        with _open_trusted(
            api_url,
            headers={"Accept": "application/vnd.github+json"},
            timeout=timeout,
        ) as resp:
            raw = resp.read(_MAX_CHECKSUMS_BYTES)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {
                "ok": True,
                "current_version": APP_VERSION,
                "latest_version": APP_VERSION,
                "update_available": False,
                "release_notes": "",
                "release_url": releases_page,
                "published_at": "",
                "asset_name": "",
                "asset_url": "",
                "asset_size": 0,
                "checksums_url": "",
            }
        raise UpdateError(f"GitHub API returned HTTP {e.code}") from e
    except Exception as e:
        raise UpdateError(f"Failed to check for updates: {e}") from e

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise UpdateError("Invalid JSON response from GitHub Releases API") from e

    tag_name = str(payload.get("tag_name") or "").strip()
    parsed_latest = parse_version(tag_name)
    latest_version = f"{parsed_latest[0]}.{parsed_latest[1]}.{parsed_latest[2]}"
    expected_asset_name = f"AntigravityControlCenter-Setup-{latest_version}.exe"

    exe_asset = None
    sums_asset = None
    for asset in payload.get("assets") or []:
        name = str(asset.get("name") or "")
        if name == expected_asset_name:
            exe_asset = asset
        elif name == "SHA256SUMS.txt":
            sums_asset = asset

    asset_url = str(exe_asset.get("browser_download_url") or "") if exe_asset else ""
    checksums_url = str(sums_asset.get("browser_download_url") or "") if sums_asset else ""
    if asset_url:
        validate_trusted_https_url(asset_url)
    if checksums_url:
        validate_trusted_https_url(checksums_url)

    release_url = str(payload.get("html_url") or releases_page)
    try:
        validate_trusted_https_url(release_url)
    except ValueError:
        release_url = releases_page

    return {
        "ok": True,
        "current_version": APP_VERSION,
        "latest_version": latest_version,
        "update_available": is_newer_version(latest_version, APP_VERSION),
        "release_notes": str(payload.get("body") or ""),
        "release_url": release_url,
        "published_at": str(payload.get("published_at") or ""),
        "asset_name": expected_asset_name if exe_asset else "",
        "asset_url": asset_url,
        "asset_size": int(exe_asset.get("size") or 0) if exe_asset else 0,
        "checksums_url": checksums_url,
    }


def download_and_verify_update(
    release_info: dict,
    progress_cb=None,
    cancel_event=None,
    timeout: float = 30.0,
) -> Path:
    """Download installer + SHA256SUMS.txt, verify digest, and atomically commit to updates_dir()."""
    if not isinstance(release_info, dict):
        raise UpdateError("Missing release metadata")

    asset_name = str(release_info.get("asset_name") or "").strip()
    asset_url = str(release_info.get("asset_url") or "").strip()
    checksums_url = str(release_info.get("checksums_url") or "").strip()

    if not _INSTALLER_NAME_RE.match(asset_name):
        raise UpdateError(f"Invalid installer filename: {asset_name!r}")
    if not asset_url:
        raise UpdateError("Release does not contain a matching Windows installer asset")
    if not checksums_url:
        raise UpdateError("Release does not contain SHA256SUMS.txt for verification")

    validate_trusted_https_url(asset_url)
    validate_trusted_https_url(checksums_url)

    if cancel_event is not None and cancel_event.is_set():
        raise UpdateCancelledError("Update download cancelled")

    # 1. Fetch and parse SHA256SUMS.txt first
    try:
        with _open_trusted(checksums_url, timeout=timeout) as resp:
            sums_raw = resp.read(_MAX_CHECKSUMS_BYTES + 1)
    except Exception as e:
        raise UpdateError(f"Failed to download SHA256SUMS.txt: {e}") from e

    if len(sums_raw) > _MAX_CHECKSUMS_BYTES:
        raise UpdateError("SHA256SUMS.txt exceeds maximum permitted size")

    expected_sha256 = parse_sha256sums(sums_raw.decode("utf-8", errors="replace"), asset_name)

    # 2. Prepare verified destination paths strictly inside updates_dir()
    upd_dir = updates_dir().resolve()
    part_path = (upd_dir / f"{asset_name}.part").resolve()
    final_path = (upd_dir / asset_name).resolve()
    if part_path.parent != upd_dir or final_path.parent != upd_dir:
        raise UpdateError("Installer destination escapes updates_dir()")

    # Remove any leftover .part file before downloading
    try:
        if part_path.exists():
            part_path.unlink()
    except OSError:
        pass

    expected_size = int(release_info.get("asset_size") or 0)
    downloaded = 0

    try:
        with _open_trusted(asset_url, timeout=timeout) as resp:
            if expected_size <= 0:
                cl = resp.headers.get("Content-Length")
                if cl and cl.isdigit():
                    expected_size = int(cl)
            with open(part_path, "wb") as out:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise UpdateCancelledError("Update download cancelled")
                    chunk = resp.read(_DOWNLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb is not None and expected_size > 0:
                        pct = min(99, int((downloaded * 100) / expected_size))
                        try:
                            progress_cb(pct)
                        except Exception:
                            pass
                out.flush()
                os.fsync(out.fileno())

        if cancel_event is not None and cancel_event.is_set():
            raise UpdateCancelledError("Update download cancelled")

        # 3. Verify SHA-256 on disk BEFORE atomic rename
        if not verify_file_sha256(part_path, expected_sha256):
            raise UpdateError("SHA-256 verification failed: installer file may be corrupted or tampered")

        os.replace(part_path, final_path)
        if progress_cb is not None:
            try:
                progress_cb(100)
            except Exception:
                pass
        return final_path
    except Exception:
        try:
            if part_path.exists():
                part_path.unlink()
        except OSError:
            pass
        raise


def launch_installer(installer_path) -> subprocess.Popen:
    """Validate installer_path is inside updates_dir() and launch it detached for silent update."""
    if not installer_path:
        raise ValueError("Installer path is required")
    upd_dir = updates_dir().resolve()
    resolved = Path(installer_path).resolve()
    if resolved.parent != upd_dir:
        raise ValueError("Installer path must reside directly inside updates_dir()")
    if not _INSTALLER_NAME_RE.match(resolved.name):
        raise ValueError(f"Unexpected installer filename: {resolved.name!r}")
    if not resolved.is_file():
        raise FileNotFoundError(f"Verified installer not found: {resolved}")

    cmd = [
        str(resolved),
        "/SILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/CLOSEAPPLICATIONS",
        "/FORCECLOSEAPPLICATIONS",
        "/RELAUNCH",
    ]
    creationflags = 0
    if sys.platform == "win32":
        detached = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        new_group = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        creationflags = detached | new_group

    return subprocess.Popen(
        cmd,
        cwd=str(upd_dir),
        creationflags=creationflags,
        close_fds=True,
    )
