"""Configuration management for PZ Save Manager.

Config stored in ~/.pz-save-manager/config.json
"""

from __future__ import annotations

import json
from pathlib import Path

from .platforms import get_app_dir

CONFIG_FILE = get_app_dir() / "config.json"

DEFAULTS = {
    "backups_dir": None,
    "debounce_seconds": 5.0,
    "auto_start_watcher": False,
    "port": 8080,
    "streamer_mode": False,
}


def _load() -> dict:
    if CONFIG_FILE.is_file():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {}


def _save(data: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2))


def get(key: str):
    """Get a config value, falling back to defaults."""
    data = _load()
    if key in data:
        return data[key]
    return DEFAULTS.get(key)


def set_(key: str, value) -> None:
    """Set a config value and save."""
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
