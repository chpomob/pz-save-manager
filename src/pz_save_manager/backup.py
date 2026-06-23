"""Backup and restore operations for full Project Zomboid save directories."""

from __future__ import annotations

import errno
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable
from uuid import uuid4

from .platforms import get_backups_root, get_saves_root, resolve_path
from .saves import SaveGame, SaveManagerError, _validate_name, get_save

if TYPE_CHECKING:
    from .config import ConfigStore

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


def _validate_component(value: str, label: str) -> None:
    try:
        _validate_name(value, label)
    except SaveManagerError as exc:
        raise BackupError(str(exc)) from exc


def _backup_path(game_mode: str, save_name: str, timestamp: str, backups_root: Path | str | None) -> Path:
    _validate_component(game_mode, "game mode")
    _validate_component(save_name, "save name")
    _validate_component(timestamp, "timestamp")
    return (resolve_path(backups_root) or get_backups_root()) / game_mode / save_name / timestamp


def _timestamp(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y%m%d-%H%M%S")


def _skip_symlinks_and_internal(d: str, names: list[str]) -> list[str]:
    return [
        name
        for name in names
        if (Path(d) / name).is_symlink()
        or name.startswith(_INTERNAL_PREFIX)
    ]


def _count_files(path: Path) -> int:
    """Count regular files under ``path`` (excludes symlinks and directories).

    Drives the "total" denominator of progress reporting.  This MUST mirror the
    filtering applied by :func:`_copy_with_progress` (which uses
    :func:`_skip_symlinks_and_internal`); otherwise the denominator includes
    files that are never copied and progress can never reach ``total``.  In
    particular ``.pz-*`` internal files/dirs (e.g. ``.pz-complete`` present in
    every backup) and symlinks are excluded here, exactly as during copy.

    os.walk does not follow symlinked directories by default, so symlinked dirs
    are never descended into; symlinked files and internal entries are filtered
    explicitly.
    """
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        base = Path(dirpath)
        # Prune internal/symlinked dirs in place so os.walk does not descend
        # into them, matching _copy_with_progress's ignore callback.
        dirnames[:] = [
            d
            for d in dirnames
            if not d.startswith(_INTERNAL_PREFIX) and not (base / d).is_symlink()
        ]
        for name in filenames:
            if name.startswith(_INTERNAL_PREFIX):
                continue
            if (base / name).is_symlink():
                continue
            total += 1
    return total


def _count_symlinks(path: Path) -> int:
    """Count symlinks (files or directories) under ``path``.

    Mirrors what :func:`_skip_symlinks_and_internal` skips so callers can
    report what is being excluded vs. processed.
    """
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        base = Path(dirpath)
        for name in (*dirnames, *filenames):
            if (base / name).is_symlink():
                total += 1
    return total


def _copy_with_progress(
    src: Path,
    dst: Path,
    ignore: Callable[[str, list[str]], list[str]] | None = None,
    progress_callback: Callable[[int, int, Path], None] | None = None,
) -> Path:
    """Recursively copy ``src`` into ``dst`` reporting per-file progress.

    Drop-in replacement for ``shutil.copytree(..., copy_function=shutil.copy2)``
    that additionally:

    * counts the regular files upfront (via :func:`_count_files`) for a total,
    * honours the ``ignore`` callback using ``shutil.copytree``'s signature
      (``ignore(dir, names) -> names_to_skip``),
    * preserves the symlink-skipping and ``.pz-`` internal-prefix filtering of
      :func:`_skip_symlinks_and_internal`,
    * invokes ``progress_callback(copied_count, total_count, relative_path)``
      after each file is copied (``relative_path`` is a :class:`Path` relative
      to ``src``).

    Returns the destination path, matching ``shutil.copytree``.
    """
    src = Path(src)
    dst = Path(dst)
    total = _count_files(src)
    copied = 0
    # exist_ok=False mirrors shutil.copytree's default (dst must not exist).
    dst.mkdir(parents=True, exist_ok=False)
    for dirpath, dirnames, filenames in os.walk(src):
        current = Path(dirpath)
        rel_dir = current.relative_to(src)
        ignored = set(ignore(dirpath, [*dirnames, *filenames])) if callable(ignore) else set()
        # Prune ignored dirs in place so os.walk does not descend into them.
        dirnames[:] = [d for d in dirnames if d not in ignored]
        # Recreate (possibly empty) subdirectories so the tree mirrors source.
        for name in dirnames:
            (dst / rel_dir / name).mkdir(parents=True, exist_ok=True)
        for name in filenames:
            if name in ignored:
                continue
            source_file = current / name
            # Defensive: skip symlinks even if the ignore callback missed them.
            if source_file.is_symlink():
                continue
            rel_path = rel_dir / name
            dest_file = dst / rel_path
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, dest_file)
            copied += 1
            if progress_callback is not None:
                progress_callback(copied, total, Path(rel_path))
    return dst


