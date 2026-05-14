from __future__ import annotations

from click.testing import CliRunner

from pz_save_manager.cli import main


def make_save(root):
    save_dir = root / "Sandbox" / "WorldOne"
    save_dir.mkdir(parents=True)
    (save_dir / "sandbox.lua").write_text("original", encoding="utf-8")
    return save_dir


def run_cli(runner, saves_root, backups_root, *args):
    return runner.invoke(main, ["--saves-dir", str(saves_root), "--backups-dir", str(backups_root), *args])


def test_cli_lists_saves_and_manages_backup_lifecycle(tmp_path):
    saves_root = tmp_path / "saves"
    backups_root = tmp_path / "backups"
    save_dir = make_save(saves_root)
    runner = CliRunner()

    result = run_cli(runner, saves_root, backups_root, "list")
    assert result.exit_code == 0, result.output
    assert "Sandbox" in result.output
    assert "WorldOne" in result.output

    result = run_cli(runner, saves_root, backups_root, "backup", "Sandbox", "WorldOne")
    assert result.exit_code == 0, result.output
    timestamp = next((backups_root / "Sandbox" / "WorldOne").iterdir()).name

    result = run_cli(runner, saves_root, backups_root, "list-backups")
    assert result.exit_code == 0, result.output
    assert timestamp in result.output

    (save_dir / "sandbox.lua").write_text("changed", encoding="utf-8")
    result = run_cli(runner, saves_root, backups_root, "restore", "Sandbox", "WorldOne", timestamp, "--yes")
    assert result.exit_code == 0, result.output
    assert (save_dir / "sandbox.lua").read_text(encoding="utf-8") == "original"

    result = run_cli(runner, saves_root, backups_root, "delete", "Sandbox", "WorldOne", timestamp, "--yes")
    assert result.exit_code == 0, result.output
    assert not (backups_root / "Sandbox" / "WorldOne" / timestamp).exists()
