"""Service helpers for configuring save watchers from runtime config."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .saves import list_saves
from .watcher import WatcherManager

if TYPE_CHECKING:
    from .config import ConfigStore


def start_watching_saves(
    manager: WatcherManager,
    config: "ConfigStore",
    *,
    saves_root: Path | str | None = None,
    backups_root: Path | str | None = None,
) -> int:
    """Watch all discovered saves using the current debounce/cooldown settings."""
    saves = list_saves(saves_root=saves_root)
    cfg = config.get_all()
    cooldown = cfg.get("backup_cooldown_minutes", 1) * 60
    debounce = cfg.get("debounce_seconds", 5.0)
    for save in saves:
        manager.watch(
            save,
            debounce_seconds=debounce,
            backup_cooldown_seconds=cooldown,
            saves_root=saves_root,
            backups_root=backups_root,
        )
    if not manager.running:
        manager.start()
    return len(saves)
