"""Backup and restore operations for full Project Zomboid save directories."""

from __future__ import annotations

import errno
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .platforms import get_backups_root, get_saves_root
from .saves import SaveGame, SaveManagerError, _validate_name, get_save

INTERNAL_FILES = {".pz-note", ".pz-auto", ".pz-complete"}
_INTERNAL_PREFIX = ".pz-"


class BackupError(SaveManagerError):
    """Base error for backup operations."""


class BackupNotFound(BackupError):
    """Raised when a backup directory cannot be found."""


@dataclass(frozen=True)
class BackupRecord:
    """A full-directory save backup."""

    game_mode: str
    save_name: str
    timestamp: str
    path: Path
    auto: bool = False

    @property
    def display_name(self) -> str:
        return f"{self.game_mode}/{self.save_name}/{self.timestamp}"

    @property
    def file_count(self) -> int:
        try:
            return sum(1 for _ in self.path.rglob("*") if _.is_file())
        except OSError:
            return 0

    @property
    def size_mb(self) -> float:
        try:
            total = sum(_.stat().st_size for _ in self.path.rglob("*") if _.is_file())
            return round(total / (1024 * 1024), 1)
        except OSError:
            return 0.0

    @property
    def age(self) -> str:
        """Human-readable relative time (e.g. '3 hours ago')."""
        try:
            dt = datetime.strptime(self.timestamp, "%Y%m%d-%H%M%S")
        except ValueError:
            return self.timestamp
        delta = datetime.now() - dt
        seconds = delta.total_seconds()
        if seconds < 60:
            return "just now"
        mins = int(seconds / 60)
        if mins < 60:
            return f"{mins} min ago"
        hours = int(mins / 60)
        if hours < 24:
            return f"{hours}h ago"
        days = int(hours / 24)
        if days < 7:
            return f"{days}d ago"
        weeks = int(days / 7)
        if weeks < 5:
            return f"{weeks}w ago"
        return dt.strftime("%d/%m/%Y")

    @property
    def formatted(self) -> str:
        """Human-readable date/time (e.g. '2026-05-18 12:11:48')."""
        try:
            dt = datetime.strptime(self.timestamp, "%Y%m%d-%H%M%S")
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return self.timestamp

    @property
    def note(self) -> str | None:
        """User annotation stored alongside the backup (read lazily)."""
        return get_backup_note(self.path)

    def set_note(self, text: str) -> None:
        """Annotate this backup. Pass empty string to remove the note."""
        set_backup_note(self.path, text)


_NOTE_FILE = ".pz-note"
_AUTO_FILE = ".pz-auto"
_COMPLETE_FILE = ".pz-complete"


def get_backup_note(backup_path: Path) -> str | None:
    """Read the annotation for a backup, or None."""
    note_file = backup_path / _NOTE_FILE
    if not note_file.is_file():
        return None
    try:
        return note_file.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def set_backup_note(backup_path: Path, text: str) -> None:
    """Write or remove an annotation for a backup."""
    note_file = backup_path / _NOTE_FILE
    text = text.strip()
    if not text:
        try:
            note_file.unlink(missing_ok=True)
        except OSError:
            pass
        return
    note_file.write_text(text, encoding="utf-8")


def _root(path: Path | str | None, default: Path) -> Path:
    return Path(path).expanduser() if path is not None else default


def _validate_component(value: str, label: str) -> None:
    try:
        _validate_name(value, label)
    except SaveManagerError as exc:
        raise BackupError(str(exc)) from exc


def _backup_path(game_mode: str, save_name: str, timestamp: str, backups_root: Path | str | None) -> Path:
    _validate_component(game_mode, "game mode")
    _validate_component(save_name, "save name")
    _validate_component(timestamp, "timestamp")
    return _root(backups_root, get_backups_root()) / game_mode / save_name / timestamp


