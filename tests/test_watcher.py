"""Tests for the save file watcher."""

from __future__ import annotations

import time
from pathlib import Path

from pz_save_manager.backup import BackupRecord
from pz_save_manager.saves import SaveGame
from pz_save_manager.watcher import SaveWatcher, WatcherManager


class FakeEvent:
    is_directory = False


def test_save_watcher_debounce(tmp_path: Path):
    save_dir = tmp_path / "Sandbox" / "test-save"
    save_dir.mkdir(parents=True)
    save = SaveGame("Sandbox", "test-save", save_dir)

    backups = []
    watcher = SaveWatcher(save, debounce_seconds=0.05, on_backup=lambda b: backups.append(b))
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


def test_stop_annule_le_timer_en_attente(tmp_path: Path, monkeypatch):
    """stop() doit empêcher un backup débouncé de partir après l'arrêt."""
    save_dir = tmp_path / "Sandbox" / "stop-save"
    save_dir.mkdir(parents=True)
    save = SaveGame("Sandbox", "stop-save", save_dir)
    created = []

    def fake_create_backup(game_mode: str, save_name: str, *, auto: bool = False) -> BackupRecord:
        created.append((game_mode, save_name, auto))
        return BackupRecord(game_mode, save_name, "20260526-120000", tmp_path / "backup", auto=auto)

    monkeypatch.setattr("pz_save_manager.watcher.create_backup", fake_create_backup)
    manager = WatcherManager()
    watcher = manager.watch(save, debounce_seconds=0.05, backup_cooldown_seconds=0.0)

    watcher.on_modified(FakeEvent())  # type: ignore
    manager.stop()
    time.sleep(0.1)

    assert created == []
    assert manager.get_backups(save) == []


def test_unwatch_annule_le_timer_en_attente(tmp_path: Path, monkeypatch):
    """unwatch() doit annuler le timer existant avant d'oublier le watcher."""
    save_dir = tmp_path / "Sandbox" / "unwatch-save"
    save_dir.mkdir(parents=True)
    save = SaveGame("Sandbox", "unwatch-save", save_dir)
    created = []

    def fake_create_backup(game_mode: str, save_name: str, *, auto: bool = False) -> BackupRecord:
        created.append((game_mode, save_name, auto))
        return BackupRecord(game_mode, save_name, "20260526-120000", tmp_path / "backup", auto=auto)

    monkeypatch.setattr("pz_save_manager.watcher.create_backup", fake_create_backup)
    manager = WatcherManager()
    watcher = manager.watch(save, debounce_seconds=0.05, backup_cooldown_seconds=0.0)

    watcher.on_modified(FakeEvent())  # type: ignore
    manager.unwatch(save)
    time.sleep(0.1)

    assert created == []
    assert save.display_name not in manager.watched_saves()


def test_pause_for_suppresses_backup_during_block(tmp_path: Path):
    """Restoring a watched save must not trigger an immediate auto-backup
    of the just-restored content."""
    save_dir = tmp_path / "Sandbox" / "world"
    save_dir.mkdir(parents=True)
    save = SaveGame("Sandbox", "world", save_dir)

    backups = []
    watcher = SaveWatcher(save, debounce_seconds=0.05, on_backup=lambda b: backups.append(b))

    manager = WatcherManager()
    manager._watchers[save.display_name] = watcher

    class FakeEvent:
        is_directory = False
        src_path = str(save_dir / "sandbox.lua")

    # Sanity: an event while NOT paused arms the debounce timer.
    watcher.on_modified(FakeEvent())
    assert watcher._timer is not None, "timer should be armed by a normal event"

    # Now pause and replay events — they must be dropped, timer cleared.
    with manager.pause_for(save):
        watcher.on_modified(FakeEvent())
        watcher.on_modified(FakeEvent())
        assert watcher._timer is None, "paused watcher should not arm a timer"

    # Immediately after resume(), there's a 1s grace window where lingering
    # in-flight events are still ignored. An event in that window stays
    # dropped — this is what prevents the post-restore auto-backup.
    watcher.on_modified(FakeEvent())
    assert watcher._timer is None, "events during grace window must be dropped"

    # After the grace window expires, normal events arm the timer again.
    time.sleep(1.1)
    watcher.on_modified(FakeEvent())
    assert watcher._timer is not None, "events after grace window must re-arm timer"
    watcher._timer.cancel()


def test_pause_for_is_noop_on_unwatched_save(tmp_path: Path):
    save_dir = tmp_path / "Sandbox" / "unwatched"
    save_dir.mkdir(parents=True)
    save = SaveGame("Sandbox", "unwatched", save_dir)
    manager = WatcherManager()
    # Save isn't in manager._watchers — pause_for must be a no-op, not raise.
    with manager.pause_for(save):
        pass
