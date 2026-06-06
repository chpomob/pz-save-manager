"""Tests for the Flask web GUI."""

from pathlib import Path

import pytest

from pz_save_manager.gui import _CSRF_TOKEN, app


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    """Flask test client with test save directories."""
    saves = tmp_path / "Zomboid" / "Saves"
    backups = tmp_path / ".pz-save-manager" / "backups"
    saves.mkdir(parents=True)
    (saves / "Apocalypse" / "test-world").mkdir(parents=True)
    (saves / "Apocalypse" / "test-world" / "sandbox.lua").write_text("return {}")
    (saves / "Apocalypse" / "test-world" / "map").mkdir()

    # Patch where they're imported: saves.py imports from platforms
    monkeypatch.setattr("pz_save_manager.saves.get_saves_root", lambda: saves)
    monkeypatch.setattr("pz_save_manager.backup.get_saves_root", lambda: saves)
    monkeypatch.setattr("pz_save_manager.backup.get_backups_root", lambda: backups)

    app.config["TESTING"] = True
    return app.test_client()


def csrf_headers() -> dict[str, str]:
    return {"X-CSRF-Token": _CSRF_TOKEN}


def test_index_shows_saves(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"test-world" in resp.data
    assert b"Apocalypse" in resp.data


def test_api_backup_creates_backup(client):
    resp = client.post("/api/backup", json={"game_mode": "Apocalypse", "save_name": "test-world"}, headers=csrf_headers())
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert "timestamp" in data


def test_api_backup_requires_csrf(client):
    resp = client.post("/api/backup", json={"game_mode": "Apocalypse", "save_name": "test-world"})
    assert resp.status_code == 403
    assert resp.get_json()["ok"] is False


def test_api_backup_missing_save_returns_400(client):
    resp = client.post("/api/backup", json={"game_mode": "Apocalypse", "save_name": "nonexistent"}, headers=csrf_headers())
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_index_keeps_total_backup_count(client, tmp_path: Path):
    backups = tmp_path / ".pz-save-manager" / "backups" / "Apocalypse" / "test-world"
    for i in range(51):
        backup = backups / f"20260526-120{i:03d}"
        backup.mkdir(parents=True)
        (backup / ".pz-complete").touch()

    resp = client.get("/")

    assert resp.status_code == 200
    assert b"Backups (51)" in resp.data
    assert b"Showing 50 of 51 backups" in resp.data


def test_api_restore_invalid_returns_400(client):
    resp = client.post("/api/restore", json={"game_mode": "X", "save_name": "Y", "timestamp": "bad"}, headers=csrf_headers())
    assert resp.status_code == 400


def test_api_rename_rolls_back_live_save_if_backup_rename_fails(client, tmp_path: Path, monkeypatch):
    from pz_save_manager.backup import BackupError

    saves = tmp_path / "Zomboid" / "Saves"

    def fail_backup_rename(*args, **kwargs):
        raise BackupError("backup rename failed")

    monkeypatch.setattr("pz_save_manager.backup.rename_backups_for_save", fail_backup_rename)

    resp = client.post(
        "/api/save/rename",
        json={"game_mode": "Apocalypse", "old_name": "test-world", "new_name": "new-world"},
        headers=csrf_headers(),
    )

    assert resp.status_code == 400
    assert (saves / "Apocalypse" / "test-world").is_dir()
    assert not (saves / "Apocalypse" / "new-world").exists()


def test_api_watcher_toggle(client):
    resp = client.post("/api/watcher/toggle", headers=csrf_headers())
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    resp = client.post("/api/watcher/toggle", headers=csrf_headers())
    assert resp.status_code == 200
