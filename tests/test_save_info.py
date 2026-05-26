from __future__ import annotations

import sqlite3
from pathlib import Path

from pz_save_manager.save_info import (
    count_players,
    count_vehicles,
    extract_all,
    has_thumbnail,
    map_name,
    map_position,
    parse_mods,
    player_info,
)


def _create_players_db(path: Path, *, include_players_table: bool = False) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE localPlayers (
                name TEXT,
                isDead INTEGER,
                x REAL,
                y REAL,
                z REAL,
                wx INTEGER,
                wy INTEGER,
                worldversion INTEGER
            )
            """
        )
        conn.execute(
            """
            INSERT INTO localPlayers
            (name, isDead, x, y, z, wx, wy, worldversion)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("Alice", 1, 123.4, 567.8, 1.2, 10, 20, 195),
        )
        if include_players_table:
            conn.execute("CREATE TABLE players (id INTEGER PRIMARY KEY, name TEXT)")
            conn.executemany(
                "INSERT INTO players (name) VALUES (?)",
                [("Alice",), ("Bob",)],
            )


def test_has_thumbnail(tmp_path: Path) -> None:
    assert has_thumbnail(tmp_path) is False

    (tmp_path / "thumb.png").write_bytes(b"png")

    assert has_thumbnail(tmp_path) is True


def test_player_info(tmp_path: Path) -> None:
    _create_players_db(tmp_path / "players.db")

    info = player_info(tmp_path)

    assert info == {
        "name": "Alice",
        "is_dead": True,
        "x": 123,
        "y": 568,
        "z": 1,
        "wx": 10,
        "wy": 20,
        "world_version": 195,
    }


def test_player_info_no_db(tmp_path: Path) -> None:
    assert player_info(tmp_path) is None


def test_player_info_empty_db(tmp_path: Path) -> None:
    (tmp_path / "players.db").touch()

    assert player_info(tmp_path) is None


def test_player_info_corrupt_db(tmp_path: Path) -> None:
    (tmp_path / "players.db").write_text("not sqlite", encoding="utf-8")

    assert player_info(tmp_path) is None


def test_count_vehicles(tmp_path: Path) -> None:
    path = tmp_path / "vehicles.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE vehicles (id INTEGER PRIMARY KEY)")
        conn.executemany("INSERT INTO vehicles DEFAULT VALUES", [(), (), ()])

    assert count_vehicles(tmp_path) == 3


def test_count_vehicles_no_db(tmp_path: Path) -> None:
    assert count_vehicles(tmp_path) is None


def test_parse_mods(tmp_path: Path) -> None:
    (tmp_path / "mods.txt").write_text('mods { "Mod1"; "Mod2" }', encoding="utf-8")

    assert parse_mods(tmp_path) == ["Mod1", "Mod2"]


def test_parse_mods_no_file(tmp_path: Path) -> None:
    assert parse_mods(tmp_path) is None


def test_map_name(tmp_path: Path) -> None:
    (tmp_path / "map_ver.bin").write_bytes(
        b"\x00" * 8 + "Rosewood, KY\x00".encode("utf-16-le")
    )

    assert map_name(tmp_path) == "Rosewood, KY"


def test_map_name_no_file(tmp_path: Path) -> None:
    assert map_name(tmp_path) is None


def test_map_position(tmp_path: Path) -> None:
    (tmp_path / "InGameMap.ini").write_text(
        "\n".join(
            [
                "WorldMap.CenterX=1234.5",
                "WorldMap.CenterY=6789.1",
                "WorldMap.Zoom=12.5",
            ]
        ),
        encoding="utf-8",
    )

    assert map_position(tmp_path) == {"x": 1234, "y": 6789, "zoom": 12.5}


def test_map_position_no_file(tmp_path: Path) -> None:
    assert map_position(tmp_path) is None


def test_count_players(tmp_path: Path) -> None:
    path = tmp_path / "players.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE players (id INTEGER PRIMARY KEY, name TEXT)")
        conn.executemany(
            "INSERT INTO players (name) VALUES (?)",
            [("Alice",), ("Bob",)],
        )

    assert count_players(tmp_path) == 2


def test_extract_all(tmp_path: Path) -> None:
    (tmp_path / "thumb.png").write_bytes(b"png")
    (tmp_path / "mods.txt").write_text('mods { "Mod1"; "Mod2" }', encoding="utf-8")
    _create_players_db(tmp_path / "players.db", include_players_table=True)

    assert extract_all(tmp_path) == {
        "has_thumbnail": True,
        "player": "Alice",
        "player_dead": True,
        "player_x": 123,
        "player_y": 568,
        "player_world_version": 195,
        "mods": ["Mod1", "Mod2"],
        "mod_count": 2,
        "players": 2,
    }
