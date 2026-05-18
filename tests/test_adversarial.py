"""Adversarial security and robustness tests for PZ Save Manager.

Each test is designed to FAIL against the current code, demonstrating a real risk.
Updated to reflect P0 fixes: path traversal guard, symlink skipping, atomic backup,
cleanup resilience, and logged (not silent) watcher errors.
"""

import logging
import threading
from datetime import datetime
from pathlib import Path

import pytest

import pz_save_manager.backup as backup_mod
from pz_save_manager.saves import SaveGame, SaveManagerError, get_save


# ── RISK 1: Path traversal in get_save() ──────────────────────────────
def test_get_save_rejects_path_traversal(tmp_path: Path) -> None:
    saves = tmp_path / "saves"
    (saves / "Sandbox").mkdir(parents=True)
    outside = tmp_path / "secret"
    outside.mkdir()

    with pytest.raises(SaveManagerError):
        get_save("Sandbox", "../../secret", saves_root=saves)


# ── RISK 2: Symlink materialisation during restore ────────────────────
def test_restore_does_not_follow_backup_symlinks(tmp_path: Path) -> None:
    saves = tmp_path / "saves"
    backups = tmp_path / "backups"
    backup_dir = backups / "Sandbox" / "World" / "20260518-120000"
    backup_dir.mkdir(parents=True)

    secret = tmp_path / "secret.txt"
    secret.write_text("do-not-copy", encoding="utf-8")
    (backup_dir / "leak.txt").symlink_to(secret)

    backup_mod.restore_backup(
        "Sandbox", "World", "20260518-120000",
        saves_root=saves, backups_root=backups,
    )

    # P0 fix: symlinks are now SKIPPED entirely during copytree
    assert not (saves / "Sandbox" / "World" / "leak.txt").exists(), (
        "Symlink was followed — external file materialised in live save!"
    )


# ── RISK 3: Non-atomic backup creation (TOCTOU race) ──────────────────
def test_concurrent_backups_get_distinct_destinations(
    tmp_path: Path,
) -> None:
    saves = tmp_path / "saves"
    backups = tmp_path / "backups"
    save_dir = saves / "Sandbox" / "World"
    save_dir.mkdir(parents=True)
    (save_dir / "map.bin").write_text("x", encoding="utf-8")

    results: list[str] = []
    errors: list[Exception] = []

    def worker() -> None:
        try:
            b = backup_mod.create_backup(
                "Sandbox", "World",
                saves_root=saves, backups_root=backups,
                now=datetime(2026, 5, 18, 12, 0, 0),
            )
            results.append(b.timestamp)
        except Exception as exc:
            errors.append(exc)

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start(); t2.start(); t1.join(); t2.join()

    # P0 fix: _unique_destination now uses atomic mkdir — no FileExistsError
    assert not errors, f"Concurrent backup failed with: {errors}"
    assert sorted(results) == ["20260518-120000", "20260518-120000-01"], (
        f"Expected two distinct timestamps, got: {results}"
    )


# ── RISK 4: Restore survives cleanup failure ──────────────────────────
def test_restore_survives_cleanup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    saves = tmp_path / "saves"
    backups = tmp_path / "backups"
    live = saves / "Sandbox" / "World"
    live.mkdir(parents=True)
    (live / "sandbox.lua").write_text("live-content", encoding="utf-8")

    backup = backup_mod.create_backup(
        "Sandbox", "World",
        saves_root=saves, backups_root=backups,
        now=datetime(2026, 5, 18, 12, 0, 0),
    )
    (backup.path / "sandbox.lua").write_text("backup-content", encoding="utf-8")

    def fail_rmtree(path, *args, **kwargs):
        raise OSError("cleanup failed")

    monkeypatch.setattr(backup_mod.shutil, "rmtree", fail_rmtree)

    # P0 fix: cleanup failure no longer raises — restore succeeds, old save is replaced
    backup_mod.restore_backup(
        "Sandbox", "World", backup.timestamp,
        saves_root=saves, backups_root=backups,
    )

    assert (live / "sandbox.lua").read_text("utf-8") == "backup-content", (
        "Restore failed to replace live save with backup content"
    )


# ── RISK 5: Watcher errors are logged, not silent ─────────────────────
def test_watcher_logs_backup_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import pz_save_manager.watcher as watcher_mod

    save = SaveGame("Sandbox", "World", tmp_path / "missing-save")
    watcher = watcher_mod.SaveWatcher(save, debounce_seconds=0)

    def fail(*args, **kwargs):
        raise RuntimeError("backup infrastructure down")

    monkeypatch.setattr(watcher_mod, "create_backup", fail)

    with caplog.at_level(logging.ERROR):
        watcher._do_backup()

    # P0 fix: errors are now LOGGED instead of silently swallowed
    assert "backup infrastructure down" in caplog.text, (
        "Watcher failure was not logged — silent error!"
    )
