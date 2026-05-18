from __future__ import annotations

import pytest

from pz_save_manager.saves import SaveNotFound, get_save, list_game_modes, list_saves


def make_save(root, mode, name):
    save_dir = root / mode / name
    save_dir.mkdir(parents=True)
    (save_dir / "map.bin").write_text("map", encoding="utf-8")
    return save_dir


def test_list_saves_discovers_mode_and_save_directories(tmp_path):
    make_save(tmp_path, "Sandbox", "Bravo")
    make_save(tmp_path, "Apocalypse", "Alpha")
    (tmp_path / "Apocalypse" / ".hidden").mkdir()

    saves = list_saves(tmp_path)

    discovered = {(save.game_mode, save.name) for save in saves}
    assert discovered == {("Apocalypse", "Alpha"), ("Sandbox", "Bravo")}
    assert list_game_modes(tmp_path) == ["Apocalypse", "Sandbox"]


def test_list_saves_returns_empty_for_missing_root(tmp_path):
    assert list_saves(tmp_path / "missing") == []


def test_get_save_raises_for_missing_save(tmp_path):
    with pytest.raises(SaveNotFound):
        get_save("Sandbox", "Missing", saves_root=tmp_path)


def test_multiplayer_saves_are_excluded(tmp_path):
    """IP-named saves (multiplayer) should not appear in listings."""
    make_save(tmp_path, "Sandbox", "My World")          # singleplayer → included
    make_save(tmp_path, "Sandbox", "127.0.0.1_16261")   # multiplayer → excluded
    make_save(tmp_path, "Apocalypse", "10.0.0.1_12345") # multiplayer → excluded
    make_save(tmp_path, "Multiplayer", "149.202.88.99_16361_cebb5ff9105b2cb")  # excluded

    saves = list_saves(tmp_path)
    names = {(s.game_mode, s.name) for s in saves}
    assert names == {("Sandbox", "My World")}
    assert len(saves) == 1


def test_get_save_rejects_single_backslash(tmp_path):
    """Single backslash (Windows path separator) must be rejected."""
    with pytest.raises(SaveNotFound):
        get_save("game\\mode", "World", saves_root=tmp_path)
    with pytest.raises(SaveNotFound):
        get_save("Sandbox", "world\\..\\secret", saves_root=tmp_path)


def test_get_save_rejects_null_byte(tmp_path):
    """Null bytes must be rejected (C-level truncation risk)."""
    with pytest.raises(SaveNotFound):
        get_save("Sandbox", "world\x00hidden", saves_root=tmp_path)
