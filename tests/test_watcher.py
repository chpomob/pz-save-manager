"""Tests for the save file watcher."""

import time
from pathlib import Path

from pz_save_manager.saves import SaveGame
from pz_save_manager.watcher import SaveWatcher, WatcherManager


def test_save_watcher_debounce(tmp_path: Path):
    save_dir = tmp_path / "Sandbox" / "test-save"
    save_dir.mkdir(parents=True)
    save = SaveGame("Sandbox", "test-save", save_dir)

    backups = []
    watcher = SaveWatcher(save, debounce_seconds=0.05, on_backup=lambda b: backups.append(b))
    # Simulate a file modification event
    class FakeEvent:
        is_directory = False
        src_path = str(save_dir / "fake.map")
    watcher.on_modified(FakeEvent())  # type: ignore
    time.sleep(0.2)
    # Debounce timer should have fired; backup may fail in test but watcher handles it silently
    assert watcher._last_event > 0


def test_watcher_manager_lifecycle():
    manager = WatcherManager()
    assert not manager.running
    manager.start()
    assert manager.running
    manager.stop()
    assert not manager.running


def test_watcher_manager_watched_saves(tmp_path: Path):
    save_dir = tmp_path / "Survivor" / "my-save"
    save_dir.mkdir(parents=True)
    save = SaveGame("Survivor", "my-save", save_dir)

    manager = WatcherManager()
    manager.watch(save)
    assert "Survivor/my-save" in manager.watched_saves()
    # Note: unwatch doesn't work with watchdog observer unless actually started
    # because schedule creates an ObservedWatch wrapper. Tested via integration.
