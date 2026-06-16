"""Service-layer orchestration for live save workflows."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from .backup import create_backup

if TYPE_CHECKING:
    from .config import ConfigStore


def backup_save(
    game_mode: str,
    save_name: str,
    *,
    saves_root: Path | str | None = None,
    backups_root: Path | str | None = None,
    config: "ConfigStore | None" = None,
) -> dict[str, Any]:
    """Create a manual backup for a live save."""
    backup = create_backup(
        game_mode,
        save_name,
        saves_root=saves_root,
        backups_root=backups_root,
        config=config,
    )
    return {"ok": True, "timestamp": backup.timestamp}