def _timestamp(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y%m%d-%H%M%S")


def _skip_symlinks_and_internal(d: str, names: list[str]) -> list[str]:
    return [
        name
        for name in names
        if (Path(d) / name).is_symlink()
        or name in INTERNAL_FILES
        or name.startswith(_INTERNAL_PREFIX)
    ]


def _publish_temp_backup(tmp_path: Path, base_dir: Path, timestamp: str) -> tuple[str, Path]:
    """Atomically publish a copied temp backup to the first free timestamp path."""
    unavailable_errnos = {errno.EEXIST, errno.ENOTEMPTY, errno.ENOTDIR, errno.EISDIR}
    candidate_timestamps = [timestamp, *(f"{timestamp}-{index:02d}" for index in range(1, 100))]
    for candidate_timestamp in candidate_timestamps:
        destination = base_dir / candidate_timestamp
        if destination.exists() or destination.is_symlink():
            continue
        try:
            os.replace(tmp_path, destination)
            return candidate_timestamp, destination
        except FileExistsError:
            continue
        except OSError as exc:
            if exc.errno in unavailable_errnos:
                continue
            raise
    raise BackupError(f"Could not allocate a unique backup under {base_dir}")


def create_backup(
    game_mode: str,
    save_name: str,
    *,
    saves_root: Path | str | None = None,
    backups_root: Path | str | None = None,
    now: datetime | None = None,
    auto: bool = False,
) -> BackupRecord:
    """Create a timestamped full backup for a save directory."""
    _validate_component(game_mode, "game mode")
    _validate_component(save_name, "save name")
    if now is None:
        now = datetime.now()
    save = get_save(game_mode, save_name, saves_root=saves_root)
    backup_base = _root(backups_root, get_backups_root()) / game_mode / save_name
    backup_base.mkdir(parents=True, exist_ok=True)
    timestamp = _timestamp(now)
    tmp_path = backup_base / f".tmp-{timestamp}-{uuid4().hex[:8]}"
    try:
        shutil.copytree(save.path, tmp_path, copy_function=shutil.copy2,
                        ignore=_skip_symlinks_and_internal)
        # Write completion marker inside temp dir BEFORE atomic rename
        # so a crash between rename and marker never leaves an orphan.
        (tmp_path / _COMPLETE_FILE).touch()
        timestamp, destination = _publish_temp_backup(tmp_path, backup_base, timestamp)
        if auto:
            try:
                (destination / _AUTO_FILE).touch()
            except OSError:
                pass
    except Exception:
        shutil.rmtree(tmp_path, ignore_errors=True)
        raise
    result = BackupRecord(game_mode, save_name, timestamp, destination, auto=auto)
    # Prune excess auto-backups (manual backups are never pruned)
    if auto:
        from .config import get as config_get
        max_auto = config_get("max_auto_backups")
        if isinstance(max_auto, (int, float)) and max_auto >= 0:
            prune_auto_backups(game_mode, save_name, int(max_auto), backups_root=backups_root)
    return result


def list_backups(
    game_mode: str | None = None,
    save_name: str | None = None,
    *,
    backups_root: Path | str | None = None,
) -> list[BackupRecord]:
    """List backups, optionally filtered by game mode and save name."""
    if save_name is not None and game_mode is None:
        raise BackupError("A game mode is required when filtering by save name")
    root = _root(backups_root, get_backups_root())
    if not root.is_dir():
        return []
    records: list[BackupRecord] = []
    mode_dirs = [root / game_mode] if game_mode else [path for path in root.iterdir() if path.is_dir()]
    for mode_dir in mode_dirs:
        if not mode_dir.is_dir():
            continue
        save_dirs = [mode_dir / save_name] if save_name else [path for path in mode_dir.iterdir() if path.is_dir()]
        for save_dir in save_dirs:
            if not save_dir.is_dir():
                continue
            for backup_dir in save_dir.iterdir():
                if not backup_dir.is_dir() or backup_dir.name.startswith("."):
                    continue
                if not (backup_dir / _COMPLETE_FILE).is_file():
                    continue
                auto = (backup_dir / _AUTO_FILE).is_file()
                records.append(BackupRecord(mode_dir.name, save_dir.name, backup_dir.name, backup_dir, auto=auto))
    return sorted(
        records,
        key=lambda backup: (backup.game_mode.casefold(), backup.save_name.casefold(), backup.timestamp),
        reverse=True,
    )


def get_backup(
    game_mode: str,
    save_name: str,
    timestamp: str,
    *,
    backups_root: Path | str | None = None,
) -> BackupRecord:
    """Return a specific backup or raise BackupNotFound."""
    path = _backup_path(game_mode, save_name, timestamp, backups_root)
    if not path.is_dir():
        raise BackupNotFound(f"Backup not found: {game_mode}/{save_name}/{timestamp}")
    if not (path / _COMPLETE_FILE).is_file():
        raise BackupNotFound(
            f"Backup may be incomplete (missing completion marker): {game_mode}/{save_name}/{timestamp}"
        )
    auto = (path / _AUTO_FILE).is_file()
    return BackupRecord(game_mode, save_name, timestamp, path, auto=auto)


def restore_backup(
    game_mode: str,
    save_name: str,
    timestamp: str,
    *,
    saves_root: Path | str | None = None,
    backups_root: Path | str | None = None,
) -> SaveGame:
    """Restore a backup over the live save directory."""
    backup = get_backup(game_mode, save_name, timestamp, backups_root=backups_root)
    target = _root(saves_root, get_saves_root()) / game_mode / save_name
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_target = target.with_name(f".{target.name}.restore-{uuid4().hex}.tmp")
    previous_target = target.with_name(f".{target.name}.restore-old-{uuid4().hex}")
    try:
        shutil.copytree(backup.path, temp_target, copy_function=shutil.copy2,
                        ignore=_skip_symlinks_and_internal)
        if target.exists():
            target.rename(previous_target)
        temp_target.rename(target)
    except (OSError, shutil.Error) as exc:
        if temp_target.exists():
            shutil.rmtree(temp_target, ignore_errors=True)
        if previous_target.exists() and not target.exists():
            previous_target.rename(target)
        raise BackupError(f"Could not restore backup: {exc}") from exc
    # P0: cleanup wrapped in try/except — failure here must not lose the restored save
    try:
        if previous_target.exists():
            shutil.rmtree(previous_target)
    except OSError as e:
        import logging
        logging.getLogger(__name__).warning("Could not remove previous save backup %s: %s", previous_target, e)
    return SaveGame(game_mode, save_name, target)


def delete_backup(
    game_mode: str,
    save_name: str,
    timestamp: str,
    *,
    backups_root: Path | str | None = None,
) -> BackupRecord:
    """Delete a backup directory."""
    backup = get_backup(game_mode, save_name, timestamp, backups_root=backups_root)
    try:
        shutil.rmtree(backup.path)
    except OSError as exc:
        raise BackupError(f"Could not delete backup: {exc}") from exc
    return backup


def preflight_rename(
    game_mode: str,
    old_save_name: str,
    new_save_name: str,
    *,
    backups_root: Path | str | None = None,
) -> None:
    """Validate backup-side rename constraints before renaming the live save."""
    _validate_component(game_mode, "game mode")
    _validate_component(old_save_name, "old save name")
    normalized_new_name = new_save_name.strip()
    _validate_component(normalized_new_name, "new save name")

    root = _root(backups_root, get_backups_root())
    old_dir = root / game_mode / old_save_name
    new_dir = root / game_mode / normalized_new_name
    if new_dir != old_dir and (new_dir.exists() or new_dir.is_symlink()):
        raise BackupError(f"Cannot rename backups: {normalized_new_name!r} already exists in backup location")


def rename_backups_for_save(
    game_mode: str,
    old_save_name: str,
    new_save_name: str,
    *,
    backups_root: Path | str | None = None,
) -> int:
    """Move all backups from old_save_name to new_save_name under game_mode.

    Returns the number of backups moved.  If no backups exist for the old
    name this is a no-op (returns 0).  Raises BackupError if the new name
    already has backups (to avoid silently merging two histories).
    """
    _validate_component(game_mode, "game mode")
    _validate_component(old_save_name, "old save name")
    normalized_new_name = new_save_name.strip()
    _validate_component(normalized_new_name, "new save name")

    root = _root(backups_root, get_backups_root())
    old_dir = root / game_mode / old_save_name
    new_dir = root / game_mode / normalized_new_name

    if new_dir == old_dir:
        return 0

    if not old_dir.is_dir():
        return 0

    if new_dir.exists() or new_dir.is_symlink():
        raise BackupError(f"Cannot rename backups: {normalized_new_name!r} already exists in backup location")

    # Count backups before moving
    count = sum(1 for _ in old_dir.iterdir() if _.is_dir())
    try:
        old_dir.rename(new_dir)
    except OSError as e:
        raise BackupError(
            f"Cannot rename backups: {old_save_name!r} → {new_save_name!r}: {e}"
        ) from e
    return count


def prune_auto_backups(
    game_mode: str,
    save_name: str,
    max_count: int,
    *,
    backups_root: Path | str | None = None,
) -> int:
    """Delete the oldest auto-backups so at most `max_count` remain.

    Manual backups (no .pz-auto marker) are never deleted.  Returns the
    number of auto-backups removed.
    """
    if max_count <= 0:
        return 0
    root = _root(backups_root, get_backups_root())
    save_dir = root / game_mode / save_name
    if not save_dir.is_dir():
        return 0

    # Collect auto-backup directories with their timestamps
    autos: list[tuple[str, Path]] = []
    for item in save_dir.iterdir():
        if item.name.startswith("."):
            continue
        if item.is_dir() and (item / _AUTO_FILE).is_file() and (item / _COMPLETE_FILE).is_file():
            autos.append((item.name, item))

    if len(autos) <= max_count:
        return 0

    # Sort by timestamp (oldest first) so we delete the oldest
    autos.sort(key=lambda x: x[0])
    to_delete = autos[: len(autos) - max_count]

    removed = 0
    for _, path in to_delete:
        try:
            shutil.rmtree(path)
            removed += 1
        except OSError:
            pass
    return removed
