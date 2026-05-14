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

    assert [(save.game_mode, save.name) for save in saves] == [("Apocalypse", "Alpha"), ("Sandbox", "Bravo")]
    assert list_game_modes(tmp_path) == ["Apocalypse", "Sandbox"]


def test_list_saves_returns_empty_for_missing_root(tmp_path):
    assert list_saves(tmp_path / "missing") == []


def test_get_save_raises_for_missing_save(tmp_path):
    with pytest.raises(SaveNotFound):
        get_save("Sandbox", "Missing", saves_root=tmp_path)
