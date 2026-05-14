from __future__ import annotations

from pz_save_manager.platforms import get_backups_root, get_saves_root, get_zomboid_dir


def test_project_zomboid_paths_use_home_directory(tmp_path):
    assert get_zomboid_dir(tmp_path) == tmp_path / "Zomboid"
    assert get_saves_root(tmp_path) == tmp_path / "Zomboid" / "Saves"
    assert get_backups_root(tmp_path) == tmp_path / ".pz-save-manager" / "backups"
