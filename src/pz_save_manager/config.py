"""Configuration management for PZ Save Manager.

Config stored in ~/.pz-save-manager/config.json
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from .platforms import get_app_dir

_lock = threading.Lock()

CONFIG_FILE = get_app_dir() / "config.json"

DEFAULTS = {
    "backups_dir": None,
    "debounce_seconds": 5.0,
    "backup_cooldown_minutes": 1,
    "max_auto_backups": 30,
    "auto_start_watcher": False,
    "port": 8080,
}


def _load() -> dict:
    if CONFIG_FILE.is_file():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save(data: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: write to temp file in the same directory, then replace.
    # This prevents corruption if the process is killed mid-write.
    fd, tmp_path = tempfile.mkstemp(
        suffix=".tmp", prefix=".config-", dir=str(CONFIG_FILE.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, CONFIG_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def get(key: str):
    """Get a config value, falling back to defaults."""
    data = _load()
    if key in data:
        return data[key]
    return DEFAULTS.get(key)


def set_(key: str, value) -> None:
    """Set a config value and save."""
    with _lock:
        data = _load()
        data[key] = value
        _save(data)


def get_all() -> dict:
    """Return all config with defaults filled in."""
    result = dict(DEFAULTS)
    result.update(_load())
    return result


def get_backups_dir() -> Path | None:
    """Return custom backup dir or None for default."""
    val = get("backups_dir")
    if val:
        return Path(val).expanduser()
    return None
