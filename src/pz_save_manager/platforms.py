"""Cross-platform path helpers for Project Zomboid saves and backups."""

from __future__ import annotations

import os
import platform
from pathlib import Path


def resolve_path(path: Path | str | None, default: Path | None = None) -> Path | None:
    """Expanduser and resolve to Path. Returns default when path is None."""
    return Path(path).expanduser() if path is not None else default


APP_DIR_NAME = ".pz-save-manager"
ZOMBOID_DIR_NAME = "Zomboid"
SAVES_DIR_NAME = "Saves"
BACKUPS_DIR_NAME = "backups"


def get_home_dir() -> Path:
    """Return the user home directory with a Windows-friendly fallback."""
    if platform.system() == "Windows":
        user_profile = os.environ.get("USERPROFILE")
        if user_profile:
            return Path(user_profile).expanduser()
    return Path.home()


def get_zomboid_dir(home: Path | str | None = None) -> Path:
    """Return the root Project Zomboid user data directory."""
    base_home = Path(home).expanduser() if home is not None else get_home_dir()
    return base_home / ZOMBOID_DIR_NAME


def get_saves_root(home: Path | str | None = None) -> Path:
    """Return the directory containing Project Zomboid save modes."""
    return get_zomboid_dir(home) / SAVES_DIR_NAME


def get_app_dir(home: Path | str | None = None) -> Path:
    """Return this tool per-user data directory."""
    base_home = Path(home).expanduser() if home is not None else get_home_dir()
    return base_home / APP_DIR_NAME


def get_backups_root(home: Path | str | None = None) -> Path:
    """Return the root directory containing all backups.

    Respects the configured custom backup directory if set.
    """
    from .config import get_backups_dir
    custom = get_backups_dir()
    if custom is not None:
        return custom
    return get_app_dir(home) / BACKUPS_DIR_NAME
