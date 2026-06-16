"""Configuration management for PZ Save Manager.

Config stored in ~/.pz-save-manager/config.json by default.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from .platforms import get_app_dir

CONFIG_PATH = get_app_dir() / "config.json"
CONFIG_FILE = CONFIG_PATH

DEFAULTS: dict[str, Any] = {
    "backups_dir": None,
    "debounce_seconds": 5.0,
    "backup_cooldown_minutes": 1,
    "max_auto_backups": 30,
    "auto_start_watcher": False,
    "port": 8080,
}


def _coerce(key: str, value: Any) -> Any:
    """Coerce a config value to its proper type. Returns None to signal clearing."""
    if key == "backups_dir" and (not value or str(value).lower() in ("none", "null")):
        return None
    if key == "debounce_seconds":
        coerced = float(value)
        if coerced < 0 or coerced > 3600:
            raise ValueError("debounce_seconds must be between 0 and 3600")
        return coerced
    if key == "backup_cooldown_minutes":
        coerced = int(value)
        if coerced < 0 or coerced > 1440:
            raise ValueError("backup_cooldown_minutes must be between 0 and 1440")
        return coerced
    if key == "max_auto_backups":
        coerced = int(value)
        if coerced < 0 or coerced > 999:
            raise ValueError("max_auto_backups must be between 0 and 999")
        return coerced
    if key == "port":
        coerced = int(value)
        if coerced < 1 or coerced > 65535:
            raise ValueError("port must be between 1 and 65535")
        return coerced
    if key == "auto_start_watcher":
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("true", "1", "yes")
    return value


class ConfigStore:
    """File-backed configuration store with an instance-owned cache."""

    def __init__(self, path: Path = CONFIG_PATH) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._cache: dict[str, Any] | None = None
        self._cache_signature: tuple[int, int] | None = None

    def _signature(self) -> tuple[int, int] | None:
        try:
            stat = self.path.stat()
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    def _load(self) -> dict[str, Any]:
        with self._lock:
            signature = self._signature()
            if self._cache is not None and signature == self._cache_signature:
                return self._cache
            if self.path.is_file():
                try:
                    loaded = json.loads(self.path.read_text(encoding="utf-8"))
                    self._cache = loaded if isinstance(loaded, dict) else {}
                    self._cache_signature = signature
                    return self._cache
                except (json.JSONDecodeError, OSError):
                    pass
            self._cache = {}
            self._cache_signature = signature
            return self._cache

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
        self._cache = data
        self._cache_signature = self._signature()

    def get(self, key: str) -> Any:
        """Get a config value, falling back to defaults."""
        data = self._load()
        if key in data:
            return data[key]
        return DEFAULTS.get(key)

    def set(self, key: str, value: Any) -> None:
        """Set a config value and save."""
        with self._lock:
            data = dict(self._load())
            data[key] = value
            self._save(data)

    def get_all(self) -> dict[str, Any]:
        """Return all config with defaults filled in."""
        result = dict(DEFAULTS)
        result.update(self._load())
        return result

    def get_backups_dir(self) -> Path | None:
        """Return custom backup dir or None for default."""
        value = self.get("backups_dir")
        if value:
            return Path(value).expanduser()
        return None


default_store = ConfigStore()


def get(key: str) -> Any:
    """Backward-compatible config getter using the default store."""
    return default_store.get(key)


def set_(key: str, value: Any) -> None:
    """Backward-compatible config setter using the default store."""
    default_store.set(key, value)


def get_all() -> dict[str, Any]:
    """Backward-compatible config dump using the default store."""
    return default_store.get_all()


def get_backups_dir() -> Path | None:
    """Backward-compatible backup directory getter using the default store."""
    return default_store.get_backups_dir()
