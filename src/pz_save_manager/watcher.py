"""File watcher for automatic save backups using watchdog."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .backup import BackupRecord, create_backup
from .saves import SaveGame

if TYPE_CHECKING:
    from .config import ConfigStore


class SaveWatcher(FileSystemEventHandler):
    """Watches a save directory and creates backups after changes settle."""

    def __init__(
        self,
        save: SaveGame,
        debounce_seconds: float = 5.0,
        backup_cooldown_seconds: float = 300.0,
        on_backup: callable | None = None,
        saves_root: Path | str | None = None,
        backups_root: Path | str | None = None,
        config: "ConfigStore | None" = None,
    ) -> None:
        self.save = save
        self.debounce_seconds = debounce_seconds
        self.backup_cooldown_seconds = backup_cooldown_seconds
        self.on_backup = on_backup
        self.saves_root = saves_root
        self.backups_root = backups_root
        self.config = config
        self._last_event = 0.0
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._backups: list[BackupRecord] = []
        self._ignore_until = 0.0  # epoch seconds; events before this are dropped
        self._last_backup_time = 0.0  # epoch seconds of last auto-backup
        self._last_backup_mtime = 0.0  # save mtime at time of last backup
        self._in_progress: bool = False
        self._pending_backup: bool = False

    def pause(self) -> None:
        """Suppress all events until resume() is called.

        Used during operations that legitimately rewrite the save dir
        (e.g. restore_backup), so the watcher doesn't immediately back
        up the just-restored content. Any pending debounce timer is
        cancelled.
        """
        with self._lock:
            self._ignore_until = float("inf")
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

    def cancel_pending(self) -> None:
        """Cancel any pending debounce backup."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """Wait until no backup is running or queued for this watcher."""
        deadline = time.time() + timeout
        while True:
            with self._lock:
                if not self._in_progress and self._timer is None:
                    return True
            if time.time() >= deadline:
                return False
            time.sleep(0.05)

    def resume(self, grace_seconds: float = 1.0) -> None:
        """Re-enable events, with a short grace window for in-flight
        watchdog events from the paused operation to drain."""
        with self._lock:
            self._ignore_until = time.time() + grace_seconds

    def on_modified(self, event) -> None:
        if event.is_directory:
            return
        now = time.time()
        with self._lock:
            if now < self._ignore_until:
                return
            self._last_event = now
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce_seconds, self._do_backup)
            self._timer.daemon = True
            self._timer.start()

    def _do_backup(self) -> None:
        now = time.time()
        from .saves import get_save_modified_time
        backup: BackupRecord | None = None
        callback = None
        started_backup = False
        try:
            with self._lock:
                self._timer = None
                if self._in_progress:
                    self._pending_backup = True
                    return
                # Enforce cooldown: skip if the last auto-backup was too recent.
                if now - self._last_backup_time < self.backup_cooldown_seconds:
                    return
                # Skip if the save hasn't actually changed since the last backup.
                # On Windows, watchdog can fire on spurious events (AV, indexing,
                # attribute changes). We guard against this by comparing mtims.
                try:
                    current_mtime = get_save_modified_time(self.save)
                except OSError:
                    return
                if current_mtime <= self._last_backup_mtime:
                    return
                self._in_progress = True
                started_backup = True
                callback = self.on_backup

            backup = create_backup(
                self.save.game_mode,
                self.save.name,
                auto=True,
                saves_root=self.saves_root,
                backups_root=self.backups_root,
                config=self.config,
            )

            with self._lock:
                self._backups.append(backup)
                self._last_backup_time = now
                self._last_backup_mtime = current_mtime
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error("Auto-backup failed for %s/%s: %s", self.save.game_mode, self.save.name, e, exc_info=True)
            return
        finally:
            if started_backup:
                with self._lock:
                    self._in_progress = False
                    if self._pending_backup:
                        self._pending_backup = False
                        self._timer = threading.Timer(self.debounce_seconds, self._do_backup)
                        self._timer.daemon = True
                        self._timer.start()
        if backup is not None and callback:
            callback(backup)


class WatcherManager:
    """Manages multiple SaveWatcher instances."""

    def __init__(
        self,
        config: "ConfigStore | None" = None,
        saves_root: Path | str | None = None,
        backups_root: Path | str | None = None,
    ) -> None:
        self.config = config
        self.saves_root = saves_root
        self.backups_root = backups_root
        self._lock = threading.Lock()
        self._observer = Observer()
        self._watchers: dict[str, SaveWatcher] = {}
        self._watches: dict[str, object] = {}  # Observer watches, used with unschedule
        self._running = False

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            if not self._observer.is_alive():
                self._observer = Observer()
                # Re-schedule all watched saves
                watcher_items = list(self._watchers.items())
                for key, watcher in watcher_items:
                    save = watcher.save
                    handle = self._observer.schedule(watcher, str(save.path), recursive=True)
                    self._watches[key] = handle
            self._observer.start()
            self._running = True

    def stop(self, timeout: float = 30.0) -> None:
        with self._lock:
            watchers = list(self._watchers.values())
            for watcher in watchers:
                watcher.cancel_pending()
            if self._running:
                self._observer.stop()
                self._observer.join(timeout=5)
                self._running = False
        deadline = time.time() + timeout
        for watcher in watchers:
            watcher.wait_idle(max(0.0, deadline - time.time()))

    def watch(
        self,
        save: SaveGame,
        debounce_seconds: float = 5.0,
        backup_cooldown_seconds: float = 300.0,
        saves_root: Path | str | None = None,
        backups_root: Path | str | None = None,
    ) -> SaveWatcher:
        key = save.display_name
        resolved_saves_root = saves_root if saves_root is not None else self.saves_root
        resolved_backups_root = backups_root if backups_root is not None else self.backups_root
        with self._lock:
            if key in self._watchers:
                old_watcher = self._watchers[key]
                old_watcher.cancel_pending()
                # Create new watcher with updated settings and re-schedule
                watcher = SaveWatcher(
                    save,
                    debounce_seconds,
                    backup_cooldown_seconds,
                    saves_root=resolved_saves_root,
                    backups_root=resolved_backups_root,
                    config=self.config,
                )
                self._watchers[key] = watcher
                if key in self._watches:
                    self._observer.unschedule(self._watches[key])
                handle = self._observer.schedule(watcher, str(save.path), recursive=True)
                self._watches[key] = handle
                return watcher
            watcher = SaveWatcher(
                save,
                debounce_seconds,
                backup_cooldown_seconds,
                saves_root=resolved_saves_root,
                backups_root=resolved_backups_root,
                config=self.config,
            )
            self._watchers[key] = watcher
            handle = self._observer.schedule(watcher, str(save.path), recursive=True)
            self._watches[key] = handle
            return watcher

    def unwatch(self, save: SaveGame) -> None:
        key = save.display_name
        with self._lock:
            if key in self._watches:
                self._observer.unschedule(self._watches[key])
                del self._watches[key]
            if key in self._watchers:
                watcher = self._watchers.pop(key)
                watcher.cancel_pending()

    def watched_saves(self) -> list[str]:
        with self._lock:
            return sorted(self._watchers.keys())

    def watcher_settings(self, save: SaveGame) -> tuple[float, float, Path | str | None, Path | str | None] | None:
        """Return the active watcher settings for a save, if it is watched."""
        with self._lock:
            watcher = self._watchers.get(save.display_name)
            if watcher is None:
                return None
            return (
                watcher.debounce_seconds,
                watcher.backup_cooldown_seconds,
                watcher.saves_root,
                watcher.backups_root,
            )

    def get_backups(self, save: SaveGame) -> list[BackupRecord]:
        key = save.display_name
        with self._lock:
            if key in self._watchers:
                return list(self._watchers[key]._backups)
            return []

    @contextmanager
    def pause_for(self, save: SaveGame):
        """Context manager: temporarily silence the watcher for `save`.

        No-op if the save isn't being watched. After the block exits,
        the watcher resumes with a short grace window so any file
        events still in watchdog's queue from the operation get dropped
        instead of triggering an immediate auto-backup.
        """
        with self._lock:
            watcher = self._watchers.get(save.display_name)
        if watcher is not None:
            watcher.pause()
        try:
            yield
        finally:
            if watcher is not None:
                watcher.resume()


# Global instance
_manager: WatcherManager | None = None
_manager_lock = threading.Lock()


def get_manager(
    config: "ConfigStore | None" = None,
    saves_root: Path | str | None = None,
    backups_root: Path | str | None = None,
) -> WatcherManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = WatcherManager(config=config, saves_root=saves_root, backups_root=backups_root)
    return _manager
