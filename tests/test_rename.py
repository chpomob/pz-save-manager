"""Tests for rename and prune operations."""

from __future__ import annotations

import pytest

from pz_save_manager.backup import (
    BackupError,
    BackupRecord,
    create_backup,
    get_backup_note,
    preflight_rename,
    prune_auto_backups,
    rename_backups_for_save,
    set_backup_note,
)
from pz_save_manager.saves import SaveManagerError, rename_save


# ── Rename tests ─────────────────────────────────────────────────────

def test_rename_save_moves_directory(tmp_path):
    """Renaming a save renames its directory and returns the new SaveGame."""
    saves = tmp_path / "saves"
    save_dir = saves / "Sandbox" / "OldWorld"
    save_dir.mkdir(parents=True)
    (save_dir / "map.bin").write_text("data", encoding="utf-8")

    result = rename_save("Sandbox", "OldWorld", "NewWorld", saves_root=saves)

    assert result.name == "NewWorld"
    assert not save_dir.exists()
    assert (saves / "Sandbox" / "NewWorld").is_dir()
    assert (saves / "Sandbox" / "NewWorld" / "map.bin").read_text() == "data"


def test_rename_save_rejects_path_traversal(tmp_path):
    """New name with .. or / is rejected."""
    saves = tmp_path / "saves"
    (saves / "Sandbox" / "World").mkdir(parents=True)

    with pytest.raises(SaveManagerError):
        rename_save("Sandbox", "World", "../escape", saves_root=saves)
    with pytest.raises(SaveManagerError):
        rename_save("Sandbox", "World", "sub/dir", saves_root=saves)


def test_rename_save_rejects_empty_name(tmp_path):
    """Empty or whitespace-only names are rejected."""
    saves = tmp_path / "saves"
    (saves / "Sandbox" / "World").mkdir(parents=True)

    with pytest.raises(SaveManagerError):
        rename_save("Sandbox", "World", "", saves_root=saves)
    with pytest.raises(SaveManagerError):
        rename_save("Sandbox", "World", "   ", saves_root=saves)


def test_rename_save_rejects_multiplayer_name(tmp_path):
    """IP-shaped names are rejected (they are already filtered as multiplayer)."""
    saves = tmp_path / "saves"
    (saves / "Sandbox" / "World").mkdir(parents=True)

    with pytest.raises(SaveManagerError):
        rename_save("Sandbox", "World", "127.0.0.1_16261", saves_root=saves)


def test_rename_save_rejects_existing_destination(tmp_path):
    """Cannot rename to a name that already exists with content."""
    saves = tmp_path / "saves"
    (saves / "Sandbox" / "World").mkdir(parents=True)
    (saves / "Sandbox" / "Collision").mkdir(parents=True)
    (saves / "Sandbox" / "Collision" / "map.bin").write_text("x", encoding="utf-8")

    with pytest.raises(SaveManagerError, match="Cannot rename"):
        rename_save("Sandbox", "World", "Collision", saves_root=saves)


def test_rename_save_strips_whitespace(tmp_path):
    """Leading/trailing whitespace is stripped from the new name."""
    saves = tmp_path / "saves"
    (saves / "Sandbox" / "World").mkdir(parents=True)

    result = rename_save("Sandbox", "World", "  Clean  ", saves_root=saves)

    assert result.name == "Clean"
    assert (saves / "Sandbox" / "Clean").is_dir()


# ── Backup rename tests ───────────────────────────────────────────────

def test_rename_backups_moves_directory(tmp_path):
    """Backups follow the save rename."""
    saves = tmp_path / "saves"
    backups = tmp_path / "backups"
    save_dir = saves / "Apocalypse" / "Alpha"
    save_dir.mkdir(parents=True)
    (save_dir / "map.bin").write_text("x", encoding="utf-8")

    create_backup("Apocalypse", "Alpha", saves_root=saves, backups_root=backups)
    assert (backups / "Apocalypse" / "Alpha").is_dir()

    n = rename_backups_for_save("Apocalypse", "Alpha", "Bravo", backups_root=backups)
    assert n == 1
    assert not (backups / "Apocalypse" / "Alpha").exists()
    assert (backups / "Apocalypse" / "Bravo").is_dir()


def test_rename_backups_noop_when_no_backups(tmp_path):
    """Renaming backups for a save with no backups returns 0."""
    backups = tmp_path / "backups"
    n = rename_backups_for_save("Apocalypse", "Ghost", "Renamed", backups_root=backups)
    assert n == 0


