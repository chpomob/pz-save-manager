"""Tests for file-backed configuration behavior."""

from pathlib import Path

import pytest

from pz_save_manager.config import ConfigStore, _coerce


def test_config_store_reloads_when_another_instance_writes(tmp_path: Path):
    config_path = tmp_path / "config.json"
    first = ConfigStore(config_path)
    second = ConfigStore(config_path)

    assert first.get("port") == 8080
    second.set("port", 9090)

    assert first.get("port") == 9090


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("port", 0),
        ("port", 999999),
        ("backup_cooldown_minutes", -1),
        ("backup_cooldown_minutes", 1441),
        ("max_auto_backups", -1),
        ("max_auto_backups", 1000),
        ("debounce_seconds", -0.1),
        ("debounce_seconds", 3601),
    ],
)
def test_coerce_rejects_out_of_range_numbers(key: str, value: object):
    with pytest.raises(ValueError):
        _coerce(key, value)
