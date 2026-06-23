"""Service-layer orchestration for live save workflows."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

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
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    """Create a manual backup for a live save.

    ``progress_callback`` is forwarded to :func:`create_backup` for per-file
    progress reporting (the CLI uses this; the GUI passes ``None``).
    """
    backup = create_backup(
        game_mode,
        save_name,
        saves_root=saves_root,
        backups_root=backups_root,
        config=config,
        progress_callback=progress_callback,
    )
    return {"ok": True, "timestamp": backup.timestamp}