def test_rename_backups_rejects_collision(tmp_path):
    """Cannot rename backups if the new name already has backups."""
    saves = tmp_path / "saves"
    backups = tmp_path / "backups"
    for name in ("Alpha", "Bravo"):
        sd = saves / "Apocalypse" / name
        sd.mkdir(parents=True)
        (sd / "map.bin").write_text("x", encoding="utf-8")
        create_backup("Apocalypse", name, saves_root=saves, backups_root=backups)

    with pytest.raises(BackupError, match="Cannot rename"):
        rename_backups_for_save("Apocalypse", "Alpha", "Bravo", backups_root=backups)


def test_rename_backups_rejects_empty_destination_dir(tmp_path):
    """An empty destination dir is still a backup-location collision."""
    saves = tmp_path / "saves"
    backups = tmp_path / "backups"
    save_dir = saves / "Apocalypse" / "Alpha"
    save_dir.mkdir(parents=True)
    (save_dir / "map.bin").write_text("x", encoding="utf-8")
    create_backup("Apocalypse", "Alpha", saves_root=saves, backups_root=backups)
    (backups / "Apocalypse" / "Bravo").mkdir()

    with pytest.raises(BackupError, match="already exists"):
        rename_backups_for_save("Apocalypse", "Alpha", "Bravo", backups_root=backups)

    assert (backups / "Apocalypse" / "Alpha").is_dir()
    assert (backups / "Apocalypse" / "Bravo").is_dir()


def test_preflight_rename_bloque_la_collision_avant_de_renommer_la_save(tmp_path):
    """Une collision de backups doit laisser la sauvegarde et ses backups sous leur nom original."""
    saves = tmp_path / "saves"
    backups = tmp_path / "backups"
    for name in ("Alpha", "Bravo"):
        sd = saves / "Apocalypse" / name
        sd.mkdir(parents=True)
        (sd / "map.bin").write_text(name, encoding="utf-8")
        create_backup("Apocalypse", name, saves_root=saves, backups_root=backups)

    with pytest.raises(BackupError, match="already exists in backup location"):
        preflight_rename("Apocalypse", "Alpha", "Bravo", backups_root=backups)
        rename_save("Apocalypse", "Alpha", "Bravo", saves_root=saves)
        rename_backups_for_save("Apocalypse", "Alpha", "Bravo", backups_root=backups)

    assert (saves / "Apocalypse" / "Alpha").is_dir()
    assert (saves / "Apocalypse" / "Alpha" / "map.bin").read_text(encoding="utf-8") == "Alpha"
    assert (backups / "Apocalypse" / "Alpha").is_dir()
    assert (backups / "Apocalypse" / "Bravo").is_dir()


# ── Annotation tests ──────────────────────────────────────────────────

def test_set_and_get_backup_note(tmp_path):
    """Set a note, read it back, remove it."""
    backup_dir = tmp_path / "backups" / "Sandbox" / "World" / "20260518-120000"
    backup_dir.mkdir(parents=True)

    assert get_backup_note(backup_dir) is None

    set_backup_note(backup_dir, "Day 12, base built in Rosewood")
    assert get_backup_note(backup_dir) == "Day 12, base built in Rosewood"

    set_backup_note(backup_dir, "  Updated note  ")
    assert get_backup_note(backup_dir) == "Updated note"

    set_backup_note(backup_dir, "")
    assert get_backup_note(backup_dir) is None


def test_backup_record_note_property(tmp_path):
    """BackupRecord.note lazily reads the .pz-note sidecar."""
    backup_dir = tmp_path / "backups" / "Apocalypse" / "Alpha" / "20260518-120000"
    backup_dir.mkdir(parents=True)

    record = BackupRecord("Apocalypse", "Alpha", "20260518-120000", backup_dir)

    assert record.note is None
    set_backup_note(backup_dir, "Died to a horde")
    assert record.note == "Died to a horde"

    set_backup_note(record.path, "New note via method")
    assert get_backup_note(backup_dir) == "New note via method"


