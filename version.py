"""Single source of truth for Antigravity Control Center version and paths."""

import sys
from pathlib import Path

APP_VERSION = "1.4.0"
GITHUB_REPO = "3bdyna/Antigravity-Control-Center"


def is_frozen() -> bool:
    """Return True when running from a PyInstaller-frozen executable."""
    return bool(getattr(sys, "frozen", False))


def user_data_dir() -> Path:
    """Return the per-user Antigravity Control Center data directory."""
    return Path.home() / ".gemini" / "antigravity-switcher"


def updates_dir() -> Path:
    """Return the per-user installer download cache directory, creating it if needed."""
    path = user_data_dir() / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cleanup_old_installers(keep_paths=None) -> int:
    """Safely remove stale .part files and old installer executables inside updates_dir().

    Never touches accounts, SQLite databases, or any path outside updates_dir().
    Returns the number of files deleted.
    """
    upd_dir = updates_dir().resolve()
    keep = set()
    if keep_paths:
        for p in keep_paths:
            try:
                keep.add(Path(p).resolve())
            except Exception:
                pass

    removed = 0
    try:
        entries = list(upd_dir.iterdir())
    except OSError:
        return 0

    for entry in entries:
        try:
            resolved = entry.resolve()
            if resolved.parent != upd_dir or not entry.is_file():
                continue
            if resolved in keep:
                continue
            name = entry.name
            if (
                name.endswith(".part")
                or (name.startswith("AntigravityControlCenter-Setup-") and name.endswith(".exe"))
                or name == "SHA256SUMS.txt"
            ):
                entry.unlink()
                removed += 1
        except OSError:
            continue
    return removed
