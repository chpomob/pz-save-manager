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


# ---- map name (map_ver.bin) ----

def map_name(save_path: Path) -> str | None:
    """Extract visible map name from map_ver.bin (e.g. 'Rosewood, KY')."""
    path = save_path / "map_ver.bin"
    if not path.is_file():
        return None
    try:
        data = path.read_bytes()
        # The format is: 4 bytes version, 4 bytes flags, then UTF-16LE strings
        # Look for the readable part (starts after ~8 bytes, UTF-16LE encoded)
        # Decode from offset 8 as UTF-16LE, grab first null-terminated string
        if len(data) > 12:
            # Try parsing as UTF-16LE from byte 8
            raw = data[8:]
            try:
                decoded = raw.decode("utf-16-le", errors="ignore")
                # Take first line / null-terminated part
                name = decoded.split("\x00")[0].strip()
                if name and len(name) > 2 and len(name) < 100:
                    return name
            except Exception:
                pass
            # Fallback: extract ASCII-readable chars
            readable = "".join(chr(b) for b in raw if 32 <= b < 127)
            if readable and len(readable) > 2:
                return readable[:80]
    except Exception:
        pass
    return None


# ---- player name (players.db) ----

def player_info(save_path: Path) -> dict | None:
    """Return player name, status, and position from players.db."""
    path = save_path / "players.db"
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        cur = conn.execute(
            "SELECT name, isDead, x, y, z, wx, wy, worldversion FROM localPlayers LIMIT 1"
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return {
            "name": row[0],
            "is_dead": bool(row[1]),
            "x": round(row[2]) if row[2] else 0,
            "y": round(row[3]) if row[3] else 0,
            "z": round(row[4]) if row[4] else 0,
            "wx": row[5],
            "wy": row[6],
            "world_version": row[7],
        }
    except Exception:
        return None


# ---- WorldDictionaryLog.lua (crafted objects) ----

def crafted_objects(save_path: Path) -> int | None:
    """Count crafted/built objects from WorldDictionaryLog.lua."""
    path = save_path / "WorldDictionaryLog.lua"
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return len(re.findall(r"registryID\s*=", text))  # P0: fixed typo 'registeryID' → 'registryID'


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

    mn = map_name(save_path)
    if mn:
        info["map_name"] = mn

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

    # crafted_objects and parse_world_dictionary read multi-megabyte .lua
    # files; their output isn't displayed anywhere in the GUI. Skipped on
    # the hot path. Call those functions directly if you need the data.

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