def test_backup_note_survives_rename(tmp_path):
    """Notes are stored in the backup dir, so they survive rename operations."""
    saves = tmp_path / "saves"
    backups = tmp_path / "backups"
    save_dir = saves / "Sandbox" / "Old"
    save_dir.mkdir(parents=True)
    (save_dir / "map.bin").write_text("x", encoding="utf-8")

    b = create_backup("Sandbox", "Old", saves_root=saves, backups_root=backups)
    set_backup_note(b.path, "Before rename")

    rename_backups_for_save("Sandbox", "Old", "New", backups_root=backups)

    new_backup_dir = backups / "Sandbox" / "New" / b.timestamp
    assert get_backup_note(new_backup_dir) == "Before rename"


# ── Prune tests ───────────────────────────────────────────────────────

def test_prune_auto_backups_deletes_oldest(tmp_path):
    """Oldest auto-backups are pruned to respect max_count."""
    saves = tmp_path / "saves"
    backups = tmp_path / "backups"
    save_dir = saves / "Sandbox" / "World"
    save_dir.mkdir(parents=True)
    (save_dir / "map.bin").write_text("x", encoding="utf-8")

    # Create 5 auto-backups at different timestamps
    from datetime import datetime
    timestamps = []
    for i in range(5):
        b = create_backup(
            "Sandbox", "World",
            saves_root=saves, backups_root=backups,
            now=datetime(2026, 5, 18, 12, i, 0),
            auto=True,
        )
        timestamps.append(b.timestamp)

    assert len(list((backups / "Sandbox" / "World").iterdir())) == 5

    # Prune to max 2
    removed = prune_auto_backups("Sandbox", "World", 2, backups_root=backups)
    assert removed == 3

    remaining = sorted(d.name for d in (backups / "Sandbox" / "World").iterdir())
    # The 2 newest should remain (timestamps are YYYYMMDD-HHMMSS format)
    assert len(remaining) == 2
    assert remaining == sorted(timestamps[-2:])


def test_prune_auto_backups_ignores_manual(tmp_path):
    """Manual backups (no .pz-auto) are never pruned."""
    saves = tmp_path / "saves"
    backups = tmp_path / "backups"
    save_dir = saves / "Sandbox" / "World"
    save_dir.mkdir(parents=True)
    (save_dir / "map.bin").write_text("x", encoding="utf-8")

    from datetime import datetime

    # 2 manual backups
    for i in range(2):
        create_backup("Sandbox", "World", saves_root=saves, backups_root=backups,
                      now=datetime(2026, 5, 18, 12, i, 0), auto=False)
    # 3 auto-backups
    for i in range(3):
        create_backup("Sandbox", "World", saves_root=saves, backups_root=backups,
                      now=datetime(2026, 5, 18, 13, i, 0), auto=True)

    assert len(list((backups / "Sandbox" / "World").iterdir())) == 5

    # Prune to max 1 auto — should keep 1 auto + 2 manual = 3 total
    removed = prune_auto_backups("Sandbox", "World", 1, backups_root=backups)
    assert removed == 2

    autos = [d for d in (backups / "Sandbox" / "World").iterdir() if (d / ".pz-auto").is_file()]
    manuals = [d for d in (backups / "Sandbox" / "World").iterdir() if not (d / ".pz-auto").is_file()]

    assert len(autos) == 1  # 1 auto remaining
    assert len(manuals) == 2  # 2 manuals untouched


def test_prune_auto_backups_noop_when_under_limit(tmp_path):
    """No pruning occurs when auto-backup count is within limit."""
    backups = tmp_path / "backups"
    (backups / "Sandbox" / "World").mkdir(parents=True)
    removed = prune_auto_backups("Sandbox", "World", 30, backups_root=backups)
    assert removed == 0


def test_prune_auto_backups_zero_disables_pruning(tmp_path):
    """max_count=0 disables pruning entirely (keeps all backups)."""
    saves = tmp_path / "saves"
    backups = tmp_path / "backups"
    save_dir = saves / "Sandbox" / "World"
    save_dir.mkdir(parents=True)
    (save_dir / "map.bin").write_text("x", encoding="utf-8")

    from datetime import datetime
    for i in range(3):
        create_backup("Sandbox", "World", saves_root=saves, backups_root=backups,
                      now=datetime(2026, 5, 18, 12, i, 0), auto=True)

    assert len(list((backups / "Sandbox" / "World").iterdir())) == 3
    removed = prune_auto_backups("Sandbox", "World", 0, backups_root=backups)
    assert removed == 0
    assert len(list((backups / "Sandbox" / "World").iterdir())) == 3
