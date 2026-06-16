# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
.venv/bin/pip install -e ".[dev]"          # install (incl. pytest)
.venv/bin/pytest                            # run all tests
.venv/bin/pytest tests/test_backup.py       # single file
.venv/bin/pytest -k traversal               # single test by name pattern
.venv/bin/pz-saves gui                      # launch Flask GUI on 8080
.venv/bin/pz-saves gui --no-browser         # GUI without opening a browser
./launcher.sh                               # bootstrap venv + launch (Linux/macOS)
```

No linter or formatter is configured — match surrounding style (4-space indent, `from __future__ import annotations`, `|`-union typing, single-quote-free where it doesn't matter).

## Architecture

### Data flow
The tool watches `~/Zomboid/Saves/<GameMode>/<SaveName>/` and writes timestamped full-directory copies to `~/.pz-save-manager/backups/<GameMode>/<SaveName>/<YYYYMMDD-HHMMSS>/` (or a user-configured `backups_dir`). All paths resolve through `platforms.py` — never hardcode `~/Zomboid` or `~/.pz-save-manager` elsewhere.

### Module layering
- `platforms.py` — OS path helpers. `get_backups_root()` reads `config.py`, so importing config inside that function avoids a circular import.
- `saves.py` — read-only discovery of save directories. `get_save()` is the security boundary: it rejects `..`, `/`, `\` in `game_mode`/`save_name` and is the entry point all backup ops route through.
- `backup.py` — atomic backup/restore. Key invariants enforced here:
  - **Atomic backup creation**: `_publish_temp_backup` copies into a sibling temp dir, writes a completion marker, then `os.replace(tmp_path, destination)` atomically publishes. A `destination.exists()` pre-check + `FileExistsError`/`ENOTEMPTY` guards handle TOCTOU races. Two concurrent backups at the same second get distinct `…-01` suffixes.
  - **Symlinks are skipped, never followed**, in both `create_backup` and `restore_backup` via the `_skip_symlinks` ignore callback.
  - **Restore stages then renames**: copy → `target.rename(previous_target)` → `temp_target.rename(target)`. Cleanup of `previous_target` is wrapped so a failed `rmtree` cannot lose the restored save — it only logs a warning.
  - Component validation lives in `_validate_component`; reuse it for any new path-accepting API.
- `watcher.py` — `SaveWatcher` (per-save debounced backup) + `WatcherManager` (singleton via `get_manager()`). The manager re-creates `Observer()` on restart because watchdog observers can't be reused after `.stop()`. Backup failures inside `_do_backup` must be logged (not silently swallowed) — the adversarial test enforces this.
- `save_info.py` — defensive extractors for player/vehicle/mod/map metadata. Every function returns `None` on any failure. SQLite files are opened read-only via `file:…?mode=ro` URIs.
- `gui.py` — Flask app, single-file inline HTML template (`PAGE`). Multiplayer saves (named as IP addresses) are excluded at the `list_saves()` level.
- `cli.py` — Click group; `pz-saves` entry point defined in `pyproject.toml`.

### Save format knowledge
`docs/format-notes.md` documents the Project Zomboid on-disk save layout (chunk endianness, world-version table, SQLite schemas). Consult it before adding new metadata extractors. `players.db` schema: `localPlayers(name, isDead, x, y, z, wx, wy, worldversion, …)`.

### Tests
`tests/conftest.py` injects `src/` into `sys.path`, so tests import `pz_save_manager` without an editable install. `tests/test_adversarial.py` encodes the P0 security invariants — keep these passing when touching `backup.py`, `saves.py`, or `watcher.py`.
