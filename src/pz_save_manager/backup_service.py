"""Service-layer orchestration for backup restore and save rename workflows."""

from __future__ import annotations

import logging
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from . import backup as backup_ops
from . import saves as save_ops
from .watcher import WatcherManager

logger = logging.getLogger(__name__)


def restore_save(
    manager: WatcherManager,
    game_mode: str,
    save_name: str,
    backup_ts: str,
    *,
    saves_root: Path | str | None = None,
    backups_root: Path | str | None = None,
) -> dict[str, Any]:
    """Restore a backup while suppressing watcher events for the live save.

    Assumption: if the live save does not currently exist, there is no watcher
    to pause and the restore should still be attempted so the lower domain
    layer can return the precise backup error.
    """
    try:
        live_save = save_ops.get_save(game_mode, save_name, saves_root=saves_root)
        pause_ctx = manager.pause_for(live_save)
    except save_ops.SaveNotFound:
        pause_ctx = nullcontext()
    with pause_ctx:
        backup_ops.restore_backup(
            game_mode,
            save_name,
            backup_ts,
            saves_root=saves_root,
            backups_root=backups_root,
        )
    return {"ok": True}


def rename_save(
    manager: WatcherManager,
    game_mode: str,
    old_name: str,
    new_name: str,
    *,
    saves_root: Path | str | None = None,
    backups_root: Path | str | None = None,
) -> dict[str, Any]:
    """Rename a live save and its backup history as one best-effort operation."""
    backup_ops.preflight_rename(game_mode, old_name, new_name, backups_root=backups_root)
    live_save = save_ops.get_save(game_mode, old_name, saves_root=saves_root)
    normalized_new_name = new_name.strip()
    moved_count = 0

    with manager.pause_for(live_save):
        new_save = save_ops.rename_save(game_mode, old_name, normalized_new_name, saves_root=saves_root)
        try:
            moved_count = backup_ops.rename_backups_for_save(
                game_mode,
                old_name,
                normalized_new_name,
                backups_root=backups_root,
            )
        except backup_ops.BackupError:
            try:
                if new_save.path.exists() and not live_save.path.exists():
                    new_save.path.rename(live_save.path)
            except Exception:
                logger.warning(
                    "could not roll back save rename %s -> %s",
                    new_save.path,
                    live_save.path,
                    exc_info=True,
                )
            raise

        watcher_settings = manager.watcher_settings(live_save)
        if watcher_settings is not None:
            debounce_seconds, backup_cooldown_seconds, watched_saves_root, watched_backups_root = watcher_settings
            manager.unwatch(live_save)
            manager.watch(
                new_save,
                debounce_seconds=debounce_seconds,
                backup_cooldown_seconds=backup_cooldown_seconds,
                saves_root=watched_saves_root,
                backups_root=watched_backups_root,
            )

    return {
        "ok": True,
        "message": f"Save renamed to {new_name}",
        "backups_moved": moved_count,
    }
