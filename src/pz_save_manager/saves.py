"""Save discovery for Project Zomboid."""

from __future__ import annotations

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
                saves.append(SaveGame(mode_dir.name, save_dir.name, save_dir))

    return sorted(saves, key=lambda save: (save.game_mode.casefold(), save.name.casefold()))


def get_save(game_mode: str, save_name: str, saves_root: Path | str | None = None) -> SaveGame:
    """Return a specific save or raise SaveNotFound."""
    # P0: prevent path traversal — reject '..' and '/' in components
    for val, label in ((game_mode, "game_mode"), (save_name, "save_name")):
        if ".." in val or "/" in val or "\\" in val:
            raise SaveNotFound(f"Invalid {label}: {val!r}")
    root = _to_root(saves_root)
    path = root / game_mode / save_name
    if not path.is_dir():
        raise SaveNotFound(f"Save not found: {game_mode}/{save_name}")
    return SaveGame(game_mode, save_name, path)
