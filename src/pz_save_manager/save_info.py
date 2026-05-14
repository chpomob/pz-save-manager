"""Safe extraction of metadata from Project Zomboid save files.

All extractors are defensive — they return None/defaults on any failure
so the GUI never crashes on a corrupted or unexpected save format.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path


# ---- thumb.png ----

def has_thumbnail(save_path: Path) -> bool:
    return (save_path / "thumb.png").is_file()


# ---- WorldDictionaryReadable.lua ----

def parse_world_dictionary(save_path: Path) -> dict | None:
    """Count total, vanilla, and modded items from WorldDictionaryReadable.lua.

    Returns None if the file doesn't exist or can't be parsed.
    """
    path = save_path / "WorldDictionaryReadable.lua"
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    total = 0
    vanilla = 0
    modded = 0
    # Simple regex: count blocks that have registryID = <number>
    ids = set()
    for m in re.finditer(r"registryID\s*=\s*(\d+)", text):
        ids.add(int(m.group(1)))
    total = len(ids)

    # Count vanilla items
    vanilla = len(re.findall(r'existsAsVanilla\s*=\s*true', text, re.IGNORECASE))
    # Count modded items
    modded = len(re.findall(r'isModded\s*=\s*true', text, re.IGNORECASE))

    return {"total": total, "vanilla": vanilla, "modded": modded}


# ---- vehicles.db ----

def count_vehicles(save_path: Path) -> int | None:
    """Return the number of vehicles, or None if the DB can't be read."""
    path = save_path / "vehicles.db"
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        cur = conn.execute("SELECT COUNT(*) FROM vehicles")
        count = cur.fetchone()[0]
        conn.close()
        return count
    except Exception:
        return None


# ---- players.db ----

def count_players(save_path: Path) -> int | None:
    """Return the number of players (multiplayer), or None."""
    path = save_path / "players.db"
    if not path.is_file() or path.stat().st_size == 0:
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if "players" in tables:
            cur = conn.execute("SELECT COUNT(*) FROM players")
            count = cur.fetchone()[0]
            conn.close()
            return count
        conn.close()
        return None
    except Exception:
        return None


# ---- InGameMap.ini ----

def map_position(save_path: Path) -> dict | None:
    """Extract map center coordinates, or None."""
    path = save_path / "InGameMap.ini"
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    cx = re.search(r"WorldMap\.CenterX=([\d.]+)", text)
    cy = re.search(r"WorldMap\.CenterY=([\d.]+)", text)
    zoom = re.search(r"WorldMap\.Zoom=([\d.]+)", text)
    if cx and cy:
        return {
            "x": int(float(cx.group(1))),
            "y": int(float(cy.group(1))),
            "zoom": float(zoom.group(1)) if zoom else 18.0,
        }
    return None


# ---- Aggregate ----

def extract_all(save_path: Path) -> dict:
    """Return all safely-extractable metadata for a save directory."""
    info: dict = {}
    info["has_thumbnail"] = has_thumbnail(save_path)

    wd = parse_world_dictionary(save_path)
    if wd:
        info["items_total"] = wd["total"]
        info["items_vanilla"] = wd["vanilla"]
        info["items_modded"] = wd["modded"]

    v = count_vehicles(save_path)
    if v is not None:
        info["vehicles"] = v

    p = count_players(save_path)
    if p is not None:
        info["players"] = p

    pos = map_position(save_path)
    if pos:
        info["map_x"] = pos["x"]
        info["map_y"] = pos["y"]
        info["map_zoom"] = pos["zoom"]

    return info
