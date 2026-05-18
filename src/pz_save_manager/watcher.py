"""File watcher for automatic save backups using watchdog."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .backup import BackupRecord, create_backup
from .saves import SaveGame


class SaveWatcher(FileSystemEventHandler):
    """Watches a save directory and creates backups after changes settle."""

    def __init__(
        self,
        save: SaveGame,
        debounce_seconds: float = 5.0,
        on_backup: callable | None = None,
    ) -> None:
        self.save = save
        self.debounce_seconds = debounce_seconds
        self.on_backup = on_backup
        self._last_event = 0.0
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._backups: list[BackupRecord] = []
        self._ignore_until = 0.0  # epoch seconds; events before this are dropped

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
        try:
            backup = create_backup(self.save.game_mode, self.save.name)
            # Mark as auto-backup by creating a new record with auto=True
            from .backup import BackupRecord
            backup = BackupRecord(
                game_mode=backup.game_mode,
                save_name=backup.save_name,
                timestamp=backup.timestamp,
                path=backup.path,
                auto=True,
            )
            self._backups.append(backup)
            if self.on_backup:
                self.on_backup(backup)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error("Auto-backup failed for %s/%s: %s", self.save.game_mode, self.save.name, e, exc_info=True)


class WatcherManager:
    """Manages multiple SaveWatcher instances."""

    def __init__(self) -> None:
        self._observer = Observer()
        self._watchers: dict[str, SaveWatcher] = {}
        self._watches: dict[str, object] = {}  # watchdog handles
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        if not self._running:
            if not self._observer.is_alive():
                self._observer = Observer()
                # Re-schedule all watched saves
                for key, watcher in list(self._watchers.items()):
                    save = watcher.save
                    handle = self._observer.schedule(watcher, str(save.path), recursive=True)
                    self._watches[key] = handle
            self._observer.start()
            self._running = True

    def stop(self) -> None:
        if self._running:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._running = False

    def watch(self, save: SaveGame, debounce_seconds: float = 5.0) -> SaveWatcher:
        key = save.display_name
        if key in self._watchers:
            return self._watchers[key]
        watcher = SaveWatcher(save, debounce_seconds)
        self._watchers[key] = watcher
        handle = self._observer.schedule(watcher, str(save.path), recursive=True)
        self._watches[key] = handle
        return watcher

    def unwatch(self, save: SaveGame) -> None:
        key = save.display_name
        if key in self._watches:
            self._observer.unschedule(self._watches[key])
            del self._watches[key]
        if key in self._watchers:
            del self._watchers[key]

    def watched_saves(self) -> list[str]:
        return sorted(self._watchers.keys())

    def get_backups(self, save: SaveGame) -> list[BackupRecord]:
        key = save.display_name
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


def get_manager() -> WatcherManager:
    global _manager
    if _manager is None:
        _manager = WatcherManager()
    return _manager
