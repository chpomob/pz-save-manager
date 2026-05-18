"""Save discovery for Project Zomboid."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .platforms import get_saves_root


class SaveManagerError(Exception):
    """Base error for save manager operations."""


class SaveNotFound(SaveManagerError):
    """Raised when a specific save cannot be found."""


@dataclass(frozen=True)
class SaveGame:
    """A discovered Project Zomboid save directory."""
    game_mode: str
    name: str
    path: Path

    @property
    def display_name(self) -> str:
        return f"{self.game_mode}/{self.name}"


def _to_root(saves_root: Path | str | None) -> Path:
    return Path(saves_root).expanduser() if saves_root is not None else get_saves_root()


def get_save_modified_time(save: SaveGame) -> float:
    """Return a representative modification time for the save (fast, no rglob).

    A full rglob is O(files) — PZ saves contain thousands of map chunks, and
    on Windows with real-time AV, walking the tree can take minutes per save.
    Sampling the save dir + the files PZ actually writes to is O(1) and gives
    the same answer for any normal play session.
    """
    latest = save.path.stat().st_mtime
    for name in ("sandbox.lua", "players.db", "vehicles.db", "map_ver.bin", "map"):
        try:
            t = (save.path / name).stat().st_mtime
            if t > latest:
                latest = t
        except OSError:
            continue
    return latest


def list_game_modes(saves_root: Path | str | None = None) -> list[str]:
    """List available game mode directories."""
    root = _to_root(saves_root)
    if not root.is_dir():
        return []
    return sorted(
        (path.name for path in root.iterdir() if path.is_dir() and not path.name.startswith(".")),
        key=str.casefold,
    )


def list_saves(saves_root: Path | str | None = None) -> list[SaveGame]:
    """Discover saves under Saves/GameMode/SaveName."""
    root = _to_root(saves_root)
    if not root.is_dir():
        return []

    saves: list[SaveGame] = []
    for mode_dir in root.iterdir():
        if not mode_dir.is_dir() or mode_dir.name.startswith("."):
            continue
        for save_dir in mode_dir.iterdir():
            if save_dir.is_dir() and not save_dir.name.startswith("."):
                if not _should_skip(save_dir.name):
                    saves.append(SaveGame(mode_dir.name, save_dir.name, save_dir))

    # Most recently modified first; tied saves fall back to alphabetical order.
    return sorted(saves, key=lambda save: (-get_save_modified_time(save),
                                             save.game_mode.casefold(),
                                             save.name.casefold()))


_MULTIPLAYER_RE = re.compile(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}_')
# Multiplayer saves created when joining a named server (e.g. "MyServer_player")
_MP_PLAYER_SUFFIX_RE = re.compile(r'_player$', re.IGNORECASE)
# Crash-recovery auto-saves created by PZ after a crash (ARK_..._crash_crash...)
_CRASH_SUFFIX_RE = re.compile(r'_crash(_crash)*$', re.IGNORECASE)


def _is_multiplayer(name: str) -> bool:
    """Return True if the save name matches a server address (multiplayer save)."""
    return bool(_MULTIPLAYER_RE.match(name))


def _should_skip(name: str) -> bool:
    """Return True for auto-generated saves that should be hidden.
    
    Excludes:
    - Multiplayer saves (IP-prefixed or _player suffix)
    - Crash-recovery auto-saves (_crash suffix)
    """
    return (
        _MULTIPLAYER_RE.match(name)
        or _MP_PLAYER_SUFFIX_RE.search(name)
        or _CRASH_SUFFIX_RE.search(name)
    )


def get_save(game_mode: str, save_name: str, saves_root: Path | str | None = None) -> SaveGame:
    """Return a specific save or raise SaveNotFound."""
    # P0: prevent path traversal — reject '..', '/', '\\' and null bytes in components
    for val, label in ((game_mode, "game_mode"), (save_name, "save_name")):
        if ".." in val or "/" in val or "\\" in val or "\x00" in val:
            raise SaveNotFound(f"Invalid {label}: {val!r}")
    root = _to_root(saves_root)
    path = root / game_mode / save_name
    if not path.is_dir():
        raise SaveNotFound(f"Save not found: {game_mode}/{save_name}")
    return SaveGame(game_mode, save_name, path)


_SANE_NAME_RE = re.compile(r'^[^/\x00]{1,200}$')


def _validate_name(value: str, label: str) -> None:
    """Reject empty, path-traversal, IP-shaped, or otherwise dangerous names."""
    if not value or not value.strip():
        raise SaveManagerError(f"{label} cannot be empty")
    if ".." in value or "/" in value or "\\" in value or "\x00" in value:
        raise SaveManagerError(f"Invalid {label}: {value!r}")
    if _is_multiplayer(value.strip()):
        raise SaveManagerError(f"{label} looks like a server address: {value!r}")
    if not _SANE_NAME_RE.match(value):
        raise SaveManagerError(f"Invalid characters in {label}: {value!r}")
    if len(value.strip()) > 200:
        raise SaveManagerError(f"{label} is too long (max 200 characters)")


def rename_save(
    game_mode: str,
    old_name: str,
    new_name: str,
    *,
    saves_root: Path | str | None = None,
) -> SaveGame:
    """Rename a save directory. Raises SaveManagerError on invalid names or conflicts."""
    _validate_name(game_mode, "game_mode")
    _validate_name(old_name, "old_name")
    _validate_name(new_name, "new_name")

    old = get_save(game_mode, old_name, saves_root=saves_root)
    root = _to_root(saves_root)
    new_path = root / game_mode / new_name.strip()
    try:
        old.path.rename(new_path)
    except OSError as e:
        raise SaveManagerError(f"Cannot rename save to {new_name!r}: {e}") from e
    return SaveGame(game_mode, new_name.strip(), new_path)