def _publish_temp_backup(tmp_path: Path, base_dir: Path, timestamp: str) -> tuple[str, Path]:
    """Atomically publish a copied temp backup to the first free timestamp path."""
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
            # exists() check is TOCTOU-unsafe — concurrent os.replace may
            # race past it and raise ENOTEMPTY/EEXIST on the destination.
            if exc.errno in (errno.ENOTEMPTY, errno.EEXIST):
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
    config: "ConfigStore | None" = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> BackupRecord:
    """Create a timestamped full backup for a save directory.

    ``progress_callback`` (optional) is invoked as ``(copied, total, path)``
    after each file is copied, where ``path`` is relative to the save root.
    """
    _validate_component(game_mode, "game mode")
    _validate_component(save_name, "save name")
    if now is None:
        now = datetime.now()
    save = get_save(game_mode, save_name, saves_root=saves_root)
    backup_base = (resolve_path(backups_root) or get_backups_root()) / game_mode / save_name
    backup_base.mkdir(parents=True, exist_ok=True)
    timestamp = _timestamp(now)
    tmp_path = backup_base / f".tmp-{timestamp}-{uuid4().hex[:8]}"
    try:
        _copy_with_progress(save.path, tmp_path,
                            ignore=_skip_symlinks_and_internal,
                            progress_callback=progress_callback)
        # Write metadata markers inside the temp dir BEFORE the atomic rename so
        # they are published together with the backup.  Writing .pz-auto after
        # publish (the old behaviour) and swallowing OSError could leave an
        # auto-backup with no .pz-auto marker — indistinguishable from a manual
        # backup, so prune_auto_backups would never reclaim it and disk usage
        # could grow past max_auto_backups.  Any failure here now propagates and
        # the temp dir is cleaned up in the except clause below.
        (tmp_path / _COMPLETE_FILE).touch()
        if auto:
            (tmp_path / _AUTO_FILE).touch()
        timestamp, destination = _publish_temp_backup(tmp_path, backup_base, timestamp)
    except Exception:
        shutil.rmtree(tmp_path, ignore_errors=True)
        raise
    result = BackupRecord(game_mode, save_name, timestamp, destination, auto=auto)
    # Prune excess auto-backups (manual backups are never pruned)
    if auto:
        from .config import get as config_get

        max_auto = config.get("max_auto_backups") if config is not None else config_get("max_auto_backups")
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
    # Validate caller-supplied filters before they are joined into paths.
    # Without this, a filter like ".." escapes backups_root and could
    # enumerate sibling directories (parity with get/create/delete).
    if game_mode is not None:
        _validate_component(game_mode, "game mode")
    if save_name is not None:
        _validate_component(save_name, "save name")
    root = resolve_path(backups_root) or get_backups_root()
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
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> SaveGame:
    """Restore a backup over the live save directory.

    ``progress_callback`` (optional) is invoked as ``(copied, total, path)``
    after each file is copied, where ``path`` is relative to the backup root.
    """
    backup = get_backup(game_mode, save_name, timestamp, backups_root=backups_root)
    target = (resolve_path(saves_root) or get_saves_root()) / game_mode / save_name
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_target = target.with_name(f".{target.name}.restore-{uuid4().hex}.tmp")
    previous_target = target.with_name(f".{target.name}.restore-old-{uuid4().hex}")
    try:
        _copy_with_progress(backup.path, temp_target,
                            ignore=_skip_symlinks_and_internal,
                            progress_callback=progress_callback)
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

    root = resolve_path(backups_root) or get_backups_root()
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

    root = resolve_path(backups_root) or get_backups_root()
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
    _validate_component(game_mode, "game mode")
    _validate_component(save_name, "save name")
    if max_count <= 0:
        return 0
    root = resolve_path(backups_root) or get_backups_root()
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
