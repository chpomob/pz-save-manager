"""Backup and restore operations for full Project Zomboid save directories."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .platforms import get_backups_root, get_saves_root
from .saves import SaveGame, SaveManagerError, get_save


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
    if value in {"", ".", ".."} or "/" in value or chr(92) in value or "\x00" in value:
        raise BackupError(f"Invalid {label}: {value!r}")


def _backup_path(game_mode: str, save_name: str, timestamp: str, backups_root: Path | str | None) -> Path:
    _validate_component(game_mode, "game mode")
    _validate_component(save_name, "save name")
    _validate_component(timestamp, "timestamp")
    return _root(backups_root, get_backups_root()) / game_mode / save_name / timestamp


def _timestamp(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y%m%d-%H%M%S")


def _unique_destination(base_dir: Path, timestamp: str) -> tuple[str, Path]:
    # P0: TOCTOU-safe — reserve via atomic mkdir, then caller copies into it
    destination = base_dir / timestamp
    try:
        destination.mkdir(parents=True, exist_ok=False)
        return timestamp, destination
    except FileExistsError:
        pass
    for index in range(1, 100):
        candidate_timestamp = f"{timestamp}-{index:02d}"
        candidate = base_dir / candidate_timestamp
        try:
            candidate.mkdir(parents=True, exist_ok=False)
            return candidate_timestamp, candidate
        except FileExistsError:
            continue
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
        now = datetime.now(tz=timezone.utc)
    save = get_save(game_mode, save_name, saves_root=saves_root)
    backup_base = _root(backups_root, get_backups_root()) / game_mode / save_name
    backup_base.mkdir(parents=True, exist_ok=True)
    timestamp, destination = _unique_destination(backup_base, _timestamp(now))
    # P0: copy to temp inside destination, then atomically move contents
    tmp = Path(tempfile.mkdtemp(dir=destination.parent, prefix=f".tmp-{timestamp}-"))
    try:
        # P0: skip symlinks entirely (security)
        def _skip_symlinks(d, names):
            return [n for n in names if (Path(d)/n).is_symlink()]
        shutil.copytree(save.path, tmp, copy_function=shutil.copy2,
                        ignore=_skip_symlinks, dirs_exist_ok=True)
        # Atomic: move all contents from tmp into destination
        for item in tmp.iterdir():
            shutil.move(str(item), str(destination / item.name))
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    # Persist auto/manual marker
    if auto:
        _AUTO_FILE = ".pz-auto"
        try:
            (destination / _AUTO_FILE).touch()
        except OSError:
            pass
    return BackupRecord(game_mode, save_name, timestamp, destination, auto=auto)


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
                if backup_dir.is_dir():
                    auto = (backup_dir / ".pz-auto").is_file()
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
    return BackupRecord(game_mode, save_name, timestamp, path)


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
        # P0: skip symlinks entirely (security: no following, no copying)
        def _skip_symlinks(d, names):
            return [n for n in names if (Path(d)/n).is_symlink()]
        shutil.copytree(backup.path, temp_target, copy_function=shutil.copy2,
                        ignore=_skip_symlinks)
        if target.exists():
            target.rename(previous_target)
        temp_target.rename(target)
    except OSError as exc:
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
    _validate_component(new_save_name, "new save name")

    root = _root(backups_root, get_backups_root())
    old_dir = root / game_mode / old_save_name
    new_dir = root / game_mode / new_save_name

    if not old_dir.is_dir():
        return 0

    # Count backups before moving
    count = sum(1 for _ in old_dir.iterdir() if _.is_dir())
    try:
        old_dir.rename(new_dir)
    except OSError as e:
        raise BackupError(
            f"Cannot rename backups: {old_save_name!r} → {new_save_name!r}: {e}"
        ) from e
    return count
