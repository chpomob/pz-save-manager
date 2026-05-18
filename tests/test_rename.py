"""Tests for rename operations."""

from __future__ import annotations

import pytest

from pz_save_manager.backup import BackupError, create_backup, rename_backups_for_save
from pz_save_manager.saves import SaveManagerError, rename_save


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
    # Put a file in the target so the rename cannot silently overwrite
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


# ── Backup renaming ──────────────────────────────────────────────────

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


# ── Backup annotations ───────────────────────────────────────────────

def test_set_and_get_backup_note(tmp_path):
    """Set a note, read it back, remove it."""
    from pz_save_manager.backup import get_backup_note, set_backup_note

    backup_dir = tmp_path / "backups" / "Sandbox" / "World" / "20260518-120000"
    backup_dir.mkdir(parents=True)

    assert get_backup_note(backup_dir) is None

    set_backup_note(backup_dir, "Day 12, base built in Rosewood")
    assert get_backup_note(backup_dir) == "Day 12, base built in Rosewood"

    set_backup_note(backup_dir, "  Updated note  ")
    assert get_backup_note(backup_dir) == "Updated note"

    # Remove note
    set_backup_note(backup_dir, "")
    assert get_backup_note(backup_dir) is None


def test_backup_record_note_property(tmp_path):
    """BackupRecord.note lazily reads the .pz-note sidecar."""
    from pz_save_manager.backup import BackupRecord, get_backup_note, set_backup_note

    backup_dir = tmp_path / "backups" / "Apocalypse" / "Alpha" / "20260518-120000"
    backup_dir.mkdir(parents=True)

    record = BackupRecord("Apocalypse", "Alpha", "20260518-120000", backup_dir)

    assert record.note is None
    set_backup_note(backup_dir, "Died to a horde")
    assert record.note == "Died to a horde"

    # set_note method
    record.set_note("New note via method")
    assert get_backup_note(backup_dir) == "New note via method"


def test_backup_note_survives_rename(tmp_path):
    """Notes are stored in the backup dir, so they survive rename operations."""
    from pz_save_manager.backup import create_backup, get_backup_note, rename_backups_for_save, set_backup_note

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
