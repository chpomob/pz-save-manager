from __future__ import annotations

from datetime import datetime

from pz_save_manager.backup import create_backup, delete_backup, list_backups, restore_backup, set_backup_note


def make_save(root, mode="Sandbox", name="WorldOne"):
    save_dir = root / mode / name
    map_dir = save_dir / "map"
    map_dir.mkdir(parents=True)
    (save_dir / "sandbox.lua").write_text("SandboxVars = {}", encoding="utf-8")
    (map_dir / "0_0.bin").write_text("chunk", encoding="utf-8")
    return save_dir


def test_create_backup_copies_save_and_uses_collision_suffix(tmp_path):
    saves_root = tmp_path / "saves"
    backups_root = tmp_path / "backups"
    make_save(saves_root)
    now = datetime(2026, 5, 14, 10, 30, 5)

    first = create_backup("Sandbox", "WorldOne", saves_root=saves_root, backups_root=backups_root, now=now)
    second = create_backup("Sandbox", "WorldOne", saves_root=saves_root, backups_root=backups_root, now=now)

    assert first.timestamp == "20260514-103005"
    assert second.timestamp == "20260514-103005-01"
    assert (first.path / "sandbox.lua").read_text(encoding="utf-8") == "SandboxVars = {}"
    assert (first.path / "map" / "0_0.bin").read_text(encoding="utf-8") == "chunk"


def test_restore_backup_replaces_current_save(tmp_path):
    saves_root = tmp_path / "saves"
    backups_root = tmp_path / "backups"
    save_dir = make_save(saves_root)
    backup = create_backup("Sandbox", "WorldOne", saves_root=saves_root, backups_root=backups_root, now=datetime(2026, 5, 14, 10, 30, 5))
    (save_dir / "sandbox.lua").write_text("changed", encoding="utf-8")
    (save_dir / "new-file.txt").write_text("new", encoding="utf-8")

    restored = restore_backup("Sandbox", "WorldOne", backup.timestamp, saves_root=saves_root, backups_root=backups_root)

    assert restored.path == saves_root / "Sandbox" / "WorldOne"
    assert (restored.path / "sandbox.lua").read_text(encoding="utf-8") == "SandboxVars = {}"
    assert not (restored.path / "new-file.txt").exists()


def test_restore_backup_ne_copie_pas_les_sidecars_internes(tmp_path):
    """Les marqueurs .pz-* du backup ne doivent jamais contaminer la sauvegarde live."""
    saves_root = tmp_path / "saves"
    backups_root = tmp_path / "backups"
    save_dir = make_save(saves_root)
    backup = create_backup(
        "Sandbox",
        "WorldOne",
        saves_root=saves_root,
        backups_root=backups_root,
        now=datetime(2026, 5, 14, 10, 30, 5),
        auto=True,
    )
    set_backup_note(backup.path, "Jour 12")
    (save_dir / "sandbox.lua").write_text("changed", encoding="utf-8")

    restored = restore_backup("Sandbox", "WorldOne", backup.timestamp, saves_root=saves_root, backups_root=backups_root)

    assert not any(path.name.startswith(".pz-") for path in restored.path.rglob("*"))

    manual = create_backup(
        "Sandbox",
        "WorldOne",
        saves_root=saves_root,
        backups_root=backups_root,
        now=datetime(2026, 5, 14, 10, 31, 5),
    )
    records = list_backups("Sandbox", "WorldOne", backups_root=backups_root)
    manual_record = next(record for record in records if record.timestamp == manual.timestamp)

    assert not manual_record.auto


def test_delete_backup_removes_backup_directory(tmp_path):
    saves_root = tmp_path / "saves"
    backups_root = tmp_path / "backups"
    make_save(saves_root)
    backup = create_backup("Sandbox", "WorldOne", saves_root=saves_root, backups_root=backups_root, now=datetime(2026, 5, 14, 10, 30, 5))

    deleted = delete_backup("Sandbox", "WorldOne", backup.timestamp, backups_root=backups_root)

    assert deleted.timestamp == backup.timestamp
    assert not backup.path.exists()
    assert list_backups(backups_root=backups_root) == []
