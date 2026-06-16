"""Safe extraction of metadata from Project Zomboid save files.

All extractors are defensive — they return None/defaults on any failure
so the GUI never crashes on a corrupted or unexpected save format.
"""

from __future__ import annotations

import contextlib
import re
import sqlite3
from pathlib import Path


# ---- thumb.png ----

def has_thumbnail(save_path: Path) -> bool:
    return (save_path / "thumb.png").is_file()


# ---- mods.txt ----

def parse_mods(save_path: Path) -> list[str] | None:
    """Return list of active mod IDs, or None."""
    path = save_path / "mods.txt"
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    # Extract quoted mod names from mods {} block
    mods = re.findall(r'"([^"]+)"', text)
    return mods if mods else []


# ---- player name (players.db) ----

def player_info(save_path: Path) -> dict | None:
    """Return player name, status, and position from players.db."""
    path = save_path / "players.db"
    if not path.is_file():
        return None
    try:
        with contextlib.closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
            cur = conn.execute(
                "SELECT name, isDead, x, y, z, wx, wy, worldversion FROM localPlayers LIMIT 1"
            )
            row = cur.fetchone()
        if not row:
            return None
        return {
            "name": row[0],
            "is_dead": bool(row[1]),
            "x": round(row[2]) if row[2] is not None else None,
            "y": round(row[3]) if row[3] is not None else None,
            "z": round(row[4]) if row[4] is not None else None,
            "wx": row[5],
            "wy": row[6],
            "world_version": row[7],
        }
    except Exception:
        return None


# ---- Aggregate ----

def extract_all(save_path: Path) -> dict:
    """Return all safely-extractable metadata for a save directory."""
    info: dict = {}
    info["has_thumbnail"] = has_thumbnail(save_path)

    pn = player_info(save_path)
    if pn:
        info["player"] = pn["name"]
        info["player_dead"] = pn["is_dead"]
        info["player_x"] = pn["x"]
        info["player_y"] = pn["y"]
        info["player_world_version"] = pn["world_version"]

    mods = parse_mods(save_path)
    if mods is not None:
        info["mods"] = mods
        info["mod_count"] = len(mods)

    return info
